"""Convert EBSCONET purchase orders from one-time to ongoing (instruction step 25).

Input is a CSV of PO numbers (Orders app CSV export, or one PO number per line).
Nothing is written to FOLIO unless --live is given; the default is a dry run.
Settings (interval, subscription flag, renewal date rule) live in the "ongoing"
section of ebsconet_config.json -- see README.md.
"""
import argparse
import csv
import re
from pathlib import Path

from ebsconet_prep import load_config

HEADER_NAMES = {"ponumber", "po"}


def read_po_numbers(path):
    """PO numbers from a CSV. Uses a 'PO number'-style header if there is one,
    otherwise the first column of every row. Duplicates are dropped."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.reader(fh) if r and any(c.strip() for c in r)]
    if not rows:
        return []
    norm = [re.sub(r"[\s_]", "", c).lower() for c in rows[0]]
    col, data = 0, rows
    for i, name in enumerate(norm):
        if name in HEADER_NAMES:
            col, data = i, rows[1:]
            break
    seen, out = set(), []
    for r in data:
        po = r[col].strip() if col < len(r) else ""
        if po and po not in seen:
            seen.add(po)
            out.append(po)
    return out


def renewal_date(order, source):
    """Renewal date taken from the lines' subscription end dates (or None)."""
    if source == "none":
        return None
    dates = [ln.get("details", {}).get("subscriptionTo")
             for ln in order.get("compositePoLines", [])]
    dates = [d for d in dates if d]
    if not dates:
        return None
    return max(dates) if source == "latest_subscription_to" else min(dates)


def build_ongoing(order, settings):
    """Return a copy of the composite order converted to an ongoing order."""
    new = dict(order)
    ongoing = {"interval": settings["interval_days"],
               "isSubscription": settings["is_subscription"],
               "manualRenewal": settings["manual_renewal"]}
    date = renewal_date(order, settings["renewal_date_source"])
    if date:
        ongoing["renewalDate"] = date
    new["orderType"] = "Ongoing"
    new["ongoing"] = ongoing
    new["compositePoLines"] = [drop_empty_product_ids(ln)
                               for ln in order.get("compositePoLines", [])]
    return new


def drop_empty_product_ids(line):
    """Data Import leaves a blank product-ID entry on lines without a title number;
    remove entries that have no product ID (returns a copy)."""
    line = dict(line)
    details = dict(line.get("details") or {})
    if "productIds" in details:
        details["productIds"] = [p for p in details["productIds"] if p.get("productId")]
        line["details"] = details
    return line


def convert_po(client, po_number, settings, live):
    """Convert one PO. Returns (status, note); status is converted / dry-run /
    skipped / not-found / error."""
    if '"' in po_number:
        return "error", "invalid PO number"
    found = client.folio_get("/orders/composite-orders", key="purchaseOrders",
                             query='poNumber=="%s"' % po_number)
    if not found:
        return "not-found", ""
    if len(found) > 1:
        return "error", "%d POs share this number" % len(found)
    path = "/orders/composite-orders/%s" % found[0]["id"]
    order = client.folio_get(path)
    if order.get("orderType") == "Ongoing":
        return "skipped", "already Ongoing"
    if order.get("workflowStatus") != "Pending":
        return "skipped", "status is %s, not Pending" % order.get("workflowStatus")
    new = build_ongoing(order, settings)
    note = "renewalDate=%s" % new["ongoing"].get("renewalDate", "none")
    if not live:
        return "dry-run", note
    client.folio_put(path, new)
    return "converted", note


def convert_all(client, po_numbers, settings, live):
    results = []
    for po in po_numbers:
        try:
            status, note = convert_po(client, po, settings, live)
        except Exception as exc:  # keep going; the log shows which POs failed
            status, note = "error", "%s: %s" % (type(exc).__name__, exc)
        results.append((po, status, note))
    return results


def write_log(path, results):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["po_number", "status", "note"])
        w.writerows(results)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv", help="CSV of PO numbers")
    p.add_argument("--ini", required=True, help="tenant .ini file")
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--log", default="out/ongoing_log.csv")
    p.add_argument("--live", action="store_true",
                   help="actually update FOLIO (default is a dry run)")
    args = p.parse_args(argv)

    from folio_common import connect
    settings = load_config(args.config)["ongoing"]
    pos = read_po_numbers(args.csv)
    print("%d PO numbers; %s" % (len(pos), "LIVE" if args.live else "dry run"))
    results = convert_all(connect(args.ini), pos, settings, args.live)
    write_log(args.log, results)
    counts = {}
    for _, status, _ in results:
        counts[status] = counts.get(status, 0) + 1
    print(", ".join("%s: %d" % kv for kv in sorted(counts.items())))
    print("log:", args.log)
    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
