"""Set up FOLIO for the EBSCONET order migration (instruction steps 8-12).

  * adds the SOP account numbers as Account entries on the EBSCONET organization
  * creates three Data Import field mapping profiles (Online, Print, P-E), each built
    from an exported Order mapping profile in template_profiles/
  * creates an action profile and a job profile for each mapping profile

Tag references follow order_marc_headers.xlsx: 990$o PO number, 990$c price, 990$s/$t
subscription dates, 990$a account, 990$f fund, 990$e expense class, 990$v access
provider, 990$i title number, 856$u URL, 264$a publisher.

Without --live nothing is written to FOLIO; the profile JSON is still written to
<out>/profiles/ for review. Existing profiles with the same name are left alone.
"""
import argparse
import copy
import json
from pathlib import Path

from openpyxl import load_workbook

from ebsconet_prep import ROUTES, load_config

TEMPLATE_FOR = {"online": "mapping_electronic.json", "print": "mapping_physical.json",
                "pe": "mapping_pe_mix.json"}
ROUTE_LABEL = {"online": "Online", "print": "Print", "pe": "P-E"}
ORDER_FORMAT = {"online": "Electronic Resource", "print": "Physical Resource",
                "pe": "P/E Mix"}
PO = "order.po."
POL = "order.poLine."


def q(text):
    """FOLIO mapping syntax for a fixed value."""
    return '"%s"' % text


def set_value(fields, path, value, action=None):
    """Set the value (and optionally booleanFieldAction) of the field at path."""
    matches = [f for f in fields if f["path"] == path]
    if len(matches) != 1:
        raise KeyError("expected one field at %s, found %d" % (path, len(matches)))
    matches[0]["value"] = value
    if action:
        matches[0]["booleanFieldAction"] = action


def set_repeatable(fields, path, entries):
    """Fill a repeatable field. entries = list of {subfield name: value}."""
    matches = [f for f in fields if f["path"] == path]
    if len(matches) != 1:
        raise KeyError("expected one field at %s, found %d" % (path, len(matches)))
    field = matches[0]
    field["value"] = ""
    field["repeatableFieldAction"] = "EXTEND_EXISTING"
    field["subfields"] = [{
        "order": i,
        "path": path,
        "fields": [{"name": name, "enabled": "true", "required": False,
                    "path": "%s.%s" % (path, name), "value": value, "subfields": []}
                   for name, value in entry.items()],
    } for i, entry in enumerate(entries)]


def blank_fields(fields):
    """Remove the template's sample values, keeping the field structure."""
    for f in fields:
        f["subfields"] = []
        f.pop("repeatableFieldAction", None)   # FOLIO rejects it on empty subfields
        if "booleanFieldAction" in f:
            f["value"] = None
            f["booleanFieldAction"] = "ALL_FALSE"
        else:
            f["value"] = ""


