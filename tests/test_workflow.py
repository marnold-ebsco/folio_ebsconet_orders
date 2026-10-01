import csv
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ebsconet as cli  # noqa: E402
from pipeline import ebsconet_prep as prep  # noqa: E402

HEADERS = ["Title Name", "ISSN", "Format", "Order Number", "Total Cost",
           "Publisher Package"]


@pytest.fixture
def cfg():
    return prep.load_config(ROOT / "ebsconet_config.json")


def make_sop(path, rows, headers=HEADERS):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    wb.save(path)


ROWS = [
    {"Title Name": "Paid", "ISSN": "1111-2222", "Format": "Online Only",
     "Order Number": "A", "Total Cost": 100.5},
    {"Title Name": "Free journal", "Order Number": "B", "Total Cost": 0},
    {"Title Name": "Package member", "Order Number": "C", "Total Cost": 0,
     "Publisher Package": "Big Deal"},
    {"Title Name": "Blank cost", "Order Number": "D", "Total Cost": None},
    {"Title Name": "Paid 2", "Format": "Online Only", "Order Number": "E",
     "Total Cost": "1,200.00"},
    {"Title Name": "Odd cost", "Format": "Database", "Order Number": "F", "Total Cost": "n/a"},
]


def test_stage1_removes_zero_dollar_lines_and_adds_highlighted_columns(cfg, tmp_path):
    src = tmp_path / "SOP.xlsx"
    make_sop(src, ROWS)
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    assert (s["read"], s["removed"], s["kept"]) == (6, 3, 3)
    assert s["columns"] == {"online": ["FOLIO Org", "FOLIO Fund", "FOLIO Expense Class",
                                       "FOLIO Order Type",
                                       "FOLIO Renewal Interval (Days)"]}
    assert s["files"] == {"online": tmp_path / "out" / "customer"
                          / "SOP_for_customer_electronic.xlsx"}

    ws = load_workbook(s["files"]["online"]).active
    names = [c.value for c in ws[1]]
    assert names == HEADERS + s["columns"]["online"]
    assert [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)] == [
        "Paid", "Paid 2", "Odd cost"]                      # unparseable cost is kept
    org = names.index("FOLIO Org") + 1
    for r in range(1, ws.max_row + 1):                     # whole column highlighted
        assert ws.cell(row=r, column=org).fill.start_color.rgb.endswith("FFFFCC")
        assert ws.cell(row=r, column=1).fill.fill_type is None
    assert ws.cell(row=2, column=org).value is None        # left for the customer

    removed = list(csv.reader(open(tmp_path / "out" / "customer"
                                   / "SOP_zero_dollar_removed.csv", encoding="utf-8")))
    assert removed[0] == ["sheet_row", "title", "order_number", "in_a_package"]
    assert [(r[0], r[1], r[3]) for r in removed[1:]] == [
        ("3", "Free journal", "No"), ("4", "Package member", "Yes"),
        ("5", "Blank cost", "No")]
    report = (tmp_path / "out" / "customer" / "SOP_for_customer_report.txt").read_text(
        encoding="utf-8")
    assert "Zero-dollar lines removed: 3 (1 in a package)" in report


def test_stage1_does_not_duplicate_columns_already_in_the_sop(cfg, tmp_path):
    headers = HEADERS + ["FOLIO Fund"]
    src = tmp_path / "SOP.xlsx"
    make_sop(src, [dict(ROWS[0], **{"FOLIO Fund": "F1"})], headers)
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    names = [c.value for c in load_workbook(s["files"]["online"]).active[1]]
    assert names.count("FOLIO Fund") == 1
    assert load_workbook(s["files"]["online"]).active.cell(
        row=2, column=names.index("FOLIO Fund") + 1).value == "F1"


def test_stage1_leaves_out_expense_class_when_not_used(cfg, tmp_path):
    cfg["rules"]["use_expense_classes"] = False
    src = tmp_path / "SOP.xlsx"
    make_sop(src, ROWS[:1])
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    assert s["columns"]["online"][:3] == ["FOLIO Org", "FOLIO Fund", "FOLIO Order Type"]


