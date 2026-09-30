"""Check a .mrc file and the target tenant BEFORE loading it through Data Import.

File checks (offline): required values, prices, dates, URLs, ISSNs, duplicate PO numbers.
Tenant checks (read-only): the PO numbers are unused; the vendor, access-provider
organizations, funds, active budgets, expense classes (in the budget), location, material
type and acquisition method that the import will look up all exist; vendor account
numbers are on the vendor organization; the budgets have enough money.

Each finding is an ERROR (the load would fail or discard lines) or a WARN.
Exit code 1 when there is any ERROR.
"""
import argparse
import re
from collections import Counter, defaultdict
from datetime import datetime

from pymarc import MARCReader

from ebsconet_prep import load_config
from folio_setup import ROUTE_LABEL

ERROR, WARN = "ERROR", "WARN"
URL_OK = re.compile(r"^[a-z][a-z0-9+.\-]*://\S+$")
PO_OK = re.compile(r"^[A-Za-z0-9]{1,22}$")
ISSN_OK = re.compile(r"^\d{4}-\d{3}[\dXx]$")
SUBFIELDS = {"o": "order", "c": "cost", "f": "fund", "e": "expense_class",
             "a": "account", "s": "start", "t": "end", "v": "org", "i": "title_number"}


def read_records(mrc_path):
    """One dict per MARC record with the values the checks need."""
    with open(mrc_path, "rb") as fh:
        raw = list(MARCReader(fh, to_unicode=True, force_utf8=True))
    recs = []
    for n, r in enumerate(raw, start=1):
        d = {"n": n, "id": r["001"].data if r.get("001") else "",
             "title": r["245"]["a"] if r.get("245") else "",
             "issn": r["020"]["a"] if r.get("020") else "",
             "url": r["856"]["u"] if r.get("856") else ""}
        d.update({name: "" for name in SUBFIELDS.values()})
        if r.get("990"):
            for sub in r["990"].subfields:
                if sub.code in SUBFIELDS:
                    d[SUBFIELDS[sub.code]] = sub.value
        recs.append(d)
    return recs


def label(rec):
    return "record %d (%s)" % (rec["n"], rec["order"] or rec["id"] or "no PO number")


def valid_date(text):
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def check_records(recs, route):
    """Offline checks on the file itself. Returns [(level, where, message)]."""
    issues = []
    needs_org = route in ("online", "pe")
    for rec in recs:
        where = label(rec)
        for key, human in (("title", "245$a title"), ("order", "990$o PO number"),
                           ("fund", "990$f fund"),
                           ("account", "990$a vendor account")):
            if not rec[key]:
                issues.append((ERROR, where, "missing %s" % human))
        if needs_org and not rec["org"]:
            issues.append((ERROR, where, "missing 990$v access provider"))
        if rec["order"] and not PO_OK.match(rec["order"]):
            issues.append((ERROR, where, "PO number %r must be 1-22 letters/digits "
                           "(FOLIO rejects other characters)" % rec["order"]))
        try:
            cost = float(rec["cost"])
            if cost <= 0:
                issues.append((WARN, where, "price is %s" % rec["cost"]))
        except ValueError:
            issues.append((ERROR, where, "990$c price %r is not a number" % rec["cost"]))
        start, end = valid_date(rec["start"]), valid_date(rec["end"])
        for key, val in (("start", start), ("end", end)):
            if rec[key] and val is None:
                issues.append((ERROR, where, "990$%s date %r is not YYYY-MM-DD"
                               % ("s" if key == "start" else "t", rec[key])))
        if start and end and end < start:
            issues.append((ERROR, where, "expiration date is before start date"))
        if rec["url"] and not URL_OK.match(rec["url"]):
            issues.append((ERROR, where, "856$u URL %r would be rejected by FOLIO "
                           "(needs a lowercase scheme://, no spaces)" % rec["url"]))
        if not rec["issn"]:
            issues.append((WARN, where, "no ISSN (020$a)"))
        elif not ISSN_OK.match(rec["issn"]):
            issues.append((WARN, where, "ISSN %r does not look like NNNN-NNNN" % rec["issn"]))
        if not rec["title_number"]:
            issues.append((WARN, where, "no title number (990$i); the line will have no title-number product ID"))
    for key, human in (("order", "PO number"), ("id", "001 control number")):
        for value, count in Counter(r[key] for r in recs if r[key]).items():
            if count > 1:
                issues.append((ERROR, "file", "%s %s appears on %d records; Data Import "
                               "makes one PO per record, so the later ones will fail"
                               % (human, value, count)))
    return issues


def q(text):
    if '"' in str(text):
        raise ValueError("unsupported character in %r" % text)
    return '"%s"' % text


def one(client, path, key, query):
    return client.folio_get(path, key=key, query_params={"query": query, "limit": 5})


