"""Map the prepared EBSCONET workbooks to folio_orders_loader's neutral line records.

An alternative to the MARC / Data Import route: the rows of the prep workbooks
(library-EBSCONET_online / -print / _P-E .xlsx) become line records that
`folio_orders_loader.load()` posts through the Orders API, so repeated order numbers
become extra lines of one PO. Nothing is written to FOLIO from here.
"""
import argparse
import re
from pathlib import Path

from pipeline.ebsconet_prep import blank, load_config
from pipeline.ebsconet_to_marc import fmt_value, read_rows
from pipeline.folio_setup import add_accounts

ROUTE_FORMAT = {
    "online": "Electronic Resource",
    "print": "Physical Resource",
    "pe": "P/E Mix",
}


def location_code(text):
    """'name (CODE)' -> 'CODE'; a bare code is returned as is."""
    found = re.search(r"\(([^()]*)\)\s*$", text)
    return found.group(1).strip() if found else text


def _text(row, column):
    return fmt_value(row.get(column)) if column else ""


def row_to_line(row, route, cfg):
    """One workbook row -> one neutral line record (see folio_orders_loader.records)."""
    col = cfg["columns"]
    add = cfg["added_columns"]
    folio = cfg["folio"]
    ongoing = cfg["ongoing"]

    order_type = _text(row, add["order_type"]) or ongoing["default_order_type"]
    org = _text(row, add["org"]) or cfg.get("default_org")
    expense = _text(row, add["expense_class"]) or cfg.get("default_expense_class")
    physical = route != "online"

    product_ids = []
    if _text(row, col["issn"]):
        product_ids.append({"type": "ISSN", "value": _text(row, col["issn"])})
    if _text(row, add["title_number"]):
        product_ids.append({
            "type": _text(row, add["title_number_type"]) or folio["title_number_type"],
            "value": _text(row, add["title_number"])})

    line = {
        "po_number": _text(row, col["order_number"]),
        "vendor_code": org,
        "title": _text(row, col["title"]),
        "order_format": ROUTE_FORMAT[route],
        "cost": _text(row, col["cost"]).replace(",", ""),
        "currency": folio["currency"],
        "fund_code": _text(row, add["fund"]),
        "expense_class_code": expense,
        "order_type": order_type,
        "acquisition_method": folio["acquisition_method"],
        "product_ids": product_ids,
        "subscription_from": _text(row, col["start_date"]),
        "subscription_to": _text(row, col["expiration_date"]),
        "publisher": _text(row, col["publisher"]),
        "description": _text(row, add["po_line_description"]),
        "receipt_status": folio["receipt_status"][route],
        "cancellation_restriction": _text(
            row, add["cancellation_restriction"]).lower() in ("yes", "true", "1"),
    }
    if _text(row, col["account"]):
        line["vendor_account"] = _text(row, col["account"])
    if order_type == "Ongoing":
        interval = _text(row, add["renewal_interval"]) or ongoing["interval_days"]
        line["interval_days"] = int(float(interval))
        line["is_subscription"] = ongoing["is_subscription"]
        line["manual_renewal"] = ongoing["manual_renewal"]
    if physical:
        line["material_type"] = (_text(row, add["material_type"])
                                 or folio["physical_material_type"])
        line["location_code"] = location_code(
            _text(row, add["location"]) or folio["location"])
    return line


def workbook_lines(in_dir, cfg):
    """All lines from the prep workbooks found in in_dir, in route order."""
    lines = []
    for route, name in cfg["output_names"].items():
        path = Path(in_dir) / name
        if not path.exists():
            continue
        for row in read_rows(path):
            if all(blank(v) for v in row.values()):
                continue
            lines.append(row_to_line(row, route, cfg))
    return lines


def accounts_by_org(lines):
    """{org code: sorted account numbers} for the lines that carry a vendor account."""
    found = {}
    for line in lines:
        if line.get("vendor_account") and line.get("vendor_code"):
            found.setdefault(line["vendor_code"], set()).add(line["vendor_account"])
    return {code: sorted(numbers) for code, numbers in found.items()}


def ensure_accounts(client, lines, payment_method, live):
    """Add each line's account number to its vendor organization if it is missing.

    Returns [(org code, added, already_there)]; an organization that is not found is
    reported with added=None and left for the loader's own checks to reject.
    """
    report = []
    for code, numbers in sorted(accounts_by_org(lines).items()):
        found = client.folio_get("/organizations/organizations", key="organizations",
                                 query_params={"query": 'code=="%s"' % code, "limit": 2})
        if not found:
            report.append((code, None, []))
            continue
        added, have = add_accounts(client, found[0], numbers, payment_method, live)
        report.append((code, added, have))
    return report


def main(argv=None):
    from folio_orders_loader.client import connect
    from folio_orders_loader.loader import load

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--in-dir", default="out", help="folder holding the prep workbooks")
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--ini", required=True, help="tenant .ini file")
    p.add_argument("--live", action="store_true", help="really POST (default: dry run)")
    p.add_argument("--skip-accounts", action="store_true",
                   help="do not add the SOP account numbers to the vendor organizations")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    lines = workbook_lines(args.in_dir, cfg)
    print("%d lines from %s" % (len(lines), args.in_dir))
    client = connect(args.ini)
    if not args.skip_accounts:
        payment = cfg["folio"]["account_payment_method"]
        for code, added, have in ensure_accounts(client, lines, payment, args.live):
            if added is None:
                print("organization %s not found; accounts not added" % code)
            else:
                print("accounts on %s: %d %s, %d already present" % (
                    code, len(added), "added" if args.live else "to add", len(have)))
    results = load(client, lines, live=args.live)
    for r in results:
        print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
