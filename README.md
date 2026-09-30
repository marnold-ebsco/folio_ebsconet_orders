# EBSCONET SOP -> FOLIO (Sunflower) order migration

Scripts that turn an EBSCONET SOP spreadsheet into MARC files for FOLIO Data Import,
and handle the follow-up work on the orders once they exist. See `PLAN.md` for the
original plan and `EBSCOnetInstructions.txt` for the manual process these replace.

Setup (Python 3.12+):
```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp sample.ini my_tenant.ini      # then fill in the tenant URL, id, user, password
```
Run everything from this folder with the venv: `.venv/bin/python <script>`.
Tests: `.venv/bin/python -m pytest -q`. Lint: `.venv/bin/flake8 .`

Not in the repo (git-ignored): filled-in `*.ini` files, the SOP spreadsheets, `out/`, and
`EBSCOnetInstructions.txt`. Only `order_marc_headers.xlsx` (the tag map) is tracked.

| Step | Script | Status |
|---|---|---|
| 1 Prep + split spreadsheet | `ebsconet_prep.py` | done |
| 2 Build MARC files | `ebsconet_to_marc.py` | done |
| 3a One-time -> ongoing orders | `folio_ongoing.py` | done (untested against a live tenant) |
| 3b PO/POL export for EBSCONET | `folio_export_pols.py` | done (untested against a live tenant) |
| 4 FOLIO profiles | `folio_setup.py` | done (dry run verified; not yet run live) |
| - Test data on tenant | `folio_test_data.py` | run once on the bugfest tenant |
| 5 Load a .mrc | `folio_import.py` | tested live (bugfest) |
| - Remove bad POs/lines | `folio_delete_orders.py` | tested with mocks only |

All tunable values live in `ebsconet_config.json`. The SOP-column -> MARC-tag map
lives in `order_marc_headers.xlsx` (edit it in Excel).

## Steps 1-2: files for Data Import
```
.venv/bin/python ebsconet_prep.py TestEBSCOnet_adjusted.xlsx --out out
.venv/bin/python ebsconet_to_marc.py
```
Outputs: `out/library-EBSCONET_*.xlsx`, `out/prep_report.txt`,
`out/prep_exclusions.csv` (every removed row and why), and `out/marc/*.mrc|.mrk`.
An empty split (for example print, when every print row is $0) produces no MARC file.

Row rules (config `rules` and `package_title_keywords`): zero-cost rows are removed;
package members at $0 are removed; rows with no ISSN are removed unless they are a
package purchase (title contains package/collection/suite, or equals the package
name); "Fee" and unrecognized formats are removed.

## Step 3a: convert POs to ongoing orders (`folio_ongoing.py`)
```
.venv/bin/python folio_ongoing.py po_numbers.csv --ini my_tenant.ini             # dry run
.venv/bin/python folio_ongoing.py po_numbers.csv --ini my_tenant.ini --live      # updates FOLIO
```
- Input: the Orders app CSV export (a "PO number" column) or a plain list with one PO
  number per line. Duplicates are ignored.
- Default is a **dry run**; nothing is written unless `--live` is given.
- Per PO it reads the composite order, and only converts it if it is **Pending** and
  not already **Ongoing**. Anything else is logged as `skipped` with the reason.
- Log: `out/ongoing_log.csv` with statuses `converted`, `dry-run`, `skipped`,
  `not-found` or `error`. The script exits non-zero if any PO errored.

### Ongoing-order defaults (change them in `ebsconet_config.json`, section `"ongoing"`)
| Setting | Default | Meaning |
|---|---|---|
| `interval_days` | `365` | FOLIO `ongoing.interval` (renewal interval, in days) |
| `is_subscription` | `true` | FOLIO `ongoing.isSubscription` |
| `manual_renewal` | `false` | FOLIO `ongoing.manualRenewal` |
| `renewal_date_source` | `latest_subscription_to` | Where `ongoing.renewalDate` comes from |

