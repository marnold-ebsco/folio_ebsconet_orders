"""Shared FOLIO helpers: read a tenant .ini file and build a FolioClient."""
import ssl
from pathlib import Path

from folioclient import FolioClient


def read_ini(path):
    """Parse the simple 'key = value' tenant files (see sample.ini in the PHP client).

    Blank lines, ';'/'#' comments and [section] headers are ignored; surrounding
    quotes and stray carriage returns are stripped from values.
    """
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line[0] in ";#[" or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def ssl_setting(value):
    """sslVerify may be true/false or the path of a CA bundle."""
    if value is None or str(value).strip().lower() in ("", "true", "1", "yes"):
        return True
    if str(value).strip().lower() in ("false", "0", "no"):
        return False
    if Path(value).exists():
        return ssl.create_default_context(cafile=value)
    return True


def connect(ini_path):
    """Return a FolioClient for the tenant described by ini_path."""
    ini = read_ini(ini_path)
    missing = [k for k in ("okapiUrl", "tenant_id", "username", "password")
               if not ini.get(k)]
    if missing:
        raise ValueError("%s is missing: %s" % (ini_path, ", ".join(missing)))
    return FolioClient(ini["okapiUrl"], ini["tenant_id"], ini["username"],
                       ini["password"], ssl_verify=ssl_setting(ini.get("sslVerify")))


# The orders "purchase order lines limit" setting (how many lines one PO may hold) lives
# in the ORDERS module configuration. Bugfest names it poLines-limit; other
# environments use order_lines_limit, so both are tried. FOLIO's default is 1.
LINES_LIMIT_NAMES = ("poLines-limit", "order_lines_limit")
DEFAULT_LINES_LIMIT = 1


def order_lines_limit(client, names=LINES_LIMIT_NAMES):
    """Return (limit, where) for the tenant's PO-lines-per-PO limit.

    `limit` is an int, or None when the setting could not be read; `where` says which
    setting name supplied it (or that the default applies)."""
    try:
        for name in names:
            found = client.folio_get("/configurations/entries", query_params={
                "query": "(module==ORDERS and configName==%s)" % name, "limit": 5})
            for entry in (found or {}).get("configs", []):
                try:
                    return int(str(entry.get("value")).strip()), name
                except ValueError:
                    continue
    except Exception as exc:  # the setting is advisory; never block on it
        return None, "could not read the setting (%s)" % type(exc).__name__
    return DEFAULT_LINES_LIMIT, "no setting found; FOLIO default"
