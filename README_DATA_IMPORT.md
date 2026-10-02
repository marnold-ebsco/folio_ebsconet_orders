# EBSCONET SOP -> FOLIO orders: loading through MARC and Data Import

These tools turn an EBSCONET SOP spreadsheet into MARC files that FOLIO (Sunflower) Data
Import loads as Pending purchase orders (one PO with one PO line per MARC record), convert
the orders to ongoing orders, and write the PO / POL numbers EBSCONET needs. One command
drives the whole workflow: `ebsconet.py`.

```
for-customer SOP.xlsx -> customer fills in columns -> build FILLED*.xlsx -> setup (once per tenant)
   -> load --use-marc (preflight dry run, then --live) -> finish --use-marc -> out/pol_export.csv
```

Data Import creates every order as One-Time and Pending and cannot set the ongoing details
(renewal interval, subscription flag, renewal date), so `finish --use-marc` converts the
orders the customer marked Ongoing afterwards, using `out/order_settings.csv`. Orders stay
Pending; nothing is opened or encumbered. `RUNBOOK.md` is the step-by-step checklist and
`docs/CLIENT_GUIDE.md` is the plain-language explanation to give a customer. `PLAN.md`
records the design.

## Setup

**Prerequisites**
- Python 3.12 or higher.
- A FOLIO tenant, and a user that can create Data Import profiles, run imports, and create /
  edit orders and organizations.
- On the tenant: the EBSCONET **vendor organization** (its code is `folio.vendor_org_code`
  in `ebsconet_config.json`, default `ebsconet`); the organizations the customer will name in
  **FOLIO Access Provider** (marked as vendors); the **funds** named in **FOLIO Fund**, each Active with an
  Active budget for the order's fiscal year that lists the **expense classes** in use (the
  budget amount does not matter for loading; a zero-based budget is fine); the **location**
  and **material type** for print / P-E lines; and the acquisition method named in the config.

**Python environment**
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Use `requirements-dev.txt` instead if you also want the test and lint tools. Run everything
from the repository folder with the venv: `.venv/bin/python <script>`.

**Tenant .ini file.** Copy `sample.ini` to a file of your own (for example `my_tenant.ini`)
and fill in the keys:

| Key | Meaning |
|---|---|
| `okapiUrl` | the tenant's API URL |
| `tenant_id` | the tenant id |
| `username`, `password` | a FOLIO user with the permissions above |
| `sslVerify` | `true`, `false`, or the path to a CA certificate bundle |

A filled-in .ini holds live credentials: never commit or share it (`*.ini` is git-ignored
except `sample.ini`). Pass it to every FOLIO command with `--ini my_tenant.ini`.

**Config file `ebsconet_config.json`** holds what a library chooses. Edit it before the first
load. The fund, expense class and organization entries are only the *defaults* used when the
customer leaves a cell blank; the values in the repository are TEST placeholders.

