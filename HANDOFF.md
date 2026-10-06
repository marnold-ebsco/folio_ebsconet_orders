# Handoff: EBSCOnet orders pipeline (updated 2026-10-02, all code decisions closed; next = EC2 / real-tenant test, then README rework)

Read this for the EBSCOnet / `folio_ebsconet_orders` work (three customer spreadsheets, the
`ebsconet.py` workflow, the adapter). For the API loader package itself
(`folio_orders_loader`) read `~/scratch/folio_orders/HANDOFF.md` instead. The two projects
are related but tracked separately; this file does not repeat loader internals.

Code: `~/scratch/EBSCOnet` (Windows: `\\wsl.localhost\Ubuntu-24.04\home\marnold\scratch\EBSCOnet`),
GitHub `marnold-ebsco/folio_ebsconet_orders`, SSH remote only. Run everything with
`.venv/bin/python` from that folder (system `python3` lacks `httpx`), via
`wsl.exe -e bash -lc '...'`. Write patch scripts / commit messages to a file with the Write
tool; inline quoting and heredocs with backticks break.

**Dev work folder:** the checkout keeps tenant `.ini` files, a working `ebsconet_config.json`
copy, `out/`, customer xlsx and `test_data_created.json` in git-ignored `work/`. Run via
`bin/ebsconet-dev <subcommand>` (cds into `work/`, uses `.venv`), or by hand:
`cd work && ../.venv/bin/python ../ebsconet.py ...`; other scripts the same way
(`../.venv/bin/python ../folio_cleanup_test_pos.py --ini sunflower_bugfest.ini`). All `out/...`,
`*.ini` paths below are relative to `work/`. The repo-root `ebsconet_config.json` is the tracked
seed template. Docs (README*, RUNBOOK) still show repo-root commands for customers; not rewritten.
221 tests pass, flake8 clean (`--max-line-length=100`).

## State
- On `main` (merged 2026-10-01; `api-load-default` deleted). Loader pinned to v0.3.4
  (`requirements.txt`). The **Orders API is the default load**; the MARC / Data Import route is
  the backup (`--use-marc`).
- `ebsconet.py load` / `finish` use `pipeline/folio_orders_adapter.py` `load_orders()`.
  `--use-marc` on both selects the MARC route. `--skip-accounts` skips the vendor-account step.
  `load` processes every PO, then exits 1 if any is invalid / lookup-failed / error /
  open-error; re-runs skip existing POs. `finish` on the API route only writes
  `out/pol_export.csv` (the API sets the ongoing block).
- **SOP heading validation:** `ebsconet_prep.check_headers()` runs at the start of `prepare()` and
  `prepare_for_customer()` and raises `ValueError` if a required heading is missing
  (`REQUIRED_COLUMNS`: title, issn, format, order_number, cost). Other `columns` may be absent and
  read as blank. To follow a renamed SOP heading, put a `columns` override in the library's
  `work/ebsconet_config.json` (deep-merged over `pipeline/pipeline_config.json`; survives
  `install.sh` upgrades). `folio_setup.accounts_from_workbooks()` uses `columns.account`.
- **Accounts:** the adapter maps SOP `Account Number` -> `vendor_account`; `ensure_accounts()` adds
  each missing account to the vendor org (payment method `folio.account_payment_method`).
  Reference numbers other than PO Number are not mapped (no SOP column).
- **Logs:** each `load` writes `<out>/logs/accounts_<ts>.txt` and `<out>/logs/load_<ts>.txt`
  (mode, ini, timing, totals by status, every PO needing attention) plus a matching `.csv`.
- **Budget checks:** the adapter calls the loader's `load(..., check_budget=True)`, so every PO
  (dry run and `--live`) is checked for an Active budget per fund and a listed expense class;
  failures are `invalid` and nothing is POSTed. Blank expense classes skip the class half, and
  `rules.use_expense_classes: false` leaves `expense_class_code` blank (verified on bugfest: 140
  `dry-run` with classes on and off). Not yet tried on a tenant with real budget limits.
- Docs: `README.md` is an index; `README_API.md` and `README_DATA_IMPORT.md` are standalone
  guides; `RUNBOOK.md`, `PLAN.md`, `docs/CLIENT_GUIDE.md`.