def build_mapping_profile(route, template, cfg, vendor_id, name_prefix=None):
    """Return the mapping profile JSON for a route, built from an exported template."""
    fo = cfg["folio"]
    profile = copy.deepcopy(template)
    for key in ("id", "metadata", "userInfo", "parentProfiles", "childProfiles"):
        profile.pop(key, None)
    prefix = name_prefix if name_prefix is not None else fo["profile_name_prefix"]
    profile["name"] = "%s - %s" % (prefix, ROUTE_LABEL[route])
    profile["description"] = "Used for EBSCONET order migration"
    profile["parentProfiles"] = []
    profile["childProfiles"] = []
    fields = profile["mappingDetails"]["mappingFields"]
    blank_fields(fields)

    # --- purchase order
    set_value(fields, PO + "workflowStatus", q("Pending"))
    set_value(fields, PO + "approved", None, "ALL_TRUE")
    set_value(fields, PO + "overridePoLinesLimit", q(fo["override_po_lines_limit"]))
    set_value(fields, PO + "poNumber", "990$o")
    set_value(fields, PO + "vendor", q(vendor_id))
    set_value(fields, PO + "orderType", q("One-Time"))
    set_value(fields, PO + "manualPo", None, "ALL_FALSE")

    # --- item details
    set_value(fields, POL + "titleOrPackage", "245$a")
    set_value(fields, POL + "details.subscriptionFrom", "990$s")
    set_value(fields, POL + "details.subscriptionTo", "990$t")
    set_value(fields, POL + "details.subscriptionInterval", q(fo["subscription_interval"]))
    set_value(fields, POL + "publisher", "264$a")
    set_repeatable(fields, POL + "details.productIds[]", [
        {"productId": "020$a", "qualifier": "", "productIdType": q("ISSN")},
        # the type comes from 990$j, which is only present when 990$i is
        {"productId": "990$i", "qualifier": "", "productIdType": "990$j"},
    ])

    # --- PO line details
    set_value(fields, POL + "acquisitionMethod", q(fo["acquisition_method"]))
    set_value(fields, POL + "orderFormat", q(ORDER_FORMAT[route]))
    set_value(fields, POL + "receiptStatus", q(fo["receipt_status"][route]))
    set_value(fields, POL + "source", q("MARC"))
    set_value(fields, POL + "checkinItems", q("true"))      # Independent receiving

    # --- vendor / cost / fund distribution
    set_value(fields, POL + "vendorDetail.vendorAccount", "990$a")
    set_value(fields, POL + "cost.currency", q(fo["currency"]))
    set_value(fields, POL + "cost.discountType", q("percentage"))
    set_repeatable(fields, POL + "fundDistribution[]", [
        {"fundId": "990$f", "expenseClassId": "990$e", "value": q("100"),
         "distributionType": q("percentage")}])

    physical = route in ("print", "pe")
    electronic = route in ("online", "pe")
    if physical:
        set_value(fields, POL + "cost.listUnitPrice", "990$c")
        set_value(fields, POL + "cost.quantityPhysical", q("1"))
        set_repeatable(fields, POL + "locations[]", [
            {"locationId": q(fo["location"]), "quantityPhysical": q("1"),
             "quantityElectronic": q("1") if electronic else ""}])
        set_value(fields, POL + "physical.createInventory", q(fo["create_inventory"]))
        set_value(fields, POL + "physical.materialType", q(fo["physical_material_type"]))
    if electronic:
        # in a P/E mix the single SOP price goes on the physical side
        set_value(fields, POL + "cost.listUnitPriceElectronic",
                  q("0") if physical else "990$c")
        set_value(fields, POL + "cost.quantityElectronic", q("1"))
        set_value(fields, POL + "eresource.accessProvider", "990$v")
        set_value(fields, POL + "eresource.activated", None, "ALL_TRUE")
        set_value(fields, POL + "eresource.createInventory", q(fo["create_inventory"]))
        set_value(fields, POL + "eresource.resourceUrl", "856$u")
    return profile


def action_profile(name):
    return {"name": name, "description": "Used for EBSCONET order migration",
            "action": "CREATE", "folioRecord": "ORDER"}


def job_profile(name):
    return {"name": name, "description": "Used for EBSCONET order migration",
            "dataType": "MARC"}


def relation(master_type, detail_id, detail_type, order=None):
    rel = {"masterProfileId": None, "masterProfileType": master_type,
           "detailProfileId": detail_id, "detailProfileType": detail_type}
    if order is not None:
        rel["order"] = order
    return rel


def account_entry(number, payment_method):
    return {"name": number, "accountNo": number, "accountStatus": "Active",
            "paymentMethod": payment_method, "acqUnitIds": [], "appSystemNo": "",
            "description": "", "libraryCode": "", "libraryEdiCode": "", "notes": ""}


def accounts_from_workbooks(in_dir, cfg):
    """Distinct Account Numbers in the prepared workbooks."""
    found = set()
    for name in cfg["output_names"].values():
        path = Path(in_dir) / name
        if not path.exists():
            continue
        ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = list(next(rows))
        if "Account Number" not in header:
            continue
        i = header.index("Account Number")
        found.update(str(r[i]).strip() for r in rows if r[i] not in (None, ""))
    return sorted(found)


