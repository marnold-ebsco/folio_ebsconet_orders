# EBSCONET SOP -> FOLIO (Sunflower) order migration

Tools that turn an EBSCONET SOP spreadsheet into FOLIO purchase orders and produce the
PO / POL list EBSCONET needs. Pick the guide for the way you load orders:

- [README_API.md](README_API.md): load orders through the Orders API.
- [README_DATA_IMPORT.md](README_DATA_IMPORT.md): load orders through MARC files and Data Import.

Also: [RUNBOOK.md](RUNBOOK.md) (start-to-finish checklist), [PLAN.md](PLAN.md) (design and
status), [docs/CLIENT_GUIDE.md](docs/CLIENT_GUIDE.md) (plain-language guide for the customer).

## Installing on a server
`install.sh` fetches the committed code (pinned to one commit SHA) and the pinned
`folio_orders_loader` straight from GitHub, so the server needs only curl, tar and Python 3.12+
(no git, SSH key or clone). Both repos are public, so no token is needed (unauthenticated GitHub
API calls are limited to 60 per hour per IP). If they are made private again, set `GITHUB_TOKEN`
to a token with read access to both; the installer sends it automatically.

Run it from the folder you want to install under. This creates `./ebsconet` there:

```
curl -fsSL https://raw.githubusercontent.com/marnold-ebsco/folio_ebsconet_orders/main/install.sh | bash -s --
```

To install directly into the current folder instead of a subfolder:

```
curl -fsSL https://raw.githubusercontent.com/marnold-ebsco/folio_ebsconet_orders/main/install.sh | bash -s -- --dir .
```

Any other option can be added after `--` (list below).

Options: `--dir PATH` (default `./ebsconet` under the directory you run it from; `--dir .` installs directly into it), `--python NAME`, `--ref REF` (branch or tag),
`--recreate-venv`, `--check` (report whether an update exists, change nothing). It installs
`app/`, `venv/` and `work/` and links `ebsconet` into `~/.local/bin`. Re-running upgrades the
code and leaves `work/` (config, `.ini` files, `out/`) untouched. Push before installing: it
installs what is on GitHub.

`install.sh` also adds `~/.local/bin` to `PATH` (in `~/.bashrc` and `~/.profile`, once) when it is
missing; run `source ~/.bashrc` or open a new shell afterwards. The `ebsconet` command wrapper
embeds the absolute install path (`--dir .` is resolved), but it reads `ebsconet_config.json`, the
`.ini` file, the SOP workbook and `out/` relative to your **current folder**, so always run it from
`work/`:

```
cd <install dir>/work
ebsconet for-customer SOP.xlsx     # SOP.xlsx in work/, or give a full path
```

If you installed with an older `install.sh` and the wrapper holds `./venv` / `./app` paths, re-run
the installer (it rewrites the wrapper). `FileNotFoundError: ebsconet_config.json` means you are
not in `work/`.

Before sending files to a customer, run `ebsconet-configure` from `work/`: it reads the tenant's
real funds, expense classes, organizations, locations, material types and acquisition methods
and writes `work/ebsconet_config.json` for you (see `README_API.md`).

To ship a new `folio_orders_loader`: bump its version and tag, change the pin in
`requirements.txt`, push, and re-run `install.sh` on the server. The installer always
force-reinstalls the loader, so its new code lands even if the version is unchanged.
