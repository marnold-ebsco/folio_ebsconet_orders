"""Remove empty product-ID entries from PO lines.

Data Import builds two product-ID rows on every line (ISSN and title number). When a
record has no ISSN or no title number the row is created anyway, empty. FOLIO shows the
empty row and will not save an edit of the line while it is there. This removes the empty
rows and keeps the real ones, so a line with only a publisher number ends up with just
that one row. folio_import.py runs it automatically after each load.

Dry run unless --live. Only lines of Pending orders are changed.
    folio_clean_product_ids.py out/marc/file.mrc --ini tenant.ini
    folio_clean_product_ids.py --csv po_numbers.csv --ini tenant.ini --live
"""
import argparse

from pipeline.folio_ongoing import drop_empty_product_ids, read_po_numbers


def has_empty_entry(line):
    ids = (line.get("details") or {}).get("productIds") or []
    return any(not p.get("productId") for p in ids)


def clean_lines(client, po_numbers, live):
    """Returns [(line number, status, detail)] for lines that had an empty entry.
    Status: cleaned / would-clean / skipped."""
    results = []
    for po in po_numbers:
        lines = client.folio_get("/orders/order-lines", key="poLines", query_params={
            "query": 'poLineNumber=="%s-*"' % po, "limit": 50})
        for line in lines:
            if not has_empty_entry(line):
                continue
            number = line.get("poLineNumber", po)
            order = client.folio_get("/orders/composite-orders/%s"
                                     % line["purchaseOrderId"])
            if order.get("workflowStatus") != "Pending":
                results.append((number, "skipped",
                                "PO status is %s, not Pending" % order.get("workflowStatus")))
                continue
            full = client.folio_get("/orders/order-lines/%s" % line["id"])
            cleaned = drop_empty_product_ids(full)
            kept = len((cleaned.get("details") or {}).get("productIds", []))
            detail = "%d product ID(s) kept" % kept
            if live:
                client.folio_put("/orders/order-lines/%s" % line["id"], cleaned)
            results.append((number, "cleaned" if live else "would-clean", detail))
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mrc", nargs="?", help=".mrc file whose POs to clean")
    p.add_argument("--csv", help="CSV of PO numbers instead of a .mrc")
    p.add_argument("--ini", required=True)
    p.add_argument("--live", action="store_true")
    args = p.parse_args(argv)
    if bool(args.mrc) == bool(args.csv):
        p.error("give either a .mrc file or --csv")
    if args.csv:
        numbers = read_po_numbers(args.csv)
    else:
        from pipeline.folio_import import po_numbers
        numbers = po_numbers(args.mrc)
    from pipeline.folio_common import connect
    results = clean_lines(connect(args.ini), numbers, args.live)
    for number, status, detail in results:
        print("%-16s %-12s %s" % (number, status, detail))
    print("%d of %d PO(s) had lines with empty product IDs (%s)" % (
        len(results), len(numbers), "cleaned" if args.live else "dry run"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
