"""EBSCONET SOP -> FOLIO orders: one command with a step per stage of the workflow.

  for-customer SOP.xlsx   stage 1: drop zero-dollar lines, split by format and add the
                          columns the customer fills in -> three spreadsheets in
                          out/customer/ (electronic, physical, P-E); send these
  build FILLED.xlsx ...   stage 2: process the filled-in spreadsheets (one, or all
                          three) and build the MARC files (out/library-EBSCONET_*.xlsx
                          and out/marc/*.mrc)
  setup                   once per tenant: vendor accounts and Data Import profiles
                          (the profiles are only needed for --use-marc)
  load                    create the POs through the Orders API (default); with
                          --use-marc: preflight + load the MARC files by Data Import
  finish                  export the PO / POL numbers for EBSCONET (out/pol_export.csv);
                          with --use-marc, first convert the loaded POs to ongoing

Nothing is written to FOLIO without --live (setup, load, finish). RUNBOOK.md has the
full workflow; the lower-level tools (retry, delete, add lines, ...) stay separate.
"""
import argparse
import sys
from pathlib import Path

from pipeline.ebsconet_prep import ROUTES, load_config, prepare, prepare_for_customer
from pipeline.ebsconet_to_marc import convert_all
from pipeline.folio_setup import ROUTE_LABEL


def marc_files(out, cfg):
    """[(route, path)] for the MARC files that exist after `build`."""
    found = []
    for route in ROUTES:
        path = Path(out) / cfg["marc_output_dir"] / (Path(cfg["output_names"][route]).stem
                                                     + ".mrc")
        if path.exists():
            found.append((route, path))
    return found


def cmd_for_customer(args, cfg):
    s = prepare_for_customer(args.input, args.out, cfg)
    print("%d lines read; %d zero-dollar lines removed; %d lines not sent (Fee or "
          "unrecognized format); %d lines for the customer"
          % (s["read"], s["removed"], s["unrouted"], s["kept"]))
    for route, path in s["files"].items():
        print("send: %s (%d lines; customer fills in: %s)" % (
            path, s["counts"][route], ", ".join(s["columns"][route])))
    return 0


def cmd_build(args, cfg):
    s = prepare(args.input, args.out, cfg, cfg["headers_file"])
    results = convert_all(args.out, cfg, cfg["headers_file"])
    print(Path(args.out, "prep_report.txt").read_text(encoding="utf-8"))
    bad = False
    for r in results:
        print("%s: %d records" % (r["file"], r["records"]))
        for problem in r["problems"]:
            print("  ERROR", problem)
            bad = True
    print("loadable: %d; excluded: %d" % (sum(s["routed"].values()), s["excluded"]))
    return 1 if bad else 0


def cmd_setup(args, cfg):
    from pipeline import folio_setup
    argv = ["--ini", args.ini, "--config", args.config, "--in-dir", args.out,
            "--out", args.out]
    if args.live:
        argv.append("--live")
    if args.update_mappings:
        argv.append("--update-mappings")
    return folio_setup.main(argv)


def cmd_load(args, cfg):
    if args.use_marc:
        return load_marc(args, cfg)
    from pipeline import folio_orders_adapter as adapter
    results = adapter.load_orders(args.out, args.ini, cfg, args.live, args.skip_accounts)
    counts = {}
    for po, status, detail in results:
        counts[status] = counts.get(status, 0) + 1
        if status in adapter.BAD_STATUS:
            print("  %s %s: %s" % (status.upper(), po, detail))
    print("load results (%s): %s" % (
        "LIVE" if args.live else "dry run",
        ", ".join("%s %d" % kv for kv in sorted(counts.items())) or "nothing to load"))
    return 1 if any(s in adapter.BAD_STATUS for s in counts) else 0


def load_marc(args, cfg):
    from pipeline import folio_import
    files = [(r, p) for r, p in marc_files(args.out, cfg)
             if not args.only or r == args.only]
    if not files:
        print("no MARC files in %s; run `build` first" % Path(args.out, cfg["marc_output_dir"]))
        return 1
    outcome = {}
    for route, path in files:
        print("\n=== %s: %s ===" % (route, path.name))
        argv = [str(path), "--ini", args.ini, "--config", args.config,
                "--job-profile", "%s - %s" % (cfg["folio"]["profile_name_prefix"],
                                              ROUTE_LABEL[route]),
                "--log-dir", str(Path(args.out) / "import_logs")]
        for flag, on in (("--live", args.live), ("--skip-preflight", args.skip_preflight),
                         ("--no-cleanup", args.no_cleanup)):
            if on:
                argv.append(flag)
        try:
            outcome[route] = folio_import.main(argv)
        except SystemExit as stop:                   # preflight errors etc.
            outcome[route] = stop.code if isinstance(stop.code, int) else 1
            if not isinstance(stop.code, int):
                print(stop.code)
    summary = ", ".join("%s %s" % (r, "ok" if not rc else "PROBLEM")
                        for r, rc in outcome.items())
    print("\nload results: " + summary)
    return 1 if any(outcome.values()) else 0


