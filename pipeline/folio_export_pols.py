"""Export PO / POL numbers for the EBSCONET renewal integration (instruction step 26).

Give it either --prefix (all order lines whose number starts with it) or a CSV of PO
numbers. EBSCONET is told the POL number is the PO number plus "-1"; lines that do not
follow that pattern (for example the second line of a two-line PO) are flagged.
"""
import argparse
import csv
from pathlib import Path

from pipeline.folio_ongoing import read_po_numbers


def split_pol(pol_number):
    """'E5046515-2' -> ('E5046515', '2')."""
    po, _, line = str(pol_number).rpartition("-")
    return (po, line) if po else (str(pol_number), "")


def fetch_lines(client, prefix=None, po_numbers=None):
    terms = [prefix] if prefix else ["%s-" % po for po in po_numbers]
    for term in terms:
        if '"' in term:
            raise ValueError("invalid PO number or prefix: %s" % term)
        query = 'poLineNumber=="%s*"' % term
        yield from client.folio_get_all("/orders/order-lines", key="poLines",
                                        query=query)


def export_rows(lines):
    rows = []
    for line in lines:
        pol = line.get("poLineNumber", "")
        po, suffix = split_pol(pol)
        expected = suffix == "1"
        rows.append({
            "po_number": po,
            "pol_number": pol,
            "title": line.get("titleOrPackage", ""),
            "subscription_to": (line.get("details") or {}).get("subscriptionTo", ""),
            "pol_id": line.get("id", ""),
            "matches_po_plus_1": "yes" if expected else "NO - line %s" % suffix,
        })
    return sorted(rows, key=lambda r: r["pol_number"])


TITLE_MAP_FIELDS = [
    "po_number", "pol_number", "folio_po_uuid", "po_status", "title", "issn",
    "title_number", "title_number_type", "vendor_po_number", "vendor_account",
    "subscription_from", "subscription_to", "publisher", "order_format",
    "po_line_description", "pol_id"]


def fetch_identifier_types(client):
    """{identifier type UUID: name}."""
    return {t["id"]: t.get("name", "") for t in client.folio_get_all(
        "/identifier-types", key="identifierTypes", query="cql.allRecords=1")}


def fetch_po_statuses(client, po_ids, chunk=50):
    """{PO UUID: workflowStatus}, looked up in batches."""
    ids = sorted(set(i for i in po_ids if i))
    found = {}
    for start in range(0, len(ids), chunk):
        query = "id==(%s)" % " or ".join(ids[start:start + chunk])
        for po in client.folio_get_all("/orders/composite-orders",
                                       key="purchaseOrders", query=query):
            found[po["id"]] = po.get("workflowStatus", "")
    return found


def title_map_rows(lines, id_types, statuses):
    """One row per order line: PO number with the title and its identifiers."""
    rows = []
    for line in lines:
        pol = line.get("poLineNumber", "")
        details = line.get("details") or {}
        issn, other = "", None
        for pid in details.get("productIds") or []:
            kind = id_types.get(pid.get("productIdType"), "")
            if kind.upper() == "ISSN":
                issn = issn or pid.get("productId", "")
            elif other is None:
                other = (pid.get("productId", ""), kind)
        vendor = line.get("vendorDetail") or {}
        refs = [r.get("refNumber", "") for r in vendor.get("referenceNumbers") or []]
        rows.append({
            "po_number": split_pol(pol)[0],
            "pol_number": pol,
            "folio_po_uuid": line.get("purchaseOrderId", ""),
            "po_status": statuses.get(line.get("purchaseOrderId"), ""),
            "title": line.get("titleOrPackage", ""),
            "issn": issn,
            "title_number": other[0] if other else "",
            "title_number_type": other[1] if other else "",
            "vendor_po_number": "; ".join(r for r in refs if r),
            "vendor_account": vendor.get("vendorAccount", ""),
            "subscription_from": details.get("subscriptionFrom", ""),
            "subscription_to": details.get("subscriptionTo", ""),
            "publisher": line.get("publisher", ""),
            "order_format": line.get("orderFormat", ""),
            "po_line_description": line.get("poLineDescription", ""),
            "pol_id": line.get("id", ""),
        })
    return sorted(rows, key=lambda r: r["pol_number"])


def write_title_map(csv_path, rows):
    """Write the title map as CSV, plus an .xlsx copy with a frozen header row."""
    from openpyxl import Workbook
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TITLE_MAP_FIELDS)
        w.writeheader()
        w.writerows(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = "po_title_map"
    ws.append(TITLE_MAP_FIELDS)
    for r in rows:
        ws.append([r[f] for f in TITLE_MAP_FIELDS])
    ws.freeze_panes = "A2"
    xlsx = Path(csv_path).with_suffix(".xlsx")
    wb.save(xlsx)
    return xlsx


def write_csv(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fields = ["po_number", "pol_number", "title", "subscription_to", "pol_id",
              "matches_po_plus_1"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--prefix", help="PO/POL number prefix, e.g. E50")
    src.add_argument("--csv", help="CSV of PO numbers")
    p.add_argument("--ini", required=True, help="tenant .ini file")
    p.add_argument("--out", default="out/pol_export.csv")
    args = p.parse_args(argv)

    from pipeline.folio_common import connect
    pos = read_po_numbers(args.csv) if args.csv else None
    rows = export_rows(fetch_lines(connect(args.ini), args.prefix, pos))
    write_csv(args.out, rows)
    odd = sum(1 for r in rows if r["matches_po_plus_1"] != "yes")
    print("%d order lines written to %s (%d not PO+'-1')" % (len(rows), args.out, odd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
