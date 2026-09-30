"""After a partial import, build a retry file with only the records that did not load.

A record counts as loaded when its PO exists and has a PO line. Records whose PO is
missing go straight into the retry file. Records whose PO exists WITHOUT a line (Data
Import created the order but discarded the line) also go into the retry file, and the
empty PO is listed in a delete CSV (same format as folio_delete_orders.py) because the
retry would otherwise collide with the existing PO number.

Read-only: nothing is changed in FOLIO. Typical use:
    folio_retry_failed.py out/marc/file.mrc --ini tenant.ini
    folio_delete_orders.py out/retry/file_delete_empty.csv --ini tenant.ini --live
    (fix the cause, then) folio_import.py out/retry/file_retry.mrc --ini ... --live
"""
import argparse
import csv
from pathlib import Path

from pymarc import MARCReader

from folio_import import po_numbers, po_results


def classify(results):
    """Split po_results output into (ok, missing, empty) lists of PO numbers."""
    ok = [r["po"] for r in results if r["ok"]]
    missing = [r["po"] for r in results if not r["exists"]]
    empty = [r["po"] for r in results if r["exists"] and r["lines"] == 0]
    return ok, missing, empty


def write_retry_mrc(source, keep, out_path):
    """Copy the records whose 990$o is in `keep` to a new .mrc; returns the count."""
    keep = set(keep)
    count = 0
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as fh, open(out_path, "wb") as out:
        for rec in MARCReader(fh, to_unicode=True, force_utf8=True):
            po = {s.code: s.value for s in rec["990"].subfields}.get("o")
            if po in keep:
                out.write(rec.as_marc())
                count += 1
    return count


def write_delete_csv(path, empty):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "number", "note"])
        for po in empty:
            w.writerow(["PO", po, "empty PO left by a failed import; delete before retry"])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mrc")
    p.add_argument("--ini", required=True)
    p.add_argument("--out-dir", default="out/retry")
    args = p.parse_args(argv)
    from folio_common import connect
    results = po_results(connect(args.ini), po_numbers(args.mrc))
    ok, missing, empty = classify(results)
    print("%d records: %d loaded, %d missing, %d empty PO(s)"
          % (len(results), len(ok), len(missing), len(empty)))
    if not missing and not empty:
        print("nothing to retry")
        return 0
    stem = Path(args.mrc).stem
    retry = Path(args.out_dir) / ("%s_retry.mrc" % stem)
    n = write_retry_mrc(args.mrc, missing + empty, retry)
    print("retry file: %s (%d records)" % (retry, n))
    if empty:
        delete_csv = Path(args.out_dir) / ("%s_delete_empty.csv" % stem)
        write_delete_csv(delete_csv, empty)
        print("delete first: %s (%d empty PO(s))" % (delete_csv, len(empty)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