def code_in_parentheses(text):
    """'test_ebsconet_location (TEST-EBSCONET-LOC)' -> 'TEST-EBSCONET-LOC'."""
    m = re.search(r"\(([^()]+)\)\s*$", text)
    return m.group(1) if m else text


def check_tenant(client, recs, route, cfg, job_profile=None):
    """Read-only checks against FOLIO. Returns [(level, where, message)]."""
    issues = []
    fo = cfg["folio"]

    if job_profile:
        profiles = one(client, "/data-import-profiles/jobProfiles", "jobProfiles",
                       "name==%s" % q(job_profile))
        if len(profiles) != 1:
            issues.append((ERROR, "tenant", "job profile %r matches %d profiles"
                           % (job_profile, len(profiles))))
        else:
            issues += check_pending(client, profiles[0]["id"], job_profile)

    for rec in recs:
        if rec["order"] and one(client, "/orders/composite-orders", "purchaseOrders",
                                "poNumber==%s" % q(rec["order"])):
            issues.append((ERROR, label(rec), "PO number already exists in FOLIO"))

    vendor = one(client, "/organizations/organizations", "organizations",
                 "code==%s" % q(fo["vendor_org_code"]))
    if not vendor:
        issues.append((ERROR, "tenant", "vendor organization %r not found"
                       % fo["vendor_org_code"]))
    else:
        have = {a.get("accountNo") for a in vendor[0].get("accounts", [])}
        for acct in sorted({r["account"] for r in recs if r["account"]} - have):
            issues.append((WARN, "tenant", "account %s is not on vendor organization %s "
                           "(run folio_setup.py)" % (acct, fo["vendor_org_code"])))

    if route in ("online", "pe"):
        for code in sorted({r["org"] for r in recs if r["org"]}):
            org = one(client, "/organizations/organizations", "organizations",
                      "code==%s" % q(code))
            if not org:
                issues.append((ERROR, "tenant", "access provider organization %r not "
                               "found (990$v)" % code))
            elif not org[0].get("isVendor"):
                issues.append((WARN, "tenant", "organization %r is not marked as a "
                               "vendor" % code))

    if route in ("print", "pe"):
        loc_code = code_in_parentheses(fo["location"])
        loc = one(client, "/locations", "locations", "code==%s" % q(loc_code))
        if not loc:
            issues.append((ERROR, "tenant", "location %r not found" % loc_code))
        elif not loc[0].get("isActive", True):
            issues.append((ERROR, "tenant", "location %r is inactive" % loc_code))
        if not one(client, "/material-types", "mtypes",
                   "name==%s" % q(fo["physical_material_type"])):
            issues.append((ERROR, "tenant", "material type %r not found"
                           % fo["physical_material_type"]))

    if not one(client, "/orders/acquisition-methods", "acquisitionMethods",
               "value==%s" % q(fo["acquisition_method"])):
        issues.append((ERROR, "tenant", "acquisition method %r not found"
                       % fo["acquisition_method"]))

    issues += check_finance(client, recs)
    return issues


def mapping_status_values(client, job_id):
    """PO status values ('"Pending"', '"Open"', ...) set by the mapping profiles behind
    a job profile (job -> action -> mapping). Returns (values, problem or None)."""
    rel = {"withRelations": "true"}
    job = client.folio_get("/data-import-profiles/jobProfiles/%s" % job_id,
                           query_params=rel)
    actions = [c for c in job.get("childProfiles", [])
               if c.get("contentType") == "ACTION_PROFILE"]
    if not actions:
        return [], "the job profile has no action profile"
    values = []
    for act in actions:
        full = client.folio_get("/data-import-profiles/actionProfiles/%s" % act["id"],
                                query_params=rel)
        maps = [c for c in full.get("childProfiles", [])
                if c.get("contentType") == "MAPPING_PROFILE"]
        if not maps:
            return [], "an action profile has no mapping profile"
        for m in maps:
            fields = (m.get("content") or {}).get("mappingDetails", {}).get(
                "mappingFields", [])
            values += [f.get("value") for f in fields
                       if f.get("path") == "order.po.workflowStatus"]
    return values, None


def check_pending(client, job_id, job_name):
    """Orders must be loaded as Pending; anything else (e.g. Open) is an error."""
    values, problem = mapping_status_values(client, job_id)
    if problem:
        return [(WARN, "tenant", "could not verify the PO status for job profile %r: %s"
                 % (job_name, problem))]
    if not values:
        return [(WARN, "tenant", "job profile %r maps no PO status" % job_name)]
    bad = sorted({v for v in values if v != '"Pending"'})
    if bad:
        return [(ERROR, "tenant", "job profile %r would load orders as %s, not \"Pending\""
                 % (job_name, ", ".join(str(b) for b in bad)))]
    return []


