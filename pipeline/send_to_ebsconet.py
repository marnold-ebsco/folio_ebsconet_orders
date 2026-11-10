"""Build send_to_ebsconet.xlsx: the SOP rows that were loaded into FOLIO, unchanged, plus the
POL number in the `ILS Number` column.

`for-customer` saves an untouched copy of the SOP as out/sop_original.xlsx (the prepared
workbooks drop many SOP columns); `finish` reads that copy and the PO lines read back from
FOLIO (the title map rows), and writes one row per loaded line.
"""
from pathlib import Path

from openpyxl import Workbook

SOP_COPY = "sop_original.xlsx"
SEND_FILE = "send_to_ebsconet.xlsx"
ILS = "ILS Number"
SEND_HEADERS = [
    "Title Name", "ISSN", "Format", "Descriptor", "Start Date", "Expiration Date", "Term",
    "Quantity", "Frequency", "Order Number", "Order Type", "Invoice Date", "Invoice Number",
    "Total Cost", "Currency", "Purchase Order Number", "Fund Code", "Publisher Identification",
    "Registration ID", "Publisher Product Code", "Publisher Package", "Publisher Name",
    "Publisher Group Name", "Publisher Country", "Publisher Dispatch Country",
    "Country of Origin", "Language", "Dewey Decimal Code", "Library of Congress Classification",
    "Universal Decimal Classification", "Subject Category", "Comment 1", "Comment 2",
    "Comment 3", "Cancellable", "E-Journal Contacts", "Open Access", "URL", "Your Access",
    "Account Number", "Subscriber Code", "Subscriber Name", "Subscriber Address",
    "Subscriber City", "Subscriber State", "Subscriber Country", "Subscriber Postal Code",
    "Special Department", "Special Name", "Customer Name", "Customer Address",
    "Customer Postal Code", ILS]


def norm(value):
    """Compare text ignoring case and runs of spaces; None is empty."""
    return " ".join(str(value if value is not None else "").split()).casefold()


def match_rows(sop_rows, map_rows, order_col, title_col, issn_col):
    """Pair each loaded FOLIO line (a title map row) with its SOP row.

    Rows are matched on Order Number, then Title Name + ISSN, then Title Name. If the title
    differs, the SOP row is taken only when it is the PO's one remaining candidate (so an
    excluded row that shares the order number is never picked by guesswork).
    Returns ([(sop_row, pol_number)] in SOP order, [map rows with no SOP row]).
    """
    by_order = {}
    for index, row in enumerate(sop_rows):
        by_order.setdefault(norm(row.get(order_col)), []).append((index, row))
    used, matched, unmatched = set(), [], []
    for line in map_rows:
        pool = [(i, r) for i, r in by_order.get(norm(line["po_number"]), []) if i not in used]
        title, issn = norm(line["title"]), norm(line["issn"])
        pick = (next((p for p in pool if norm(p[1].get(title_col)) == title
                      and norm(p[1].get(issn_col)) == issn), None)
                or next((p for p in pool if norm(p[1].get(title_col)) == title), None)
                or (pool[0] if len(pool) == 1 else None))
        if pick is None:
            unmatched.append(line)
            continue
        used.add(pick[0])
        matched.append((pick[0], pick[1], line["pol_number"]))
    matched.sort(key=lambda m: m[0])
    return [(row, pol) for _, row, pol in matched], unmatched


def write_send_file(path, matched):
    """Write the headers and one row per (sop_row, pol_number); returns the row count."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(SEND_HEADERS)
    for row, pol in matched:
        ws.append([pol if h == ILS else row.get(h) for h in SEND_HEADERS])
    ws.freeze_panes = "A2"
    wb.save(path)
    return len(matched)
