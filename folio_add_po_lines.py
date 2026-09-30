"""Add extra PO lines to existing Pending POs through the Orders API.

Data Import makes one PO with one line per MARC record, so a second record with an
already used PO number is discarded ("PO Number already exists"). This script takes the
same .mrc file and, for every record whose PO already exists but whose title is not yet
on it, adds the record as another line of that PO (POST /orders/order-lines).

The new line is a copy of the PO's first line (so order format, receipt status, location,
material type, acquisition method and so on stay as the import profile set them) with
the record's own values swapped in: title, publisher, product IDs, subscription dates,
price, fund / expense class, vendor account, access provider, URL, description and
cancellation restriction. This mirrors folio_setup.py's mapping; keep the two in step.

Safety: dry run unless --live; only Pending POs; a record whose title is already on the
PO is skipped, so re-running does nothing; the tenant's lines-per-PO limit is checked
first. Undo a line with folio_delete_orders.py (POL,<po>-<n>).
"""
import argparse
import copy
import csv
from pathlib import Path

from pymarc import MARCReader

from folio_common import order_lines_limit

STAMP = "T00:00:00.000+00:00"
SUBFIELDS = {"o": "order", "c": "cost", "f": "fund", "e": "expense_class",
             "a": "account", "s": "start", "t": "end", "v": "org", "i": "title_number",
             "j": "title_number_type"}
DEFAULT_TN_TYPE = "Publisher or distributor number"


def read_values(mrc_path):
    """One dict of the values the line needs per MARC record."""
    with open(mrc_path, "rb") as fh:
        recs = list(MARCReader(fh, to_unicode=True, force_utf8=True))
    out = []
    for r in recs:
        def sub(tag, code):
            f = r.get(tag)
            return (f[code] if f and f.get_subfields(code) else "") or ""
        d = {"title": sub("245", "a"), "issn": sub("020", "a"), "url": sub("856", "u"),
             "publisher": sub("264", "a") or sub("260", "a"),
             "description": sub("980", "d"), "cancel": sub("980", "k")}
        d.update({name: sub("990", code) for code, name in SUBFIELDS.items()})
        out.append(d)
    return out


def iso_stamp(date_text):
    return date_text + STAMP if date_text else None


def build_line(template, vals, ids):
    """New PO line = copy of `template` with the record's values swapped in.

    `ids` resolves codes/names: ids["fund"](code), ["expense_class"](code),
    ["org"](code), ["identifier_type"](name)."""
    line = copy.deepcopy(template)
    for key in ("id", "poLineNumber", "metadata", "instanceId", "searchLocationIds"):
        line.pop(key, None)
    line["titleOrPackage"] = vals["title"]
    if vals["publisher"]:
        line["publisher"] = vals["publisher"]
    else:
        line.pop("publisher", None)
    if vals["description"]:
        line["description"] = vals["description"]
    else:
        line.pop("description", None)
    if vals["cancel"] in ("true", "false"):
        line["cancellationRestriction"] = vals["cancel"] == "true"

    details = line.setdefault("details", {})
    product_ids = []
    if vals["issn"]:
        product_ids.append({"productId": vals["issn"],
                            "productIdType": ids["identifier_type"]("ISSN")})
    if vals["title_number"]:
        tn_type = vals["title_number_type"] or DEFAULT_TN_TYPE
        product_ids.append({"productId": vals["title_number"],
                            "productIdType": ids["identifier_type"](tn_type)})
    details["productIds"] = product_ids
    details["subscriptionFrom"] = iso_stamp(vals["start"])
    details["subscriptionTo"] = iso_stamp(vals["end"])
    for key in ("subscriptionFrom", "subscriptionTo"):
        if details[key] is None:
            del details[key]

    cost = line.setdefault("cost", {})
    cost.pop("poLineEstimatedPrice", None)
    price = float(vals["cost"])
    fmt = line.get("orderFormat")
    if fmt == "Electronic Resource":
        cost["listUnitPriceElectronic"] = price
        cost.pop("listUnitPrice", None)
    elif fmt == "Physical Resource":
        cost["listUnitPrice"] = price
        cost.pop("listUnitPriceElectronic", None)
    else:                                   # P/E Mix: the SOP price goes on the physical side
        cost["listUnitPrice"] = price
        cost["listUnitPriceElectronic"] = 0.0

    dist = {"code": vals["fund"], "fundId": ids["fund"](vals["fund"]),
            "distributionType": "percentage", "value": 100.0}
    if vals["expense_class"]:
        dist["expenseClassId"] = ids["expense_class"](vals["expense_class"])
    line["fundDistribution"] = [dist]
    line.setdefault("vendorDetail", {})["vendorAccount"] = vals["account"]
    if "eresource" in line:
        if vals["org"]:
            line["eresource"]["accessProvider"] = ids["org"](vals["org"])
        if vals["url"]:
            line["eresource"]["resourceUrl"] = vals["url"]
    return line


