"""Prepare an EBSCONET SOP spreadsheet for FOLIO order migration.

Covers instruction steps 2-7: add FOLIO fund / expense class / org columns, flag and
exclude rows that should not load, convert dates to ISO, highlight the added
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
from openpyxl.worksheet.datavalidation import DataValidation

from pipeline import customer_settings

HIGHLIGHT = PatternFill("solid", start_color="FFFFCC", end_color="FFFFCC")
ROUTES = ("online", "print", "pe")


PIPELINE_CONFIG = Path(__file__).with_name("pipeline_config.json")


def merge(base, over):
    """Recursively merge dicts: values in `over` win; nested dicts are merged."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path):
    """The fixed, process-level settings (pipeline/pipeline_config.json) merged with the
    library's choices (`path`, normally ebsconet_config.json). The library file wins if
    both define a key."""
    with open(PIPELINE_CONFIG, encoding="utf-8") as fh:
        fixed = json.load(fh)
    with open(path, encoding="utf-8") as fh:
        return merge(fixed, json.load(fh))


def read_sop(path, all_sheets=False):
    """Return (headers, rows) where each row is a dict plus a '_row' sheet number.

    Reads the first sheet only (the SOP). With `all_sheets` it reads every data sheet, as in
    the customer workbook, skipping the Defaults and option-list sheets; headers are the
    union in first-seen order and, if more than one sheet has rows, `_row` is
    "<sheet>:<row>"."""
    wb = load_workbook(path, read_only=True, data_only=True)
    skip = {customer_settings.SETTINGS_SHEET, *customer_settings.LIST_SHEETS}
    prefix = customer_settings.LIST_PREFIX
    sheets = ([ws for ws in wb.worksheets
               if ws.title not in skip and not ws.title.startswith(prefix)]
              if all_sheets else wb.worksheets[:1])
    headers, rows, labelled = [], [], False
    for ws in sheets:
        it = ws.iter_rows(values_only=True)
        first = next(it, None)
        if first is None:
            continue
        names = [str(h).strip() if h is not None else "" for h in first]
        headers += [h for h in names if h not in headers]
        found = []
        for n, values in enumerate(it, start=2):
            if all(v is None or v == "" for v in values):
                continue
            row = dict(zip(names, values))
            row["_row"] = n
            found.append(row)
        if found and rows:
            labelled = True
        rows += [dict(r, _sheet=ws.title) for r in found]
    wb.close()
    for row in rows:
        sheet = row.pop("_sheet")
        if labelled:
            row["_row"] = "%s:%s" % (sheet, row["_row"])
    return headers, rows


def read_sops(paths):
    """Read one or more spreadsheets (the customer workbook, or the old electronic /
    physical / P-E files) as one. Headers are the union in first-seen order. With a single
    file and sheet `_row` is the sheet row number; otherwise it is "<sheet>:<row>" and,
    with several files, "<file name>:<row>" or "<file name>:<sheet>:<row>"."""
    paths = [paths] if isinstance(paths, (str, Path)) else list(paths)
    headers, rows = [], []
    for path in paths:
        h, r = read_sop(path, all_sheets=True)
        headers += [name for name in h if name not in headers]
        if len(paths) > 1:
            for row in r:
                row["_row"] = "%s:%s" % (Path(path).stem, row["_row"])
        rows += r
    return headers, rows


REQUIRED_COLUMNS = ("title", "issn", "format", "order_number", "cost")


def check_headers(headers, cfg):
    """Fail loudly if the SOP lacks a heading the pipeline cannot work without.

    `cfg["columns"]` maps each logical column to the SOP heading; a renamed heading would
    otherwise read as blank on every row. Fix it in pipeline_config.json."""
    missing = [(key, cfg["columns"][key]) for key in REQUIRED_COLUMNS
               if cfg["columns"][key] not in headers]
    if missing:
        raise ValueError(
            "SOP is missing required column heading(s): %s. Headings found: %s. If SOP "
            "renamed a heading, override it under `columns` in your ebsconet_config.json "
            "(keys are listed in pipeline/pipeline_config.json)." % (
                ", ".join("%r (%s)" % (h, k) for k, h in missing),
                ", ".join(repr(h) for h in headers if h)))


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


