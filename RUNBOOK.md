# Runbook: EBSCONET SOP -> FOLIO orders

The workflow from receiving the spreadsheet to handing EBSCONET the PO / POL numbers.
`README_API.md` and `README_DATA_IMPORT.md` explain each script in detail; `PLAN.md` records the design and open
decisions. Run everything from the repo folder with the venv (`.venv/bin/python ...`).
`TENANT.ini` means your filled-in copy of `sample.ini`. Nothing is written to FOLIO
unless a command says `--live`.

## The workflow at a glance

```
 EBSCONET                    WE                                CUSTOMER
 --------                    --                                --------
 1. sends the SOP  ------->  2. ebsconet.py for-customer SOP
                                (removes every $0 line, splits by
                                 format, adds the columns to fill in)
                             send  the 3 *_for_customer_*.xlsx ->  3. fills in FOLIO Org,
                                                                   Fund, Expense Class on
                                                                   every line; Order Type
                                                                   + Renewal Interval
                                                                   (all three files);
                                                                   Location + Material
                                                                   Type (physical, P-E)
                             4. receive the filled-in files  <--
                             5. ebsconet.py build FILLED*.xlsx
                             6. ebsconet.py load --ini ...      (dry run)
                                errors? send the list back  ->  fixes the cells, returns
                                                                the file; repeat 5-6
                             7. ebsconet.py load --ini ... --live
                             8. ebsconet.py finish --ini ...
                             9. send out/pol_export.csv to EBSCONET
```

`load` creates the orders through the Orders API. The MARC / Data Import route is the
backup, selected with `--use-marc` on `load` and `finish` (see "Backup route" below).

One-time per tenant (before the first load): section A below. The `setup --live` step
(accounts and Data Import profiles) is needed only for the backup MARC route; the API
`load` adds the vendor accounts itself.

### The five commands
| Command | When | What it does | Writes to FOLIO? |
|---|---|---|---|
| `ebsconet.py for-customer SOP.xlsx` | step 2 | Removes every zero-dollar line; splits the rest into an **electronic**, a **physical** and a **P-E** spreadsheet, each with its own highlighted customer columns; logs what was removed or not sent | no |
| `ebsconet.py build FILLED*.xlsx` | step 5 | Takes the customer's filled-in files (all three, or one), applies the remaining rules, uses the customer's values, builds the MARC files and `order_settings.csv` | no |
| `ebsconet.py setup --ini TENANT.ini` | once per tenant | Adds the SOP's account numbers to the vendor organization; creates the Online / Print / P-E Data Import profiles (the profiles are needed only for `--use-marc`) | only with `--live` |
| `ebsconet.py load --ini TENANT.ini` | steps 6-7 | Creates the POs through the Orders API (default; adds SOP account numbers to the vendors). With `--use-marc`, for each MARC file: preflight checks, then upload, import, verify, clean up empty product IDs, audit log | only with `--live` |
| `ebsconet.py finish --ini TENANT.ini` | step 8 | Writes the PO / POL export for EBSCONET; with `--use-marc` it first converts the loaded POs to ongoing orders | ongoing conversion only with `--live` |

The steps behind these (in `pipeline/`) are not run by hand. The tools in section D are
the ones you run separately, when something needs fixing.

---

## A. One-time setup (per tenant)
- [ ] On a server such as the EC2 (no clone, no git or SSH key; no GitHub token needed): run
      `install.sh` (curl one-liner in `README.md`), then work from `./ebsconet/work`. Skip the next two items. See
      "Installing on a server" in `README.md`.
- [ ] `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`
- [ ] `.venv/bin/python -m pytest -q` passes.
- [ ] Copy `sample.ini` to `TENANT.ini`, fill it in (never commit it), and check the
      connection: `.venv/bin/python ebsconet.py setup --ini TENANT.ini` (a dry run that
      logs in and shows what it would create).
- [ ] The EBSCONET **vendor organization** exists (its code is `folio.vendor_org_code` in
      `ebsconet_config.json`).
- [ ] The organizations the customer will name in **FOLIO Org** exist and are marked as
      vendors.
