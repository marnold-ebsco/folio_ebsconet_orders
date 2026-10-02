from pipeline.ebsconet_prep import load_config
from pipeline.folio_orders_adapter import row_to_line

CFG = load_config("ebsconet_config.json")

ROW = {
    "Title Name": "Some Journal", "ISSN": "1938-3207", "Order Number": "S0110567",
    "Total Cost": 715.28, "Start Date": "2026-01-01",
    "Expiration Date": "2026-12-31", "Publisher Name": "Elsevier",
    "Cancellable": "No", "FOLIO Access Provider": "EBSCO", "FOLIO Fund": "TEST-ELEC",
    "FOLIO Expense Class": "GEN", "FOLIO Order Type": "Ongoing",
    "FOLIO Renewal Interval (Days)": 180,
    "Account Number": "XW14722-82",
    "Title Number": "31525", "Title Number Type": "Publisher or distributor number",
}


def test_online_row():
    line = row_to_line(ROW, "online", CFG)
    assert line["po_number"] == "S0110567"
    assert line["order_format"] == "Electronic Resource"
    assert line["cost"] == "715.28"
    assert line["interval_days"] == 180
    assert line["product_ids"] == [
        {"type": "ISSN", "value": "1938-3207"},
        {"type": "Publisher or distributor number", "value": "31525"}]
    assert line["vendor_account"] == "XW14722-82"
    assert "material_type" not in line


def test_physical_row_gets_location_and_material_type():
    row = dict(ROW, **{"FOLIO Order Type": "One-Time", "FOLIO Location": "LOC1"})
    line = row_to_line(row, "print", CFG)
    assert line["order_format"] == "Physical Resource"
    assert line["location_code"] == "LOC1"
    assert line["material_type"] == CFG["folio"]["physical_material_type"]
    assert "interval_days" not in line


def test_location_code_extracts_parenthesised_code():
    from pipeline.folio_orders_adapter import location_code
    assert location_code("test_loc (TEST-LOC)") == "TEST-LOC"
    assert location_code("TEST-LOC") == "TEST-LOC"


def test_blank_account_number_is_omitted():
    line = row_to_line(dict(ROW, **{"Account Number": None}), "online", CFG)
    assert "vendor_account" not in line


class FakeClient:
    def __init__(self, orgs):
        self.orgs = orgs
        self.puts = []

    def folio_get(self, path, key=None, query_params=None):
        code = query_params["query"].split('"')[1]
        return [o for o in self.orgs if o["code"] == code]

    def folio_put(self, path, payload):
        self.puts.append((path, payload))


def test_accounts_by_org_groups_and_skips_blank():
    from pipeline.folio_orders_adapter import accounts_by_org
    lines = [{"vendor_code": "A", "vendor_account": "2"},
             {"vendor_code": "A", "vendor_account": "1"},
             {"vendor_code": "A", "vendor_account": "1"},
             {"vendor_code": "B"}]
    assert accounts_by_org(lines) == {"A": ["1", "2"]}


def test_ensure_accounts_adds_missing_only_when_live():
    from pipeline.folio_orders_adapter import ensure_accounts
    org = {"id": "o1", "code": "A", "accounts": [{"accountNo": "1"}]}
    lines = [{"vendor_code": "A", "vendor_account": "1"},
             {"vendor_code": "A", "vendor_account": "2"},
             {"vendor_code": "ZZ", "vendor_account": "9"}]
    dry = FakeClient([org])
    assert ensure_accounts(dry, lines, "Other", False) == [
        ("A", ["2"], ["1"]), ("ZZ", None, [])]
    assert dry.puts == []
    live = FakeClient([org])
    ensure_accounts(live, lines, "Other", True)
    path, payload = live.puts[0]
    assert path.endswith("/o1")
    assert [a["accountNo"] for a in payload["accounts"]] == ["1", "2"]


def test_accounts_log_is_timestamped_and_lists_accounts(tmp_path):
    from datetime import datetime, timedelta
    from pipeline.folio_orders_adapter import format_elapsed, write_accounts_log
    start = datetime(2026, 10, 1, 14, 5, 9)
    report = [("EBSCO", ["A1", "A2"], ["A0"]), ("GONE", None, [])]
    path = write_accounts_log(tmp_path / "logs", start, start + timedelta(seconds=75),
                              True, "/x/tenant.ini", "out", report)
    assert path.name == "accounts_20261001_140509.txt"
    text = path.read_text(encoding="utf-8")
    assert "Started:   2026-10-01 14:05:09" in text and "Elapsed:   0:01:15" in text
    assert "added: A1" in text and "already present: A0" in text
    assert "GONE: ORGANIZATION NOT FOUND" in text and "tenant.ini" in text
    assert "/x/" not in text and "accounts added: 2" in text
    dry = write_accounts_log(tmp_path, start, start, False, "t.ini", "out", report)
    assert "DRY RUN" in dry.read_text(encoding="utf-8")
    assert format_elapsed(3725) == "1:02:05"


