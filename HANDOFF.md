# Handoff: EBSCOnet orders pipeline (updated 2026-10-02, first EC2 run, ebsconet-configure added)

Read this for the EBSCOnet / `folio_ebsconet_orders` work (three customer spreadsheets, the
`ebsconet.py` workflow, the adapter). For the API loader package itself
(`folio_orders_loader`) read `~/scratch/folio_orders/HANDOFF.md` instead. The two projects
are related but tracked separately; this file does not repeat loader internals.

Code: `~/scratch/EBSCOnet` (Windows: `\\wsl.localhost\Ubuntu-24.04\home\marnold\scratch\EBSCOnet`),
GitHub `marnold-ebsco/folio_ebsconet_orders`, SSH remote only. Run everything with
`.venv/bin/python` from that folder (system `python3` lacks `httpx`), via
`wsl.exe -e bash -lc '...'`. Write patch scripts / commit messages to a file with the Write
tool; inline quoting and heredocs with backticks break.

- Merged to `main` 2026-10-01 (fast-forward, `8d58b75`; the `api-load-default` branch is deleted).
  Loader pinned to v0.3.4. The **Orders API is the default load**; the MARC / Data Import
  route is the backup (`--use-marc`). 200 tests pass, flake8 clean.
- **SOP heading validation (`fe2c5cc`, on `main`, pushed):** `ebsconet_prep.check_headers()` runs at
  the start of `prepare()` and `prepare_for_customer()` and raises `ValueError` if a required SOP
  heading is missing (`REQUIRED_COLUMNS`: title, issn, format, order_number, cost), listing the
  missing and found headings. Other `columns` (package, url, descriptor, ...) may be absent and
  read as blank. `folio_setup.accounts_from_workbooks()` now uses `columns.account` instead of a
  hardcoded `"Account Number"`. To follow a renamed SOP heading, put a `columns` override in
  the library's `work/ebsconet_config.json` (deep-merged over `pipeline/pipeline_config.json`;
  survives `install.sh` upgrades, which replace `app/` but never overwrite `work/`). A separate
  map file was considered and rejected as not worth it for one fixed SOP layout.
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
- **Installer (root `install.sh`, rewritten 2026-10-01 in the style of marc-repair's; the old
  bundle build `packaging/` was deleted; on `main` since `76eb911`, not yet tried on a real EC2):**
  fetches the app tarball pinned to a commit SHA from the GitHub API (no tests, `packaging`,
  dev docs) plus the `folio_orders_loader` tag read from the `requirements.txt` pin, over HTTPS
  (no git or SSH key). Repos are public, so no token is needed (60 API calls/hour/IP
  unauthenticated); if made private again the server needs `GITHUB_TOKEN` (read access to both). Options `--dir` (alias `--prefix`), `--python`, `--ref`,
  `--recreate-venv`, `--check`; SHA kept in `.ebsconet_install_version`. Layout
  `~/ebsconet/{app,venv,work}`, `ebsconet` linked into `~/.local/bin`; re-running upgrades code
  and deps and leaves `work/` alone. Loader is always force-reinstalled (pip builds its
  tarball, so the server needs PyPI). To ship a new loader: bump the loader tag, bump the pin
  in `requirements.txt`, push, re-run `install.sh`. Fails early with a friendly message
  (`0648176`) if the interpreter is below 3.12 or cannot `import venv, ensurepip` (Debian/Ubuntu:
  `sudo apt install python3-venv`). Tested into a temp dir with a `gh auth token` as
  `GITHUB_TOKEN`: fresh install, `--check`, in-place re-run (`work/` kept), the loader imports,
  the venv-check error via a stub interpreter, and the update path (installed `--ref 76eb911`,
  then `--check` reported the update without changing anything, then a plain run upgraded to
  `main` and kept `work/`), and the README `curl ... | bash -s --` one-liner (fresh install; it
  printed curl-form re-run hints with a literal `$GITHUB_TOKEN`). First real EC2 run 2026-10-02: `for-customer` worked after fixes: `c4d4e97` adds `~/.local/bin` to PATH in `~/.bashrc`/`~/.profile`; the wrapper must hold absolute paths (`--dir .` is realpath-resolved, an older installer wrote `./venv`); `ebsconet` must be run from `work/` (reads config and SOP relative to cwd). `load`/`finish` on the EC2 not yet tried. `bin/ebsconet_configure.py` (installed as `ebsconet-configure`, wrapper written by install.sh) is an interactive, read-only wizard that builds `work/ebsconet_config.json` from the tenant's real codes (`tests/test_configure.py`; not yet tried against a live tenant). `ebsconet-configure --worksheet [FILE]` instead writes `ebsconet_config_worksheet.xlsx` (setting, description, yellow answer cell with drop-down of the tenant's real options, plus one sheet per option list) for the customer to fill in; answers are typed back into the wizard by hand (no import mode yet). Latest commit `e03e89b`. On the EC2 the user must re-run `install.sh --dir /working/migration/scripts/ebsconet` to get `ebsconet-configure`. Suggested next: re-run installer, `ebsconet-configure` (or `--worksheet`), then re-run `for-customer` (the Moffitt files were built from the stock TEST config, so their drop-downs are wrong), send files, then `build`/`load` dry run on the EC2.