- [ ] The **funds** the customer will name in **FOLIO Fund** exist and are Active, each
      with an **Active budget** for the order's fiscal year that lists the **expense
      classes** in use. (The budget amount does not matter for loading; a zero-based
      budget is fine.)
- [ ] The **location** and **material type** for print / P-E lines exist.
- [ ] Note the ledger's "Restrict encumbrance" setting and the budgets' allowable-
      encumbrance %: they decide whether the orders can be *opened* later.
- [ ] Your user can create / edit orders and organizations (accounts are added to the
      vendor organizations). For the backup MARC route it must also be able to create Data
      Import profiles and run imports.
- [ ] Edit `ebsconet_config.json` (only this one: the fixed settings in
      `pipeline/pipeline_config.json` are the same for every library). The fund / expense-class / organization entries there
      are only the **defaults** used when the customer leaves a cell blank. Also set the
      `folio` section (location, material type, vendor org, acquisition method, payment
      method for new accounts), and `rules.use_expense_classes` (false if the tenant does
      not use them). See "Data rules" in README_API.md or README_DATA_IMPORT.md.
- [ ] Backup MARC route only: `ebsconet.py setup --ini TENANT.ini`, read the plan, then
      add `--live`. Afterwards check in FOLIO (Settings -> Data import) that the three job
      profiles exist and that each mapping profile sets the PO status to **Pending**.

## B. For each SOP

### 1-2. Receive the SOP and prepare the customer's copy
- [ ] Put the SOP .xlsx in the folder.
- [ ] `.venv/bin/python ebsconet.py for-customer SOP.xlsx`
- [ ] Read `out/customer/<name>_for_customer_report.txt`: lines read, **zero-dollar
      lines removed**, lines not sent, and the line count of each spreadsheet. The removed
      lines are listed in `out/customer/<name>_zero_dollar_removed.csv`; skim them. Fee
      lines and lines with an unrecognized format are not sent to the customer and are
      listed in `out/customer/<name>_not_sent.csv`.
- [ ] Send the customer the files in `out/customer/` (a type with no lines gets no file):
      `<name>_for_customer_electronic.xlsx`, `..._physical.xlsx` and `..._P-E.xlsx`, with
      the note below.

What the customer fills in on each file (highlighted light yellow):

| Spreadsheet | FOLIO Org / Fund / Expense Class | FOLIO Order Type + FOLIO Renewal Interval (Days) | FOLIO Location + FOLIO Material Type |
|---|---|---|---|
| electronic (online only, database, e-book) | yes | yes | |
| physical (print) | yes | yes (interval rarely used) | yes |
| P-E (print + online) | yes | yes | yes |

