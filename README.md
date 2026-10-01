# EBSCONET SOP -> FOLIO (Sunflower) order migration

Tools that turn an EBSCONET SOP spreadsheet into FOLIO purchase orders and produce the
PO / POL list EBSCONET needs. Pick the guide for the way you load orders:

- [README_API.md](README_API.md): load orders through the Orders API.
- [README_DATA_IMPORT.md](README_DATA_IMPORT.md): load orders through MARC files and Data Import.

Also: [RUNBOOK.md](RUNBOOK.md) (start-to-finish checklist), [PLAN.md](PLAN.md) (design and
status), [docs/CLIENT_GUIDE.md](docs/CLIENT_GUIDE.md) (plain-language guide for the customer).

## Installing on a server without cloning the repo
`packaging/make_bundle.sh` (run on the dev machine) builds `dist/ebsconet-<version>.tar.gz`: the
committed code plus a wheelhouse of all dependencies, including `folio_orders_loader`. On the
server (Python 3.12+, no git or SSH key needed):
`tar xzf ebsconet-<version>.tar.gz && ebsconet-<version>/install.sh [--prefix DIR]`. It installs
to `~/ebsconet` (`app/`, `venv/`, `work/`) and links `ebsconet` into `~/.local/bin`. Re-running
upgrades the code and leaves `work/` (config, `.ini` files, `out/`) untouched. Commit before
building: the bundle is made from `HEAD`.
