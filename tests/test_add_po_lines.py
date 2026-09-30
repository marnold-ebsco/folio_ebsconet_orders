import copy
import sys
from pathlib import Path

import pytest
from pymarc import Field, Record, Subfield

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folio_add_po_lines as al  # noqa: E402

IDS = {"fund": lambda c: "fund-" + c, "expense_class": lambda c: "ec-" + c,
       "org": lambda c: "org-" + c, "identifier_type": lambda n: "type-" + n}


def vals(**over):
    d = {"order": "P1", "title": "Second Journal", "issn": "1111-2222", "url": "http://x.org",
         "publisher": "Pub", "description": "Site License; Monthly", "cancel": "true",
         "cost": "500.00", "fund": "F1", "expense_class": "GEN", "account": "ACC2",
         "start": "2026-01-01", "end": "2026-12-31", "org": "EBSCO",
         "title_number": "T9", "title_number_type": "Publisher or distributor number"}
    d.update(over)
    return d


def template(fmt="Electronic Resource"):
    return {
        "id": "l1", "poLineNumber": "P1-1", "purchaseOrderId": "o1", "metadata": {"x": 1},
        "titleOrPackage": "First Journal", "orderFormat": fmt, "receiptStatus": "Pending",
        "acquisitionMethod": "acq-id", "checkinItems": True, "source": "MARC",
        "publisher": "Old Pub", "locations": [{"locationId": "loc"}],
        "physical": {"materialType": "mt"},
        "cost": {"currency": "USD", "listUnitPriceElectronic": 10.0, "quantityElectronic": 1,
                 "poLineEstimatedPrice": 10.0, "discountType": "percentage"},
        "details": {"productIds": [{"productId": "old"}], "subscriptionInterval": 1},
        "fundDistribution": [{"code": "OLD", "fundId": "old", "value": 100.0}],
        "vendorDetail": {"vendorAccount": "ACC1", "referenceNumbers": []},
        "eresource": {"activated": True, "accessProvider": "old", "resourceUrl": "http://old"},
    }


def test_build_line_swaps_in_the_records_values_and_keeps_the_rest():
    t = template()
    line = al.build_line(t, vals(), IDS)
    assert "id" not in line and "poLineNumber" not in line and "metadata" not in line
    assert line["purchaseOrderId"] == "o1"                 # kept from the copy
    assert line["titleOrPackage"] == "Second Journal" and line["publisher"] == "Pub"
    assert line["description"] == "Site License; Monthly"
    assert line["cancellationRestriction"] is True
    assert line["details"]["productIds"] == [
        {"productId": "1111-2222", "productIdType": "type-ISSN"},
        {"productId": "T9", "productIdType": "type-Publisher or distributor number"}]
    assert line["details"]["subscriptionFrom"] == "2026-01-01T00:00:00.000+00:00"
    assert line["details"]["subscriptionTo"] == "2026-12-31T00:00:00.000+00:00"
    assert line["details"]["subscriptionInterval"] == 1
    assert line["fundDistribution"] == [{"code": "F1", "fundId": "fund-F1",
                                         "distributionType": "percentage", "value": 100.0,
                                         "expenseClassId": "ec-GEN"}]
    assert line["vendorDetail"]["vendorAccount"] == "ACC2"
    assert line["eresource"] == {"activated": True, "accessProvider": "org-EBSCO",
                                 "resourceUrl": "http://x.org"}
    # format, receipt, acquisition method and locations come from the existing line
    assert (line["orderFormat"], line["receiptStatus"], line["acquisitionMethod"]) == (
        "Electronic Resource", "Pending", "acq-id")
    assert line["locations"] == [{"locationId": "loc"}]
    assert t["titleOrPackage"] == "First Journal"          # the template is untouched


@pytest.mark.parametrize("fmt,expect", [
    ("Electronic Resource", {"listUnitPriceElectronic": 500.0}),
    ("Physical Resource", {"listUnitPrice": 500.0}),
    ("P/E Mix", {"listUnitPrice": 500.0, "listUnitPriceElectronic": 0.0})])
def test_price_goes_where_the_import_profile_puts_it(fmt, expect):
    cost = al.build_line(template(fmt), vals(), IDS)["cost"]
    for k, v in expect.items():
        assert cost[k] == v
    assert "poLineEstimatedPrice" not in cost
    if fmt == "Electronic Resource":
        assert "listUnitPrice" not in cost
    if fmt == "Physical Resource":
        assert "listUnitPriceElectronic" not in cost