def code_value(row, column):
    """customer_value() for a drop-down of "CODE - Name" entries: just the code."""
    return customer_value(row, column).split(" - ", 1)[0].strip()


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


def customer_fields(route, cfg):
    """Names of the columns the customer fills in on the spreadsheet for `route`."""
    a = cfg["added_columns"]
    use_classes = cfg["rules"].get("use_expense_classes", True)
    return [a[key] for key in cfg["customer_columns"][route]
            if use_classes or key != "expense_class"]


def choice(value, choices):
    """The entry of `choices` that `value` matches ignoring case, spaces and hyphens
    ("one time" -> "One-Time"); None when it matches none."""
    def key(text):
        return re.sub(r"[^a-z0-9]", "", str(text).lower())
    for option in choices:
        if key(option) == key(value):
            return option
    return None


TERM_UNIT_DAYS = {"year": 365, "month": 365 / 12, "week": 7, "day": 1}


def term_days(value):
    """The SOP Term ("1 Year(s)", "15 Month(s)") in days, or None when it is blank, zero
    or not of that form."""
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*(year|month|week|day)", str(value or ""),
                     re.I)
    days = round(float(match.group(1)) * TERM_UNIT_DAYS[match.group(2).lower()]) \
        if match else 0
    return days or None


def order_settings(row, cfg):
    """(order type, interval in days or "", warnings) from the customer's columns on a
    spreadsheet line. A blank or unrecognised order type comes from the SOP Term: a line
    with a Term is Ongoing, renewing every Term, and a line with no Term is One-Time
    (the configured defaults apply only when the sheet has no Term column). A blank or
    bad interval on an Ongoing order gets the Term, else the default interval; a
    One-Time order carries no interval."""
    a, ong = cfg["added_columns"], cfg["ongoing"]
    where = "row %s" % row["_row"]
    warnings = []
    term_col = cfg["columns"].get("term")
    term = term_days(row.get(term_col)) if term_col in row else None
    fallback = (("Ongoing" if term else "One-Time") if term_col in row
                else ong["default_order_type"])
    given = customer_value(row, a["order_type"])
    order_type = choice(given, cfg["order_type_choices"]) if given else None
    if given and order_type is None:
        warnings.append("%s: %s '%s' is not one of %s; used %s" % (
            where, a["order_type"], given, " / ".join(cfg["order_type_choices"]),
            fallback))
    order_type = order_type or fallback
    if order_type == "One-Time":
        return order_type, "", warnings
    default_days = term or ong["interval_days"]
    text = customer_value(row, a["renewal_interval"])
    try:
        days = int(float(text)) if text else 0
    except ValueError:
        days = 0
    if days <= 0:
        if text:
            warnings.append("%s: %s '%s' is not a positive whole number of days; "
                            "used %d" % (where, a["renewal_interval"], text, default_days))
        days = default_days
    return order_type, days, warnings


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
    out[a["fund"]] = code_value(row, a["fund"]) or cfg["fund_by_route"][route]
    out[a["expense_class"]] = (
        code_value(row, a["expense_class"])
        or cfg["expense_class_by_subject"].get(
            str(row.get(c["subject"]) or "").strip(), cfg["default_expense_class"])
        if cfg["rules"].get("use_expense_classes", True) else "")
    out[a["org"]] = code_value(row, a["org"])
    out[a["order_type"]], out[a["renewal_interval"]] = "", ""
    out[a["order_type"]], out[a["renewal_interval"]], more = order_settings(row, cfg)
    warnings += more
    out[a["location"]] = out[a["material_type"]] = ""
    if route in ("print", "pe"):
        out[a["location"]] = customer_value(row, a["location"]) or cfg["folio"]["location"]
        out[a["material_type"]] = (customer_value(row, a["material_type"])
                                   or cfg["folio"]["physical_material_type"])
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


