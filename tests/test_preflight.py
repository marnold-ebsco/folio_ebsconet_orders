import sys
from pathlib import Path

import pytest
from pymarc import Field, Record, Subfield

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import folio_preflight as pf  # noqa: E402
from pipeline.ebsconet_prep import load_config  # noqa: E402


@pytest.fixture
def cfg():
    return load_config(ROOT / "ebsconet_config.json")


def rec(**over):
    d = {"n": 1, "id": "U1", "title": "T", "issn": "1234-5678",
         "url": "https://x.org/a", "order": "U1", "cost": "10.00", "fund": "F1",
         "expense_class": "GEN", "account": "ACC1", "start": "2026-01-01",
         "end": "2026-12-31", "org": "EBSCO", "title_number": "P1",
         "title_number_type": "", "location": "", "material_type": ""}
    d.update(over)
    return d


def messages(issues, level=None):
    return [m for lv, _, m in issues if level in (None, lv)]


# ---------------------------------------------------------------- file checks
def test_clean_record_has_no_errors():
    assert messages(pf.check_records([rec()], "online"), pf.ERROR) == []


@pytest.mark.parametrize("field,expect", [
    ("title", "245$a"), ("order", "990$o"), ("fund", "990$f"),
    ("account", "990$a"), ("org", "990$v")])
def test_missing_required_values(field, expect):
    errs = messages(pf.check_records([rec(**{field: ""})], "online"), pf.ERROR)
    assert any(expect in m for m in errs)


def test_expense_class_is_optional():
    assert pf.check_records([rec(expense_class="")], "online") == []


def test_access_provider_not_needed_for_print():
    assert messages(pf.check_records([rec(org="")], "print"), pf.ERROR) == []


@pytest.mark.parametrize("over,expect", [
    ({"cost": "abc"}, "not a number"), ({"start": "01/02/2026"}, "990$s date"),
    ({"end": "2025-01-01"}, "before start"),
    ({"url": "HTTP://WWW.X.ORG"}, "URL"), ({"url": "http://a b.org"}, "URL")])
def test_bad_values_are_errors(over, expect):
    errs = messages(pf.check_records([rec(**over)], "online"), pf.ERROR)
    assert any(expect in m for m in errs), errs


def test_warnings_for_issn_title_number_and_zero_price():
    warns = messages(pf.check_records(
        [rec(issn="", title_number="", cost="0")], "online"), pf.WARN)
    assert len(warns) == 3
    assert any("ISSN" in m for m in messages(pf.check_records(
        [rec(issn="12345678")], "online"), pf.WARN))


@pytest.mark.parametrize("po,ok", [("U1234567", True), ("A" * 22, True), ("A" * 23, False),
                                   ("TCANC-NO", False), ("U 1", False), ("Ué", False)])
def test_po_number_format(po, ok):
    errs = messages(pf.check_records([rec(order=po)], "online"), pf.ERROR)
    assert (not any("PO number" in m and "letters/digits" in m for m in errs)) == ok


def test_duplicate_po_numbers_in_file():
    errs = messages(pf.check_records([rec(), rec(n=2, id="U2")], "online"), pf.ERROR)
    assert any("U1 appears on 2 records" in m for m in errs)


# ---------------------------------------------------------------- read_records
def test_read_records(tmp_path):
    r = Record(force_utf8=True)
    r.leader = "00000nas a2200000   4500"
    r.add_field(Field(tag="001", data="U9"))
    r.add_field(Field(tag="020", indicators=[" ", " "], subfields=[Subfield("a", "1111-2222")]))
    r.add_field(Field(tag="245", indicators=["0", "0"], subfields=[Subfield("a", "Title")]))
    r.add_field(Field(tag="990", indicators=[" ", " "], subfields=[
        Subfield("o", "U9"), Subfield("c", "5.00"), Subfield("f", "F"),
        Subfield("s", "2026-01-01")]))
    path = tmp_path / "a.mrc"
    path.write_bytes(r.as_marc())
    [got] = pf.read_records(path)
    assert (got["id"], got["title"], got["issn"], got["order"], got["cost"],
            got["fund"], got["start"], got["url"], got["end"]) == (
        "U9", "Title", "1111-2222", "U9", "5.00", "F", "2026-01-01", "", "")


