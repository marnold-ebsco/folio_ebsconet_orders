# EBSCOnet orders: quick start (spreadsheet to finished POs)

This file is copied to the top of the install folder (`/working/migration/scripts/ebsconet`)
by `install.sh`. Edit it in the repo (`QUICKSTART.md`), not on the server: every upgrade
replaces it. Full detail is in `app/RUNBOOK.md`.

Everything below runs from the `work/` folder. Nothing is written to FOLIO unless a
command says `--live`.

```bash
cd /working/migration/scripts/ebsconet/work
```

`TENANT.ini` below means your filled-in copy of `sample.ini` (never commit or share it).

## 0. One-time setup per tenant (skip if already done)

1. Make the connection file and fill it in:
   ```bash
   cp sample.ini TENANT.ini
   ```
2. Build `ebsconet_config.json` from the tenant's real codes (read-only against FOLIO):
   ```bash
   ebsconet-configure --ini TENANT.ini
   ```
3. In FOLIO, check that the EBSCOnet vendor organization, the access-provider
   organizations (marked as vendors), the funds (Active, with an Active budget that lists
   the expense classes), and the locations / material types exist.

## 1. Receive the SOP spreadsheet and prepare the customer copy

1. Copy the SOP `.xlsx` into `work/`.
2. Build the customer workbook (`--ini` fills the drop-downs from the tenant):
   ```bash
   ebsconet for-customer SOP.xlsx --ini TENANT.ini
   ```
3. Read `out/customer/<name>_for_customer_report.txt`. Skim
   `out/customer/<name>_zero_dollar_removed.csv` and `out/customer/<name>_not_sent.csv`.
4. Send the customer `out/customer/<name>_for_customer.xlsx`. They fill in the yellow
   columns on every line (Access Provider, Fund, Expense Class, Order Type, Renewal
   Interval, and Location / Material Type on physical and P-E) and the **Defaults** sheet.

## 2. Customer returns the filled-in workbook

1. Copy it into `work/` (example name: `FILLED.xlsx`).
2. Save the Defaults sheet answers into the config (`load` reads the config, not the workbook):
   ```bash
   ebsconet-configure --from-worksheet FILLED.xlsx
   ```
3. Build the order files:
   ```bash
   ebsconet build FILLED.xlsx
   ```
4. Read `out/prep_report.txt`. Check `out/prep_defaults_used.csv` (blank cells that fell
   back to defaults), `out/prep_exclusions.csv` (rows left out) and `out/prep_no_issn.csv`
   (rows loaded without an ISSN; every row is still loaded).

## 3. Dry run, then fix errors

```bash
ebsconet load --ini TENANT.ini
```

Every PO gets a status: `dry-run` is good; `invalid` and `lookup-failed` are not. Send
the list to the customer (or fix the tenant setup), get a corrected workbook, and repeat
section 2 steps 2-3 and this dry run until there are no `invalid` or `lookup-failed` POs.

## 4. Load for real

```bash
ebsconet load --ini TENANT.ini --live
```

- POs are created **Pending**. Vendor accounts are added first.
- A bad PO does not stop the others, but the command exits 1. Fix the cause and run the
  same command again: POs that already exist are skipped.
- Logs: `out/logs/accounts_<time>.txt` and `out/logs/load_<time>.txt` (plus `.csv`).
- In FOLIO, spot-check a few PO numbers in Orders (status, order type, vendor, fund,
  expense class, price, location, account number).

## 5. Hand off to EBSCOnet

```bash
ebsconet finish --ini TENANT.ini --live
```

Send `out/pol_export.csv` to EBSCOnet. The POL number is the PO number plus `-1`; a line
not ending in `-1` is flagged `NO - line N` for you to sort out by hand.

## Backup route and troubleshooting

- If the Orders API load cannot be used, add `--use-marc` to `load` and `finish`
  (MARC / Data Import; see `app/RUNBOOK.md`, "Backup route").
- Run `ebsconet` from `work/`; it reads the config and `.ini` files from the current folder.
- `ebsconet --help` lists every subcommand and option.

## Updating this install

Always pass the absolute `--dir`. Without it the installer creates a nested
`ebsconet/ebsconet` copy and re-points the `ebsconet` command at it.

```bash
curl -fsSL https://raw.githubusercontent.com/marnold-ebsco/folio_ebsconet_orders/main/install.sh | bash -s -- --dir /working/migration/scripts/ebsconet
```

`work/` (config, `.ini` files, `out/`) is left alone. Add `--check` to see whether an
update exists without changing anything.
