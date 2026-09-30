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

## Pipeline (all built and tested)
| Step | Script | Notes |
|---|---|---|
| 1 | `ebsconet_prep.py` | Add fund / expense class / org columns, apply row rules, ISO dates, normalize URLs, split by format into Online / Print / P-E workbooks, highlight mapped columns, write report + exclusions log |
| 2 | `ebsconet_to_marc.py` | Build `.mrc` + `.mrk` from the workbooks; tag map read from `order_marc_headers.xlsx` |
| 3 | `folio_setup.py` | Accounts on the ebsconet org; per route a field mapping, action and job profile (built from templates in `template_profiles/`) |
| 4 | `folio_preflight.py` | Read-only checks of the file and tenant before a load |
| 5 | `folio_import.py` | Preflight, upload (S3 or local), run job profile, follow parent/child jobs, print log and POs |
| 6 | `folio_ongoing.py` | One-time -> Ongoing (interval 365, subscription, renewal date = latest subscription end) |
| - | `folio_retry_failed.py` | After a partial load: retry .mrc for records with no PO / an empty PO, plus a delete CSV for the empty POs |
| 7 | `folio_export_pols.py` | PO/POL numbers for the EBSCONET renewal integration (POL = PO + `-1`) |
| - | `folio_delete_orders.py` | Remove problem Pending POs / lines from a CSV, with backups |
| - | `folio_test_data.py` | Creates test ledger / funds / budgets / classes / org / location on a **test** tenant |

## Decisions that shaped the build
- **Tags follow `order_marc_headers.xlsx`**, not the instructions doc: 990$t (not $x)
  for the end date, 990$a (not $n) for the account, 264$a (not 260$a) for the publisher.
  Added by prep: 990$f fund, 990$e expense class, 990$v access provider, 990$i title
  number (= `Publisher Product Code`), 990$j title-number type.
- **Zero-cost rows are not loaded**; package members at $0, "Fee" and unrecognized
  formats are not loaded; single journals with no ISSN are not loaded; package rows
  (title has package / collection / suite, or equals the package name) load without an
  ISSN. See "Open data decisions" in the README.
- **Orders stay Pending.** The mapping profiles set `workflowStatus` to `"Pending"`;
  no script opens an order, and the preflight check refuses to load with a job profile
  whose mapping sets any other status. Budgets matter only for having an Active budget with the
  expense class attached (else lines are discarded), not for the amount.
- **Data Import makes one PO per record**, so two SOP rows with the same order number
  cannot become two lines on one PO (the second fails). Preflight reports it.
- **Fund / expense class / organization are matched by code** (proven on bugfest).
- **Extra line fields**: Descriptor + Frequency -> line Description; Cancellable
  (inverted) -> cancellation restriction. **Expense classes are optional**
  (`rules.use_expense_classes`).
- **Independent receiving** = `checkinItems: true`; create-inventory = None.
- Anonymized test spreadsheet (`TestEBSCOnet_adjusted.xlsx`, not in the repo).

## Verified live (bugfest tenant, 2026-09-30)
Online imports (2, then 25, then 82 records: all 107 POs created with lines), P-E import
(2), a pure Print record, profile creation and update, account creation, ongoing
conversion (4 POs), live PO and PO-line delete with backup, POL export (112 lines),
retry helper, preflight on real files. Mock-tested only: the non-S3 upload path.

## Still to do
1. **Real values**: replace the TEST fund / expense class / org / location / material
   type in `ebsconet_config.json`; confirm the title-number source column against a real SOP.
2. **Real tenant**: run `folio_preflight.py` first; check ledger "Restrict encumbrance" and
   budget allowable-encumbrance settings (they decide whether orders can later be opened);
   confirm Data Import permissions.
3. **Decide the data rules** listed in the README (no-ISSN rows, no-title-number rows,
   duplicate order numbers).
4. **Blank product ID**: Data Import leaves a blank entry on lines without a title number;
   it is removed only when `folio_ongoing.py` converts the PO.
5. **Test-tenant cleanup**: the ~115 test POs, 9 profiles, 3 accounts and the `test_ebsconet_*`
   finance / org / location records on bugfest (no cleanup script exists).
6. Untested path: the non-S3 upload (only matters if the real tenant has file splitting off).