| Section / key | Meaning |
|---|---|
| `fund_by_route` | default fund code for `online` / `print` / `pe` |
| `expense_class_by_subject`, `default_expense_class` | expense class by SOP subject, and the fallback |
| `customer_choices` | optional drop-down lists for the customer's `location` and `material_type` columns (empty list = free text) |
| `rules.exclude_zero_cost`, `rules.exclude_zero_cost_package_members` | drop $0 rows / $0 package members (both default `true`) |
| `rules.exclude_usage_loading_service` | `true` leaves out "Usage Loading Service" lines (default `false`: they load) |
| `rules.skip_missing_issn` | `false`: rows without an ISSN are loaded and logged, never skipped |
| `rules.use_expense_classes` | `false` if the tenant does not use expense classes (no 990$e is written) |
| `ongoing.default_order_type` | `Ongoing` or `One-Time`, used when the customer leaves the cell blank and the SOP has no `Term` column (otherwise Term decides) |
| `ongoing.interval_days` | default renewal interval (365) |
| `ongoing.is_subscription`, `ongoing.manual_renewal` | `ongoing.isSubscription` / `ongoing.manualRenewal` (`true` / `false`) |
| `ongoing.renewal_date_source` | where the renewal date comes from (see Finish) |
| `folio.profile_name_prefix` | prefix of the profile names (`EBSCONET order migration`) |
| `folio.vendor_org_code` | the EBSCONET vendor organization (`ebsconet`) |
| `folio.acquisition_method`, `folio.currency` | acquisition method name that must exist on the tenant; currency |
| `folio.override_po_lines_limit` | each PO's own "override lines limit" (`1`) |
| `folio.subscription_interval`, `folio.title_number_type` | profile subscription interval; product-ID type for the Title Number |
| `folio.create_inventory` | `None`: no inventory records are created |
| `folio.receipt_status` | receipt status per `online` / `print` / `pe` |
| `folio.location`, `folio.physical_material_type` | defaults for physical and P-E lines when the customer leaves the cells blank |
| `folio.account_payment_method` | payment method for account numbers added to the vendor organization |
| `folio.template_dir` | folder of exported mapping-profile templates (`template_profiles`) |

The fixed, process-level settings (SOP column names, MARC tags and indicators, format
routing, output file names, the customer columns) are in `pipeline/pipeline_config.json`;
they are the same for every library and are merged in automatically. The SOP-column -> MARC-tag
map lives in `order_marc_headers.xlsx` (edit it in Excel).

**One-time per-tenant setup (`setup`).**
```
.venv/bin/python ebsconet.py setup --ini my_tenant.ini            # dry run: logs in, shows the plan
.venv/bin/python ebsconet.py setup --ini my_tenant.ini --live     # writes to FOLIO
.venv/bin/python ebsconet.py setup --ini my_tenant.ini --live --update-mappings
```
`setup` adds the SOP account numbers (from `out/*.xlsx`, so run `build` first) to the
`ebsconet` organization, then creates for Online / Print / P-E a field mapping profile, an
action profile (CREATE, ORDER) and a job profile linked to it, all named
"EBSCONET order migration - <Online|Print|P-E>" (`folio.profile_name_prefix`). Existing
profiles with the same name are skipped. The generated mapping JSON is always written to
`out/profiles/` for review, even in a dry run. Read the plan, then add `--live`; afterwards
check in FOLIO (Settings -> Data import) that the three job profiles exist and that each
mapping profile sets the PO status to **Pending**.

`--update-mappings --live` overwrites existing mapping profiles with the current build. Run
it whenever the mapping changes, and on a tenant whose profiles were created before location
and material type were read per record from the MARC (990$l / 990$m).

The mapping profiles are built from the exported Order mapping profiles in
`template_profiles/` (electronic, physical, P/E mix). All sample values in the templates are
blanked, then set: PO Pending / approved, PO number 990$o, vendor = the `ebsconet` org id,
title 245$a, subscription 990$s / $t, ISSN 020$a + title number 990$i product IDs, price
990$c, quantity 1, fund 990$f / expense class 990$e at 100%, account 990$a, access provider
990$v, resource URL 856$u, location 990$l and material type 990$m (physical and P-E).
Receiving workflow is Independent (`checkinItems` = true). In the P-E profile the SOP price
goes on the physical side and the electronic price is 0.

## Step 1: prepare the customer's copy (`for-customer`)
```
.venv/bin/python ebsconet.py for-customer SOP.xlsx
```
Removes every zero-dollar line, drops "Fee" and unrecognized-format lines, splits the rest
by format, and adds the highlighted columns the customer fills in **line by line**. It writes
ONE workbook, `out/customer/<name>_for_customer.xlsx`, with these sheets in order:

1. **Defaults**: the library's setup questions (default fund per type, expense classes,
   organization, location, material type, acquisition method, payment method, order type and
   renewal interval), one row each with a yellow "Your answer" cell. Same questions as
   `ebsconet-configure --worksheet`.