# ---------------------------------------------------------------- tenant checks
class FakeTenant:
    """Answers the read-only queries the preflight makes."""

    def __init__(self, **kw):
        self.data = {
            "jobProfiles": [{"id": "jp"}],
            "purchaseOrders": [],
            "organizations": {"ebsconet": {"id": "v", "isVendor": True,
                                           "accounts": [{"accountNo": "ACC1"}]},
                              "EBSCO": {"id": "o", "isVendor": True}},
            "locations": {"TEST-EBSCONET-LOC": {"id": "l", "isActive": True}},
            "mtypes": ["journal"],
            "acquisitionMethods": ["Purchase At Vendor System"],
            "funds": {"F1": {"id": "f1", "fundStatus": "Active", "ledgerId": "led1"}},
            "ledger": {"restrictEncumbrance": True},
            "budgets": [{"id": "b1", "fundId": "f1", "budgetStatus": "Active"}],
            "budget_detail": {"allocated": 1000, "allowableEncumbrance": 100,
                              "statusExpenseClasses": [{"expenseClassId": "ec1",
                                                        "status": "Active"}]},
            "expenseClasses": {"GEN": {"id": "ec1"}},
            "identifierTypes": ["ISSN", "Local identifier", "Publisher or distributor number"],
            "status": '"Pending"',
        }
        self.data.update(kw)

    def folio_get(self, path, key=None, query_params=None, **kw):
        d = self.data
        if path.startswith("/finance/budgets/"):
            return dict(d["budget_detail"], id="b1")
        if path.startswith("/finance/ledgers/"):
            return d["ledger"]
        if path.startswith("/data-import-profiles/jobProfiles/"):
            return d.get("job", {"childProfiles": [
                {"id": "ap", "contentType": "ACTION_PROFILE"}]})
        if path.startswith("/data-import-profiles/actionProfiles/"):
            return d.get("action", {"childProfiles": [{
                "id": "mp", "contentType": "MAPPING_PROFILE", "content": {
                    "mappingDetails": {"mappingFields": [
                        {"path": "order.po.workflowStatus", "value": d["status"]},
                        {"path": "order.po.poNumber", "value": "990$o"}]}}}]})
        query = (query_params or {}).get("query", "")
        val = query.split('"')[1] if '"' in query else ""
        if key == "jobProfiles":
            return d["jobProfiles"]
        if key == "purchaseOrders":
            return [{"id": "x"}] if val in d["purchaseOrders"] else []
        if key == "organizations":
            return [d["organizations"][val]] if val in d["organizations"] else []
        if key == "locations":
            return [d["locations"][val]] if val in d["locations"] else []
        if key == "mtypes":
            return [{}] if val in d["mtypes"] else []
        if key == "acquisitionMethods":
            return [{}] if val in d["acquisitionMethods"] else []
        if key == "funds":
            return [d["funds"][val]] if val in d["funds"] else []
        if key == "budgets":
            return d["budgets"]
        if key == "identifierTypes":
            return [{}] if val in d["identifierTypes"] else []
        if key == "expenseClasses":
            return [d["expenseClasses"][val]] if val in d["expenseClasses"] else []
        raise AssertionError((path, key, query))


def tenant_errors(cfg, route="online", recs=None, **kw):
    issues = pf.check_tenant(FakeTenant(**kw), recs or [rec()], route, cfg,
                             "EBSCONET order migration - Online")
    return messages(issues, pf.ERROR), messages(issues, pf.WARN)


def test_clean_tenant(cfg):
    assert tenant_errors(cfg) == ([], [])


def test_existing_po_number(cfg):
    errs, _ = tenant_errors(cfg, purchaseOrders=["U1"])
    assert any("already exists" in m for m in errs)


def test_job_profile_missing(cfg):
    errs, _ = tenant_errors(cfg, jobProfiles=[])
    assert any("job profile" in m for m in errs)


def test_vendor_and_access_provider(cfg):
    errs, _ = tenant_errors(cfg, organizations={})
    assert any("vendor organization" in m for m in errs)
    assert any("access provider" in m for m in errs)


def test_org_not_a_vendor_is_warning(cfg):
    orgs = FakeTenant().data["organizations"]
    orgs["EBSCO"]["isVendor"] = False
    errs, warns = tenant_errors(cfg, organizations=orgs)
    assert errs == [] and any("not marked as a vendor" in m for m in warns)


def test_missing_account_is_warning(cfg):
    _, warns = tenant_errors(cfg, recs=[rec(account="NEW9")])
    assert any("NEW9" in m for m in warns)


def test_fund_missing_or_inactive(cfg):
    errs, _ = tenant_errors(cfg, funds={})
    assert any("fund 'F1' not found" in m for m in errs)
    errs, _ = tenant_errors(cfg, funds={"F1": {"id": "f1", "fundStatus": "Inactive"}})
    assert any("is Inactive" in m for m in errs)