def test_build_uses_the_filled_in_columns(cfg, tmp_path, capsys):
    """Stage 2 on a spreadsheet the customer has filled in."""
    headers = ["Title Name", "ISSN", "Format", "Start Date", "Expiration Date",
               "Order Number", "Total Cost", "Publisher Package", "Publisher Name",
               "Subject Category", "FOLIO Org", "FOLIO Fund", "FOLIO Expense Class"]
    row = {"Title Name": "Journal", "ISSN": "1234-5678", "Format": "Online Only",
           "Start Date": "01/01/2026", "Expiration Date": "12/31/2026",
           "Order Number": "U1", "Total Cost": 50, "Publisher Name": "Pub",
           "Subject Category": "Art", "FOLIO Org": "MYORG", "FOLIO Fund": "MYFUND",
           "FOLIO Expense Class": "MYEC"}
    src = tmp_path / "filled.xlsx"
    make_sop(src, [row], headers)
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text((ROOT / "ebsconet_config.json").read_text(encoding="utf-8"),
                        encoding="utf-8")
    rc = cli.main(["--config", str(cfg_path), "--out", str(tmp_path / "out"),
                   "build", str(src)])
    assert rc == 0                      # (the tag map path is relative to the repo root)
    mrk = (tmp_path / "out" / "marc" / "library-EBSCONET_online.mrk").read_text(
        encoding="utf-8")
    assert "$fMYFUND" in mrk and "$eMYEC" in mrk and "$vMYORG" in mrk
    assert "customer column present; blank on 0 of 1" in (
        tmp_path / "out" / "prep_report.txt").read_text(encoding="utf-8")


class Recorder:
    def __init__(self, result=0):
        self.calls, self.result = [], result

    def __call__(self, argv):
        self.calls.append(argv)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def marc_dir(tmp_path, routes):
    folder = tmp_path / "marc"
    folder.mkdir()
    names = {"online": "library-EBSCONET_online.mrc", "print": "library-EBSCONET-print.mrc",
             "pe": "library-EBSCONET_P-E.mrc"}
    for r in routes:
        (folder / names[r]).write_bytes(b"")
    return tmp_path


def test_load_runs_each_file_with_its_own_job_profile(tmp_path, monkeypatch, capsys):
    from pipeline import folio_import
    rec = Recorder()
    monkeypatch.setattr(folio_import, "main", rec)
    out = marc_dir(tmp_path, ["online", "pe"])
    rc = cli.main(["--out", str(out), "load", "--use-marc", "--ini", "t.ini", "--live"])
    assert rc == 0 and len(rec.calls) == 2
    first, second = rec.calls
    assert first[0].endswith("library-EBSCONET_online.mrc")
    assert first[first.index("--job-profile") + 1] == "EBSCONET order migration - Online"
    assert second[second.index("--job-profile") + 1] == "EBSCONET order migration - P-E"
    assert "--live" in first and "--skip-preflight" not in first


def test_load_only_and_flags(tmp_path, monkeypatch):
    from pipeline import folio_import
    rec = Recorder()
    monkeypatch.setattr(folio_import, "main", rec)
    out = marc_dir(tmp_path, ["online", "print"])
    cli.main(["--out", str(out), "load", "--use-marc", "--ini", "t.ini", "--only", "print",
              "--no-cleanup", "--skip-preflight"])
    assert len(rec.calls) == 1 and rec.calls[0][0].endswith("library-EBSCONET-print.mrc")
    assert "--live" not in rec.calls[0]
    assert "--no-cleanup" in rec.calls[0] and "--skip-preflight" in rec.calls[0]