2. **electronic**, **physical**, **P-E**: the lines of each type (a type with no lines gets no
   sheet) with its own customer columns.
3. The option lists the Defaults drop-downs use (`--Funds`, `--Locations`, ...; the `--` prefix marks sheets that only feed drop-downs), at the end.

Add `--ini <tenant>.ini` to fill the Defaults drop-downs, and the location and material-type
drop-downs on the data sheets, with the tenant's real options (otherwise they are free text
unless `customer_choices` in your config lists values). Read
`out/customer/<name>_for_customer_report.txt` (lines read, removed, not sent, per sheet);
removed lines are in `<name>_zero_dollar_removed.csv`, lines not sent in
`<name>_not_sent.csv`. Send the customer the one `_for_customer.xlsx` file.

When it comes back, `build` reads every data sheet and applies any answers on the Defaults
sheet for that run. To keep them for `load` and later runs, save them into the config:
`ebsconet-configure --from-worksheet <returned file>.xlsx`. (The older three separate files
are still accepted by `build`.)

**Customer columns** (which columns go on which file is `customer_columns` in
`pipeline/pipeline_config.json`):

| Sheet | Columns |
|---|---|
| electronic (`online`) | `FOLIO Access Provider`, `FOLIO Fund`, `FOLIO Expense Class`, `FOLIO Order Type`, `FOLIO Renewal Interval (Days)` |
| physical (`print`) | the five above plus `FOLIO Location`, `FOLIO Material Type` |
| P-E (`pe`) | the same seven columns as physical |

`FOLIO Order Type` is an Excel drop-down limited to `Ongoing` / `One-Time`. It arrives pre-filled from the SOP `Term` column (a line with a Term is Ongoing and its interval is the Term in days; a line with no Term is One-Time); change it as needed.
`FOLIO Renewal Interval (Days)` accepts only whole numbers above 0 and is used only when the
order type is Ongoing. `FOLIO Location` and `FOLIO Material Type` are drop-downs when
`customer_choices` lists values, otherwise free text exactly as FOLIO names them (location as
`Name (CODE)`, material type by name). The SOP's own `Order Type` column is a different,
ignored column. If a column is already in the SOP it is used in place, never duplicated. Use
codes and names exactly as they appear in FOLIO; the customer should not add, delete or
reorder other columns.

## Step 2: build (`build`)
```
.venv/bin/python ebsconet.py build FILLED_electronic.xlsx FILLED_physical.xlsx FILLED_P-E.xlsx
```
List whichever filled-in files you have (one or all three; with several, rows are reported as
`<file>:<row>`). `build` runs prep and then builds the MARC files. It uses the customer's
values as they are. A blank cell, or a SOP without that column, falls back to the config
defaults (`fund_by_route`, `expense_class_by_subject` / `default_expense_class`,
`ongoing.default_order_type` / `ongoing.interval_days`,
`folio.location` / `folio.physical_material_type`). A wrong order type or a non-numeric
interval is replaced by the default with a warning in the report; a One-Time order has no
interval. `build` exits 1 if it finds a problem. Outputs:

- `out/library-EBSCONET_online.xlsx`, `library-EBSCONET-print.xlsx`, `library-EBSCONET_P-E.xlsx`:
  the filled-in lines split by format.
- `out/marc/*.mrc` (for Data Import) and `out/marc/*.mrk` (readable text copies; open one and
  eyeball a few records). An empty split (for example print, when every print row is $0)
  produces no MARC file.
- `out/prep_report.txt`: rows loadable per route, exclusions, removed rows with a non-zero cost
  (money that will not be loaded), and how many cells of each customer column were blank.