*FOLIO Order Type* is a **drop-down** that accepts only `Ongoing` or `One-Time`;
*Renewal Interval* accepts only a whole number of days and is used only for Ongoing
orders. *Location* and *Material Type* become drop-downs when `customer_choices` in
`ebsconet_config.json` lists the tenant's values (otherwise free text, exactly as FOLIO
names them: location as `Name (CODE)`, material type by name).
(The SOP's own `Order Type` column is a different column and is not used.)

> **Note to the customer:** please fill in the highlighted columns on **every** line of
> each spreadsheet, and send all of them back. *FOLIO Org* = the code of the
> access-provider organization in FOLIO (optional per the process; blank uses our
> default). *FOLIO Fund* = the code of the fund that pays for the line. *FOLIO Expense
> Class* = the expense class code, if your library uses them. *FOLIO Order Type* =
> choose Ongoing or One-Time from the list; if Ongoing, enter the renewal interval in
> days in *FOLIO Renewal Interval (Days)*. *FOLIO Location* and *FOLIO Material Type* =
> where the print copy goes and what kind of item it is. Use the codes and names exactly
> as they appear in FOLIO. Do not add, delete or reorder other columns.

### 3. The customer fills in the columns
Nothing for us to do. A blank cell falls back to the defaults in the config.

### 4-5. Receive the filled-in files and build
- [ ] `.venv/bin/python ebsconet.py build FILLED_electronic.xlsx FILLED_physical.xlsx FILLED_P-E.xlsx`
      (list whichever files you have; with several, rows are reported as `<file>:<row>`)
- [ ] Read `out/prep_report.txt`: rows loadable per route, exclusions, the "Removed rows
      with a non-zero cost" list (money that will not be loaded), and, for each customer
      column, how many cells were blank (default used). Blank cells are listed in
      `out/prep_defaults_used.csv`; ask the customer to fill them if the defaults are
      not right.
- [ ] `out/prep_no_issn.csv` lists the rows loaded without an ISSN. A row with neither an
      ISSN nor a title number gets a generated identifier `NOISSN-<order number>`.
- [ ] `out/prep_exclusions.csv` lists every row left out and why (Fee or unknown format,
      Usage Loading Service if switched on, ...).
- [ ] Open a `.mrk` file in `out/marc/` and eyeball a few records.

### 6. Dry-run the load
- [ ] `.venv/bin/python ebsconet.py load --ini TENANT.ini`
- [ ] The dry run validates every PO and looks up the codes in the tenant. It prints one
      status per PO (`dry-run`, `exists`, `invalid`, `lookup-failed`) with the reason for
      each problem, and shows which vendor accounts would be added. It writes
      `out/logs/accounts_<timestamp>.txt` (mode, start / end / elapsed time, the account
      numbers).
- [ ] Send the error list to the customer (or fix the tenant setup), get a corrected file,
      and repeat steps 5-6 until there are no `invalid` or `lookup-failed` POs.

### 7. Load
- [ ] `.venv/bin/python ebsconet.py load --ini TENANT.ini --live`. The vendor accounts are
      added first, then the POs are created Pending with the order type and renewal
      interval already set on the line. Several rows with one Order Number become extra
      lines of one PO.
- [ ] The summary counts the POs by status (`created`, `exists`, `error`, ...). A bad PO
      does not stop the others, but the command then exits with 1. Fix the cause and run
      the same command again: POs that already exist are skipped.
- [ ] In FOLIO: search a few PO numbers in Orders. Confirm status **Pending**, order type,
      vendor, fund and expense class, price, dates, location, account number.
- [ ] Something failed? Section D.

### 8-9. The EBSCONET hand-off
- [ ] `.venv/bin/python ebsconet.py finish --ini TENANT.ini` writes `out/pol_export.csv`.
      There is no ongoing conversion on this route (the settings were applied at load),
      so `--live` changes nothing.
- [ ] Send `out/pol_export.csv` to EBSCONET. The POL number is the PO number + `-1`;
      any line not ending in `-1` is flagged `NO - line N` for you to sort out by hand.

### Backup route: MARC / Data Import (`--use-marc`)
Use this when the Orders API load cannot be used. It replaces steps 6-9 above; run
`ebsconet.py setup --ini TENANT.ini --live` once per tenant first, and add `--use-marc` to
`load` and `finish`. Steps M6-M9 below are the MARC versions of steps 6-9.

#### M6. Dry-run the load (preflight)
- [ ] `.venv/bin/python ebsconet.py load --use-marc --ini TENANT.ini`
- [ ] The preflight check reads the files and the tenant and reports **ERROR**s (the load
      would fail or discard lines) and warnings. Typical errors are a fund, expense class
      or organization code the customer mistyped or that does not exist in FOLIO, an
      expense class not on the fund's budget, a PO number already in FOLIO, and a URL
      FOLIO rejects.
- [ ] Send the error list to the customer (or fix the tenant setup), get a corrected file,
      and repeat steps 5-6 until there are **no errors**. The load refuses to run while
      there are errors.

#### M7. Load
Do a small trial first if this is a new tenant (copy a few records into a test .mrc and
load it with `python -m pipeline.folio_import`; see README_DATA_IMPORT.md).
- [ ] `.venv/bin/python ebsconet.py load --use-marc --ini TENANT.ini --live`. Long loads can exceed a
      terminal's time limit; run it in the background or a second terminal and read the
      result afterwards.
- [ ] Per file the summary shows "POs with a PO line: N of N" and "empty product IDs
      removed from N line(s)" (Data Import leaves an empty product-ID row when an ISSN or
      title number is missing; FOLIO will not save a line that has one, so the loader
      removes it). The audit log is `out/import_logs/<time>_<file>.csv`.