def test_load_reports_a_stopped_file_and_carries_on(tmp_path, monkeypatch, capsys):
    from pipeline import folio_import
    results = iter([SystemExit("preflight found errors"), 0])

    def fake(argv):
        r = next(results)
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(folio_import, "main", fake)
    out = marc_dir(tmp_path, ["online", "pe"])
    rc = cli.main(["--out", str(out), "load", "--use-marc", "--ini", "t.ini"])
    text = capsys.readouterr().out
    assert rc == 1
    assert "preflight found errors" in text and "online PROBLEM, pe ok" in text


def test_load_without_marc_files_says_so(tmp_path, capsys):
    assert cli.main(["--out", str(tmp_path), "load", "--use-marc",
                     "--ini", "t.ini"]) == 1
    assert "run `build` first" in capsys.readouterr().out


def test_load_defaults_to_the_orders_api(tmp_path, monkeypatch, capsys):
    from pipeline import folio_import, folio_orders_adapter as adapter
    calls = []

    def fake(in_dir, ini, cfg, live, skip_accounts=False):
        calls.append((in_dir, ini, live, skip_accounts))
        return [("A1", "created", "A1-1"), ("A2", "error", "boom")]

    monkeypatch.setattr(adapter, "load_orders", fake)
    monkeypatch.setattr(folio_import, "main", lambda argv: pytest.fail("MARC used"))
    rc = cli.main(["--out", str(tmp_path), "load", "--ini", "t.ini", "--live",
                   "--skip-accounts"])
    text = capsys.readouterr().out
    assert calls == [(str(tmp_path), "t.ini", True, True)]
    assert rc == 1 and "ERROR A2: boom" in text and "created 1" in text


def test_api_load_succeeds_when_nothing_is_bad(tmp_path, monkeypatch):
    from pipeline import folio_orders_adapter as adapter
    monkeypatch.setattr(adapter, "load_orders",
                        lambda *a, **k: [("A1", "dry-run", "1 line(s)"), ("A2", "exists", "")])
    assert cli.main(["--out", str(tmp_path), "load", "--ini", "t.ini"]) == 0


def test_finish_api_route_exports_without_ongoing_conversion(tmp_path, monkeypatch):
    from pipeline import folio_export_pols, folio_ongoing, folio_common
    from pipeline import folio_orders_adapter as adapter
    monkeypatch.setattr(adapter, "workbook_lines",
                        lambda d, c: [{"po_number": "A1"}, {"po_number": "A1"},
                                      {"po_number": "A2"}])
    monkeypatch.setattr(folio_common, "connect", lambda ini: object())
    monkeypatch.setattr(folio_ongoing, "convert_all",
                        lambda *a, **k: pytest.fail("ongoing conversion ran"))
    seen = {}

    def fetch(client, po_numbers):
        seen["numbers"] = po_numbers
        return []

    monkeypatch.setattr(folio_export_pols, "fetch_lines", fetch)
    monkeypatch.setattr(folio_export_pols, "export_rows", lambda lines: [])
    monkeypatch.setattr(folio_export_pols, "write_csv", lambda path, rows: None)
    assert cli.main(["--out", str(tmp_path), "finish", "--ini", "t.ini"]) == 0
    assert seen["numbers"] == ["A1", "A2"]


def test_setup_passes_its_options_through(monkeypatch):
    from pipeline import folio_setup
    rec = Recorder()
    monkeypatch.setattr(folio_setup, "main", rec)
    cli.main(["setup", "--ini", "t.ini", "--live", "--update-mappings"])
    argv = rec.calls[0]
    assert argv[argv.index("--ini") + 1] == "t.ini"
    assert "--live" in argv and "--update-mappings" in argv


def test_every_stage_has_a_subcommand():
    parser = cli.build_parser()
    for name in ("for-customer", "build", "setup", "load", "finish"):
        assert name in parser.format_help()


