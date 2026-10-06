# CLAUDE.md

Guidance for Claude Code in this repo (EBSCOnet -> FOLIO orders pipeline;
GitHub: `marnold-ebsco/folio_ebsconet_orders`).

## Read first, every new or cleared session

Read `HANDOFF.md` in this folder before doing anything else. It holds current
state, what is done, and NEXT steps. Before the user clears or ends a session,
update `HANDOFF.md` without being asked.

Other docs: `RUNBOOK.md` (operating procedure), `README.md` (install and usage),
`README_API.md`, `README_DATA_IMPORT.md`, `PLAN.md`.

The API loader (`folio_orders_loader`) is a separate project with its own handoff at
`~/scratch/folio_orders/HANDOFF.md`. Only use it when the user says so.

## Running things

- Work in WSL (`~/scratch/EBSCOnet`), not on the Windows side.
- Tests: `.venv/bin/python -m pytest -q`
- Python 3.12+, pytest, flake8. Use `FolioClient` (FOLIO-FSE) for FOLIO access.
- Config: copy `sample.ini` to `TENANT.ini`. Never commit a filled-in `.ini`; it
  holds live tenant credentials.

## Deploying to the EC2

`install.sh` installs what is on GitHub, so push first. Re-running it upgrades in
place: `app/` is replaced, `work/` (config, `.ini` files, `out/`) is left alone.
Run it from the folder that contains `ebsconet`:

    curl -fsSL https://raw.githubusercontent.com/marnold-ebsco/folio_ebsconet_orders/main/install.sh | bash -s --

Options: `--check` (report only), `--dir PATH` (reuse the original value),
`--recreate-venv`, `--ref REF`. See "Installing on a server" in `README.md`.

## Rules

- Load every row; log rows without an ISSN, never skip them.
- Don't use shell heredocs with backticks to write docs; use Edit/Write.