- [ ] In FOLIO: search a few PO numbers in Orders. Confirm status **Pending**, vendor,
      fund and expense class, price, dates, access provider / location, account number.
- [ ] Data Import -> Logs shows the same jobs (parent + child).
- [ ] Something failed? Section D.

#### M8-M9. Ongoing conversion and the EBSCONET hand-off

**What this step does, and why.** (The customer now chooses, per order, whether it is Ongoing or One-Time and its renewal interval; `build` records the choices in `out/order_settings.csv` and `finish` follows them: One-Time orders are left alone, Ongoing orders get the customer's interval.) Each order has two separate settings: its **status**
(Pending / Open / Closed) and its **order type** (One-Time / Ongoing). Data Import creates
every order as **One-Time** and **Pending**. The `finish` step changes only the *type*, to
**Ongoing**, and never the status: the orders stay **Pending** (nothing is encumbered, and
nothing is opened by these scripts).

Why convert: these are annual subscriptions, and an Ongoing order carries the renewal
details a One-Time order lacks: a renewal interval, a "subscription" flag and a renewal
date. The instructions (step 25) call for this conversion, and the EBSCONET renewal
integration works from those orders. It is a separate step because the Data Import mapping
profile has no fields for the ongoing details, so they cannot be set during the import.

What it sets (config section `ongoing` in `ebsconet_config.json`): interval 365 days,
subscription on, manual renewal off, and the renewal date taken from the **latest
subscription end date** of the order's lines (`renewal_date_source`; other choices are the
earliest end date, or no date). It also removes any empty product-ID rows. It only converts
orders that are **Pending** and not already Ongoing; anything else is skipped and logged.

It is optional and safe to leave for later: nothing is converted unless you run it with
`--live`. Without `--live` it is a dry run (shows the renewal dates in
`out/ongoing_log.csv`), and the orders simply stay One-Time. The decision to keep this step
as is was made on 2026-09-30; revisit it if the renewal dates should work differently.

- [ ] `.venv/bin/python ebsconet.py finish --use-marc --ini TENANT.ini` (dry run: shows the renewal
      dates in `out/ongoing_log.csv` and writes the PO / POL export).
- [ ] Same with `--live` to convert the POs to ongoing orders. Orders stay **Pending**.
      In FOLIO each converted order shows type Ongoing and status Pending.
- [ ] Send `out/pol_export.csv` to EBSCONET. The POL number is the PO number + `-1`;
      any line not ending in `-1` is flagged `NO - line N` for you to sort out by hand.

### Wrap up
- [ ] Keep `out/` (reports, audit logs, backups) with the project records.
- [ ] Do not keep filled-in `.ini` files or SOP spreadsheets in a shared or public place.
- [ ] Decide when the orders will be opened (they are left Pending on purpose).

---

## D. When something goes wrong (run these by hand)
| Problem | Tool |
|---|---|
| Some POs came back `error`, `invalid` or `lookup-failed` | Fix the cause (the message names it), then run `ebsconet.py load --ini TENANT.ini --live` again; POs that exist are skipped |
| MARC route: some records did not load (discarded, or an empty PO left behind) | `.venv/bin/python folio_retry_failed.py out/marc/<file>.mrc --ini TENANT.ini` lists them and writes `out/retry/<file>_retry.mrc` plus `_delete_empty.csv` |
| Empty POs or wrongly loaded orders to remove | List them in `orders_to_delete.csv` (`PO,<number>` or `POL,<number>`), then `folio_delete_orders.py orders_to_delete.csv --ini TENANT.ini` (dry run) and again with `--live`. Pending orders only; backups in `out/deleted_backup/` |
| MARC route: several lines for one PO number (Data Import discards the later records) | After the first line has loaded: `folio_add_po_lines.py out/marc/<file>.mrc --ini TENANT.ini` (dry run), then `--live` |
| MARC route: load the retry file | `.venv/bin/python -m pipeline.folio_import out/retry/<file>_retry.mrc --ini TENANT.ini --job-profile "EBSCONET order migration - Online"` (add `--live`) |
| MARC route: empty product IDs on orders loaded another way | `.venv/bin/python -m pipeline.folio_clean_product_ids --csv po_numbers.csv --ini TENANT.ini --live` |
| Test tenant: remove the test POs you loaded | List them in a CSV and use `folio_delete_orders.py` as above. MARC route: `folio_cleanup_test_pos.py --ini TENANT.ini` (dry run) then `--live` deletes the POs in your local `.mrc` files. Test tenants only |
| The Orders API load fails or is unavailable | Use the backup MARC / Data Import route: `ebsconet.py load --use-marc --ini TENANT.ini` (dry run = preflight), `--live`, then `ebsconet.py finish --use-marc --ini TENANT.ini --live`. Needs `setup` profiles. Several lines on one PO are not possible on this route |
| One step on its own (any `pipeline/` step) | `.venv/bin/python -m pipeline.<step> --help` |