SPLIT_HEADERS = HEADERS + ["Order Type"]      # the SOP's own (ignored) Order Type column
SPLIT_ROWS = [
    {"Title Name": "E1", "Format": "Online Only", "Order Number": "E1", "Total Cost": 10},
    {"Title Name": "E2", "Format": "Database", "Order Number": "E2", "Total Cost": 10},
    {"Title Name": "P1", "Format": "Print", "Order Number": "P1", "Total Cost": 10},
    {"Title Name": "B1", "Format": "Print + Online", "Order Number": "B1",
     "Total Cost": 10},
    {"Title Name": "Fee", "Format": "Fee", "Order Number": "F1", "Total Cost": 10},
    {"Title Name": "Odd", "Format": "Carrier pigeon", "Order Number": "O1",
     "Total Cost": 10},
]


def test_stage1_writes_one_spreadsheet_per_type_with_its_own_columns(cfg, tmp_path):
    src = tmp_path / "SOP.xlsx"
    make_sop(src, SPLIT_ROWS, SPLIT_HEADERS)
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    assert s["counts"] == {"online": 2, "print": 1, "pe": 1}
    assert s["unrouted"] == 2
    assert sorted(p.name for p in s["files"].values()) == [
        "SOP_for_customer_P-E.xlsx", "SOP_for_customer_electronic.xlsx",
        "SOP_for_customer_physical.xlsx"]
    added = {r: load_workbook(p).active[1] for r, p in s["files"].items()}
    added = {r: [c.value for c in row][len(SPLIT_HEADERS):] for r, row in added.items()}
    assert added["online"] == ["FOLIO Org", "FOLIO Fund", "FOLIO Expense Class",
                               "FOLIO Order Type", "FOLIO Renewal Interval (Days)"]
    assert added["pe"] == added["online"] + ["FOLIO Location", "FOLIO Material Type"]
    assert added["print"] == added["pe"]        # physical asks the same questions
    titles = [r[0].value for r in load_workbook(s["files"]["online"]).active.iter_rows(
        min_row=2)]
    assert titles == ["E1", "E2"]
    not_sent = list(csv.reader(open(tmp_path / "out" / "customer" / "SOP_not_sent.csv",
                                    encoding="utf-8")))
    assert [(r[1], r[4]) for r in not_sent[1:]] == [("Fee", "Fee"),
                                                    ("Odd", "Unrecognized format")]


def test_stage1_order_type_is_a_drop_down_and_interval_a_whole_number(cfg, tmp_path):
    src = tmp_path / "SOP.xlsx"
    make_sop(src, SPLIT_ROWS, SPLIT_HEADERS)
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    ws = load_workbook(s["files"]["pe"]).active
    names = [c.value for c in ws[1]]
    letter = lambda name: ws.cell(row=1, column=names.index(name) + 1).column_letter  # noqa
    checks = {str(dv.sqref): dv for dv in ws.data_validations.dataValidation}
    order = checks["%s2:%s1000" % ((letter("FOLIO Order Type"),) * 2)]
    assert (order.type, order.formula1, order.showErrorMessage) == (
        "list", '"Ongoing,One-Time"', True)
    days = checks["%s2:%s1000" % ((letter("FOLIO Renewal Interval (Days)"),) * 2)]
    assert (days.type, days.operator, days.formula1) == ("whole", "greaterThan", "0")
    loc = checks["%s2:%s1000" % ((letter("FOLIO Location"),) * 2)]
    assert loc.type == "list" and "TEST-EBSCONET-LOC" in loc.formula1
    phys = load_workbook(s["files"]["print"]).active
    assert len(phys.data_validations.dataValidation) == 4     # type, days, loc, material


def test_stage1_makes_no_file_for_a_type_with_no_lines(cfg, tmp_path):
    src = tmp_path / "SOP.xlsx"
    make_sop(src, SPLIT_ROWS[:2], SPLIT_HEADERS)
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    assert list(s["files"]) == ["online"]


