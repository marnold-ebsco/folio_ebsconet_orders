"""Create the test ledger, funds, expense classes, organization and location that the
sample EBSCONET spreadsheet refers to, on a test tenant.

Codes match the values written by ebsconet_prep.py (TEST-ELEC, TEST-PRINT, GEN, PHY,
SOC, EBSCO); every record's NAME starts with "test_ebsconet_" so the set is easy to
find and remove. Existing records with the same code are left alone. The ids of what
exists afterwards are written to test_data_created.json.

Writes to FOLIO: run only against a test tenant (--live is required).
"""
import argparse
import json
import uuid

from pipeline.folio_common import connect

PREFIX = "test_ebsconet_"
FISCAL_YEAR_CODE = "FY2026"
# Existing location hierarchy / service point on the bugfest tenant (looked up by code)
LIBRARY_CODE = "JCL"
SERVICE_POINT_CODE = "TEST POINT"
BUDGET_ALLOCATION = 1000000


def find(client, path, key, code):
    found = client.folio_get(path, key=key,
                             query_params={"query": 'code=="%s"' % code, "limit": 5})
    return found[0] if found else None


def ensure(client, live, path, key, code, payload, wrap=None, log=None):
    existing = find(client, path, key, code)
    if existing:
        log.append((key, code, "exists", existing["id"]))
        return existing
    if not live:
        log.append((key, code, "would create", ""))
        return None
    client.folio_post(path, wrap(payload) if wrap else payload)
    created = find(client, path, key, code)
    log.append((key, code, "created", created["id"] if created else "?"))
    return created


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ini", required=True)
    p.add_argument("--live", action="store_true", help="actually create records")
    p.add_argument("--out", default="test_data_created.json")
    args = p.parse_args(argv)
    c = connect(args.ini)
    log, ids = [], {}

    fy = find(c, "/finance/fiscal-years", "fiscalYears", FISCAL_YEAR_CODE)
    ledger = ensure(c, args.live, "/finance/ledgers", "ledgers", "TESTEBSCONET",
                    {"code": "TESTEBSCONET", "name": PREFIX + "ledger",
                     "ledgerStatus": "Active", "fiscalYearOneId": fy["id"]}, log=log)
    ids["ledger"] = ledger and ledger["id"]

    for code, kind in (("TEST-ELEC", "electronic"), ("TEST-PRINT", "print")):
        fund = ensure(
            c, args.live, "/finance/funds", "funds", code,
            {"code": code, "name": PREFIX + "fund_" + kind, "fundStatus": "Active",
             "ledgerId": ledger["id"] if ledger else None,
             "externalAccountNo": PREFIX + kind},
            wrap=lambda f: {"fund": f, "groupIds": []}, log=log)
        ids["fund_" + code] = fund and fund["id"]

    for code in ("GEN", "PHY", "SOC"):
        ec = ensure(c, args.live, "/finance/expense-classes", "expenseClasses", code,
                    {"code": code, "name": PREFIX + "expense_class_" + code.lower()},
                    log=log)
        ids["expense_class_" + code] = ec and ec["id"]

    # budgets: needed so orders can use the expense classes with each fund
    for code, kind in (("TEST-ELEC", "electronic"), ("TEST-PRINT", "print")):
        name = PREFIX + "budget_" + kind
        fund_id = ids["fund_" + code]
        found = c.folio_get("/finance/budgets", key="budgets", query_params={
            "query": 'name=="%s"' % name, "limit": 2})
        if found:
            budget = c.folio_get("/finance/budgets/%s" % found[0]["id"])
            have = {s["expenseClassId"] for s in budget.get("statusExpenseClasses", [])}
            missing = [ids["expense_class_" + ec] for ec in ("GEN", "PHY", "SOC")
                       if ids["expense_class_" + ec] not in have]
            state = "exists"
            if missing and args.live:
                budget["statusExpenseClasses"] = budget.get("statusExpenseClasses", []) + [
                    {"expenseClassId": m, "status": "Active"} for m in missing]
                c.folio_put("/finance/budgets/%s" % budget["id"], budget)
                state = "exists, added %d expense classes" % len(missing)
            log.append(("budgets", name, state, found[0]["id"]))
            ids["budget_" + code] = found[0]["id"]
        elif args.live and fund_id:
            budget_id = str(uuid.uuid4())
            c.folio_post("/finance/budgets", {
                "id": budget_id,
                "name": name, "fundId": fund_id, "fiscalYearId": fy["id"],
                "budgetStatus": "Active", "allocated": BUDGET_ALLOCATION,
                "statusExpenseClasses": [
                    {"expenseClassId": ids["expense_class_" + ec], "status": "Active"}
                    for ec in ("GEN", "PHY", "SOC")]})
            made = c.folio_get("/finance/budgets", key="budgets", query_params={
                "query": 'name=="%s"' % name, "limit": 2})
            log.append(("budgets", name, "created", made[0]["id"]))
            ids["budget_" + code] = made[0]["id"]
        else:
            log.append(("budgets", name, "would create", ""))

    org = ensure(c, args.live, "/organizations/organizations", "organizations",
                 "EBSCO", {"code": "EBSCO", "name": PREFIX + "org", "status": "Active",
                           "isVendor": True}, log=log)
    ids["organization_EBSCO"] = org and org["id"]

    lib = find(c, "/location-units/libraries", "loclibs", LIBRARY_CODE)
    campus = c.folio_get("/location-units/campuses/%s" % lib["campusId"])
    sp = find(c, "/service-points", "servicepoints", SERVICE_POINT_CODE)
    loc = ensure(c, args.live, "/locations", "locations", "TEST-EBSCONET-LOC",
                 {"code": "TEST-EBSCONET-LOC", "name": PREFIX + "location",
                  "isActive": True, "institutionId": campus["institutionId"],
                  "campusId": campus["id"], "libraryId": lib["id"],
                  "primaryServicePoint": sp["id"], "servicePointIds": [sp["id"]]},
                 log=log)
    ids["location_TEST-EBSCONET-LOC"] = loc and loc["id"]

    for row in log:
        print("%-16s %-20s %-13s %s" % row)
    if args.live:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(ids, fh, indent=2)
        print("ids written to", args.out)
    else:
        print("dry run: nothing created (use --live)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