- **Budget checks:** the adapter calls the loader's `load(..., check_budget=True)` (loader v0.3.2),
  so every PO (dry run and `--live`) is checked for an Active budget per fund and for a listed
  expense class; failures are `invalid` and nothing is POSTed. Replaces the old adapter-side
  `check_dry_run_budgets` (removed 2026-10-01). Blank expense classes skip the class half.
  Re-verified on bugfest 2026-10-01 after the switch (`out/three_type_test`,
  `sunflower_bugfest.ini`, `--skip-accounts`, `use_expense_classes: true`): 140/140 `dry-run`
  (TEST-ELEC/GEN x135, TEST-PRINT/GEN x5, all with Active budgets listing GEN). That data has no
  failing case; calling `check_budgets` directly on ZSS2025 + `access` returns "fund ZSS2025 has
  no Active budget for the current fiscal year" (the class itself is never reached).
  Not yet tried on a tenant with real budget limits.

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
1. **Done:** `api-load-default` merged to `main` 2026-10-01.
2. **Real-tenant test (user will run it).** Bugfest allows overspend and is lenient, so
   budget enforcement, acquisition-unit restrictions and `open-error` have only unit tests.
   Suggested order: adapter dry run, then a small batch (5-7 POs, one per format) from `/tmp`,
   check in the UI, delete with `folio_delete_orders.py` (dry run, then `--live`). Tenant codes
   (vendor, fund, expense class, location, acquisition method) will differ: edit a copy of
   `ebsconet_config.json`, keep the `.ini` outside the repos. Then delete `out/three_type_test/*.xlsx`.
2b. **DONE 2026-10-01 incl. step 5 (bugfest dry run: 140 dry-run with classes on and off): expense classes optional; loader live-verified too (blank-class PO loaded and opened on bugfest, loader v0.3.2 adds opt-in check_budget).** FOLIO does not require them but
   the old loader did (blank class => `invalid`), and the adapter ignored
   `rules.use_expense_classes: false` (it fell back to `default_expense_class`). The loader
   fix (v0.3.1) was done in the separate loader-CLI session; see
   `~/scratch/folio_orders/HANDOFF.md`. Do here, in order:
   1. Confirm the `v0.3.1` tag exists on `marnold-ebsco/folio_orders_loader`
      (`git ls-remote --tags git@github.com:marnold-ebsco/folio_orders_loader.git`). If not,
      stop: the loader session is not finished.
   2. Bump `requirements.txt` to `@v0.3.1`, then
      `.venv/bin/pip install --force-reinstall --no-deps <the requirements line>`
      (a plain install does not upgrade).
   3. In `pipeline/folio_orders_adapter.py` (`row_to_line`, line ~43) leave
      `expense_class_code` blank when `cfg["rules"].get("use_expense_classes", True)` is
      false, instead of using the cell or `default_expense_class`. the loader's `check_budgets`
      (via `check_budget=True`) skipping the class check for blank classes.
   4. Tests: a `use_expense_classes: false` row gives no `expense_class_code`; classes still
      pass through when true. Run the suite and flake8 (`--max-line-length=100`).
   5. Read-only bugfest dry run of `out/three_type_test` with the setting both true (expect
      140 `dry-run`) and false (expect 140 `dry-run`, no class on the lines).
   6. Update `README_API.md` if wording needs it (it already says no class is put on lines),
      this file, and commit. Do this BEFORE the real-tenant test if that tenant does not use
      expense classes.
3. Docs: `RUNBOOK.md` "Lessons" rewritten 2026-10-01 (API and MARC sections); some MARC-only
   tool rows in section D are labelled but not rewritten.
4. Review `docs/CLIENT_GUIDE.md` before it goes to a library; real-tenant config values,
   repeated order numbers and the real tenant's permissions (`PLAN.md`); whether ongoing
   defaults need adjusting per library.
5. The adapter has no source column for `vendor_account` beyond `Account Number` and none for
   reference numbers.

## Dependencies
- `requirements.txt` pins `folio_orders_loader` by git tag (`@v0.3.4`). After a pin bump,
  reinstall: `.venv/bin/pip install --force-reinstall --no-deps <requirements line>` (a plain
  install does not upgrade).
- PO numbers must match `^[a-zA-Z0-9]{1,22}$` (no hyphens).

## Working notes
- Keep sessions short and single-purpose (a long session cost ~1.3M tokens).
- Commands time out at about 2 minutes; run long loads in the background.
- This file replaces `HANDOFF_ebsconet_three_spreadsheets.md` that lived in the (non-git)
  `ClaudeSessions` folder.