def test_no_active_budget(cfg):
    errs, _ = tenant_errors(cfg, budgets=[{"id": "b1", "budgetStatus": "Frozen"}])
    assert any("no Active budget" in m for m in errs)


def test_no_expense_class_skips_the_budget_class_check(cfg):
    errs, _ = tenant_errors(cfg, recs=[rec(expense_class="")],
                            budget_detail={"allocated": 1000, "statusExpenseClasses": []},
                            expenseClasses={})
    assert errs == []


def test_expense_class_missing_or_not_in_budget(cfg):
    errs, _ = tenant_errors(cfg, expenseClasses={})
    assert any("expense class 'GEN' not found" in m for m in errs)
    errs, _ = tenant_errors(cfg, budget_detail={"allocated": 1000,
                                                "statusExpenseClasses": []})
    assert any("Budget expense class not found" in m for m in errs)


def budget(**kw):
    base = {"allocated": 1000, "allowableEncumbrance": 100,
            "statusExpenseClasses": [{"expenseClassId": "ec1", "status": "Active"}]}
    base.update(kw)
    return base


def test_over_encumbrance_limit_is_warning(cfg):
    errs, warns = tenant_errors(cfg, recs=[rec(cost="5000")])
    assert errs == [] and any("encumbrance limit" in m for m in warns)


def test_limit_counts_what_is_already_used(cfg):
    detail = budget(encumbered=600, awaitingPayment=100, expenditures=200)
    _, warns = tenant_errors(cfg, recs=[rec(cost="150")], budget_detail=detail)
    assert any("(100.00)" in m for m in warns)
    _, warns = tenant_errors(cfg, recs=[rec(cost="90")], budget_detail=detail)
    assert warns == []


def test_allowable_percentage_scales_the_limit(cfg):
    _, warns = tenant_errors(cfg, recs=[rec(cost="600")],
                             budget_detail=budget(allowableEncumbrance=50))
    assert any("(500.00)" in m for m in warns)


def test_zero_based_budget_is_unlimited(cfg):
    detail = budget(allocated=0, allowableEncumbrance=None)
    errs, warns = tenant_errors(cfg, recs=[rec(cost="999999")], budget_detail=detail)
    assert (errs, warns) == ([], [])


def test_ledger_not_restricting_means_unlimited(cfg):
    errs, warns = tenant_errors(cfg, recs=[rec(cost="999999")],
                                ledger={"restrictEncumbrance": False})
    assert (errs, warns) == ([], [])


def test_print_route_checks_location_and_material_type(cfg):
    errs, _ = tenant_errors(cfg, route="print", locations={}, mtypes=[])
    assert any("location" in m for m in errs) and any("material type" in m for m in errs)
    errs, _ = tenant_errors(cfg, route="online", locations={}, mtypes=[])
    assert errs == []                      # not needed for the online route


def test_open_status_blocks_the_load(cfg):
    errs, _ = tenant_errors(cfg, status='"Open"')
    assert any("would load orders as \"Open\", not \"Pending\"" in m for m in errs)


def test_pending_status_passes(cfg):
    assert tenant_errors(cfg, status='"Pending"') == ([], [])


def test_unverifiable_status_is_warning_not_error(cfg):
    errs, warns = tenant_errors(cfg, job={"childProfiles": []})
    assert errs == [] and any("could not verify" in m for m in warns)
    errs, warns = tenant_errors(cfg, action={"childProfiles": []})
    assert errs == [] and any("no mapping profile" in m for m in warns)


def test_missing_product_id_type_is_an_error(cfg):
    recs = [rec(title_number_type="Local identifier")]
    errs, _ = tenant_errors(cfg, recs=recs,
                            identifierTypes=["ISSN", "Publisher or distributor number"])
    assert any("'Local identifier' not found" in m for m in errs)
    errs, _ = tenant_errors(cfg, identifierTypes=[])
    assert any("'ISSN' not found" in m for m in errs)
    assert tenant_errors(cfg, recs=recs) == ([], [])


def test_acquisition_method_missing(cfg):
    errs, _ = tenant_errors(cfg, acquisitionMethods=[])
    assert any("acquisition method" in m for m in errs)


def test_helpers(cfg):
    assert pf.code_in_parentheses("test_ebsconet_location (TEST-EBSCONET-LOC)") == \
        "TEST-EBSCONET-LOC"
    assert pf.code_in_parentheses("PLAIN") == "PLAIN"
    assert pf.route_from_profile("EBSCONET order migration - P-E", cfg) == "pe"
    assert pf.route_from_profile("something else", cfg) is None
    with pytest.raises(ValueError):
        pf.q('bad"value')