def test_missing_optional_values_are_left_out():
    line = al.build_line(template(), vals(issn="", title_number="", expense_class="",
                                          description="", publisher="", cancel="",
                                          start="", end="", url="", org=""), IDS)
    assert line["details"]["productIds"] == []           # never an empty product ID
    assert "expenseClassId" not in line["fundDistribution"][0]
    assert "description" not in line and "publisher" not in line
    assert "subscriptionFrom" not in line["details"]
    assert line["eresource"]["accessProvider"] == "old"   # copied value not overwritten


class FakeClient:
    def __init__(self, status="Pending", lines=None, has_po=True):
        self.status, self.has_po = status, has_po
        self.lines = lines if lines is not None else [template()]
        self.posts = []

    def folio_get(self, path, key=None, query_params=None, **kw):
        if key == "purchaseOrders":
            return [{"id": "o1"}] if self.has_po else []
        if key == "poLines":
            return [dict(ln, id="l%d" % i) for i, ln in enumerate(self.lines, 1)]
        if path.startswith("/orders/composite-orders/"):
            return {"id": "o1", "workflowStatus": self.status}
        return copy.deepcopy(self.lines[0])

    def folio_post(self, path, payload, **kw):
        self.posts.append((path, payload))
        return {"poLineNumber": "P1-%d" % (len(self.lines) + 1)}


def run(client, recs=None, live=False, limit=None):
    return al.add_lines(client, recs or [vals()], live, limit, IDS)


def test_dry_run_adds_nothing():
    c = FakeClient()
    assert run(c) == [("P1", "Second Journal", "would-add", "as line 2")]
    assert c.posts == []


def test_live_posts_the_new_line():
    c = FakeClient()
    res = run(c, live=True)
    assert res == [("P1", "Second Journal", "added", "P1-2")]
    path, payload = c.posts[0]
    assert path == "/orders/order-lines" and payload["purchaseOrderId"] == "o1"
    assert payload["titleOrPackage"] == "Second Journal"


def test_rerun_is_a_no_op_when_the_title_is_already_on_the_po():
    c = FakeClient(lines=[template(), dict(template(), titleOrPackage="second journal")])
    assert run(c, live=True)[0][2] == "already-present"
    assert c.posts == []


def test_skips():
    assert run(FakeClient(has_po=False))[0][2] == "no-po"
    res = run(FakeClient(status="Open"), live=True)[0]
    assert res[2] == "skipped" and "Open" in res[3]
    assert run(FakeClient(lines=[]))[0][2] == "no-lines"


def test_tenant_limit_blocks_the_extra_line():
    c = FakeClient()
    res = run(c, live=True, limit=1)[0]
    assert res[2] == "limit" and "limit is 1" in res[3]
    assert c.posts == []
    assert run(FakeClient(), limit=2)[0][2] == "would-add"


def test_lookup_failure_is_reported_not_raised():
    def boom(code):
        raise LookupError("fund %r not found in FOLIO" % code)

    res = al.add_lines(FakeClient(), [vals()], True, None, dict(IDS, fund=boom))
    assert res[0][2] == "error" and "not found" in res[0][3]


def test_read_values_from_marc(tmp_path):
    r = Record(force_utf8=True)
    r.leader = "00000nas a2200000   4500"
    r.add_field(Field(tag="020", indicators=[" ", " "], subfields=[Subfield("a", "1111-2222")]))
    r.add_field(Field(tag="245", indicators=["0", "0"], subfields=[Subfield("a", "Title")]))
    r.add_field(Field(tag="264", indicators=[" ", "1"], subfields=[Subfield("a", "Pub")]))
    r.add_field(Field(tag="980", indicators=[" ", " "], subfields=[
        Subfield("d", "Site License"), Subfield("k", "false")]))
    r.add_field(Field(tag="990", indicators=[" ", " "], subfields=[
        Subfield("o", "P9"), Subfield("c", "5.00"), Subfield("f", "F"),
        Subfield("a", "ACC"), Subfield("s", "2026-01-01")]))
    path = tmp_path / "a.mrc"
    path.write_bytes(r.as_marc())
    [v] = al.read_values(path)
    assert (v["title"], v["issn"], v["publisher"], v["order"], v["cost"], v["fund"],
            v["account"], v["start"], v["description"], v["cancel"]) == (
        "Title", "1111-2222", "Pub", "P9", "5.00", "F", "ACC", "2026-01-01",
        "Site License", "false")
    assert v["title_number"] == "" and v["url"] == "" and v["expense_class"] == ""
