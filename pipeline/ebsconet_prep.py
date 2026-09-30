"""Prepare an EBSCONET SOP spreadsheet for FOLIO order migration.

Covers instruction steps 2-7: add FOLIO fund / expense class / org columns, flag and
exclude rows that should not load, convert dates to ISO, highlight the mapped
columns and split the remainder into online / print / print+electronic workbooks.
"""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill

HIGHLIGHT = PatternFill("solid", start_color="FFFF00", end_color="FFFF00")
ROUTES = ("online", "print", "pe")


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_sop(path):
    """Return (headers, rows) where each row is a dict plus a '_row' sheet number."""
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    headers = [str(h).strip() if h is not None else "" for h in next(it)]
    rows = []
    for n, values in enumerate(it, start=2):
        if all(v is None or v == "" for v in values):
            continue
        row = dict(zip(headers, values))
        row["_row"] = n
        rows.append(row)
    wb.close()
    return headers, rows


def read_mapped_columns(headers_file):
    """SOP columns that the order_marc_headers file maps to a MARC tag."""
    if not headers_file or not Path(headers_file).exists():
        return []
    wb = load_workbook(headers_file, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    tags, names = list(ws.iter_rows(min_row=1, max_row=2, values_only=True))
    wb.close()
    return [n for t, n in zip(tags, names)
            if n and t and str(t).strip().lower() != "ignore"]


def to_iso(value):
    """Convert MM/DD/YYYY (or a date/datetime) to YYYY-MM-DD; None if unparseable."""
    if value is None or value == "":
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_url(value):
    """Lowercase the scheme and host (FOLIO rejects 'HTTP://WWW.X.ORG'); keep the
    path and query as they are. Values without a scheme are only stripped."""
    if blank(value):
        return ""
    text = str(value).strip()
    parts = urlsplit(text)
    if not parts.scheme or not parts.netloc:
        return text
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       parts.query, parts.fragment))


def customer_value(row, column):
    """The customer's own value from a SOP column, or '' when blank or absent."""
    value = row.get(column)
    return "" if blank(value) else str(value).strip()


def cancellation_restriction(cancellable):
    """SOP 'Cancellable' Yes/No -> FOLIO cancellationRestriction (inverted): a title
    that is not cancellable is restricted. Anything else is left blank."""
    text = str(cancellable or "").strip().lower()
    return {"yes": "false", "no": "true"}.get(text, "")


def line_description(descriptor, frequency, separator):
    """Descriptor and Frequency joined into one line description; empty values and
    'Not Applicable' are left out."""
    parts = [str(v).strip() for v in (descriptor, frequency)
             if not blank(v) and str(v).strip().lower() != "not applicable"]
    return separator.join(parts)


def to_cost(value):
    if value is None or value == "":
        return 0.0
    try:
        return float(str(value).replace(",", "").replace("$", ""))
    except ValueError:
        return None


def blank(value):
    return value is None or str(value).strip() == ""


def route_for(fmt, cfg):
    """Return 'online' | 'print' | 'pe', 'excluded' or None (unrecognized)."""
    key = str(fmt or "").strip().lower()
    if key in cfg["excluded_formats"]:
        return "excluded"
    for route in ROUTES:
        if key in cfg["format_routes"][route]:
            return route
    return None


def is_package_member(row, cfg):
    """Row belongs to a package (Publisher Package filled)."""
    return not blank(row.get(cfg["columns"]["package"]))


def is_package(row, cfg):
    """Row IS a package purchase: title has a package keyword or equals the package name."""
    c = cfg["columns"]
    title = str(row.get(c["title"]) or "").strip().lower()
    name = str(row.get(c["package"]) or "").strip().lower()
    pattern = r"\b(%s)\b" % "|".join(map(re.escape, cfg["package_title_keywords"]))
    return bool(re.search(pattern, title)) or (title != "" and title == name)


def is_usage_loading_service(row, cfg):
    """EBSCONET 'Usage Loading Service - <platform>' lines (service fees, not titles)."""
    title = str(row.get(cfg["columns"]["title"]) or "").strip().lower()
    return title.startswith(cfg["usage_loading_service_prefix"].lower())


def classify(row, cfg):
    """Return (route, reason). route is None when the row is excluded."""
    c = cfg["columns"]
    rules = cfg["rules"]
    route = route_for(row.get(c["format"]), cfg)
    if route == "excluded":
        return None, "Excluded format: %s" % row.get(c["format"])
    if route is None:
        return None, "Unrecognized format: %s" % row.get(c["format"])
    if rules.get("exclude_usage_loading_service") and is_usage_loading_service(row, cfg):
        return None, "Usage Loading Service"
    cost = to_cost(row.get(c["cost"]))
    if cost is None:
        return None, "Unparseable cost: %s" % row.get(c["cost"])
    if (rules["exclude_zero_cost_package_members"] and is_package_member(row, cfg)
            and cost == 0):
        return None, "Package member at zero cost"
    if rules["exclude_zero_cost"] and cost == 0:
        return None, "Zero cost"
    if rules["skip_missing_issn"] and blank(row.get(c["issn"])):
        if not (rules["exempt_costed_packages_from_issn_skip"]
                and is_package(row, cfg)):
            return None, "Missing ISSN"
    return route, ""