## Installer (root `install.sh`, on `main`, latest commit `e03e89b`)
Fetches the app tarball pinned to a commit SHA from the GitHub API (no tests, packaging, dev
docs) plus the `folio_orders_loader` tag read from the `requirements.txt` pin, over HTTPS (no git
or SSH key). Repos are public, so no token is needed (60 API calls/hour/IP); if made private
again the server needs `GITHUB_TOKEN` with read access to both. Options `--dir` (alias
`--prefix`), `--python`, `--ref`, `--recreate-venv`, `--check`; SHA kept in
`.ebsconet_install_version`. Layout `~/ebsconet/{app,venv,work}`, `ebsconet` linked into
`~/.local/bin`; re-running upgrades code and deps and leaves `work/` alone. The loader is always
force-reinstalled (pip builds its tarball, so the server needs PyPI). To ship a new loader: bump
the loader tag, bump the pin in `requirements.txt`, push, re-run `install.sh`. Fails early if the
interpreter is below 3.12 or cannot `import venv, ensurepip` (Debian/Ubuntu: `sudo apt install
python3-venv`).
- First real EC2 run 2026-10-02: `for-customer` worked after fixes (PATH in
  `~/.bashrc`/`~/.profile`; the wrapper must hold absolute paths; `ebsconet` must be run from
  `work/`). `load`/`finish` on the EC2 not yet tried.
- `bin/ebsconet_configure.py` (installed as `ebsconet-configure`) is an interactive, read-only
  wizard that builds `work/ebsconet_config.json` from the tenant's real codes (not yet tried
  against a live tenant). `--worksheet [FILE]` writes `ebsconet_config_worksheet.xlsx` for the
  customer to fill in; `--from-worksheet FILE` saves the answers into `ebsconet_config.json`
  (needed for `load`, which reads the config, not the workbook).
- On the EC2 the user must re-run `install.sh --dir /working/migration/scripts/ebsconet` to get
  `ebsconet-configure`.
- **Nested-install gotcha (2026-10-06):** running the curl one-liner with no `--dir` from inside
  `/working/migration/scripts/ebsconet` created `/working/migration/scripts/ebsconet/ebsconet`
  (default `--dir` is `./ebsconet` under the current directory) and re-pointed the
  `~/.local/bin/ebsconet*` links at that empty copy. Fix: delete the nested folder, re-run with
  the absolute `--dir /working/migration/scripts/ebsconet`, check `ls -l ~/.local/bin/ebsconet*`.
  Always pass the absolute `--dir`; `CLAUDE.md` says so. Whether the fix has been run on the EC2
  is not confirmed.

## What the workflow does
1. `ebsconet.py for-customer SOP.xlsx [--ini T.ini]` writes ONE workbook,
   `out/customer/<name>_for_customer.xlsx`: sheet 1 `Defaults` (the setup questions of
   `ebsconet-configure --worksheet`, `pipeline/customer_settings.py`), then `electronic`,
   `physical`, `P-E` (a type with no lines gets no sheet), then option-list sheets (named with a
   `--` prefix, `customer_settings.LIST_PREFIX`; `read_sop` skips them). `--ini` fills the
   drop-downs from the tenant. Zero-dollar lines are removed; Fee and unrecognized-format lines go
   to `<name>_not_sent.csv`. 30 `drop_columns.names` (`pipeline_config.json`) are removed from the
   headers; required columns and Account Number are never dropped.
2. Customer columns (light yellow `FFFFCC`): all files `FOLIO Access Provider`, `FOLIO Fund`,
   `FOLIO Expense Class`, `FOLIO Order Type` (Ongoing / One-Time), `FOLIO Renewal Interval
   (Days)`; physical and P-E also `FOLIO Location`, `FOLIO Material Type` (drop-downs when
   `customer_choices` in `ebsconet_config.json` lists values). Placement: `customer_columns` in
   `pipeline/pipeline_config.json`. The SOP's own `Order Type` column is ignored (dropped).
   Order type and interval are pre-filled from the SOP `Term` (`ebsconet_prep.term_days()`:
   "1 Year(s)"/"12 Month(s)" = 365, "15 Month(s)" = 456; no Term -> One-Time, else Ongoing with
   Term days; customer entries kept).
3. `ebsconet.py build A.xlsx B.xlsx C.xlsx` (or the one workbook) takes the returned files and
   applies the Defaults answers (`customer_settings.read_overrides`). Blank or bad values fall
   back to config defaults with warnings (`ongoing.default_order_type`, `ongoing.interval_days`
   365, `folio.location`, `folio.physical_material_type`); writes `out/order_settings.csv` and
   three workbooks to `out/` (so the adapter, `folio_setup` and the MARC converter are unchanged).
   A blank "Default EBSCOnet organization" on the Defaults sheet stops `build` and
   `--from-worksheet` with an error; old separate files with no Defaults sheet use the config value.
4. `load` (dry run, then `--live`), then `finish`.
- **Vendor vs access provider:** the PO vendor is always the EBSCOnet org
  (`folio.vendor_org_code`; Defaults row "Default EBSCOnet organization", REQUIRED). The customer
  column goes to the loader's `access_provider_code` on electronic and P-E lines only; blank stays
  blank. Old customer files with a `FOLIO Org` header are not read.
