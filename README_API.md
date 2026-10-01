# EBSCONET SOP -> FOLIO orders: loading through the Orders API

These tools turn an EBSCONET SOP spreadsheet into Pending purchase orders in FOLIO
(Sunflower) by posting them through the FOLIO Orders API, then write the PO / POL numbers
EBSCONET needs. One command drives the whole workflow: `ebsconet.py`.

```
for-customer SOP.xlsx   ->  customer fills in columns  ->  build FILLED*.xlsx
   ->  load (dry run, then --live)  ->  finish  ->  out/pol_export.csv to EBSCONET
```

What you get: one Pending PO per EBSCONET order number. **Several spreadsheet rows with the
same Order Number become extra lines of one PO.** The order type (Ongoing / One-Time) and
the renewal interval are set directly on each PO line, so no conversion step is needed
afterwards. The SOP's account numbers are added to the vendor organizations automatically.
Nothing is opened or encumbered. `RUNBOOK.md` is the step-by-step checklist and
`docs/CLIENT_GUIDE.md` is the plain-language explanation to give a customer.

## Setup

**Prerequisites**
- Python 3.12 or higher, and git access to the `folio_orders_loader` repository
  (it is installed from GitHub over ssh, see below).
- A FOLIO tenant, and a user that can create and edit orders and organizations.
- On the tenant: the organizations the customer will name in **FOLIO Org** (marked as
  vendors); the **funds** named in **FOLIO Fund**, each Active with an Active budget for the
  order's fiscal year that lists the **expense classes** in use (the budget amount does not
  matter; a zero-based budget is fine); and the **location** and **material type** used for
  print / P-E lines.

**Python environment**
On a server where you do not want to clone the repo, use the bundle installer instead of the
commands below: see "Installing on a server" in `README.md`.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
`requirements.txt` pins `openpyxl`, `pymarc`, `folioclient`, `httpx` and
`folio_orders_loader` (a separate package, pinned by git tag, that validates the line
records and creates the orders). Use `requirements-dev.txt` instead if you also want the
test and lint tools. Run everything from the repository folder with the venv:
`.venv/bin/python <script>`.

**Tenant .ini file.** Copy `sample.ini` to a file of your own (for example
`my_tenant.ini`) and fill in the keys:

| Key | Meaning |
|---|---|
| `okapiUrl` | the tenant's API URL |
| `tenant_id` | the tenant id |
| `username`, `password` | a FOLIO user with the permissions above |
| `sslVerify` | `true`, `false`, or the path to a CA certificate bundle |

A filled-in .ini holds live credentials: never commit or share it (`*.ini` is git-ignored
except `sample.ini`). Pass it to every FOLIO command with `--ini my_tenant.ini`.

**Config file `ebsconet_config.json`** holds what a library chooses. Edit it before the
first load. The fund, expense class and organization entries are only the *defaults* used
when the customer leaves a cell blank; the values in the repository are TEST placeholders.

| Section / key | Meaning |
|---|---|
| `fund_by_route` | default fund code for `online` / `print` / `pe` |
| `expense_class_by_subject`, `default_expense_class` | expense class by SOP subject, and the fallback |
| `org_by_publisher`, `default_org` | vendor organization code by publisher, and the fallback |
| `customer_choices` | optional drop-down lists for the customer's `location` and `material_type` columns (empty list = free text) |
| `rules.exclude_zero_cost`, `rules.exclude_zero_cost_package_members` | drop $0 rows / $0 package members (both default `true`) |
| `rules.exclude_usage_loading_service` | `true` leaves out "Usage Loading Service" lines (default `false`: they load) |
| `rules.skip_missing_issn` | `false`: rows without an ISSN are loaded and logged, never skipped |
| `rules.use_expense_classes` | `false` if the tenant does not use expense classes (no class is put on the lines) |
| `ongoing.default_order_type` | `Ongoing` or `One-Time`, used when the customer leaves the cell blank |
| `ongoing.interval_days` | default renewal interval (365) |
| `ongoing.is_subscription`, `ongoing.manual_renewal` | set on every Ongoing line (`true` / `false`) |
| `folio.acquisition_method` | acquisition method name that must exist on the tenant |
| `folio.currency` | currency of the lines (`USD`) |
| `folio.receipt_status` | line receipt status per `online` / `print` / `pe` |
| `folio.location`, `folio.physical_material_type` | defaults for physical and P-E lines when the customer leaves the cells blank |
| `folio.title_number_type` | product-ID type for the Title Number (`Publisher or distributor number`) |
| `folio.account_payment_method` | payment method given to account numbers added to an organization (`Other`) |