def enrich(row, route, cfg):
    """Return a copy of row with the added FOLIO columns and ISO dates."""
    c, a = cfg["columns"], cfg["added_columns"]
    out = dict(row)
    warnings = []
    for col in cfg["date_columns"]:
        if col in out and not blank(out[col]):
            iso = to_iso(out[col])
            if iso is None:
                warnings.append("row %s: unparseable %s '%s'"
                                % (row["_row"], col, out[col]))
                iso = ""
            out[col] = iso
    if c["url"] in out:
        out[c["url"]] = normalize_url(out[c["url"]])
    out[a["cancellation_restriction"]] = cancellation_restriction(
        row.get(c["cancellable"]))
    out[a["po_line_description"]] = line_description(
        row.get(c["descriptor"]), row.get(c["frequency"]), cfg["description_separator"])
    # FOLIO Fund / Expense Class / Org are filled in by the customer line by line in the
    # SOP; a blank cell (or a missing column) falls back to the config defaults.
    out[a["fund"]] = customer_value(row, a["fund"]) or cfg["fund_by_route"][route]
    out[a["expense_class"]] = (
        customer_value(row, a["expense_class"])
        or cfg["expense_class_by_subject"].get(
            str(row.get(c["subject"]) or "").strip(), cfg["default_expense_class"])
        if cfg["rules"].get("use_expense_classes", True) else "")
    out[a["org"]] = customer_value(row, a["org"]) or cfg["org_by_publisher"].get(
        str(row.get(c["publisher"]) or "").strip(), cfg["default_org"])
    out[a["package_flag"]] = "Yes" if is_package(row, cfg) else "No"
    tn = row.get(c["title_number_source"])
    out[a["title_number"]] = "" if blank(tn) else str(tn).strip()
    out[a["generated_id"]] = "No"
    out[a["title_number_type"]] = ("" if blank(tn)
                                   else cfg["folio"]["title_number_type"])
    # No ISSN and no title number: generate an identifier from the EBSCONET order number
    # so the line still carries one (it goes in the title-number product ID).
    order = row.get(c["order_number"])
    if blank(tn) and blank(row.get(c["issn"])) and not blank(order):
        gen = cfg["generated_id"]
        out[a["title_number"]] = gen["prefix"] + str(order).strip()
        out[a["title_number_type"]] = gen["type"]
        out[a["generated_id"]] = "Yes"
    return out, warnings


def write_workbook(path, columns, rows, highlight):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(columns)
    for row in rows:
        ws.append([row.get(col) for col in columns])
    for idx, name in enumerate(columns, start=1):
        if name in highlight:
            for r in range(1, ws.max_row + 1):
                ws.cell(row=r, column=idx).fill = HIGHLIGHT
    wb.save(path)