- `out/prep_defaults_used.csv`: every blank cell that took a default, row by row.
- `out/prep_exclusions.csv`: every row left out and why.
- `out/prep_no_issn.csv`: rows loaded without an ISSN (see Data rules).
- `out/order_settings.csv`: each order's type and renewal interval, read later by `finish`.

How the customer columns flow on: Location and Material Type go into MARC `990$l` and
`990$m` and the mapping profile reads them per record (re-run `setup --update-mappings --live`
on a tenant whose profiles were made before this); the preflight checks every location and
material type actually used. Order Type and interval go into `out/order_settings.csv`.

Extra PO line fields: prep adds two columns that the MARC carries as 980$d and 980$k.
**Descriptor + Frequency** are joined (`"Site License; Monthly (8-14 issues)"`; empty values
and "Not Applicable" are dropped, separator is `description_separator`) and mapped to the PO
line **Description**. **Cancellable** is inverted (SOP "No" -> `cancellationRestriction` true,
"Yes" -> false) and mapped to the line's cancellation restriction. The raw 980$r / $f / $c
values also stay in the MARC record. 264$a is used for the publisher (not 260$a). Prep
lowercases the scheme and host of the URL column (FOLIO rejects `HTTP://WWW.X.ORG` and would
discard the whole PO line); paths and query strings are left alone.

## Step 3: load (`load --use-marc`)
```
.venv/bin/python ebsconet.py load --use-marc --ini my_tenant.ini            # dry run = preflight
.venv/bin/python ebsconet.py load --use-marc --ini my_tenant.ini --live     # loads
```
For each MARC file (online, print, pe) `load --use-marc` runs the preflight checks, then
uploads the file through the Data Import API (S3 presigned upload when the tenant has file
splitting on), runs the job profile "EBSCONET order migration - <Online|Print|P-E>", waits for
the parent / child jobs, verifies the POs, removes empty product IDs, and prints the log
entries. Without `--live` it only runs the preflight and checks the PO numbers are unused; it
refuses to run while any PO number in the file already exists. Options:
`--only {online,print,pe}` loads just one file; `--skip-preflight` overrides the preflight
stop; `--no-cleanup` leaves the empty product-ID rows. The command exits 1 if any file had a
problem. Long loads can exceed a terminal's time limit: run them in the background or a second
terminal and read the result afterwards. Do a small trial first on a new tenant (copy a few
records into a test .mrc and load it with `python -m pipeline.folio_import`).

**Preflight (`pipeline/folio_preflight.py`)** runs automatically before every load and stops
it on any error. It reads only; nothing is written. Findings are ERROR (the load would fail or
discard lines) or WARN, grouped by type. Checks:
- File: missing title / PO number / fund / account / access provider; PO number not 1-22
  letters or digits (FOLIO rejects hyphens etc.); price not a number; dates not ISO or end
  before start; a URL FOLIO would reject; ISSN format; missing title number; duplicate PO
  numbers or 001s inside the file.
- Tenant: the job profile exists **and its mapping profile loads orders as "Pending"** (an Open
  status is an ERROR; if the profile chain cannot be read it is a WARN); PO numbers not already
  in FOLIO; the vendor organization exists and has the account numbers (WARN);
  access-provider organizations exist; each fund exists, is Active and has an Active budget;
  each expense class exists **and is Active on that budget**; location and material type exist
  (print / P-E); the acquisition method exists. The amount in a budget never blocks the load
  (imported orders are Pending; encumbrances are made when an order is *opened*). The only
  money check is a WARN that the file's total exceeds the room left under the fund's
  encumbrance limit; it applies only when the ledger has "Restrict encumbrance" on AND a
  budget has an allowable-encumbrance %. Zero-based budgets are unlimited and give no warning.

