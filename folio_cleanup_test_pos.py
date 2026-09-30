"""Remove the purchase orders that test loads created on a test tenant.

The list of POs comes from the PO numbers (990$o) in your local .mrc files, so only
orders you loaded from this project can be touched. Each PO must also be
  * Pending, and
  * for the EBSCONET vendor organization (vendor_org_code in ebsconet_config.json).
Anything else is skipped and reported. Every PO is saved as JSON in the backup folder
before it is deleted. Dry run unless --live.

Default input: every out/marc/*.mrc (add more with --mrc, or single POs with --po).
Only run this against a TEST tenant.
"""
import argparse
import glob

from pipeline.ebsconet_prep import load_config
from folio_delete_orders import delete_po, write_log
from pipeline.folio_import import po_numbers


def collect_numbers(mrc_paths, extra=()):
    """Distinct PO numbers from the .mrc files plus any explicit ones, in order."""
    numbers = []
    for path in mrc_paths:
        try:
            numbers += po_numbers(path)
        except (KeyError, OSError):          # a file with no 990$o
            continue
    numbers += list(extra)
    return list(dict.fromkeys(n for n in numbers if n))


def vendor_matches(client, number, vendor_id):
    """True/False, or None when the PO does not exist."""
    found = client.folio_get("/orders/composite-orders", key="purchaseOrders",
                             query_params={"query": 'poNumber=="%s"' % number,
                                           "limit": 2})
    if not found:
        return None
    return found[0].get("vendor") == vendor_id


def cleanup(client, numbers, vendor_id, live, backup_dir):
    """Returns [(number, status, detail)]."""
    results = []
    for n in numbers:
        try:
            match = vendor_matches(client, n, vendor_id)
            if match is None:
                results.append((n, "not-found", ""))
            elif not match:
                results.append((n, "skipped", "PO is for a different vendor"))
            else:
                status, detail = delete_po(client, n, live, backup_dir)
                results.append((n, status, detail))
        except Exception as exc:  # keep going; the log shows what failed
            results.append((n, "error", "%s: %s" % (type(exc).__name__, exc)))
    return results


def tally(results):
    counts = {}
    for _, status, _ in results:
        counts[status] = counts.get(status, 0) + 1
    return ", ".join("%s: %d" % kv for kv in sorted(counts.items()))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ini", required=True)
    p.add_argument("--mrc", action="append", help=".mrc file to take PO numbers from "
                   "(repeatable; default out/marc/*.mrc)")
    p.add_argument("--po", action="append", default=[], help="extra PO number")
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--live", action="store_true", help="actually delete")
    p.add_argument("--max", type=int, default=300)
    p.add_argument("--backup-dir", default="out/deleted_backup")
    p.add_argument("--log", default="out/cleanup_test_pos_log.csv")
    args = p.parse_args(argv)

    mrcs = args.mrc or sorted(glob.glob("out/marc/*.mrc"))
    numbers = collect_numbers(mrcs, args.po)
    if not numbers:
        print("no PO numbers found")
        return 0
    if len(numbers) > args.max:
        raise SystemExit("%d POs is more than --max %d" % (len(numbers), args.max))

    from pipeline.folio_common import connect
    client = connect(args.ini)
    code = load_config(args.config)["folio"]["vendor_org_code"]
    vendor = client.folio_get("/organizations/organizations", key="organizations",
                              query_params={"query": 'code=="%s"' % code, "limit": 2})
    if not vendor:
        raise SystemExit("vendor organization %s not found" % code)
    print("%d PO numbers from %d file(s); %s (%s)" % (
        len(numbers), len(mrcs), "LIVE - DELETING" if args.live else "dry run",
        args.ini))
    results = cleanup(client, numbers, vendor[0]["id"], args.live, args.backup_dir)
    write_log(args.log, [("PO", n, s, d, "") for n, s, d in results])
    for n, status, detail in results:
        if status in ("skipped", "error"):
            print("  %-10s %-10s %s" % (n, status, detail))
    print(tally(results))
    print("log:", args.log)
    return 1 if any(r[1] == "error" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