- **Other adapter mappings (`row_to_line`):** URL -> `resource_url` (electronic and P-E only);
  `Package?` Yes -> `is_package`; Currency -> per-row 3-letter code, else `folio.currency`;
  Quantity > 1 -> that many copies at cost / quantity only when it reproduces the total to the
  cent, else 1 copy at full cost; Purchase Order Number -> line reference number of type
  `folio.po_number_reference_type` ("Vendor order reference number"); `Open Access` = Yes -> line
  tag `Open Access` (`folio.open_access_tag`); `Your Access` -> `details.receivingNote`. Fund Code
  is deliberately NOT active (vendor code, not a FOLIO fund); a fallback to it when `FOLIO Fund`
  is blank is written but commented out. Full column audit: `work/composite_orders_column_audit.md`
  (git-ignored).
- MARC route only: location / material type go to `990$l` / `990$m`; tenants need
  `ebsconet.py setup --update-mappings --live` once (done on bugfest). Data Import cannot set
  ongoing details, which is why `finish` exists on that route.
- **Not tried on a tenant or the EC2:** everything added 2026-10-02 (Defaults sheet, required org,
  Term logic, new mappings, load log, `drop_columns`); a real Excel open of the workbook with tenant
  lists (`--ini`); `build` end to end on the new file (`work/` lacks `order_marc_headers.xlsx`, a
  pre-existing gap).

## Bugfest (`sunflower_bugfest.ini`, never copy or commit)
- Bugfest holds none of this project's POs (all test POs and backup folders deleted). Profiles,
  `test_ebsconet_*` finance / org / location records and the `--update-mappings` change remain.
  Two vendor accounts remain on org EBSCO (RZ41049-91, XW14722-82); remove if unwanted.
- Verified live: adapter loads of 140/140 POs (0 errors), 7 POs checked in the FOLIO UI, a 25-PO
  run (20 electronic, 3 print, 2 P/E) with 0 mismatches against the workbooks, and a 140/140
  budget-checked dry run (TEST-ELEC/GEN x135, TEST-PRINT/GEN x5).
- `out/three_type_test/*.xlsx` are derived from real but anonymized orders. Git-ignored (`out/`,
  `work/`, `*.xlsx`); never commit. KEEP them for now (user decision 2026-10-02), do not delete.
  They are also the input for quick batches: trim copies into `/tmp/<dir>` and run
  `.venv/bin/python -m pipeline.folio_orders_adapter --in-dir /tmp/<dir> --ini <ini> [--live]`
  (the print workbook is `library-EBSCONET-print.xlsx`, with a hyphen).
- `folio_cleanup_test_pos.py` with its default input (`out/marc/*.mrc`) overlaps the PO numbers in
  `out/three_type_test/`; check scope before running it. Bugfest has 1000+ POs from other vendors:
  never touch those.
- Test file `work/TestEBSCOnet.xlsx` is anonymized (53 columns, `FOLIO Org/Fund/Expense Class`
  removed). Rows 4737-4746 are 10 appended individual-book Print rows with no dates or frequency
  (good for the no-dates path).

## Bugfest end-to-end run "testLibrary" (2026-10-02) and how to repeat it
Done on bugfest from a copy of `work/TestEBSCOnet.xlsx` named `work/testLibrary_ebsconet.xlsx`:
`for-customer --ini sunflower_bugfest.ini` -> filled in as the customer
(`out/customer/testLibrary_ebsconet_filled.xlsx`: Defaults answered, fund TEST-ELEC / TEST-PRINT,
expense class cycling GEN / PHY / SOC, access provider EBSCO on electronic only, location
`test_ebsconet_location (TEST-EBSCONET-LOC)`, material type journal) -> `build` ->
`ebsconet-configure --from-worksheet` -> `load` dry run (150) -> `load --live` (150 created,
0 errors, account RU22774-06 added) -> `finish` (150 POL rows). All 150 POs were then deleted
with `folio_delete_orders.py` (list `out/delete_testlibrary.csv`, backups in
`out/deleted_backup_testlibrary/`, log `out/delete_live.csv`). Vendor account RU22774-06 remains.
Fixed on the way (uncommitted until committed): `build` no longer writes MARC unless
`--use-marc` (and no longer needs `order_marc_headers.xlsx`); the adapter defaults
`folio.po_number_reference_type`; Fund / Expense Class / Access Provider columns now have
drop-downs ("CODE - Name" from `--ini`) and `build` keeps only the code (`code_value()`).