Run alone, it needs `--route online|print|pe` (`load --use-marc` works the route out from the
file for you):
```
.venv/bin/python -m pipeline.folio_preflight out/marc/<file>.mrc --ini my_tenant.ini \
    --route online --job-profile "EBSCONET order migration - Online"
```
Typical errors are a fund, expense class or organization code the customer mistyped or that
does not exist in FOLIO, an expense class not on the fund's budget, a PO number already in
FOLIO, and a URL FOLIO rejects. Send the error list to the customer (or fix the tenant),
get a corrected file, and repeat build and the dry run until there are **no errors**.

**Audit log and retries.** Every live load writes `out/import_logs/<time>_<file>.csv`
(columns kind / ref / status / detail: one row per job, per log record and per PO) and prints a
summary: POs that have a PO line, and each discarded record with its error.

**Empty product IDs.** The import profile always builds two product-ID rows (ISSN and title
number). A record missing either still gets the row, empty; FOLIO shows the empty row and
refuses to save an edit of the line while it is there. A profile cannot skip a row, so
`pipeline/folio_import.py` removes the empty rows automatically right after each load
(`pipeline/folio_clean_product_ids.py`; `--no-cleanup` to leave them). A line ends up with only
its real IDs: ISSN + title number, just one of them, or none (package rows). The ID *type* is
carried in the MARC as 990$j (only when a title number exists). For earlier loads, run the
cleaner on its own:
```
.venv/bin/python -m pipeline.folio_clean_product_ids --csv po_numbers.csv --ini my_tenant.ini --live
```

After a live load, search a few PO numbers in FOLIO Orders: status **Pending**, vendor, fund
and expense class, price, dates, access provider / location, account number. Data Import ->
Logs shows the same jobs (parent + child). The fund needs a **budget** containing the expense
class, or the PO line is discarded ("Budget expense class not found").

