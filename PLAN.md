# EBSCOnet -> FOLIO (Sunflower) order migration: design and status

Last updated 2026-09-30. `RUNBOOK.md` is the start-to-finish checklist; `README.md` is the
how-to-run guide; this file records what was
built, why, and what is left.

## Goal
Turn an EBSCONET SOP spreadsheet into MARC files that FOLIO Data Import loads as
**Pending** purchase orders (one PO + one PO line per record), then convert them to
ongoing orders and give EBSCONET the PO/POL numbers. This replaces the manual MarcEdit
process in `EBSCOnetInstructions.txt` (not in the repo; internal).

Rules: Python 3.12+, FolioClient for all FOLIO access, pytest, flake8, pure Python
except pymarc / openpyxl / httpx.

## Workflow (rehearsed end to end on bugfest, 2026-09-30)
1. EBSCONET sends the SOP. 2. `ebsconet.py for-customer` removes every zero-dollar line and
adds the columns the customer fills in (FOLIO Org / Fund / Expense Class, highlighted).
3. The customer fills them in line by line and returns the file. 4. `ebsconet.py build`
processes it (remaining rules, the customer's values, split by format, MARC files).
5. `ebsconet.py load` (dry run = preflight) reports errors such as mistyped codes; the
customer corrects and returns the file; repeat 4-5. 6. `ebsconet.py load --live`.
7. `ebsconet.py finish --live` converts to ongoing orders and writes the PO / POL export.
`ebsconet.py setup` creates the Data Import profiles once per tenant. The rehearsal used
the test SOP with a simulated customer (three deliberate mistakes caught by preflight,
then corrected): 4,735 lines -> 141 for the customer -> 140 loaded, all with PO lines,
all converted to ongoing. `RUNBOOK.md` has the step-by-step version.

**Layout:** `ebsconet.py` is the one command; the steps it calls live in `pipeline/`;
the fix-up tools (retry, delete, add lines) and test-tenant tools stay in the root.

## Pipeline (all built and tested)
| Step | Script | Notes |
|---|---|---|
| 1 | `pipeline/ebsconet_prep.py` | Add fund / expense class / org columns, apply row rules, ISO dates, normalize URLs, split by format into Online / Print / P-E workbooks, highlight mapped columns, write report + exclusions log |
| 2 | `pipeline/ebsconet_to_marc.py` | Build `.mrc` + `.mrk` from the workbooks; tag map read from `order_marc_headers.xlsx` |
| 3 | `pipeline/folio_setup.py` | Accounts on the ebsconet org; per route a field mapping, action and job profile (built from templates in `template_profiles/`) |
| 4 | `pipeline/folio_preflight.py` | Read-only checks of the file and tenant before a load |
| 5 | `pipeline/folio_import.py` | Preflight, upload (S3 or local), run job profile, follow parent/child jobs, print log and POs |
| 6 | `pipeline/folio_ongoing.py` | One-time -> Ongoing (interval 365, subscription, renewal date = latest subscription end) |
| - | `folio_retry_failed.py` | After a partial load: retry .mrc for records with no PO / an empty PO, plus a delete CSV for the empty POs |
| 7 | `pipeline/folio_export_pols.py` | PO/POL numbers for the EBSCONET renewal integration (POL = PO + `-1`) |
| - | `folio_delete_orders.py` | Remove problem Pending POs / lines from a CSV, with backups |
| - | `pipeline/folio_clean_product_ids.py` | Removes the empty product-ID rows Data Import creates when an ISSN or title number is missing (runs after each load) |
| - | `folio_add_po_lines.py` | Adds records whose PO number is already taken as extra lines of that PO (Orders API), copying the PO's first line |
| - | `folio_cleanup_test_pos.py` | Deletes the test POs listed in your local .mrc files (Pending, EBSCONET vendor only) from a **test** tenant |
| - | `folio_test_data.py` | Creates test ledger / funds / budgets / classes / org / location on a **test** tenant |

## Decisions that shaped the build
- **Tags follow `order_marc_headers.xlsx`**, not the instructions doc: 990$t (not $x)
  for the end date, 990$a (not $n) for the account, 264$a (not 260$a) for the publisher.
  Added by prep: 990$f fund, 990$e expense class, 990$v access provider, 990$i title
  number (= `Publisher Product Code`), 990$j title-number type.
- **Zero-cost rows are not loaded**; package members at $0, "Fee" and unrecognized
  formats are not loaded. **Every other row is loaded; rows without an ISSN are logged**
  (`out/prep_no_issn.csv`). A row with neither an ISSN nor a title number gets a generated
  product ID `NOISSN-<order number>` (type Local identifier). See "Data rules" in the README.
- **Fund, expense class and org come from the customer's SOP columns** (FOLIO Fund /
  FOLIO Expense Class / FOLIO Org, filled line by line); the config values are only the
  fallback for blank cells. Fallbacks are logged (`out/prep_defaults_used.csv`).
- **Orders stay Pending.** The mapping profiles set `workflowStatus` to `"Pending"`;
  no script opens an order, and the preflight check refuses to load with a job profile
  whose mapping sets any other status. Budgets matter only for having an Active budget with the
  expense class attached (else lines are discarded), not for the amount.
- **Data Import makes one PO per record**, so two SOP rows with the same order number
  cannot become two lines on one PO. Tested live: the second record is discarded with
  "PO Number already exists". Preflight reports it. For multi-line POs, load the first
  line by import, then run `folio_add_po_lines.py` on the same file (tested live), or
  give the repeated order numbers distinct suffixes (which changes the POL numbers
  EBSCONET expects).
- **Fund / expense class / organization are matched by code** (proven on bugfest).
- **Extra line fields**: Descriptor + Frequency -> line Description; Cancellable
  (inverted) -> cancellation restriction. **Expense classes are optional**
  (`rules.use_expense_classes`).
- **Independent receiving** = `checkinItems: true`; create-inventory = None.
- Anonymized test spreadsheet (`TestEBSCOnet.xlsx`, not in the repo).

## Verified live (bugfest tenant, 2026-09-30)
Online imports (2, then 25, then 82 records: all 107 POs created with lines), P-E import
(2), a pure Print record, profile creation and update, account creation, ongoing
conversion (4 POs), live PO and PO-line delete with backup, POL export (112 lines),
retry helper, preflight on real files. Mock-tested only: the non-S3 upload path.

## Still to do
1. **Real values**: replace the TEST fund / expense class / org / location / material
   type in `ebsconet_config.json`; confirm the title-number source column against a real SOP.
2. **Real tenant**: run `pipeline/folio_preflight.py` first; check ledger "Restrict encumbrance" and
   budget allowable-encumbrance settings (they decide whether orders can later be opened);
   confirm Data Import permissions.
3. **Decide the remaining data rule**: repeated order numbers (handled by
   `folio_add_po_lines.py`, or suffixes). The "Usage Loading Service" lines (service fees,
   not journals) currently load as orders; `rules.exclude_usage_loading_service` leaves
   them out when you decide they should not.
4. **Test-tenant cleanup**: `folio_cleanup_test_pos.py` removes the ~115 test POs; the
   9 profiles, 3 accounts and the `test_ebsconet_*` finance / org / location records on
   bugfest still have no cleanup script.
5. Untested path: the non-S3 upload (only matters if the real tenant has file splitting off).