The fixed, process-level settings (SOP column names, format routing, output file names, the
customer columns) are in `pipeline/pipeline_config.json`; they are the same for every
library and are merged in automatically.

**One-time per-tenant setup.** There is no profile or job-profile setup. Vendor account
numbers are added to the organizations automatically by `load`. Check the tenant with a
dry run of `load` (below), which logs in and reports any code it cannot find.

## Step 1: prepare the customer's copy (`for-customer`)
```
.venv/bin/python ebsconet.py for-customer SOP.xlsx
```
Removes every zero-dollar line, drops "Fee" and unrecognized-format lines, splits the rest
by format into three spreadsheets in `out/customer/`, and adds the highlighted columns the
customer fills in **line by line**. A format with no lines gets no file. Read
`out/customer/<name>_for_customer_report.txt` (lines read, removed, not sent, per file);
removed lines are in `<name>_zero_dollar_removed.csv`, lines not sent in
`<name>_not_sent.csv`. Send the customer the `_for_customer_electronic.xlsx`,
`_physical.xlsx` and `_P-E.xlsx` files.

**Customer columns** (which columns go on which file is `customer_columns` in
`pipeline/pipeline_config.json`):

| Spreadsheet | Columns |
|---|---|
| electronic (`online`) | `FOLIO Org`, `FOLIO Fund`, `FOLIO Expense Class`, `FOLIO Order Type`, `FOLIO Renewal Interval (Days)` |
| physical (`print`) | the five above plus `FOLIO Location`, `FOLIO Material Type` |
| P-E (`pe`) | the same seven columns as physical |

`FOLIO Order Type` is an Excel drop-down limited to `Ongoing` / `One-Time`;
`FOLIO Renewal Interval (Days)` accepts only whole numbers above 0 and is used only when the
order type is Ongoing. `FOLIO Location` and `FOLIO Material Type` are drop-downs when
`customer_choices` lists values, otherwise free text exactly as FOLIO names them (location as
`Name (CODE)`, material type by name). The SOP's own `Order Type` column is a different,
ignored column. If a column is already in the SOP it is used in place, never duplicated.
Use codes and names exactly as they appear in FOLIO; the customer should not add, delete or
reorder other columns.

## Step 2: build (`build`)
```
.venv/bin/python ebsconet.py build FILLED_electronic.xlsx FILLED_physical.xlsx FILLED_P-E.xlsx
```
List whichever filled-in files you have (one or all three; with several, rows are reported as
`<file>:<row>`). `build` uses the customer's values as they are. A blank cell, or a SOP
without that column, falls back to the config defaults (`fund_by_route`,
`expense_class_by_subject` / `default_expense_class`, `org_by_publisher` / `default_org`,
`ongoing.default_order_type` / `ongoing.interval_days`, `folio.location` /
`folio.physical_material_type`). A wrong order type or a non-numeric interval is replaced by
the default with a warning in the report; a One-Time order has no interval. `build` exits 1
if it finds a problem. It writes the prepared workbooks the load reads
(`out/library-EBSCONET_online.xlsx`, `out/library-EBSCONET-print.xlsx`,
`out/library-EBSCONET_P-E.xlsx`; `--out` selects another folder) and:

- `out/prep_report.txt`: rows loadable per route, exclusions, removed rows with a non-zero
  cost (money that will not be loaded), and how many cells of each customer column were blank.