def cmd_finish(args, cfg):
    from pipeline import folio_export_pols
    from pipeline import folio_ongoing
    from pipeline.folio_common import connect
    from pipeline.folio_import import po_numbers
    if args.use_marc:
        numbers = []
        for _, path in marc_files(args.out, cfg):
            numbers += po_numbers(path)
        empty = "no MARC files in %s; nothing to finish" % args.out
    else:
        from pipeline.folio_orders_adapter import workbook_lines
        numbers = [line["po_number"] for line in workbook_lines(args.out, cfg)]
        empty = "no prepared workbooks in %s; nothing to finish" % args.out
    numbers = list(dict.fromkeys(numbers))
    if not numbers:
        print(empty)
        return 1
    client = connect(args.ini)
    counts = {}
    if args.use_marc:
        print("%d PO numbers; ongoing conversion: %s" % (
            len(numbers), "LIVE" if args.live else "dry run"))
        settings_file = Path(args.out) / "order_settings.csv"
        choices = (folio_ongoing.read_order_settings(settings_file)
                   if settings_file.exists() else {})
        results = folio_ongoing.convert_all(client, numbers, cfg["ongoing"], args.live,
                                            choices)
        log = Path(args.out) / "ongoing_log.csv"
        folio_ongoing.write_log(log, results)
        for _, status, _ in results:
            counts[status] = counts.get(status, 0) + 1
        print(", ".join("%s: %d" % kv for kv in sorted(counts.items())), "| log:", log)
    else:
        print("%d PO numbers; the API load already set order type and renewal "
              "details, so there is no ongoing conversion" % len(numbers))
    rows = folio_export_pols.export_rows(
        folio_export_pols.fetch_lines(client, po_numbers=numbers))
    export = Path(args.out) / "pol_export.csv"
    folio_export_pols.write_csv(export, rows)
    odd = sum(1 for r in rows if r["matches_po_plus_1"] != "yes")
    print("PO / POL export: %d lines -> %s (%d not PO+'-1')" % (len(rows), export, odd))
    return 1 if counts.get("error") else 0


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--out", default="out", help="working folder (default out)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("for-customer", help="stage 1: spreadsheet to send to the customer")
    s.add_argument("input", help="the SOP .xlsx received from EBSCONET")
    s.set_defaults(func=cmd_for_customer)

    s = sub.add_parser("build", help="stage 2: process the filled-in spreadsheet")
    s.add_argument("input", nargs="+", help="the spreadsheet(s) the customer sent back "
                   "(electronic, physical and P-E)")
    s.set_defaults(func=cmd_build)

    for name, func, text in (("setup", cmd_setup, "once per tenant: accounts and profiles"),
                             ("load", cmd_load, "preflight and load the MARC files"),
                             ("finish", cmd_finish, "ongoing conversion and POL export")):
        s = sub.add_parser(name, help=text)
        s.add_argument("--ini", required=True, help="tenant .ini file")
        s.add_argument("--live", action="store_true", help=(
            "write to FOLIO (default: dry run)" if name != "finish" else
            "--use-marc only: really convert the POs to ongoing (default: dry run)"))
        if name == "setup":
            s.add_argument("--update-mappings", action="store_true",
                           help="overwrite existing mapping profiles")
        if name in ("load", "finish"):
            s.add_argument("--use-marc", action="store_true",
                           help="use the MARC / Data Import route instead of the Orders "
                           "API (the backup route)")
        if name == "load":
            s.add_argument("--skip-accounts", action="store_true",
                           help="API route: do not add SOP account numbers to the vendors")
            s.add_argument("--only", choices=ROUTES,
                           help="--use-marc only: load just one file")
            s.add_argument("--skip-preflight", action="store_true",
                           help="--use-marc only")
            s.add_argument("--no-cleanup", action="store_true", help="--use-marc only")
        s.set_defaults(func=func)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)
    return args.func(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
