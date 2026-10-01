# Handoff: EBSCOnet orders pipeline (updated 2026-10-01)

Read this for the EBSCOnet / `folio_ebsconet_orders` work (three customer spreadsheets, the
`ebsconet.py` workflow, the adapter). For the API loader package itself
(`folio_orders_loader`) read `~/scratch/folio_orders/HANDOFF.md` instead. The two projects
are related but tracked separately; this file does not repeat loader internals.

Code: `~/scratch/EBSCOnet` (Windows: `\\wsl.localhost\Ubuntu-24.04\home\marnold\scratch\EBSCOnet`),
GitHub `marnold-ebsco/folio_ebsconet_orders`, SSH remote only. Run everything with
`.venv/bin/python` from that folder (system `python3` lacks `httpx`), via
`wsl.exe -e bash -lc '...'`. Write patch scripts / commit messages to a file with the Write
tool; inline quoting and heredocs with backticks break.

## Current state
- Branch `api-load-default`, pushed, NOT merged to `main`, no PR yet. `main` is at `84a99ac`
  (loader pinned to v0.3.0). The branch makes the **Orders API the default load**; the
  MARC / Data Import route is the backup (`--use-marc`). 195 tests pass, flake8 clean.
- `ebsconet.py load` / `finish` use `pipeline/folio_orders_adapter.py` `load_orders()`.
  `--use-marc` on both selects the MARC route. `--skip-accounts` skips the vendor-account
  step. `load` processes every PO, then exits 1 if any is invalid / lookup-failed / error /
  open-error; re-runs skip existing POs. `finish` on the API route only writes
  `out/pol_export.csv` (no ongoing conversion; the API sets the ongoing block).
- The adapter maps SOP `Account Number` -> `vendor_account` and `ensure_accounts()` adds each
  missing account to the organization on the line (payment method
  `folio.account_payment_method`). Reference numbers are deliberately not mapped (no SOP
  column). Each `load` writes `<out>/logs/accounts_<YYYYMMDD_HHMMSS>.txt` (mode, ini name,
  timing of the account step only, accounts added / present, orgs not found). A whole-run
  summary log was offered, not built.
- Docs: `README.md` is an index; `README_API.md` and `README_DATA_IMPORT.md` are standalone
  guides (Setup near the top); `RUNBOOK.md`, `PLAN.md`, `docs/CLIENT_GUIDE.md`.
- **Dry-run limits:** the adapter dry run looks up fund, expense class, org, location and
  material type (`lookup-failed`) but does NOT check that a fund has an Active budget listing
  the expense class. That check exists only in the loader CLI `validate`
  (`budgets.check_budgets`). FOLIO rejects it at `--live` time with `budgetExpenseClassNotFound`
  (a clean 400, nothing created for that PO). `README_API.md` says so. Possible follow-up:
  call `check_budgets` from the adapter dry run.

## What the workflow does
1. `ebsconet.py for-customer SOP.xlsx` writes up to three spreadsheets in `out/customer/`
   (`..._electronic`, `..._physical`, `..._P-E`; a type with no lines gets no file).
   Zero-dollar lines are removed; Fee and unrecognized-format lines go to `<name>_not_sent.csv`.
2. Customer columns (light yellow `FFFFCC`): all files `FOLIO Org`, `FOLIO Fund`,
   `FOLIO Expense Class`, `FOLIO Order Type` (Ongoing / One-Time), `FOLIO Renewal Interval
   (Days)`; physical and P-E also `FOLIO Location`, `FOLIO Material Type` (drop-downs when
   `customer_choices` in `ebsconet_config.json` lists values). Column placement:
   `customer_columns` in `pipeline/pipeline_config.json`. The SOP's own `Order Type` column
   is a different, ignored column.
3. `ebsconet.py build A.xlsx B.xlsx C.xlsx` takes the returned files. Blank or bad values fall
   back to config defaults with warnings (`ongoing.default_order_type`, `ongoing.interval_days`
   365, `folio.location`, `folio.physical_material_type`) and it writes
   `out/order_settings.csv`.
4. `load` (dry run, then `--live`), then `finish`.
- MARC route only: location / material type go to `990$l` / `990$m`; tenants need
  `ebsconet.py setup --update-mappings --live` once (done on bugfest). Data Import cannot set
  ongoing details, which is why `finish` exists on that route.

## Bugfest (`sunflower_bugfest.ini`, never copy or commit)
- Bugfest holds none of this project's POs. All test POs were deleted and the backup folders
  under `~/scratch/ebsconet_bugfest_backup_*` have been deleted. Profiles, `test_ebsconet_*`
  finance / org / location records and the `--update-mappings` change remain. Two vendor
  accounts remain on org EBSCO (RZ41049-91, XW14722-82); remove if unwanted.
- Verified live: adapter loads of 140/140 POs (0 errors), 7 POs checked in the FOLIO UI,
  and a 25-PO run (20 electronic, 3 print, 2 P/E) with 0 mismatches against the workbooks.
- `out/three_type_test/*.xlsx` are DERIVED, real-looking orders: sensitive, never commit, and
  delete after the real-tenant test. They are also the input for quick batches: trim copies
  into `/tmp/<dir>` and run
  `.venv/bin/python -m pipeline.folio_orders_adapter --in-dir /tmp/<dir> --ini <ini> [--live]`
  (the print workbook is `library-EBSCONET-print.xlsx`, with a hyphen).
- `folio_cleanup_test_pos.py` with its default input (`out/marc/*.mrc`) overlaps the PO
  numbers in `out/three_type_test/`; check scope before running it. Bugfest has 1000+ POs from
  other vendors: never touch those.

## Open
1. **Merge `api-load-default`**: open a PR or merge to `main` (user wants the real-tenant
   test, item below, handled by the user later; it does not block the merge unless that
   changes).
2. **Real-tenant test (user will run it).** Bugfest allows overspend and is lenient, so
   budget enforcement, acquisition-unit restrictions and `open-error` have only unit tests.
   Suggested order: adapter dry run, then a small batch (5-7 POs, one per format) from `/tmp`,
   check in the UI, delete with `folio_delete_orders.py` (dry run, then `--live`). Tenant codes
   (vendor, fund, expense class, location, acquisition method) will differ: edit a copy of
   `ebsconet_config.json`, keep the `.ini` outside the repos. Remember the dry run does not
   check budgets (see above). Then delete `out/three_type_test/*.xlsx`.
3. Docs: `RUNBOOK.md` "Lessons" and some MARC-only tool rows are labelled but not rewritten.
4. Review `docs/CLIENT_GUIDE.md` before it goes to a library; real-tenant config values,
   repeated order numbers and the real tenant's permissions (`PLAN.md`); whether ongoing
   defaults need adjusting per library.
5. The adapter has no source column for `vendor_account` beyond `Account Number` and none for
   reference numbers.

## Dependencies
- `requirements.txt` pins `folio_orders_loader` by git tag (`@v0.3.0`). After a pin bump,
  reinstall: `.venv/bin/pip install --force-reinstall --no-deps <requirements line>` (a plain
  install does not upgrade).
- PO numbers must match `^[a-zA-Z0-9]{1,22}$` (no hyphens).

## Working notes
- Keep sessions short and single-purpose (a long session cost ~1.3M tokens).
- Commands time out at about 2 minutes; run long loads in the background.
- This file replaces `HANDOFF_ebsconet_three_spreadsheets.md` that lived in the (non-git)
  `ClaudeSessions` folder.