def check_finance(client, recs):
    issues = []
    spend = defaultdict(float)
    pairs = defaultdict(set)
    for r in recs:
        try:
            spend[r["fund"]] += float(r["cost"])
        except ValueError:
            pass
        pairs[r["fund"]].add(r["expense_class"])
    for fund_code in sorted(f for f in pairs if f):
        funds = one(client, "/finance/funds", "funds", "code==%s" % q(fund_code))
        if not funds:
            issues.append((ERROR, "tenant", "fund %r not found (990$f)" % fund_code))
            continue
        fund = funds[0]
        if fund.get("fundStatus") != "Active":
            issues.append((ERROR, "tenant",
                           "fund %r is %s" % (fund_code, fund.get("fundStatus"))))
        budgets = [b for b in one(client, "/finance/budgets", "budgets",
                                  "fundId==%s" % q(fund["id"]))
                   if b.get("budgetStatus") == "Active"]
        if not budgets:
            issues.append((ERROR, "tenant", "fund %r has no Active budget; the import "
                           "would discard its PO lines" % fund_code))
            continue
        budgets = [client.folio_get("/finance/budgets/%s" % b["id"]) for b in budgets]
        allowed = {s["expenseClassId"] for b in budgets
                   for s in b.get("statusExpenseClasses", [])
                   if s.get("status") == "Active"}
        for ec_code in sorted(e for e in pairs[fund_code] if e):
            ec = one(client, "/finance/expense-classes", "expenseClasses",
                     "code==%s" % q(ec_code))
            if not ec:
                issues.append((ERROR, "tenant", "expense class %r not found (990$e)"
                               % ec_code))
            elif ec[0]["id"] not in allowed:
                issues.append((ERROR, "tenant", "expense class %r is not Active on any "
                               "budget of fund %r (\"Budget expense class not found\")"
                               % (ec_code, fund_code)))
        room = encumbrance_room(client, fund, budgets)
        if room is not None and spend[fund_code] > room:
            issues.append((WARN, "tenant", "fund %r: file total %.2f exceeds the room "
                           "left under its encumbrance limit (%.2f); these orders could "
                           "not be opened" % (fund_code, spend[fund_code], room)))
    return issues


def encumbrance_room(client, fund, budgets):
    """Money that can still be encumbered on the fund, or None when nothing limits it.

    FOLIO only stops an order from being *opened* when the ledger restricts
    encumbrance AND the budget has an allowable-encumbrance percentage. A zero-based
    budget (allocation 0, no percentage) is unlimited; pending orders are never
    limited, so this only matters for opening the orders later."""
    ledger_id = fund.get("ledgerId")
    if not ledger_id or not client.folio_get(
            "/finance/ledgers/%s" % ledger_id).get("restrictEncumbrance"):
        return None
    limits = []
    for b in budgets:
        pct = b.get("allowableEncumbrance")
        if pct is None:
            return None                   # one unrestricted budget removes the limit
        cap = ((b.get("allocated") or 0) + (b.get("netTransfers") or 0)) * pct / 100.0
        used = ((b.get("encumbered") or 0) + (b.get("awaitingPayment") or 0)
                + (b.get("expenditures") or 0))
        limits.append(cap - used)
    return max(limits)


def route_from_profile(name, cfg):
    prefix = cfg["folio"]["profile_name_prefix"]
    for route, text in ROUTE_LABEL.items():
        if name == "%s - %s" % (prefix, text):
            return route
    return None


def report(issues):
    errors = [i for i in issues if i[0] == ERROR]
    grouped = {}
    for level, where, msg in issues:                  # same message -> one line
        grouped.setdefault((level, msg), []).append(where)
    for (level, msg), wheres in sorted(grouped.items(), key=lambda kv: kv[0][0] != ERROR):
        if len(wheres) == 1:
            print("%-5s %s: %s" % (level, wheres[0], msg))
        else:
            shown = ", ".join(w.replace("record ", "") for w in wheres[:6])
            more = " ..." if len(wheres) > 6 else ""
            print("%-5s %s  [%d records: %s%s]" % (level, msg, len(wheres), shown, more))
    print("preflight: %d error(s), %d warning(s)" % (len(errors), len(issues) - len(errors)))
    return not errors


def run_preflight(client, mrc, route, cfg, job_profile=None, out=print):
    """Full preflight. Returns True when there are no errors."""
    recs = read_records(mrc)
    out("preflight: %d records, route %s" % (len(recs), route))
    return report(check_records(recs, route) + check_tenant(client, recs, route, cfg,
                                                            job_profile))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mrc")
    p.add_argument("--ini", required=True)
    p.add_argument("--route", choices=sorted(ROUTE_LABEL), required=True)
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--job-profile", help="also check this job profile exists")
    args = p.parse_args(argv)
    from folio_common import connect
    ok = run_preflight(connect(args.ini), args.mrc, args.route,
                       load_config(args.config), args.job_profile)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