- `out/prep_defaults_used.csv`: every blank cell that took a default, row by row. Ask the
  customer to fill them in if a default is not right.
- `out/prep_exclusions.csv`: every row left out and why.
- `out/prep_no_issn.csv`: rows loaded without an ISSN (see Data rules).
- `out/order_settings.csv`: each order's type and renewal interval.

Prep also lowercases the scheme and host of the URL column (FOLIO rejects
`HTTP://WWW.X.ORG`) and writes dates as ISO dates. An empty split (for example print, when
every print row is $0) produces no workbook.

## Step 3: load (`load`)
```
.venv/bin/python ebsconet.py load --ini my_tenant.ini            # dry run
.venv/bin/python ebsconet.py load --ini my_tenant.ini --live     # creates the POs
```
`load` reads the prepared workbooks, maps each row to a line record, and hands the records to
the `folio_orders_loader` package, which validates them against the tenant and creates the
orders. **Always run the dry run first**: it validates every PO, looks up the tenant codes
and prints what it would create; nothing is written without `--live`. Fix any reported
`invalid` or `lookup-failed` PO (a mistyped or missing fund, expense class, organization,
location or material type; a fund with no Active budget for the current fiscal year, or whose
budget does not list the expense class as Active) by correcting the spreadsheet or the
tenant, re-run `build`, and repeat until the dry run is clean. The budget check runs on
every PO, in the dry run and with `--live`: a PO that fails it is `invalid` and nothing is
created for it. Long live loads can exceed a terminal's time limit: run them in the background
or a second terminal and read the result afterwards.

What a row becomes: Order Number -> PO number; FOLIO Org -> vendor; Title Name -> title;
ISSN and Title Number (with its type) -> product IDs; Publisher Name; Start / Expiration
Date -> subscription from / to; Total Cost -> price; FOLIO Fund and Expense Class -> fund
distribution; FOLIO Order Type / Renewal Interval -> order type and renewal interval;
Cancellation Restriction (SOP "No" -> restricted); PO Line Description (Descriptor +
Frequency joined with `description_separator`, empty values and "Not Applicable" dropped);
account -> vendor account; order format from the file (electronic = Electronic Resource,
print = Physical Resource, P-E = P/E Mix); receipt status from `folio.receipt_status`;
physical and P-E rows also get FOLIO Location and Material Type. Ongoing lines get the
renewal interval, `ongoing.is_subscription` and `ongoing.manual_renewal`.

