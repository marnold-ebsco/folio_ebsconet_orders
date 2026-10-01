import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import folio_setup as fs  # noqa: E402
from pipeline.ebsconet_prep import load_config  # noqa: E402

VENDOR = "b5f89734-a475-4d12-9442-c1ce131c5ed1"


@pytest.fixture
def cfg():
    return load_config(ROOT / "ebsconet_config.json")


def template(route):
    path = ROOT / "template_profiles" / fs.TEMPLATE_FOR[route]
    return json.loads(path.read_text(encoding="utf-8"))


def build(route, cfg):
    return fs.build_mapping_profile(route, template(route), cfg, VENDOR)


def by_path(profile):
    return {f["path"]: f for f in profile["mappingDetails"]["mappingFields"]}


def sub(field):
    return [{f["name"]: f["value"] for f in s["fields"]} for s in field["subfields"]]


@pytest.mark.parametrize("route", fs.ROUTES)
def test_common_po_and_pol_values(route, cfg):
    p = build(route, cfg)
    f = by_path(p)
    assert p["name"] == "EBSCONET order migration - " + fs.ROUTE_LABEL[route]
    assert p["description"] == "Used for EBSCONET order migration"
    assert p["incomingRecordType"] == "MARC_BIBLIOGRAPHIC"
    assert p["existingRecordType"] == "ORDER"
    assert "id" not in p and "metadata" not in p and "userInfo" not in p
    assert f["order.po.workflowStatus"]["value"] == '"Pending"'
    assert f["order.po.approved"]["booleanFieldAction"] == "ALL_TRUE"
    assert f["order.po.overridePoLinesLimit"]["value"] == '"1"'
    assert f["order.po.poNumber"]["value"] == "990$o"
    assert f["order.po.vendor"]["value"] == '"%s"' % VENDOR
    assert f["order.poLine.titleOrPackage"]["value"] == "245$a"
    assert f["order.poLine.details.subscriptionFrom"]["value"] == "990$s"
    assert f["order.poLine.details.subscriptionTo"]["value"] == "990$t"
    assert f["order.poLine.details.subscriptionInterval"]["value"] == '"1"'
    assert f["order.poLine.publisher"]["value"] == "264$a"
    assert f["order.poLine.acquisitionMethod"]["value"] == '"Purchase At Vendor System"'
    assert f["order.poLine.checkinItems"]["value"] == '"true"'
    assert f["order.poLine.vendorDetail.vendorAccount"]["value"] == "990$a"
    assert f["order.poLine.description"]["value"] == "980$d"
    assert f["order.poLine.cancellationRestriction"]["value"] == "980$k"
    assert sub(f["order.poLine.details.productIds[]"]) == [
        {"productId": "020$a", "qualifier": "", "productIdType": '"ISSN"'},
        {"productId": "990$i", "qualifier": "", "productIdType": "990$j"}]
    assert sub(f["order.poLine.fundDistribution[]"]) == [
        {"fundId": "990$f", "expenseClassId": "990$e", "value": '"100"',
         "distributionType": '"percentage"'}]


@pytest.mark.parametrize("route", fs.ROUTES)
def test_no_template_sample_values_survive(route, cfg):
    text = json.dumps(build(route, cfg))
    for leftover in ("GOBI", "Depository", '"20"', '"25"', '"Open"',
                     "userInfo", "5236990e", "532b6934"):
        assert leftover not in text


@pytest.mark.parametrize("route", fs.ROUTES)
def test_repeatable_action_only_with_subfields(route, cfg):
    for f in build(route, cfg)["mappingDetails"]["mappingFields"]:
        assert bool(f.get("repeatableFieldAction")) == bool(f["subfields"]), f["path"]


def test_field_structure_preserved(cfg):
    for route in fs.ROUTES:
        t = template(route)["mappingDetails"]["mappingFields"]
        b = build(route, cfg)["mappingDetails"]["mappingFields"]
        assert [x["path"] for x in t] == [x["path"] for x in b]


def test_online_profile(cfg):
    f = by_path(build("online", cfg))
    assert f["order.poLine.orderFormat"]["value"] == '"Electronic Resource"'
    assert f["order.poLine.receiptStatus"]["value"] == '"Receipt Not Required"'
    assert f["order.poLine.cost.listUnitPriceElectronic"]["value"] == "990$c"
    assert f["order.poLine.cost.quantityElectronic"]["value"] == '"1"'
    assert f["order.poLine.eresource.accessProvider"]["value"] == "990$v"
    assert f["order.poLine.eresource.activated"]["booleanFieldAction"] == "ALL_TRUE"
    assert f["order.poLine.eresource.createInventory"]["value"] == '"None"'
    assert f["order.poLine.eresource.resourceUrl"]["value"] == "856$u"
    assert f["order.poLine.cost.listUnitPrice"]["value"] == ""
    assert f["order.poLine.locations[]"]["subfields"] == []
    assert f["order.poLine.physical.materialType"]["value"] == ""