def test_expense_class_passes_through_when_enabled():
    assert row_to_line(ROW, "online", CFG)["expense_class_code"] == "GEN"


def test_no_expense_class_when_disabled():
    cfg = {**CFG, "rules": {**CFG["rules"], "use_expense_classes": False}}
    assert not row_to_line(ROW, "online", cfg)["expense_class_code"]


def test_open_access_becomes_a_tag_and_your_access_a_receiving_note():
    line = row_to_line(dict(ROW, **{"Open Access": "Yes",
                                    "Your Access": "All content from 01/01/1997 to present"}),
                       "online", CFG)
    assert line["line_tags"] == ["Open Access"]
    assert line["receiving_note"] == "All content from 01/01/1997 to present"
    line = row_to_line(dict(ROW, **{"Open Access": "No", "Your Access": None}),
                       "online", CFG)
    assert "line_tags" not in line and "receiving_note" not in line


def test_vendor_is_always_the_ebsconet_org_and_the_cell_is_the_access_provider():
    line = row_to_line(dict(ROW, **{"FOLIO Access Provider": "ELSEVIER"}), "online", CFG)
    assert line["vendor_code"] == CFG["folio"]["vendor_org_code"]
    assert line["access_provider_code"] == "ELSEVIER"


def test_blank_access_provider_stays_blank_and_print_has_none():
    blank = dict(ROW, **{"FOLIO Access Provider": ""})
    assert "access_provider_code" not in row_to_line(blank, "pe", CFG)
    line = row_to_line(dict(blank, **{"FOLIO Order Type": "One-Time"}), "print", CFG)
    assert "access_provider_code" not in line
    assert line["vendor_code"] == CFG["folio"]["vendor_org_code"]


def test_quantity_splits_total_into_unit_prices_only_when_exact():
    line = row_to_line(dict(ROW, Quantity=3, **{"Total Cost": 30}), "online", CFG)
    assert line["cost"] == "10.00" and line["quantity_electronic"] == 3
    line = row_to_line(dict(ROW, Quantity=3, **{"Total Cost": 10}), "print", CFG)
    assert line["cost"] == "10" and "quantity_physical" not in line


def test_currency_row_value_or_config_fallback():
    assert row_to_line(dict(ROW, Currency="gbp"), "online", CFG)["currency"] == "GBP"
    assert row_to_line(dict(ROW, Currency="?"), "online", CFG)["currency"] == "USD"


def test_url_package_and_po_number_mappings():
    row = dict(ROW, URL="https://x.org", **{"Package?": "Yes",
                                            "Purchase Order Number": "2026 WRSHN"})
    line = row_to_line(row, "online", CFG)
    assert line["resource_url"] == "https://x.org" and line["is_package"] is True
    assert line["vendor_reference_number"] == "2026 WRSHN"
    assert line["vendor_reference_type"] == "Vendor order reference number"
    assert "resource_url" not in row_to_line(row, "print", CFG)


def test_load_log_has_totals_problems_and_csv(tmp_path):
    from datetime import datetime, timedelta
    from pipeline.folio_orders_adapter import write_load_log
    start = datetime(2026, 10, 2, 9, 0, 0)
    results = [("A1", "dry-run", ""), ("A2", "invalid", "no Active budget"),
               ("A3", "dry-run", "")]
    txt = write_load_log(tmp_path / "logs", start, start + timedelta(seconds=75), False,
                         "/x/t.ini", "out", 5, results)
    text = txt.read_text()
    assert txt.name == "load_20261002_090000.txt"
    assert "DRY RUN" in text and "Elapsed:   0:01:15" in text and "t.ini" in text
    assert "Lines: 5; POs: 3" in text and "  dry-run: 2" in text and "  invalid: 1" in text
    assert "1 PO(s) need attention" in text and "A2  invalid  no Active budget" in text
    rows = txt.with_suffix(".csv").read_text().splitlines()
    assert rows[0] == "po_number,status,detail" and len(rows) == 4
    ok = write_load_log(tmp_path, start, start, True, "t.ini", "out", 1, [("B", "created", "")])
    assert "No PO needs attention" in ok.read_text()
