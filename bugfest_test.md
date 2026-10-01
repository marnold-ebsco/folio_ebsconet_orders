# Bugfest test report - 2026-10-01

Bugfest (kong-bugfest-sunflower, tenant fs09000000) was reachable; login returned 201 (earlier checks: 503).

## Results (tests run once)
- EBSCOnet pytest: 188 passed. flake8: clean.
- folio_orders pytest: 90 passed.
- ebsconet vs bugfest (dry runs only, nothing written):
  - `setup`: accounts and the mapping/action/job profiles for Online, Print and P-E all exist.
  - `load` preflight (out/three_type_test): online 135 records, print 3, pe 2; 0 errors. Warnings only: records without ISSN (020$a) and without title number (990$i), expected per the no-ISSN rule.
  - `finish`: 140 PO numbers, "not-found: 106, skipped: 34" - expected, the test POs were deleted from bugfest earlier.

## Problems
- folio_orders: flake8 reports 133 issues, all E501 (line > 79 chars). That repo has no .flake8 config (EBSCOnet's sets its own limit). No functional impact; consider adding a max-line-length config.
- phpFolioClient2 not tested (not used).