## Step 4: finish (`finish --use-marc`)
```
.venv/bin/python ebsconet.py finish --use-marc --ini my_tenant.ini            # dry run
.venv/bin/python ebsconet.py finish --use-marc --ini my_tenant.ini --live     # converts
```
`finish --use-marc` takes the PO numbers from the MARC files, converts the orders to ongoing
(following the customer's choices in `out/order_settings.csv`: One-Time orders stay One-Time,
Ongoing orders get the customer's interval), writes `out/ongoing_log.csv`, then writes
`out/pol_export.csv`. Without `--live` the conversion is a dry run (the log shows the renewal
dates) and the orders stay One-Time; the PO / POL export is written either way. The command
exits 1 if any conversion errored.

Each order has two separate settings: its **status** (Pending / Open / Closed) and its
**order type** (One-Time / Ongoing). The conversion changes only the type, to Ongoing, and
never the status: orders stay **Pending**. An Ongoing order carries the renewal details a
One-Time order lacks: a renewal interval, a "subscription" flag and a renewal date. The
conversion also removes any empty product-ID rows as a safety net. Per PO it reads the
composite order and converts it only if it is **Pending** and not already **Ongoing**;
anything else is logged `skipped` with the reason. Log statuses: `converted`, `dry-run`,
`skipped`, `not-found`, `error`.

Ongoing-order defaults (section `"ongoing"` of `ebsconet_config.json`):

| Setting | Default | Meaning |
|---|---|---|
| `interval_days` | `365` | FOLIO `ongoing.interval` (renewal interval, in days) |
| `is_subscription` | `true` | FOLIO `ongoing.isSubscription` |
| `manual_renewal` | `false` | FOLIO `ongoing.manualRenewal` |
| `renewal_date_source` | `latest_subscription_to` | Where `ongoing.renewalDate` comes from |

`renewal_date_source` options:
- `latest_subscription_to`: the latest "subscription to" date across the PO's lines (the
  lines' 990$t end date loaded at import), so the PO never renews before its last line ends.
- `earliest_subscription_to`: the earliest of those dates.
- `none`: do not set a renewal date.
If no line has an end date, no renewal date is set.

The code is `build_ongoing()` and `renewal_date()` in `pipeline/folio_ongoing.py`: the existing
composite order gets `orderType: "Ongoing"` and an `ongoing` block, sent with a PUT to
`/orders/composite-orders/{id}`. Other ongoing fields (`reviewPeriod`, `reviewDate`, `notes`)
are not set; add them in `build_ongoing()`. The conversion can also be run on its own on a
list of PO numbers (the Orders app CSV export with a "PO number" column, or one number per line):
```
.venv/bin/python -m pipeline.folio_ongoing po_numbers.csv --ini my_tenant.ini            # dry run
.venv/bin/python -m pipeline.folio_ongoing po_numbers.csv --ini my_tenant.ini --live
```

**PO / POL export.** `out/pol_export.csv` has PO number, POL number, title, subscription end,
POL id and a `matches_po_plus_1` column. EBSCONET is told the POL number is the PO number plus
`-1`, so any line that is not `-1` (such as the second line of a two-line PO) is flagged
`NO - line N` for you to handle by hand. Send it to EBSCONET. Stand-alone:
```
.venv/bin/python -m pipeline.folio_export_pols --prefix E50 --ini my_tenant.ini
.venv/bin/python -m pipeline.folio_export_pols --csv po_numbers.csv --ini my_tenant.ini
```
(`--out` changes the file name.)

## Data rules
Which rows load is decided in `pipeline/ebsconet_prep.py` from `rules` in
`ebsconet_config.json`.

**Every row is loaded; a row without an ISSN is logged, not skipped** (`rules.skip_missing_issn`
is `false`). `out/prep_no_issn.csv` records the sheet row, order number, title, cost, route,
identifier used and whether it was generated, and the preflight warns "no ISSN". The
identifiers a line gets:

| Situation | Product IDs on the line |
|---|---|
| ISSN and title number | both (ISSN, then `Publisher or distributor number`) |
| ISSN, no title number | the ISSN only |
| No ISSN, has a title number | the title number only (the empty ISSN row is removed after the load) |
| No ISSN and no title number | a **generated** identifier `NOISSN-<EBSCONET order number>` of type `Local identifier` (`generated_id` in `pipeline/pipeline_config.json`; flagged in the prep workbook's "Generated ID?" column and in `prep_no_issn.csv`). Unique and reproducible, and not an ISSN |

The `Local identifier` type must exist on the tenant (preflight checks).

| Situation | What happens | Where to change it |
|---|---|---|
| "Usage Loading Service - ..." lines (service fees, not titles) | **Loaded** for now; set the rule to `true` to leave them out (logged in `out/prep_exclusions.csv`) | `rules.exclude_usage_loading_service` |
| Zero-cost row | **Not loaded** ("Zero cost") | `rules.exclude_zero_cost` |
| Zero-cost member of a package | **Not loaded** ("Package member at zero cost"); packages are recognized by `package_title_keywords` | `rules.exclude_zero_cost_package_members` |
| "Fee" format or unrecognized format | **Not loaded**, logged | `excluded_formats`, `format_routes` |
| Same order number on more than one row | Kept, but Data Import makes one PO per record, so the later record fails as a duplicate PO number (preflight reports it); see `folio_add_po_lines.py` | not yet decided |

**Expense classes are optional.** Set `rules.use_expense_classes` to `false` (or leave a value
blank) and no 990$e is written; the line's fund distribution then has no expense class.
Preflight does not require one, and only checks a class against the budget when the record has
one. The fund still needs an Active budget.

## Outputs (in `out/`)
| File | Made by | What it is |
|---|---|---|
| `customer/<name>_for_customer.xlsx` | for-customer | Send to the customer (Defaults sheet + one sheet per type) |
| `customer/<name>_zero_dollar_removed.csv`, `_not_sent.csv`, `_report.txt` | for-customer | What was removed or not sent, and why |
| `library-EBSCONET_online / -print / _P-E.xlsx` | build | The filled-in lines split by format |
| `prep_report.txt`, `prep_exclusions.csv`, `prep_no_issn.csv`, `prep_defaults_used.csv` | build | What was excluded, loaded without an ISSN, or given a default |
| `order_settings.csv` | build | Each order's type and renewal interval; read by `finish` |
| `marc/*.mrc`, `marc/*.mrk` | build | Files for Data Import, and readable text copies |
| `profiles/` | setup | The generated mapping-profile JSON, for review |
| `import_logs/*.csv` | load | Audit log of each import |
| `retry/` | folio_retry_failed.py | Retry .mrc and delete CSV |
| `ongoing_log.csv`, `pol_export.csv` | finish | Conversion results; the PO / POL list for EBSCONET |
| `add_lines_log.csv`, `delete_log.csv`, `deleted_backup/` | the tools below | Logs and backups |

`build` rebuilds everything in `out/`, so keep each SOP's files together or give each SOP its
own folder with the global option, for example `ebsconet.py --out out/2026-spring build ...`
(the global options `--config` and `--out` go before the subcommand).

## Troubleshooting and fix-up tools
| Problem | Tool |
|---|---|
| Some records did not load (discarded, or an empty PO left behind) | `.venv/bin/python folio_retry_failed.py out/marc/<file>.mrc --ini my_tenant.ini` lists them and writes `out/retry/<file>_retry.mrc` plus `_delete_empty.csv` |
| `SOP is missing required column heading(s)` | SOP renamed a heading. Override it in `columns` in your `work/ebsconet_config.json`, e.g. `{"columns": {"cost": "New Heading"}}` (survives upgrades; keys are in `pipeline/pipeline_config.json`) |
| Empty POs or wrongly loaded orders to remove | `folio_delete_orders.py` (below) |
| Load the retry file | `.venv/bin/python -m pipeline.folio_import out/retry/<file>_retry.mrc --ini my_tenant.ini --job-profile "EBSCONET order migration - Online"` (add `--live`) |
| Several lines for one PO number (Data Import discards the later records) | `folio_add_po_lines.py` (below) |
| Empty product IDs on orders loaded another way | `folio_clean_product_ids` (above) |
| Test tenant: remove the test POs you loaded | `folio_cleanup_test_pos.py` (below) |
| One step on its own (any `pipeline/` step) | `.venv/bin/python -m pipeline.<step> --help` |

After fixing the cause, regenerate the `.mrc` if the data changed (`build` again), then load
the retry file.

**Retry.** `folio_retry_failed.py <file>.mrc --ini ...` is read-only: it finds the records with
no PO or an empty PO and writes `out/retry/<file>_retry.mrc` plus, for empty POs,
`out/retry/<file>_delete_empty.csv` (same format as `folio_delete_orders.py`). Delete those
first, fix the cause, then load the retry file.

### Removing problem orders (`folio_delete_orders.py`)
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
  `POL_<number>.json`) before it is deleted. For reference; there is no restore script.
- `--max N` (default 50) refuses longer lists. A missing or duplicate number is logged and the
  run continues; the exit code is non-zero if any entry errored.
- Results are written to `out/delete_log.csv` (statuses `deleted`, `dry-run`, `skipped`,
  `not-found`, `error`).

Deleting a PO does not undo anything Data Import created outside the order (for example
inventory records, if create-inventory was ever turned on). With the default of `None`
nothing else is created.

### Several lines on one PO (`folio_add_po_lines.py`)
Data Import can only make one line per PO, so a record whose PO number is already taken is
discarded. To put it on the existing PO as another line, run the same `.mrc` through:
```
.venv/bin/python folio_add_po_lines.py out/marc/<file>.mrc --ini my_tenant.ini          # dry run
.venv/bin/python folio_add_po_lines.py out/marc/<file>.mrc --ini my_tenant.ini --live   # adds lines
```
For each record whose PO exists it POSTs a new line to `/orders/order-lines`: a copy of the PO's
first line (so order format, receipt status, location, material type and acquisition method stay
as the import profile set them) with the record's title, publisher, product IDs, subscription
dates, price, fund / expense class, vendor account, access provider, URL, description and
cancellation restriction swapped in. Only Pending POs are touched; a record whose title is
already on the PO is skipped, so re-running adds nothing; the tenant's lines-per-PO limit
(`poLines-limit`) is checked first. Skips are explained in the output and in
`out/add_lines_log.csv` (`no-po`: load it normally; `limit`: raise the tenant setting first).
New lines are numbered `<PO>-2`, `-3`... (FOLIO never reuses a deleted line number). Undo a line
with `folio_delete_orders.py` (`POL,<po>-<n>`). The value mapping mirrors
`pipeline/folio_setup.py`; change both together. `pipeline/folio_export_pols.py` flags these
extra lines (`NO - line N`) because EBSCONET is told POL = PO + `-1`.

### Test tenants only
- `folio_test_data.py --ini my_tenant.ini --live` creates the test ledger, funds, expense
  classes, budgets (allocation 1,000,000), organization and location the sample spreadsheet
  refers to (`TEST-ELEC`, `TEST-PRINT`, `GEN`, `PHY`, `SOC`, `EBSCO`; every name starts with
  `test_ebsconet_`). The ids are written to `test_data_created.json`.
- `folio_cleanup_test_pos.py --ini my_tenant.ini` (dry run; add `--live` to delete) removes the
  POs your test loads created. The list comes from the PO numbers (990$o) in your local
  `out/marc/*.mrc` files (or `--mrc FILE`, plus `--po NUMBER` for one-offs), so it can only
  touch orders you loaded. A PO is deleted only if it is **Pending** and belongs to the
  EBSCONET vendor organization; others are skipped and shown. Each PO is saved to
  `out/deleted_backup/` first; the log is `out/cleanup_test_pos_log.csv`. It does not remove
  profiles, accounts or the `test_ebsconet_*` records. Never point either tool at a production
  tenant.

## Limitations and notes
- **One PO line per MARC record.** Tested on bugfest: two records with the same PO number in
  one import -> the first loads, the second is discarded with "PO Number already exists" (it
  does not add a line to the existing PO). Many POs per import work fine (107 in two loads).
  Use `folio_add_po_lines.py` for extra lines. The tenant's own limit on lines per PO is read
  from the ORDERS configuration (`poLines-limit` on bugfest, where it is 11; `order_lines_limit`
  in other environments; FOLIO's default is 1 when neither exists) by
  `folio_common.order_lines_limit()`, and preflight prints it. The profiles also set each PO's
  own "override lines limit" to 1 (`folio.override_po_lines_limit`).
- Data Import cannot set ongoing details, hence the `finish` conversion.
- Fund, expense class and access provider are accepted by code (proven on bugfest). The
  tag choices follow `order_marc_headers.xlsx`: 990$t for the end date, 990$a for the account,
  264$a for the publisher; 990$i (title number) = `Publisher Product Code`.
- Location and material type are carried in 990$l / 990$m and need `setup --update-mappings`
  on profiles made earlier.
- Reference numbers are not mapped.
- The non-S3 upload path (a tenant with file splitting off) is mock-tested only.
- Trial results on bugfest: 107 online POs created Pending with a PO line, none discarded;
  a pure Print record and P-E records (P/E Mix, one physical + one electronic quantity) also
  loaded; the POL export listed 112 lines, all POL = PO + `-1`.

## Tests and lint
```
.venv/bin/python -m pytest -q
.venv/bin/flake8 --max-line-length=100 .
```
(Install `requirements-dev.txt` for pytest and flake8.) Not in the repository (git-ignored):
filled-in `*.ini` files, the SOP spreadsheets, and `out/`. Only `order_marc_headers.xlsx` (the
tag map) is tracked.
