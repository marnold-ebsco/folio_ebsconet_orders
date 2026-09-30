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