def add_accounts(client, org, numbers, payment_method, live):
    """Add missing accounts to the organization. Returns (added, already_there)."""
    have = {a.get("accountNo") for a in org.get("accounts", [])}
    new = [n for n in numbers if n not in have]
    if new and live:
        org = dict(org)
        org["accounts"] = list(org.get("accounts", [])) + [
            account_entry(n, payment_method) for n in new]
        client.folio_put("/organizations/organizations/%s" % org["id"], org)
    return new, sorted(have & set(numbers))


def find_by_name(client, path, key, name):
    found = client.folio_get(path, key=key,
                             query_params={"query": 'name=="%s"' % name, "limit": 5})
    return found[0] if found else None


def create_profile(client, path, key, profile, relations, live):
    """POST a profile unless one with that name exists. Returns (status, id)."""
    existing = find_by_name(client, path, key, profile["name"])
    if existing:
        return "exists", existing["id"]
    if not live:
        return "would create", ""
    created = client.folio_post(path, {"profile": profile, "addedRelations": relations,
                                       "deletedRelations": []})
    pid = (created or {}).get("id") or find_by_name(client, path, key,
                                                    profile["name"])["id"]
    return "created", pid


def update_profile(client, path, profile_id, profile, live):
    """PUT new content onto an existing profile; its links are left as they are."""
    if not live:
        return "would update"
    client.folio_put("%s/%s" % (path, profile_id),
                     {"profile": dict(profile, id=profile_id), "addedRelations": [],
                      "deletedRelations": []})
    return "updated"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ini", required=True)
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--in-dir", default="out", help="prep output (for account numbers)")
    p.add_argument("--out", default="out")
    p.add_argument("--name-prefix", help="override the profile name prefix")
    p.add_argument("--skip-accounts", action="store_true")
    p.add_argument("--update-mappings", action="store_true",
                   help="also overwrite existing mapping profiles with the current build")
    p.add_argument("--live", action="store_true", help="actually write to FOLIO")
    args = p.parse_args(argv)

    from folio_common import connect
    cfg = load_config(args.config)
    fo = cfg["folio"]
    client = connect(args.ini)
    print("LIVE" if args.live else "dry run", "-", args.ini)

    vendor = client.folio_get("/organizations/organizations",
                              key="organizations", query_params={
                                  "query": 'code=="%s"' % fo["vendor_org_code"],
                                  "limit": 2})
    if not vendor:
        raise SystemExit("vendor organization %s not found" % fo["vendor_org_code"])
    vendor = vendor[0]

    if not args.skip_accounts:
        new, have = add_accounts(client, vendor, accounts_from_workbooks(
            args.in_dir, cfg), fo["account_payment_method"], args.live)
        print("accounts on %s: %d %s, %d already present" % (
            vendor["code"], len(new), "added" if args.live else "to add", len(have)))

    out_dir = Path(args.out) / "profiles"
    out_dir.mkdir(parents=True, exist_ok=True)
    for route in ROUTES:
        template = json.loads((Path(fo["template_dir"]) / TEMPLATE_FOR[route])
                              .read_text(encoding="utf-8"))
        mapping = build_mapping_profile(route, template, cfg, vendor["id"],
                                        args.name_prefix)
        (out_dir / ("mapping_%s.json" % route)).write_text(
            json.dumps(mapping, indent=2), encoding="utf-8")
        name = mapping["name"]
        st, mid = create_profile(client, "/data-import-profiles/mappingProfiles",
                                 "mappingProfiles", mapping, [], args.live)
        if st == "exists" and args.update_mappings:
            st = update_profile(client, "/data-import-profiles/mappingProfiles", mid,
                                mapping, args.live)
        print("mapping profile %-45s %s %s" % (name, st, mid))
        st, aid = create_profile(
            client, "/data-import-profiles/actionProfiles", "actionProfiles",
            action_profile(name), [relation("ACTION_PROFILE", mid, "MAPPING_PROFILE")]
            if mid else [], args.live)
        print("action profile  %-45s %s %s" % (name, st, aid))
        st, jid = create_profile(
            client, "/data-import-profiles/jobProfiles", "jobProfiles",
            job_profile(name), [relation("JOB_PROFILE", aid, "ACTION_PROFILE", 0)]
            if aid else [], args.live)
        print("job profile     %-45s %s %s" % (name, st, jid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