def prepare(input_path, out_dir, cfg, headers_file=None):
    """Run the whole prep. Returns a summary dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    headers, rows = read_sop(input_path)
    added = list(cfg["added_columns"].values())
    columns = headers + [name for name in added if name not in headers]
    highlight = set(read_mapped_columns(headers_file)) | set(added)
    highlight.add(cfg["columns"]["format"])
    a = cfg["added_columns"]
    customer_fields = [a["fund"], a["org"]]
    if cfg["rules"].get("use_expense_classes", True):
        customer_fields.append(a["expense_class"])

    routed = {r: [] for r in ROUTES}
    defaults_used = []
    no_issn = []
    exclusions = []
    warnings = []
    for row in rows:
        route, reason = classify(row, cfg)
        if route is None:
            exclusions.append((row["_row"], row.get(cfg["columns"]["title"]), reason))
            continue
        new, warn = enrich(row, route, cfg)
        warnings.extend(warn)
        for field in customer_fields:            # a customer column exists but is blank
            if field in headers and blank(row.get(field)):
                defaults_used.append((row["_row"], field, new[field]))
        if blank(row.get(cfg["columns"]["issn"])):
            no_issn.append((row["_row"], new.get(cfg["columns"]["order_number"]),
                            row.get(cfg["columns"]["title"]),
                            to_cost(row.get(cfg["columns"]["cost"])), route,
                            new[cfg["added_columns"]["title_number"]],
                            new[cfg["added_columns"]["generated_id"]]))
        routed[route].append(new)

    for route in ROUTES:
        write_workbook(out_dir / cfg["output_names"][route], columns,
                       routed[route], highlight)

    with open(out_dir / "prep_exclusions.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_row", "title", "reason"])
        w.writerows(exclusions)

    by_row = {r["_row"]: to_cost(r.get(cfg["columns"]["cost"])) for r in rows}
    with open(out_dir / "prep_no_issn.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_row", "order_number", "title", "cost", "route",
                    "identifier_used", "identifier_generated"])
        w.writerows(no_issn)

    with open(out_dir / "prep_defaults_used.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_row", "column", "default_used"])
        w.writerows(defaults_used)

    order_col = cfg["columns"]["order_number"]
    counts = Counter(r.get(order_col) for rs in routed.values() for r in rs)
    dupes = sorted(k for k, v in counts.items() if v > 1 and k)
    reasons = Counter(reason for _, _, reason in exclusions)

    lines = ["EBSCONET prep report", "Input: %s" % input_path,
             "Rows read: %d" % len(rows),
             "Rows loadable: %d" % sum(len(v) for v in routed.values())]
    lines += ["  %s: %d -> %s" % (r, len(routed[r]), cfg["output_names"][r])
              for r in ROUTES]
    lines.append("Rows excluded: %d" % len(exclusions))
    lines += ["  %s: %d" % kv for kv in sorted(reasons.items())]
    costed = [(r, t, why) for r, t, why in exclusions
              if by_row[r] and why != "Package member at zero cost"]
    lines.append("Removed rows with a non-zero cost (review): %d" % len(costed))
    lines += ["  row %s: %s -- %s (cost %s)" % (r, t, why, by_row[r])
              for r, t, why in costed]
    lines.append("Rows loaded WITHOUT an ISSN (see prep_no_issn.csv): %d (%d with a real "
                 "title number, %d with a generated identifier)" % (
                     len(no_issn), sum(1 for r in no_issn if r[6] == "No" and r[5]),
                     sum(1 for r in no_issn if r[6] == "Yes")))
    loaded = sum(len(v) for v in routed.values())
    for field in customer_fields:
        if field in headers:
            blanks = sum(1 for d in defaults_used if d[1] == field)
            lines.append("%s: customer column present; blank on %d of %d loaded rows "
                         "(default used; see prep_defaults_used.csv)" % (field, blanks, loaded))
        else:
            lines.append("%s: no such column in the SOP; the config default was used "
                         "for all %d rows" % (field, loaded))
    lines.append("Order numbers on more than one line (kept as multi-line POs): %s"
                 % (", ".join(map(str, dupes)) or "none"))
    lines.append("Warnings: %d" % len(warnings))
    lines += ["  " + w for w in warnings]
    (out_dir / "prep_report.txt").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")
    return {"read": len(rows), "routed": {r: len(v) for r, v in routed.items()},
            "excluded": len(exclusions), "reasons": dict(reasons),
            "duplicate_orders": dupes, "warnings": warnings}


def prepare_for_customer(input_path, out_dir, cfg):
    """Stage 1 of the workflow: the spreadsheet that goes to the customer.

    Removes every zero-dollar line, adds the columns the customer fills in line by line
    (FOLIO Org, FOLIO Fund and, if used, FOLIO Expense Class; highlighted yellow) and
    writes <out_dir>/customer/<name>_for_customer.xlsx plus a log of the removed lines.
    Everything else about the SOP is left untouched; the remaining rules (formats, Fee
    rows, ...) are applied later, when the filled-in spreadsheet comes back."""
    c, a = cfg["columns"], cfg["added_columns"]
    headers, rows = read_sop(input_path)
    customer_cols = [a["org"], a["fund"]]
    if cfg["rules"].get("use_expense_classes", True):
        customer_cols.append(a["expense_class"])
    columns = headers + [name for name in customer_cols if name not in headers]

    kept, removed = [], []
    for row in rows:
        if to_cost(row.get(c["cost"])) == 0:            # blank counts as zero dollars
            removed.append((row["_row"], row.get(c["title"]), row.get(c["order_number"]),
                            "Yes" if not blank(row.get(c["package"])) else "No"))
        else:
            kept.append(row)

    folder = Path(out_dir) / "customer"
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(input_path).stem
    target = folder / ("%s_for_customer.xlsx" % stem)
    write_workbook(target, columns, kept, set(customer_cols))
    with open(folder / ("%s_zero_dollar_removed.csv" % stem), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_row", "title", "order_number", "in_a_package"])
        w.writerows(removed)
    report = ["Stage 1: spreadsheet for the customer", "Input: %s" % input_path,
              "Rows read: %d" % len(rows),
              "Zero-dollar lines removed: %d (%d in a package); listed in %s"
              % (len(removed), sum(1 for r in removed if r[3] == "Yes"),
                 "%s_zero_dollar_removed.csv" % stem),
              "Lines for the customer: %d" % len(kept),
              "Columns for the customer to fill in (highlighted): %s"
              % ", ".join(customer_cols),
              "Send: %s" % target.name]
    (folder / ("%s_for_customer_report.txt" % stem)).write_text(
        "\n".join(report) + "\n", encoding="utf-8")
    return {"read": len(rows), "removed": len(removed), "kept": len(kept),
            "file": target, "columns": customer_cols}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", help="EBSCONET SOP .xlsx")
    p.add_argument("--config", default="ebsconet_config.json")
    p.add_argument("--out", default="out")
    p.add_argument("--headers", help="order_marc_headers.xlsx (default from config)")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    summary = prepare(args.input, args.out, cfg, args.headers or cfg["headers_file"])
    print(Path(args.out, "prep_report.txt").read_text(encoding="utf-8"))
    return summary


if __name__ == "__main__":
    main()