`renewal_date_source` options:
- `latest_subscription_to` - the latest "subscription to" date across the PO's lines
  (the lines' 990$t end date loaded at import). Chosen so the PO never renews before
  its last line ends.
- `earliest_subscription_to` - the earliest of those dates.
- `none` - do not set a renewal date.
If no line has an end date, no renewal date is set.

The code that applies these is `build_ongoing()` and `renewal_date()` in
`folio_ongoing.py`; the payload is the existing composite order with
`orderType: "Ongoing"` and an `ongoing` block, sent with a PUT to
`/orders/composite-orders/{id}`. If FOLIO rejects the payload, the first dry run/live
run on one PO will show the error text in the log. Other ongoing fields
(`reviewPeriod`, `reviewDate`, `notes`) are not set; add them in `build_ongoing()`.

## Step 3b: PO/POL export (`folio_export_pols.py`)
```
.venv/bin/python folio_export_pols.py --prefix E50 --ini my_tenant.ini
.venv/bin/python folio_export_pols.py --csv po_numbers.csv --ini my_tenant.ini
```
Writes `out/pol_export.csv` (`--out` to change): PO number, POL number, title,
subscription end, POL id and a `matches_po_plus_1` column. EBSCONET is told the POL is
the PO number plus `-1`, so any line that is not `-1` (such as the second line of a
two-line PO) is flagged `NO - line N` for you to handle by hand.

## Step 4: accounts and Data Import profiles (`folio_setup.py`)
```
.venv/bin/python folio_setup.py --ini sunflower_bugfest.ini            # dry run
.venv/bin/python folio_setup.py --ini sunflower_bugfest.ini --live     # writes to FOLIO
```
Does instruction steps 8-12: adds the SOP account numbers (from `out/*.xlsx`) to the
`ebsconet` organization, then creates for Online / Print / P-E a field mapping profile,
an action profile (CREATE, ORDER) and a job profile linked to it, all named
"EBSCONET order migration - <Online|Print|P-E>" (`--name-prefix` to change). Existing
profiles with the same name are skipped. The generated mapping JSON is always written to
`out/profiles/` for review, even in a dry run.

Mapping profiles are built from exported Order mapping profiles in `template_profiles/`
(electronic, physical, P/E mix, taken from the bugfest tenant). All sample values in the
templates are blanked, then set: PO Pending/approved, PO number 990$o, vendor = the
`ebsconet` org id, title 245$a, subscription 990$s/$t, ISSN 020$a + title number 990$i
product ids, price 990$c, quantity 1, fund 990$f / expense class 990$e at 100%, account
990$a, access provider 990$v, resource URL 856$u. Receiving workflow is Independent
(`checkinItems` = true). In the P-E profile the SOP price goes on the physical side and
the electronic price is 0. Tenant-specific values live in `ebsconet_config.json`
section `"folio"` (acquisition method, material type, location, receipt status,
create-inventory, payment method for new accounts).

Known limitations / things to verify on the first real import:
- Data Import creates one PO per MARC record, so a second SOP line with an already used
  PO number (one such order in the sample) will probably fail as a duplicate.
- 980$r/$f/$c (Descriptor, Frequency, Cancellable) are in the MARC but not mapped to
  any PO field; 264$a is used for the publisher (not 260$a).
- Whether the import accepts fund/expense class/access provider by code (as in the
  instructions) has not been proven; check the first job log.

## Step 5: load a .mrc (`folio_import.py`)
```
.venv/bin/python folio_import.py out/marc/<file>.mrc --ini sunflower_bugfest.ini \
    --job-profile "EBSCONET order migration - Online" --live
```
Uploads the file through the Data Import API (S3 presigned upload when the tenant has
file splitting on, as bugfest does), runs the job profile, waits for the parent/child
jobs and prints the log entries. Without `--live` it only checks the PO numbers are
unused. Refuses to run if any PO number in the file already exists.

**Preflight check (`folio_preflight.py`)** runs automatically before every load and
stops it on any error (`--skip-preflight` overrides). It can also be run alone:
```
.venv/bin/python folio_preflight.py out/marc/<file>.mrc --ini my_tenant.ini --route online \
    --job-profile "EBSCONET order migration - Online"
```
It reads only; nothing is written. Findings are ERROR (the load would fail or discard
lines) or WARN, grouped by type. Checks:
- File: missing title / PO number / fund / expense class / account / access provider;
  price not a number; dates not ISO or end before start; URL FOLIO would reject; ISSN
  format; missing title number; duplicate PO numbers or 001s inside the file.
- Tenant: job profile exists **and its mapping profile loads orders as "Pending"** (an
  Open status is an ERROR; if the profile chain cannot be read it is a WARN); PO numbers not already in FOLIO; vendor organization
  exists and has the account numbers (WARN); access-provider organizations exist;
  each fund exists, is Active and has an Active budget; each expense class exists **and
  is Active on that budget**; location and material type exist (print / P-E);
  acquisition method exists. The amount in a budget never blocks the load (imported
  orders are Pending; encumbrances are made when an order is *opened*). The only
  money check is a WARN that the file's total exceeds the room left under the
  fund's encumbrance limit, and it applies only when the ledger has "Restrict
  encumbrance" on AND a budget has an allowable-encumbrance %. Zero-based budgets
  (allocation 0, no percentage) are unlimited and give no warning.
The route (`online` / `print` / `pe`) is taken from the standard job-profile name, or
give `--route`. On 2026-09-30 it correctly blocked re-loading POs that already exist.

Test on bugfest (2026-09-30): two online records (PO L9544821, S0110567) created Pending,
approved, vendor `ebsconet`, one electronic line each with correct ISSN, dates, publisher,
account, price, fund `TEST-ELEC`, expense class `GEN`, access provider and URL. Fund,
expense class and access provider are matched **by code**. The fund needs a **budget**
containing the expense class, or the PO line is discarded ("Budget expense class not
found"): `folio_test_data.py` creates budgets (allocation 1,000,000) for the test funds.

URLs: `ebsconet_prep.py` lowercases the scheme and host of the URL column (FOLIO
rejects `HTTP://WWW.X.ORG` for the resource URL and discards the whole PO line); paths
and query strings are left alone.

P-E test on bugfest: PO S6134100 and E5115378 created as P/E Mix, one physical + one
electronic quantity, test location and `journal` material type, fund `TEST-PRINT`,
receipt Pending, SOP price on the physical side and 0 electronic.

Empty product ID: a record with no 990$i (Publisher Product Code) still gets a blank
second product-ID entry on its PO line (Data Import cannot make a mapping row
conditional). To limit it, the ID *type* is carried in the MARC as 990$j (added by
`ebsconet_prep.py`, only when a title number exists) and the profile maps the type from
990$j, so the blank entry has no type either. `folio_ongoing.py` removes blank
product-ID entries when it converts a PO, so it disappears at that step.

`folio_setup.py --update-mappings --live` overwrites existing mapping profiles with the
current build (used after changing the mapping).

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
- Dry run unless `--live`; the dry run says how many lines a PO has, or warns when a
  line is the PO's last (the PO would be left empty).
- Only **Pending** orders are deleted; an Open order is skipped with the reason and
  must be handled in FOLIO first.
- Each PO / line is saved as JSON in `out/deleted_backup/` (`PO_<number>.json`,
  `POL_<number>.json`) before it is deleted. This is for reference; there is no
  restore script.
- `--max N` (default 50) refuses longer lists. A missing or duplicate number is logged
  and the run continues; the exit code is non-zero if any entry errored.
- Results are written to `out/delete_log.csv` (statuses `deleted`, `dry-run`,
  `skipped`, `not-found`, `error`).

Deleting a PO does not undo anything Data Import created outside the order (for example
inventory records, if create-inventory was ever turned on). With the default of `None`
nothing else is created.

## Tenant .ini files
`folio_common.py` reads the same `key = value` format as the PHP client (`okapiUrl`,
`tenant_id`, `username`, `password`, `sslVerify`). These hold live credentials: keep
them out of version control and out of this folder's shared copies.

## Open data decisions (current behavior, deliberately left as is)
Which rows load is decided in `ebsconet_prep.py` from the `rules` in
`ebsconet_config.json`. The preferred approach is not settled; today's behavior:

| Situation | What happens now | Where to change it |
|---|---|---|
| Single journal, no ISSN | **Not loaded.** Logged in `out/prep_exclusions.csv` ("Missing ISSN") and listed in `out/prep_report.txt` when it has a cost (29 rows in the sample, e.g. "Chem", "Library Journal", "Usage Loading Service" lines) | `rules.skip_missing_issn` |
| Package row (title has package / collection / suite, or equals its package name), no ISSN | **Loaded** without 020$a (10 rows in the sample); logged as a warning | `rules.exempt_costed_packages_from_issn_skip`, `package_title_keywords` |
| No title number (990$i) | **Loaded.** The PO line just has the ISSN product ID. 26 of 111 sample rows. Data Import leaves a blank product-ID entry, removed by `folio_ongoing.py` | title number comes from `columns.title_number_source` (`Publisher Product Code`) |
| No ISSN and no title number | Loaded (only package rows; 9 in the sample). The line has no product IDs, so it cannot be matched later by ISSN or title number | as above |
| Zero-cost row | **Not loaded** ("Zero cost") | `rules.exclude_zero_cost` |
| Zero-cost member of a package | **Not loaded** ("Package member at zero cost") | `rules.exclude_zero_cost_package_members` |
| "Fee" format or unrecognized format | **Not loaded**, logged | `excluded_formats`, `format_routes` |
| Same order number on more than one row | Kept, but Data Import makes one PO per record, so the later record will fail as a duplicate PO number (preflight reports it) | not yet decided |

## Assumptions to revisit
- Column tags follow `order_marc_headers.xlsx` where it disagrees with the
  instructions doc (990$t not $x, 990$a not $n, 264$a not 260$a).
- Fund, expense class and org values are TEST placeholders (`ebsconet_config.json`).
- 990$i (title number) = `Publisher Product Code`.
- "Fee" rows are excluded; all zero-cost rows are excluded (`exclude_zero_cost`).
