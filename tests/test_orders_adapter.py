from pipeline.ebsconet_prep import load_config
from pipeline.folio_orders_adapter import row_to_line

CFG = load_config("ebsconet_config.json")

ROW = {
    "Title Name": "Some Journal", "ISSN": "1938-3207", "Order Number": "S0110567",
    "Total Cost": 715.28, "Start Date": "2026-01-01",
    "Expiration Date": "2026-12-31", "Publisher Name": "Elsevier",
    "Cancellable": "No", "FOLIO Org": "EBSCO", "FOLIO Fund": "TEST-ELEC",
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