**Vendor accounts.** The SOP's **Account Number** becomes the line's vendor account. FOLIO
stores the value whether or not the organization has such an account, so before creating the
orders `load` adds each missing account number to the organization named on its lines (the
line's FOLIO Org), with payment method `folio.account_payment_method` and status Active.
Organizations already holding the account are left alone; rows with no Account Number get no
vendor account. A dry run prints "N to add" and changes nothing in FOLIO. An organization
that cannot be found is reported and skipped (the loader then rejects its lines).
`--skip-accounts` turns the step off.

Every run of this step (dry runs too) writes `out/logs/accounts_<YYYYMMDD_HHMMSS>.txt`. It
records the mode (LIVE or DRY RUN), the tenant `.ini` file name, the start and end times and
the elapsed time, how many organizations were checked, and for each organization the account
numbers added (or "would add"), the ones already present, and any organization that was not
found. The console prints the same account numbers and the log path. FOLIO keeps no history
of these changes, so keep the log if an account has to be removed later.

**Results and exit code.** `load` prints the number of POs per status (for example `created`,
`dry-run`, `exists`, `invalid`, `lookup-failed`, `error`, `open-error`) and lists each bad
one. It **exits 1 if any PO is invalid, lookup-failed, error or open-error, but it still
processes every PO**, so one bad PO never stops the rest. **Re-runs are safe: a PO that
already exists is skipped** (`exists`), so after fixing the bad ones just run `load --live`
again.

The adapter can also be run directly:
`.venv/bin/python -m pipeline.folio_orders_adapter --ini my_tenant.ini [--live] [--in-dir out] [--skip-accounts]`.

After a live load, check a few PO numbers in FOLIO (Orders): status **Pending**, vendor, fund
and expense class, price, dates, account number, and (for print / P-E) location and material
type.

## Step 4: finish (`finish`)
```
.venv/bin/python ebsconet.py finish --ini my_tenant.ini
```
Orders are created Pending with the order type and renewal interval already on the line, so
`finish` has no conversion to do; it only reads the POs back from FOLIO and writes
`out/pol_export.csv`: PO number, POL number, title, subscription end, POL id and a
`matches_po_plus_1` column. EBSCONET is told the POL number is the PO number plus `-1`, so
any line that is not `-1` (such as the second line of a two-line PO) is flagged
`NO - line N` for you to handle by hand. Send `pol_export.csv` to EBSCONET. `finish` takes
`--live` for symmetry but writes nothing to FOLIO.

## Data rules
Which rows load is decided in `pipeline/ebsconet_prep.py` from `rules` in
`ebsconet_config.json`.

**Every row is loaded; a row without an ISSN is logged, not skipped** (`rules.skip_missing_issn`
is `false`). `out/prep_no_issn.csv` records the sheet row, order number, title, cost, route,
identifier used and whether it was generated. The identifiers a line gets:

| Situation | Product IDs on the line |
|---|---|
| ISSN and title number | both (ISSN, then `Publisher or distributor number`) |
| ISSN, no title number | the ISSN only |
| No ISSN, has a title number | the title number only |
| No ISSN and no title number | a **generated** identifier `NOISSN-<EBSCONET order number>` of type `Local identifier` (`generated_id` in `pipeline/pipeline_config.json`; flagged in the prep workbook's "Generated ID?" column and in `prep_no_issn.csv`). Unique and reproducible, and not an ISSN |

The `Local identifier` product-ID type must exist on the tenant.

| Situation | What happens | Where to change it |
|---|---|---|
| "Usage Loading Service - ..." lines (service fees, not titles) | **Loaded** for now; set the rule to `true` to leave them out (they are then logged in `out/prep_exclusions.csv`) | `rules.exclude_usage_loading_service` |
| Zero-cost row | **Not loaded** ("Zero cost") | `rules.exclude_zero_cost` |
| Zero-cost member of a package | **Not loaded** ("Package member at zero cost"); packages are recognized by `package_title_keywords` | `rules.exclude_zero_cost_package_members` |
| "Fee" format or unrecognized format | **Not loaded**, logged | `excluded_formats`, `format_routes` |
| Same order number on several rows | Kept: they become additional lines of one PO | n/a |

**Expense classes are optional.** Set `rules.use_expense_classes` to `false` (or leave the
value blank) and no expense class is put on the fund distribution. The fund still needs an
Active budget.

## Outputs (in `out/`)
| File | Made by | What it is |
|---|---|---|
| `customer/<name>_for_customer_electronic / _physical / _P-E.xlsx` | for-customer | Send to the customer |
| `customer/<name>_zero_dollar_removed.csv`, `_not_sent.csv`, `_report.txt` | for-customer | What was removed or not sent, and why |
| `library-EBSCONET_online / -print / _P-E.xlsx` | build | The filled-in lines split by format; what `load` reads |
| `prep_report.txt`, `prep_exclusions.csv`, `prep_no_issn.csv`, `prep_defaults_used.csv` | build | What was excluded, loaded without an ISSN, or given a default |
| `order_settings.csv` | build | Each order's type and renewal interval |
| `pol_export.csv` | finish | The PO / POL list for EBSCONET |
| `deleted_backup/` | delete tools | JSON copy of each PO / line before it is deleted |

`build` rebuilds everything in `out/`, so keep each SOP's files together or give each SOP its
own folder with the global option, for example `ebsconet.py --out out/2026-spring build ...`
(the global options `--config` and `--out` go before the subcommand).

## Troubleshooting
| Problem | What to do |
|---|---|
| Dry run reports `lookup-failed` or `invalid` for a PO | Read the detail: a code the customer mistyped or that does not exist in FOLIO. Fix the cell (or the tenant), run `build` again, repeat the dry run |
| A fund line fails on the expense class | The fund needs an Active budget for the fiscal year that lists the expense class |
| `organization X not found; accounts not added` | The FOLIO Org code is wrong or the organization does not exist; fix it, or the loader rejects the lines |
| `load` exited 1 | At least one PO was invalid / lookup-failed / error / open-error. Every other PO was still processed. Fix the listed ones and run `load --live` again; existing POs are skipped |
| PO numbers | FOLIO accepts 1-22 letters and digits only |
| A resource URL FOLIO rejects | Lowercase scheme and host are required; prep fixes this. Other malformed URLs must be fixed in the spreadsheet |
| Wrongly loaded orders to remove | See "Removing problem orders" |
| One tool on its own | `.venv/bin/python -m pipeline.<step> --help` |

## Removing problem orders (`folio_delete_orders.py`)
List the POs / PO lines to remove in `orders_to_delete.csv`, then:
```
.venv/bin/python folio_delete_orders.py orders_to_delete.csv --ini my_tenant.ini          # dry run
.venv/bin/python folio_delete_orders.py orders_to_delete.csv --ini my_tenant.ini --live   # deletes
```
CSV columns: `type,number,note` (header required; lines starting with `#` are ignored).
- `PO,U1234567,reason` deletes the whole order and all its lines.
- `POL,U1234567-2,reason` deletes only that line (PO line number = PO number + `-n`).

Safety features:
- Dry run unless `--live`; the dry run says how many lines a PO has, or warns when a line is
  the PO's last (the PO would be left empty).
- Only **Pending** orders are deleted; an Open order is skipped with the reason and must be
  handled in FOLIO first.
- Each PO / line is saved as JSON in `out/deleted_backup/` (`PO_<number>.json`,
  `POL_<number>.json`) before it is deleted. This is for reference; there is no restore script.
- `--max N` (default 50) refuses longer lists. A missing or duplicate number is logged and the
  run continues; the exit code is non-zero if any entry errored.
- Results are written to `out/delete_log.csv` (statuses `deleted`, `dry-run`, `skipped`,
  `not-found`, `error`).

After deleting, run `load --live` again to recreate the POs you removed (existing POs are
skipped).

## Test tenants only
`folio_test_data.py --ini my_tenant.ini --live` creates the test ledger, funds, expense
classes, budgets, organization and location that the sample spreadsheet refers to (codes
`TEST-ELEC`, `TEST-PRINT`, `GEN`, `PHY`, `SOC`, `EBSCO`; every name starts with
`test_ebsconet_`). Existing records with the same code are left alone and the ids are written
to `test_data_created.json`. Never point it at a production tenant.

## Limitations and notes
- Reference numbers are not mapped: the SOP has no reference-number column. The loader
  supports vendor reference numbers (`vendor_reference_number` + `vendor_reference_type`);
  add a source column in `row_to_line()` in `pipeline/folio_orders_adapter.py` if a customer
  provides one.
- Orders are created Pending and are never opened by these tools. Decide separately when they
  will be opened; the ledger's "Restrict encumbrance" setting and the budgets'
  allowable-encumbrance % decide whether they can be opened later.
- The publisher goes to the line's publisher field; Descriptor + Frequency go to the line
  Description.
- Fund, expense class and organization are matched by code.
- `finish` flags every line that is not `<PO>-1` for manual handling.
- Tested live on a bugfest tenant: 140 POs created and deleted, and a 7-PO sample
  (electronic, physical, P-E) checked in the FOLIO UI; the vendor-account step was run live
  and reverted.

## Tests and lint
```
.venv/bin/python -m pytest -q
.venv/bin/flake8 --max-line-length=100 .
```
(Install `requirements-dev.txt` for pytest and flake8.) Not in the repository (git-ignored):
filled-in `*.ini` files, the SOP spreadsheets, and `out/`.
