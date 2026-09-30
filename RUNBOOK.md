# Runbook: EBSCONET SOP -> FOLIO orders, start to finish

Follow this in order for a real migration. `README.md` explains each script in detail;
`PLAN.md` records the design and open decisions. Run every command from the repo
folder with the venv (`.venv/bin/python ...`). `TENANT.ini` below means your filled-in
copy of `sample.ini`. Nothing writes to FOLIO unless a step says `--live`.

## 0. One-time setup
- [ ] `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`
- [ ] `.venv/bin/python -m pytest -q` passes.
- [ ] Copy `sample.ini` to `TENANT.ini` and fill it in (never commit it).
- [ ] Confirm a connection: `.venv/bin/python -c "from folio_common import connect; print(connect('TENANT.ini').folio_get('/locations', key='locations', query_params={'limit': 1}))"`

## 1. Prepare the tenant (once per tenant)
- [ ] The EBSCONET **vendor organization** exists (code in `ebsconet_config.json` ->
      `folio.vendor_org_code`).
- [ ] The **access-provider organization(s)** exist and are marked as vendors.
- [ ] The **funds** exist and are Active, each with an **Active budget** for the
      order's fiscal year that lists the **expense classes** you use. (The budget amount
      does not matter for loading; a zero-based budget is fine.)
- [ ] The **location** and **material type** used for print / P-E lines exist.
- [ ] Note the ledger's "Restrict encumbrance" and the budgets' allowable-encumbrance
      %: they decide whether the orders can be *opened* later.
- [ ] Your user can create Data Import profiles, run imports, and create/edit orders.
- [ ] Edit `ebsconet_config.json`: fund per route (`fund_by_route`), expense classes
      (`expense_class_by_subject`, `default_expense_class`), `default_org` /
      `org_by_publisher`, and the `folio` section (location, material type, vendor org,
      acquisition method, payment method for new accounts).
- [ ] Settle the data rules in the README ("Open data decisions") and set the `rules`
      in the config to match.

## 2. Prepare the files (each SOP)
- [ ] Put the SOP .xlsx in the folder.
- [ ] `.venv/bin/python ebsconet_prep.py SOP.xlsx --out out`
- [ ] Read `out/prep_report.txt`: row counts per route, exclusions by reason, and the
      **"Removed rows with a non-zero cost"** list (money that will not be loaded).
- [ ] Skim `out/prep_exclusions.csv`; confirm nothing important was dropped.
- [ ] Open the three `out/library-EBSCONET_*.xlsx` workbooks; check the yellow mapped
      columns and the added FOLIO Fund / Expense Class / Org columns look right.
- [ ] `.venv/bin/python ebsconet_to_marc.py`  (writes `out/marc/*.mrc` and `.mrk`; open a
      `.mrk` to eyeball a few records). Empty routes produce no file.

## 3. Create the Data Import profiles (once per tenant)
- [ ] `.venv/bin/python folio_setup.py --ini TENANT.ini`   (dry run: adds nothing; review
      the plan and `out/profiles/*.json`)
- [ ] `.venv/bin/python folio_setup.py --ini TENANT.ini --live`   (adds the SOP account
      numbers to the vendor organization and creates the Online / Print / P-E mapping,
      action and job profiles).
- [ ] In the FOLIO UI (Settings -> Data import) confirm the three job profiles and that
      each mapping profile sets the PO status to **Pending**.
- [ ] After any later change to the mapping: `folio_setup.py ... --update-mappings --live`.

## 4. Load, one file at a time
Do a small trial first (a few records copied into a test .mrc), then the full file.
- [ ] Dry run = preflight only:
      `.venv/bin/python folio_import.py out/marc/library-EBSCONET_online.mrc --ini TENANT.ini --job-profile "EBSCONET order migration - Online"`
      Fix every **ERROR** (the load refuses to run with errors). Read the WARNs.
- [ ] Load: same command plus `--live`. Long loads can exceed a terminal's time limit;
      run in the background or a second terminal and read the audit log afterwards.
- [ ] Repeat for `- Print` and `- P-E` files if they exist.
- [ ] Check the summary: "POs with a PO line: N of N", and the audit log written to
      `out/import_logs/<time>_<file>.csv` (one row per job, record and PO).
- [ ] In the FOLIO UI: search a few PO numbers in Orders; confirm status **Pending**, vendor,
      fund and expense class, price, dates, access provider / location, account number.
- [ ] Data Import -> Logs shows the same jobs (parent + child).

## 5. If something failed
- [ ] `.venv/bin/python folio_retry_failed.py out/marc/<file>.mrc --ini TENANT.ini`
      lists records with no PO or with an *empty* PO, and writes
      `out/retry/<file>_retry.mrc` (records to load again) and, if needed,
      `out/retry/<file>_delete_empty.csv`.
- [ ] Delete the empty POs: `.venv/bin/python folio_delete_orders.py out/retry/<file>_delete_empty.csv --ini TENANT.ini`
      (dry run), then again with `--live`. Backups go to `out/deleted_backup/`.
- [ ] Fix the cause (audit log / preflight message; often a config value, a missing budget
      or expense class, or bad source data), regenerate the .mrc if the data changed, and
      load `out/retry/<file>_retry.mrc`.
- [ ] To remove orders that loaded wrongly: list them in `orders_to_delete.csv`
      (`PO,<number>` or `POL,<number>`) and run `folio_delete_orders.py` (dry run, then
      `--live`). Only **Pending** orders can be deleted this way.

## 6. Convert to ongoing orders
- [ ] Get the PO numbers (Orders app CSV export, or use the list you loaded).
- [ ] `.venv/bin/python folio_ongoing.py po_numbers.csv --ini TENANT.ini`  (dry run; check
      the renewal dates in `out/ongoing_log.csv`)
- [ ] Same with `--live`. Orders stay **Pending**; empty product-ID entries are removed.
- [ ] Settings (interval, subscription, renewal-date rule) live in the config's
      `ongoing` section.

## 7. Give EBSCONET the PO / POL numbers
- [ ] `.venv/bin/python folio_export_pols.py --csv po_numbers.csv --ini TENANT.ini`
      (or `--prefix`). Send `out/pol_export.csv`; the POL number is the PO number + `-1`.
- [ ] Any line not ending in `-1` is flagged `NO - line N`; sort those out by hand.

## 8. Wrap up
- [ ] Keep `out/prep_report.txt`, `out/import_logs/` and `out/deleted_backup/` with the
      project records.
- [ ] Do not keep filled-in `.ini` files or SOP spreadsheets in a shared or public place.
- [ ] Decide when the orders will be opened (they are left Pending on purpose).

## Lessons from the bugfest trials
- Missing budget / expense class on a fund -> PO created but its line discarded
  ("Budget expense class not found").
- FOLIO rejects `HTTP://WWW...` resource URLs (lowercase scheme and host required);
  the prep step fixes this.
- One PO per MARC record: a repeated order number fails on the second record.
- Bugfest splits files (parent + child jobs); the import script handles it.
