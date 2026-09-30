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
    {"Title Name": "Paid 2", "Order Number": "E", "Total Cost": "1,200.00"},
    {"Title Name": "Odd cost", "Order Number": "F", "Total Cost": "n/a"},
]


def test_stage1_removes_zero_dollar_lines_and_adds_highlighted_columns(cfg, tmp_path):
    src = tmp_path / "SOP.xlsx"
    make_sop(src, ROWS)
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    assert (s["read"], s["removed"], s["kept"]) == (6, 3, 3)
    assert s["columns"] == ["FOLIO Org", "FOLIO Fund", "FOLIO Expense Class"]
    assert s["file"] == tmp_path / "out" / "customer" / "SOP_for_customer.xlsx"

    ws = load_workbook(s["file"]).active
    names = [c.value for c in ws[1]]
    assert names == HEADERS + s["columns"]
    assert [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)] == [
        "Paid", "Paid 2", "Odd cost"]                      # unparseable cost is kept
    org = names.index("FOLIO Org") + 1
    for r in range(1, ws.max_row + 1):                     # whole column highlighted
        assert ws.cell(row=r, column=org).fill.start_color.rgb.endswith("FFFF00")
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
    names = [c.value for c in load_workbook(s["file"]).active[1]]
    assert names.count("FOLIO Fund") == 1
    assert load_workbook(s["file"]).active.cell(
        row=2, column=names.index("FOLIO Fund") + 1).value == "F1"


def test_stage1_leaves_out_expense_class_when_not_used(cfg, tmp_path):
    cfg["rules"]["use_expense_classes"] = False
    src = tmp_path / "SOP.xlsx"
    make_sop(src, ROWS[:1])
    s = cli.prepare_for_customer(src, tmp_path / "out", cfg)
    assert s["columns"] == ["FOLIO Org", "FOLIO Fund"]


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
    rc = cli.main(["--out", str(out), "load", "--ini", "t.ini", "--live"])
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
    cli.main(["--out", str(out), "load", "--ini", "t.ini", "--only", "print",
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
    rc = cli.main(["--out", str(out), "load", "--ini", "t.ini"])
    text = capsys.readouterr().out
    assert rc == 1
    assert "preflight found errors" in text and "online PROBLEM, pe ok" in text


def test_load_without_marc_files_says_so(tmp_path, capsys):
    assert cli.main(["--out", str(tmp_path), "load", "--ini", "t.ini"]) == 1
    assert "run `build` first" in capsys.readouterr().out


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