def fill_sheet(ws, columns, rows, highlight, validations=None):
    """validations: {column name: DataValidation}, applied down that column (and well
    below the last row, so the customer can add lines)."""
    ws.append(columns)
    for row in rows:
        ws.append([row.get(col) for col in columns])
    for name, validation in (validations or {}).items():
        if name in columns:
            letter = ws.cell(row=1, column=columns.index(name) + 1).column_letter
            validation.add("%s2:%s%d" % (letter, letter, max(ws.max_row, 1000)))
            ws.add_data_validation(validation)
    for idx, name in enumerate(columns, start=1):
        if name in highlight:
            ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = max(
                len(name) + 3, 14)
            for r in range(1, ws.max_row + 1):
                ws.cell(row=r, column=idx).fill = HIGHLIGHT


def write_workbook(path, columns, rows, highlight, validations=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    fill_sheet(ws, columns, rows, highlight, validations)
    wb.save(path)


def prepare(input_path, out_dir, cfg, headers_file=None):
    """Run the whole prep. `input_path` is one spreadsheet or a list of them (the
    electronic / physical / P-E files the customer returned). Returns a summary dict."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    headers, rows = read_sops(input_path)
    check_headers(headers, cfg)
    added = list(cfg["added_columns"].values())
    columns = headers + [name for name in added if name not in headers]
    highlight = set(added)                     # only the columns we add, not the SOP's
    a = cfg["added_columns"]
    all_fields = list(dict.fromkeys(f for r in ROUTES for f in customer_fields(r, cfg)))
    settings_rows = []

    routed = {r: [] for r in ROUTES}
    defaults_used = []
    blank_cells = []
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
        for field in customer_fields(route, cfg):   # customer column exists but is blank
            if field == a["renewal_interval"] and new[a["order_type"]] == "One-Time":
                continue                                 # no interval for a one-time order
            if field in headers and blank(row.get(field)):
                blank_cells.append(field)
                if not blank(new[field]):                # a blank stays blank: no default
                    defaults_used.append((row["_row"], field, new[field]))
        settings_rows.append((new.get(cfg["columns"]["order_number"]), route,
                              new[a["order_type"]], new[a["renewal_interval"]]))
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

    # What `finish` needs to convert each PO: one-time or ongoing, and
    # the renewal interval. A PO number on several lines keeps its first line's choice.
    chosen = {}
    for number, route, order_type, days in settings_rows:
        number = str(number).strip() if not blank(number) else ""
        if not number:
            continue
        if number in chosen and chosen[number][1:] != (order_type, days):
            warnings.append("order %s: lines disagree on order type / interval; "
                            "using the first (%s %s)" % ((number,) + chosen[number][1:]))
        chosen.setdefault(number, (route, order_type, days))
    with open(out_dir / "order_settings.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["order_number", "route", "order_type", "interval_days"])
        w.writerows((n,) + v for n, v in chosen.items())

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
    for field in all_fields:
        applies = sum(len(routed[r]) for r in ROUTES if field in customer_fields(r, cfg))
        if field in headers:
            blanks = blank_cells.count(field)
            lines.append("%s: customer column present; blank on %d of %d rows it applies "
                         "to (default used; see prep_defaults_used.csv)"
                         % (field, blanks, applies))
        else:
            lines.append("%s: no such column in the SOP; the config default was used "
                         "for all %d rows" % (field, applies))
    lines.append("Orders: %d ongoing, %d one-time (see order_settings.csv)"
                 % (sum(1 for v in chosen.values() if v[1] == "Ongoing"),
                    sum(1 for v in chosen.values() if v[1] == "One-Time")))
    lines.append("Order numbers on more than one line (kept as multi-line POs): %s"
                 % (", ".join(map(str, dupes)) or "none"))
    lines.append("Warnings: %d" % len(warnings))
    lines += ["  " + w for w in warnings]
    (out_dir / "prep_report.txt").write_text("\n".join(lines) + "\n",
                                             encoding="utf-8")
    return {"read": len(rows), "routed": {r: len(v) for r, v in routed.items()},
            "excluded": len(exclusions), "reasons": dict(reasons),
            "duplicate_orders": dupes, "warnings": warnings}


def customer_validations(route, cfg, lists=None):
    """Drop-down / number checks for the customer columns of a sheet. `lists` (from
    customer_settings.tenant_lists) supplies tenant-wide drop-downs for location and
    material type when the config does not restrict them."""
    a = cfg["added_columns"]
    fields = customer_fields(route, cfg)
    checks = {}
    if a["order_type"] in fields:
        dv = DataValidation(type="list", allow_blank=True, showDropDown=False,
                            formula1='"%s"' % ",".join(cfg["order_type_choices"]))
        dv.error, dv.errorTitle = ("Choose %s from the list."
                                   % " or ".join(cfg["order_type_choices"]),
                                   "Order type")
        dv.prompt, dv.promptTitle = ("Choose Ongoing or One-Time. If Ongoing, fill in "
                                     "the renewal interval in days.", "Order type")
        checks[a["order_type"]] = dv
    if a["renewal_interval"] in fields:
        dv = DataValidation(type="whole", operator="greaterThan", formula1="0",
                            allow_blank=True)
        dv.error, dv.errorTitle = ("Enter the renewal interval as a whole number of "
                                   "days, e.g. 365.", "Renewal interval")
        dv.prompt, dv.promptTitle = ("Days between renewals. Needed only when the "
                                     "order type is Ongoing.", "Renewal interval")
        checks[a["renewal_interval"]] = dv
    for key, sheet in (("org", "Organizations"), ("fund", "Funds"),
                       ("expense_class", "ExpenseClasses"), ("location", "Locations"),
                       ("material_type", "MaterialTypes")):
        options = cfg.get("customer_choices", {}).get(key) or []
        formula = ('"%s"' % ",".join(options) if options
                   else customer_settings.list_range(sheet, lists or {}))
        if a[key] in fields and formula:
            dv = DataValidation(type="list", allow_blank=True, showDropDown=False,
                                formula1=formula)
            dv.error, dv.errorTitle = "Choose a value from the list.", a[key]
            checks[a[key]] = dv
    for dv in checks.values():
        dv.showErrorMessage = dv.showInputMessage = True
    return checks


def prepare_for_customer(input_path, out_dir, cfg, lists=None):
    """Stage 1 of the workflow: the workbook that goes to the customer.

    Removes every zero-dollar line, splits the rest by format into an electronic, a
    physical and a print + electronic (P-E) sheet (a type with no lines gets no sheet)
    and adds the columns the customer fills in on each (highlighted light yellow; see
    `customer_columns` in the config: org, fund, expense class, order type and renewal
    interval on all three, plus location and material type on physical and P-E). The first
    sheet, Defaults, asks the library's setup questions (customer_settings); `lists` holds
    the options for its drop-downs (customer_settings.tenant_lists; fixed lists only if
    omitted). Writes <out_dir>/customer/<name>_for_customer.xlsx, a log of the removed
    lines and a log of the lines that belong on none of the sheets (Fee or unrecognised
    format). Everything else about the SOP is left untouched; the remaining rules are
    applied later, when the filled-in workbook comes back."""
    c = cfg["columns"]
    lists = lists if lists is not None else customer_settings.tenant_lists()
    headers, rows = read_sop(input_path)
    check_headers(headers, cfg)
    dropped = set(cfg.get("drop_columns", {}).get("names", []))
    needed = {c[k] for k in REQUIRED_COLUMNS} | {c["account"]}
    dropped -= needed
    dropped &= set(headers)
    headers = [h for h in headers if h not in dropped]

    kept = {r: [] for r in ROUTES}
    removed, unrouted = [], []
    for row in rows:
        if to_cost(row.get(c["cost"])) == 0:            # blank counts as zero dollars
            removed.append((row["_row"], row.get(c["title"]), row.get(c["order_number"]),
                            "Yes" if not blank(row.get(c["package"])) else "No"))
            continue
        route = route_for(row.get(c["format"]), cfg)
        if route in kept:
            a = cfg["added_columns"]
            # Suggest order type and interval from the SOP Term; the customer's own
            # entries are kept, and a One-Time line gets no interval.
            suggested = order_settings(row, cfg)[:2]
            if blank(row.get(a["order_type"])):
                row[a["order_type"]] = suggested[0]
            if blank(row.get(a["renewal_interval"])):
                row[a["renewal_interval"]] = (
                    suggested[1] if row[a["order_type"]] != "One-Time" else "")
            kept[route].append(row)
        else:
            unrouted.append((row["_row"], row.get(c["title"]), row.get(c["order_number"]),
                             row.get(c["format"]), "Fee" if route == "excluded"
                             else "Unrecognized format"))

    folder = Path(out_dir) / "customer"
    folder.mkdir(parents=True, exist_ok=True)
    stem = Path(input_path).stem
    target = folder / ("%s_for_customer.xlsx" % stem)
    wb = Workbook()
    wb.remove(wb.active)
    customer_settings.add_settings_sheets(wb, cfg, lists)
    sheets, fill_in = {}, {}
    for route in ROUTES:
        if not kept[route]:
            continue
        fields = customer_fields(route, cfg)
        columns = headers + [name for name in fields if name not in headers]
        name = cfg["customer_file_labels"][route]
        fill_sheet(wb.create_sheet(name, len(sheets) + 1), columns, kept[route], set(fields),
                   customer_validations(route, cfg, lists))
        sheets[route], fill_in[route] = name, fields
    wb.save(target)
    with open(folder / ("%s_zero_dollar_removed.csv" % stem), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_row", "title", "order_number", "in_a_package"])
        w.writerows(removed)
    with open(folder / ("%s_not_sent.csv" % stem), "w", newline="",
              encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sheet_row", "title", "order_number", "format", "reason"])
        w.writerows(unrouted)
    report = ["Stage 1: workbook for the customer", "Input: %s" % input_path,
              "Rows read: %d" % len(rows),
              "Zero-dollar lines removed: %d (%d in a package); listed in %s"
              % (len(removed), sum(1 for r in removed if r[3] == "Yes"),
                 "%s_zero_dollar_removed.csv" % stem),
              "Lines not sent (Fee or unrecognized format): %d; listed in %s"
              % (len(unrouted), "%s_not_sent.csv" % stem),
              "Columns dropped from the SOP (drop_columns): %d" % len(dropped),
              "Workbook: %s; first sheet %s (setup questions)" % (
                  target.name, customer_settings.SETTINGS_SHEET)]
    for route in ROUTES:
        if route in sheets:
            report.append("sheet %s: %d lines; customer fills in (highlighted): %s" % (
                sheets[route], len(kept[route]), ", ".join(fill_in[route])))
        else:
            report.append("%s: no lines; no sheet" % cfg["customer_file_labels"][route])
    (folder / ("%s_for_customer_report.txt" % stem)).write_text(
        "\n".join(report) + "\n", encoding="utf-8")
    return {"read": len(rows), "removed": len(removed), "unrouted": len(unrouted),
            "kept": sum(len(v) for v in kept.values()),
            "counts": {r: len(v) for r, v in kept.items()},
            "file": target, "sheets": sheets, "columns": fill_in}


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
