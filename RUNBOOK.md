# Runbook: EBSCONET SOP -> FOLIO orders

The workflow from receiving the spreadsheet to handing EBSCONET the PO / POL numbers.
`README.md` explains each script in detail; `PLAN.md` records the design and open
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
                             6. ebsconet.py load --ini ...      (dry run = preflight)
                                errors? send the list back  ->  fixes the cells, returns
                                                                the file; repeat 5-6
                             7. ebsconet.py load --ini ... --live
                             8. ebsconet.py finish --ini ... --live
                             9. send out/pol_export.csv to EBSCONET
```

One-time per tenant (before the first load): section A below, then
`ebsconet.py setup --ini TENANT.ini --live`.

### The five commands
| Command | When | What it does | Writes to FOLIO? |
|---|---|---|---|
| `ebsconet.py for-customer SOP.xlsx` | step 2 | Removes every zero-dollar line; splits the rest into an **electronic**, a **physical** and a **P-E** spreadsheet, each with its own highlighted customer columns; logs what was removed or not sent | no |
| `ebsconet.py build FILLED*.xlsx` | step 5 | Takes the customer's filled-in files (all three, or one), applies the remaining rules, uses the customer's values, builds the MARC files and `order_settings.csv` | no |
| `ebsconet.py setup --ini TENANT.ini` | once per tenant | Adds the SOP's account numbers to the vendor organization; creates the Online / Print / P-E Data Import profiles | only with `--live` |
| `ebsconet.py load --ini TENANT.ini` | steps 6-7 | Creates the POs through the Orders API (default; adds SOP account numbers to the vendors). With `--use-marc`, for each MARC file: preflight checks, then upload, import, verify, clean up empty product IDs, audit log | only with `--live` |
| `ebsconet.py finish --ini TENANT.ini` | step 8 | Writes the PO / POL export for EBSCONET; with `--use-marc` it first converts the loaded POs to ongoing orders | ongoing conversion only with `--live` |

The steps behind these (in `pipeline/`) are not run by hand. The tools in section D are
the ones you run separately, when something needs fixing.

---

## A. One-time setup (per tenant)
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
- [ ] Your user can create Data Import profiles, run imports, and create / edit orders.
- [ ] Edit `ebsconet_config.json` (only this one: the fixed settings in
      `pipeline/pipeline_config.json` are the same for every library). The fund / expense-class / organization entries there
      are only the **defaults** used when the customer leaves a cell blank. Also set the
      `folio` section (location, material type, vendor org, acquisition method, payment
      method for new accounts), and `rules.use_expense_classes` (false if the tenant does
      not use them). See the README ("Data rules").
- [ ] `ebsconet.py setup --ini TENANT.ini`, read the plan, then add `--live`. Afterwards
      check in FOLIO (Settings -> Data import) that the three job profiles exist and that
      each mapping profile sets the PO status to **Pending**.

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

### 6. Dry-run the load (preflight)
Steps 6-8 describe the backup MARC route (add `--use-marc` to `load` and `finish`). The default Orders API `load` works the same way (dry run, then `--live`) but has no preflight, no job profile and no ongoing conversion; `finish` only writes the POL export. See README "Default load".
- [ ] `.venv/bin/python ebsconet.py load --ini TENANT.ini`
- [ ] The preflight check reads the files and the tenant and reports **ERROR**s (the load
      would fail or discard lines) and warnings. Typical errors are a fund, expense class
      or organization code the customer mistyped or that does not exist in FOLIO, an
      expense class not on the fund's budget, a PO number already in FOLIO, and a URL
      FOLIO rejects.
- [ ] Send the error list to the customer (or fix the tenant setup), get a corrected file,
      and repeat steps 5-6 until there are **no errors**. The load refuses to run while
      there are errors.

### 7. Load
Do a small trial first if this is a new tenant (copy a few records into a test .mrc and
load it with `python -m pipeline.folio_import`; see the README).
- [ ] `.venv/bin/python ebsconet.py load --ini TENANT.ini --live`. Long loads can exceed a
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

### 8-9. Ongoing conversion and the EBSCONET hand-off

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

- [ ] `.venv/bin/python ebsconet.py finish --ini TENANT.ini` (dry run: shows the renewal
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
| Some records did not load (discarded, or an empty PO left behind) | `.venv/bin/python folio_retry_failed.py out/marc/<file>.mrc --ini TENANT.ini` lists them and writes `out/retry/<file>_retry.mrc` plus `_delete_empty.csv` |
| Empty POs or wrongly loaded orders to remove | List them in `orders_to_delete.csv` (`PO,<number>` or `POL,<number>`), then `folio_delete_orders.py orders_to_delete.csv --ini TENANT.ini` (dry run) and again with `--live`. Pending orders only; backups in `out/deleted_backup/` |
| Several lines for one PO number (Data Import discards the later records) | After the first line has loaded: `folio_add_po_lines.py out/marc/<file>.mrc --ini TENANT.ini` (dry run), then `--live` |
| Load the retry file | `.venv/bin/python -m pipeline.folio_import out/retry/<file>_retry.mrc --ini TENANT.ini --job-profile "EBSCONET order migration - Online"` (add `--live`) |
| Empty product IDs on orders loaded another way | `.venv/bin/python -m pipeline.folio_clean_product_ids --csv po_numbers.csv --ini TENANT.ini --live` |
| Test tenant: remove the test POs you loaded | `folio_cleanup_test_pos.py --ini TENANT.ini` (dry run) then `--live`. Test tenants only |
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
| `order_settings.csv` | build | Each order: Ongoing or One-Time, and its renewal interval; read by `finish` |
| `library-EBSCONET_online / -print / _P-E.xlsx` | build | The filled-in lines split by format |
| `prep_report.txt`, `prep_exclusions.csv`, `prep_no_issn.csv`, `prep_defaults_used.csv` | build | What was excluded, loaded without an ISSN, or given a default |
| `marc/*.mrc`, `marc/*.mrk` | build | Files for Data Import, and readable text copies |
| `import_logs/*.csv` | load | Audit log of each import |
| `ongoing_log.csv`, `pol_export.csv` | finish | Conversion results; the PO / POL list for EBSCONET |

## Lessons from the bugfest trials
- A fund without an Active budget containing the expense class: the PO is created but its
  line is discarded ("Budget expense class not found"). Preflight checks this.
- FOLIO rejects `HTTP://WWW...` resource URLs (lowercase scheme and host required); the
  build fixes this. PO numbers must be 1-22 letters and digits.
- One PO with one line per MARC record: a repeated order number is discarded on the
  second record (use `folio_add_po_lines.py`).
- Bugfest splits files (parent + child jobs); the loader handles it.
- A line missing its ISSN or title number gets an empty product-ID row from Data Import;
  the loader removes it, otherwise FOLIO will not let anyone save the line.