def test_print_profile(cfg):
    f = by_path(build("print", cfg))
    assert f["order.poLine.orderFormat"]["value"] == '"Physical Resource"'
    assert f["order.poLine.receiptStatus"]["value"] == '"Pending"'
    assert f["order.poLine.cost.listUnitPrice"]["value"] == "990$c"
    assert f["order.poLine.cost.quantityPhysical"]["value"] == '"1"'
    assert f["order.poLine.physical.materialType"]["value"] == "990$m"
    assert sub(f["order.poLine.locations[]"]) == [
        {"locationId": "990$l",
         "quantityPhysical": '"1"', "quantityElectronic": ""}]
    assert f["order.poLine.eresource.accessProvider"]["value"] == ""
    assert f["order.poLine.eresource.activated"]["booleanFieldAction"] == "ALL_FALSE"


def test_pe_profile(cfg):
    f = by_path(build("pe", cfg))
    assert f["order.poLine.orderFormat"]["value"] == '"P/E Mix"'
    assert f["order.poLine.cost.listUnitPrice"]["value"] == "990$c"
    assert f["order.poLine.cost.listUnitPriceElectronic"]["value"] == '"0"'
    assert f["order.poLine.eresource.accessProvider"]["value"] == "990$v"
    assert sub(f["order.poLine.locations[]"])[0]["quantityElectronic"] == '"1"'


def test_name_prefix_override(cfg):
    p = fs.build_mapping_profile("print", template("print"), cfg, VENDOR, "test_x")
    assert p["name"] == "test_x - Print"


def test_set_value_requires_exactly_one_match():
    with pytest.raises(KeyError):
        fs.set_value([], "nope", "x")


def test_update_profile():
    c = FakeClient()
    assert fs.update_profile(c, "/p", "id1", {"name": "N"}, False) == "would update"
    assert c.puts == []
    assert fs.update_profile(c, "/p", "id1", {"name": "N"}, True) == "updated"
    assert c.puts == [("/p/id1", {"profile": {"name": "N", "id": "id1"},
                                  "addedRelations": [], "deletedRelations": []})]


def test_relations_and_profiles():
    assert fs.relation("JOB_PROFILE", "a", "ACTION_PROFILE", 0) == {
        "masterProfileId": None, "masterProfileType": "JOB_PROFILE",
        "detailProfileId": "a", "detailProfileType": "ACTION_PROFILE", "order": 0}
    assert fs.action_profile("n")["folioRecord"] == "ORDER"
    assert fs.job_profile("n")["dataType"] == "MARC"


class FakeClient:
    def __init__(self, existing=None):
        self.existing = existing or {}
        self.posts, self.puts = [], []

    def folio_get(self, path, key=None, query_params=None, **kw):
        name = (query_params or {}).get("query", "").split('"')[1]
        return [self.existing[name]] if name in self.existing else []

    def folio_post(self, path, payload, **kw):
        self.posts.append((path, payload))
        return {"id": "new-id"}

    def folio_put(self, path, payload, **kw):
        self.puts.append((path, payload))


def test_create_profile_dry_run_and_live_and_exists():
    prof = {"name": "N"}
    c = FakeClient()
    assert fs.create_profile(c, "/p", "k", prof, [], False) == ("would create", "")
    assert c.posts == []
    assert fs.create_profile(c, "/p", "k", prof, ["r"], True) == ("created", "new-id")
    assert c.posts[0][1] == {"profile": prof, "addedRelations": ["r"],
                             "deletedRelations": []}
    c2 = FakeClient({"N": {"id": "old"}})
    assert fs.create_profile(c2, "/p", "k", prof, [], True) == ("exists", "old")
    assert c2.posts == []


def test_add_accounts():
    org = {"id": "o1", "code": "ebsconet", "accounts": [{"accountNo": "A1"}]}
    c = FakeClient()
    new, have = fs.add_accounts(c, org, ["A1", "B2"], "Other", live=False)
    assert (new, have) == (["B2"], ["A1"]) and c.puts == []
    fs.add_accounts(c, org, ["A1", "B2"], "Other", live=True)
    path, payload = c.puts[0]
    assert path == "/organizations/organizations/o1"
    assert [a["accountNo"] for a in payload["accounts"]] == ["A1", "B2"]
    assert payload["accounts"][1]["paymentMethod"] == "Other"
    assert len(org["accounts"]) == 1                  # original not mutated


def test_accounts_from_workbooks(tmp_path, cfg):
    for name, nums in ((cfg["output_names"]["online"], ["X1", "X2", "X1"]),
                       (cfg["output_names"]["pe"], ["X2", "X3"])):
        wb = Workbook()
        ws = wb.active
        ws.append(["Title Name", "Account Number"])
        for n in nums:
            ws.append(["t", n])
        wb.save(tmp_path / name)
    assert fs.accounts_from_workbooks(tmp_path, cfg) == ["X1", "X2", "X3"]


def test_accounts_from_workbooks_uses_configured_heading(tmp_path, cfg):
    cfg = dict(cfg, columns=dict(cfg["columns"], account="Acct No"))
    wb = Workbook()
    ws = wb.active
    ws.append(["Title Name", "Acct No"])
    ws.append(["t", "Z9"])
    wb.save(tmp_path / cfg["output_names"]["online"])
    assert fs.accounts_from_workbooks(tmp_path, cfg) == ["Z9"]