def test_build_combines_the_three_files_and_writes_order_settings(cfg, tmp_path):
    extra = ["FOLIO Fund", "FOLIO Order Type", "FOLIO Renewal Interval (Days)",
             "FOLIO Location", "FOLIO Material Type"]
    hdr = ["Title Name", "ISSN", "Format", "Order Number", "Total Cost"] + extra

    def row(title, fmt, order, **cols):
        return dict({"Title Name": title, "ISSN": "1234-5678", "Format": fmt,
                     "Order Number": order, "Total Cost": 5, "FOLIO Fund": "F1"}, **cols)
    elec, phys, both = (tmp_path / "e.xlsx", tmp_path / "p.xlsx", tmp_path / "b.xlsx")
    make_sop(elec, [row("E1", "Online Only", "E1", **{"FOLIO Order Type": "Ongoing",
                                                      "FOLIO Renewal Interval (Days)": 90}),
                    row("E2", "Online Only", "E2", **{"FOLIO Order Type": "one time",
                                                      "FOLIO Renewal Interval (Days)": 30}),
                    row("E3", "Online Only", "E3")], hdr)
    make_sop(phys, [row("P1", "Print", "P1", **{"FOLIO Location": "Main (MAIN)",
                                                "FOLIO Material Type": "book"}),
                    row("P2", "Print", "P2")], hdr)
    make_sop(both, [row("B1", "Print + Online", "B1", **{"FOLIO Order Type": "Ongoing",
                                                         "FOLIO Location": "Annex (ANX)"})],
             hdr)
    s = prep.prepare([elec, phys, both], tmp_path / "out", cfg)
    assert s["routed"] == {"online": 3, "print": 2, "pe": 1}

    settings = list(csv.DictReader(open(tmp_path / "out" / "order_settings.csv",
                                        encoding="utf-8")))
    assert [(r["order_number"], r["order_type"], r["interval_days"]) for r in settings] == [
        ("E1", "Ongoing", "90"), ("E2", "One-Time", ""),       # customer's choices
        ("E3", "Ongoing", "365"), ("P1", "Ongoing", "365"),    # blank -> defaults
        ("P2", "Ongoing", "365"), ("B1", "Ongoing", "365")]
    rows = {r["Order Number"]: r for r in (
        dict(zip([c.value for c in ws[1]], [c.value for c in r]))
        for ws in (load_workbook(tmp_path / "out" / cfg["output_names"][k]).active
                   for k in ("print", "pe")) for r in ws.iter_rows(min_row=2))}
    assert (rows["P1"]["FOLIO Location"], rows["P1"]["FOLIO Material Type"]) == (
        "Main (MAIN)", "book")
    assert (rows["P2"]["FOLIO Location"], rows["P2"]["FOLIO Material Type"]) == (
        cfg["folio"]["location"], cfg["folio"]["physical_material_type"])   # defaults
    assert rows["B1"]["FOLIO Location"] == "Annex (ANX)"
    report = (tmp_path / "out" / "prep_report.txt").read_text(encoding="utf-8")
    assert "Orders: 5 ongoing, 1 one-time" in report
    results = cli.convert_all(tmp_path / "out", cfg, cfg["headers_file"])
    assert sum(r["records"] for r in results) == 6
    from pymarc import MARCReader
    with open(tmp_path / "out" / "marc" / (Path(cfg["output_names"]["print"]).stem
                                           + ".mrc"), "rb") as fh:
        recs = list(MARCReader(fh, to_unicode=True, force_utf8=True))
    assert recs[0]["990"]["l"] == "Main (MAIN)" and recs[0]["990"]["m"] == "book"


def test_bad_order_type_and_interval_fall_back_with_warnings(cfg):
    row = {"_row": 7, "FOLIO Order Type": "monthly",
           "FOLIO Renewal Interval (Days)": "soon"}
    assert prep.order_settings(row, cfg)[:2] == ("Ongoing", 365)
    assert len(prep.order_settings(row, cfg)[2]) == 2
    row = {"_row": 8, "FOLIO Order Type": "Ongoing", "FOLIO Renewal Interval (Days)": 45.0}
    assert prep.order_settings(row, cfg) == ("Ongoing", 45, [])
