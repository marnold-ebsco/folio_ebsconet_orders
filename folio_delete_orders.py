"""Delete problem purchase orders / PO lines listed in a CSV file.

CSV columns (header required; lines starting with # are ignored):
    type,number,note
    PO,U1234567,imported with wrong fund      <- deletes the PO and all its lines
    POL,U1234567-2,duplicate line             <- deletes just that line

Safety: dry run unless --live; only Pending orders are touched (an Open order must be
handled in FOLIO first); every PO/line is saved as JSON in <backup-dir> before it is
deleted; --max stops a runaway list. Results go to a CSV log.
"""
import argparse
import csv
import json
from pathlib import Path

TYPES = {"PO", "POL"}


def read_targets(path):
    """Return [(type, number, note)] from the CSV; raises ValueError on bad rows."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        lines = [ln for ln in fh if ln.strip() and not ln.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines))
    if not rows and not lines:
        return []
    targets, seen = [], set()
    for n, row in enumerate(rows, start=2):
        kind = (row.get("type") or "").strip().upper()
        number = (row.get("number") or "").strip()
        if kind not in TYPES or not number or '"' in number:
            raise ValueError("row %d: type must be PO or POL and number is required "
                             "(got %r, %r)" % (n, row.get("type"), row.get("number")))
        if (kind, number) not in seen:
            seen.add((kind, number))
            targets.append((kind, number, (row.get("note") or "").strip()))
    return targets


def backup(backup_dir, name, payload):
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    path = Path(backup_dir) / ("%s.json" % name)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def find_one(client, path, key, field, number):
    found = client.folio_get(path, key=key, query_params={
        "query": '%s=="%s"' % (field, number), "limit": 3})
    return found


def delete_po(client, number, live, backup_dir):
    found = find_one(client, "/orders/composite-orders", "purchaseOrders",
                     "poNumber", number)
    if not found:
        return "not-found", ""
    if len(found) > 1:
        return "error", "%d POs share this number" % len(found)
    order = client.folio_get("/orders/composite-orders/%s" % found[0]["id"])
    if order.get("workflowStatus") != "Pending":
        return "skipped", "status is %s, not Pending" % order.get("workflowStatus")
    lines = len(order.get("compositePoLines", []))
    note = "%d line(s)" % lines
    if not live:
        return "dry-run", note
    backup(backup_dir, "PO_" + number, order)
    client.folio_delete("/orders/composite-orders/%s" % order["id"])
    return "deleted", note


def delete_pol(client, number, live, backup_dir):
    found = find_one(client, "/orders/order-lines", "poLines", "poLineNumber", number)
    if not found:
        return "not-found", ""
    if len(found) > 1:
        return "error", "%d lines share this number" % len(found)
    line = client.folio_get("/orders/order-lines/%s" % found[0]["id"])
    order = client.folio_get("/orders/composite-orders/%s" % line["purchaseOrderId"])
    if order.get("workflowStatus") != "Pending":
        return "skipped", "PO status is %s, not Pending" % order.get("workflowStatus")
    others = len(order.get("compositePoLines", [])) - 1
    note = "PO keeps %d other line(s)" % others if others else "LAST line - PO left empty"
    if not live:
        return "dry-run", note
    backup(backup_dir, "POL_" + number, line)
    client.folio_delete("/orders/order-lines/%s" % line["id"])
    return "deleted", note


def run(client, targets, live, backup_dir):
    results = []
    for kind, number, note in targets:
        try:
            fn = delete_po if kind == "PO" else delete_pol
            status, detail = fn(client, number, live, backup_dir)
        except Exception as exc:  # keep going; the log shows what failed
            status, detail = "error", "%s: %s" % (type(exc).__name__, exc)
        results.append((kind, number, status, detail, note))
    return results


def write_log(path, results):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "number", "status", "detail", "note"])
        w.writerows(results)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", nargs="?", default="orders_to_delete.csv")
    p.add_argument("--ini", required=True)
    p.add_argument("--live", action="store_true", help="actually delete (default: dry run)")
    p.add_argument("--max", type=int, default=50, help="refuse lists longer than this")
    p.add_argument("--backup-dir", default="out/deleted_backup")
    p.add_argument("--log", default="out/delete_log.csv")
    args = p.parse_args(argv)

    targets = read_targets(args.csv)
    if not targets:
        print("nothing listed in", args.csv)
        return 0
    if len(targets) > args.max:
        raise SystemExit("%d entries is more than --max %d; raise --max if intended"
                         % (len(targets), args.max))
    from pipeline.folio_common import connect
    client = connect(args.ini)
    print("%d entries; %s (%s)" % (len(targets), "LIVE - DELETING" if args.live
                                   else "dry run", args.ini))
    results = run(client, targets, args.live, args.backup_dir)
    write_log(args.log, results)
    for kind, number, status, detail, _ in results:
        print("%-3s %-16s %-10s %s" % (kind, number, status, detail))
    return 1 if any(r[2] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