class Resolver:
    """Looks codes and names up in FOLIO once each."""

    def __init__(self, client):
        self.client, self.cache = client, {}

    def _lookup(self, kind, path, key, field, value):
        if (kind, value) not in self.cache:
            found = self.client.folio_get(path, key=key, query_params={
                "query": '%s=="%s"' % (field, value), "limit": 2})
            if not found:
                raise LookupError("%s %r not found in FOLIO" % (kind, value))
            self.cache[(kind, value)] = found[0]["id"]
        return self.cache[(kind, value)]

    def ids(self):
        return {
            "fund": lambda v: self._lookup("fund", "/finance/funds", "funds", "code", v),
            "expense_class": lambda v: self._lookup(
                "expense class", "/finance/expense-classes", "expenseClasses", "code", v),
            "org": lambda v: self._lookup(
                "organization", "/organizations/organizations", "organizations",
                "code", v),
            "identifier_type": lambda v: self._lookup(
                "identifier type", "/identifier-types", "identifierTypes", "name", v),
        }


def add_lines(client, records, live, limit=None, ids=None):
    """Process the records. Returns [(po, title, status, detail)]."""
    ids = ids or Resolver(client).ids()
    results = []
    for vals in records:
        po, title = vals["order"], vals["title"]
        try:
            orders = client.folio_get("/orders/composite-orders", key="purchaseOrders",
                                      query_params={"query": 'poNumber=="%s"' % po,
                                                    "limit": 2})
            if not orders:
                results.append((po, title, "no-po", "PO does not exist; load it normally"))
                continue
            order = client.folio_get("/orders/composite-orders/%s" % orders[0]["id"])
            if order.get("workflowStatus") != "Pending":
                results.append((po, title, "skipped",
                                "PO status is %s, not Pending" % order.get("workflowStatus")))
                continue
            existing = client.folio_get("/orders/order-lines", key="poLines", query_params={
                "query": 'poLineNumber=="%s-*"' % po, "limit": 200})
            if not existing:
                results.append((po, title, "no-lines", "PO has no lines to copy from"))
                continue
            if any((ln.get("titleOrPackage") or "").strip().lower() == title.strip().lower()
                   for ln in existing):
                results.append((po, title, "already-present", "a line with this title exists"))
                continue
            if limit is not None and len(existing) + 1 > limit:
                results.append((po, title, "limit", "PO has %d line(s); tenant limit is %d"
                                % (len(existing), limit)))
                continue
            template = client.folio_get("/orders/order-lines/%s" % existing[0]["id"])
            line = build_line(template, vals, ids)
            line["purchaseOrderId"] = order["id"]
            if not live:
                results.append((po, title, "would-add", "as line %d" % (len(existing) + 1)))
                continue
            made = client.folio_post("/orders/order-lines", line) or {}
            results.append((po, title, "added", made.get("poLineNumber", "")))
        except Exception as exc:  # keep going; the log shows what failed
            results.append((po, title, "error", "%s: %s" % (type(exc).__name__, exc)))
    return results


def write_log(path, results):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["po_number", "title", "status", "detail"])
        w.writerows(results)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mrc")
    p.add_argument("--ini", required=True)
    p.add_argument("--live", action="store_true", help="actually add the lines")
    p.add_argument("--log", default="out/add_lines_log.csv")
    args = p.parse_args(argv)
    from folio_common import connect
    client = connect(args.ini)
    limit, where = order_lines_limit(client)
    print("tenant PO lines limit: %s (%s); %s" % (
        "unknown" if limit is None else limit, where,
        "LIVE" if args.live else "dry run"))
    results = add_lines(client, read_values(args.mrc), args.live, limit)
    write_log(args.log, results)
    for po, title, status, detail in results:
        if status not in ("already-present",):
            print("%-12s %-10s %-45s %s" % (po, status, title[:45], detail))
    counts = {}
    for r in results:
        counts[r[2]] = counts.get(r[2], 0) + 1
    print(", ".join("%s: %d" % kv for kv in sorted(counts.items())))
    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