After fixing the cause, regenerate the `.mrc` if the data changed (`build` again), then
load the retry file. The `build` step rebuilds everything in `out/`, so keep each SOP's
files together (or use a separate `--out` folder per SOP, e.g. `--out out/2026-spring`).

## Files produced (in `out/`)
| File | Made by | What it is |
|---|---|---|
| `customer/<name>_for_customer_electronic / _physical / _P-E.xlsx` | for-customer | Send to the customer (one per type that has lines) |
| `customer/<name>_zero_dollar_removed.csv`, `..._not_sent.csv`, `..._report.txt` | for-customer | What was removed, what was not sent (Fee / unrecognized format) and why |
| `order_settings.csv` | build | Each order: Ongoing or One-Time, and its renewal interval; read by `finish --use-marc` |
| `library-EBSCONET_online / -print / _P-E.xlsx` | build | The filled-in lines split by format |
| `prep_report.txt`, `prep_exclusions.csv`, `prep_no_issn.csv`, `prep_defaults_used.csv` | build | What was excluded, loaded without an ISSN, or given a default |
| `logs/accounts_<timestamp>.txt` | load | Vendor accounts added (or that would be): mode, start / end / elapsed time, account numbers |
| `pol_export.csv` | finish | The PO / POL list for EBSCONET |
| `marc/*.mrc`, `marc/*.mrk` | build | MARC route: files for Data Import, and readable text copies |
| `import_logs/*.csv` | load --use-marc | MARC route: audit log of each import |
| `ongoing_log.csv` | finish --use-marc | MARC route: conversion results |

## Lessons from the bugfest trials

### Orders API route (default)
- Budgets are checked on every PO, in the dry run and with `--live` (loader `check_budget`).
  A fund with no Active budget for the current fiscal year, or one that does not list the
  expense class, makes the PO `invalid` and nothing is POSTed. Blank expense classes skip the
  class check. Bugfest allows overspend and is lenient, so a real tenant may reject more than
  the bugfest dry run did.
- Expense classes are optional. Set `rules.use_expense_classes` to `false` in the config for a
  tenant that does not use them; the lines then carry no class.
- PO numbers must be 1-22 letters and digits (no hyphens).
- SOP `Account Number` becomes the line's vendor account; `load` adds any missing account to the
  organization (skip with `--skip-accounts`) and logs it in `logs/accounts_<timestamp>.txt`.
  Reference numbers are not mapped (the SOP has no column for them).
- `load` processes every PO before exiting 1 if any failed; re-runs skip POs that already exist,
  so fix the cause and run it again.
- After bumping the `folio_orders_loader` pin in `requirements.txt`, reinstall with
  `pip install --force-reinstall --no-deps <requirements line>`; a plain install does not upgrade.

### MARC / Data Import route (`--use-marc`)
- A fund without an Active budget containing the expense class: the PO is created but its
  line is discarded ("Budget expense class not found"). Preflight checks this.
- FOLIO rejects `HTTP://WWW...` resource URLs (lowercase scheme and host required); the
  build fixes this.
- One PO with one line per MARC record: a repeated order number is discarded on the
  second record (use `folio_add_po_lines.py`).
- Bugfest splits files (parent + child jobs); the loader handles it.
- A line missing its ISSN or title number gets an empty product-ID row from Data Import;
  the loader removes it, otherwise FOLIO will not let anyone save the line.