**To start the run again** (from `work/`, via `bin/ebsconet-dev` or `../.venv/bin/python ../ebsconet.py`):
1. `for-customer testLibrary_ebsconet.xlsx --ini sunflower_bugfest.ini` (regenerates the
   workbook with the new drop-downs; the filled copy from the earlier run is kept and still
   valid, since a bare code or "CODE - Name" both work). Re-fill, or reuse
   `out/customer/testLibrary_ebsconet_filled.xlsx` as is.
2. `build out/customer/testLibrary_ebsconet_filled.xlsx` (no MARC).
3. `echo y | ../.venv/bin/python ../bin/ebsconet_configure.py --from-worksheet <filled>`
   (needs the `y`; it asks to confirm and fails without a terminal). Already applied to
   `work/ebsconet_config.json` (backup `.bak-*` beside it).
4. `load --ini sunflower_bugfest.ini` (dry run), then `--live`, then `finish --ini ... --live`.
5. Spot-check POs in the FOLIO UI (still NOT done: no UI check of the testLibrary POs).
6. Delete: build the CSV from `out/pol_export.csv` (type `PO`), dry run, then `--live`
   (the dry run takes about 2 minutes for 150; run it in the background).
Open points from this run: prep report counts print rows in "Access Provider blank on N of 150"
though the column does not apply to them; `--from-worksheet` needs a terminal for its prompt.

**Repeat run (2026-10-02, later), simulating the customer's return:** started from
`out/customer/testLibrary_ebsconet_filled.xlsx` (did NOT re-run `for-customer`). `build` (150 rows:
138 online, 10 print, 2 P-E; 140 ongoing / 10 one-time; 0 warnings) -> `--from-worksheet`
(backup `ebsconet_config.json.bak-20261002_131354`) -> `load` dry run (dry-run 150) -> `load --live`
(created 150, exit 0, 3 accounts already present, none added) -> `finish --live` (150 POL rows).
Then all 150 POs were deleted: list `out/delete_testlibrary_rerun.csv`, dry run 150 `dry-run`,
live 150 `deleted`, 0 failures, backups `out/deleted_backup_testlibrary_rerun/`, log
`out/delete_live_rerun.csv`. No UI spot-check was done. Bugfest again holds none of this
project's POs; the vendor accounts remain.

## NEXT STEPS, in order
1. You: EC2 / real-tenant test. Re-run `install.sh` first, then `ebsconet-configure` (or
   `--worksheet`), `for-customer` (the Moffitt files were built from the stock TEST config, so
   their drop-downs are wrong; rebuild them), send files, then `build` / `load` dry run, then a
   small batch (5-7 POs, one per format) from `/tmp`, check in the UI, delete with
   `folio_delete_orders.py` (dry run, then `--live`). Bugfest is lenient (allows overspend), so
   budget enforcement, acquisition-unit restrictions and `open-error` have only unit tests. Tenant
   codes (vendor, fund, expense class, location, acquisition method) will differ: edit a copy of
   `ebsconet_config.json`, keep the `.ini` outside the repos.
2. Fix whatever that run finds.
3. Review `docs/CLIENT_GUIDE.md` before it goes to a library (real-tenant config values, repeated
   order numbers, the tenant's permissions per `PLAN.md`, ongoing defaults per library).
4. README rework (below).

## TASK (after all other work is done): rework all of the READMEs
Rewrite `README.md` (index), `README_API.md`, `README_DATA_IMPORT.md`, `RUNBOOK.md`, `PLAN.md`
and `docs/CLIENT_GUIDE.md` together once the code settles. Known gaps to fold in: the one customer
workbook with its Defaults sheet, `ebsconet-configure` (+ `--worksheet`, `--from-worksheet`), the
EC2 installer layout (`~/ebsconet/{app,venv,work}`) and `work/` folder, `FOLIO Access Provider`
and the required EBSCOnet org, the Term-based order type and interval, the `drop_columns` list, and
the new mappings (URL, `Package?`, Currency, Quantity, Purchase Order Number, Open Access, Your
Access, Fund Code commented out). Also remove the repo-root-vs-`work/` command mismatch and the
unrewritten MARC-only rows in RUNBOOK section D.

## Dependencies and working notes
- `requirements.txt` pins `folio_orders_loader` by git tag (`@v0.3.4`). After a pin bump,
  reinstall: `.venv/bin/pip install --force-reinstall --no-deps <requirements line>` (a plain
  install does not upgrade).
- PO numbers must match `^[a-zA-Z0-9]{1,22}$` (no hyphens).
- Keep sessions short and single-purpose (a long session cost ~1.3M tokens).
- Commands time out at about 2 minutes; run long loads in the background.
- This file replaces `HANDOFF_ebsconet_three_spreadsheets.md` that lived in the (non-git)
  `ClaudeSessions` folder.
