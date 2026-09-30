"""Export PO / POL numbers for the EBSCONET renewal integration (instruction step 26).

Give it either --prefix (all order lines whose number starts with it) or a CSV of PO
numbers. EBSCONET is told the POL number is the PO number plus "-1"; lines that do not
follow that pattern (for example the second line of a two-line PO) are flagged.
"""
import argparse
import csv
from pathlib import Path

from folio_ongoing import read_po_numbers


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

    from folio_common import connect
    pos = read_po_numbers(args.csv) if args.csv else None
    rows = export_rows(fetch_lines(connect(args.ini), args.prefix, pos))
    write_csv(args.out, rows)
    odd = sum(1 for r in rows if r["matches_po_plus_1"] != "yes")
    print("%d order lines written to %s (%d not PO+'-1')" % (len(rows), args.out, odd))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
