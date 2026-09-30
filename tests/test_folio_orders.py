import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import folio_common  # noqa: E402
from pipeline import folio_export_pols as exp  # noqa: E402
from pipeline import folio_ongoing as ong  # noqa: E402
from pipeline.ebsconet_prep import load_config  # noqa: E402


class FakeClient:
    def __init__(self, orders=None, lines=None):
        self.orders = orders or {}      # poNumber -> composite order
        self.lines = lines or []
        self.puts = []
        self.queries = []

    def folio_get(self, path, key=None, query="", **kw):
        if path == "/orders/composite-orders":
            po = query.split('"')[1]
            found = self.orders.get(po)
            return [{"id": found["id"]}] if found else []
        return next(o for o in self.orders.values() if path.endswith(o["id"]))

    def folio_get_all(self, path, key=None, query=None, **kw):
        self.queries.append(query)
        prefix = query.split('"')[1].rstrip("*")
        return [ln for ln in self.lines if ln["poLineNumber"].startswith(prefix)]

    def folio_put(self, path, payload, **kw):
        self.puts.append((path, payload))


def order(po="U1", status="Pending", otype="One-Time", ends=("2026-12-31T00:00:00.000+00:00",)):
    return {"id": "id-" + po, "poNumber": po, "workflowStatus": status,
            "orderType": otype,
            "compositePoLines": [{"details": {"subscriptionTo": d}} for d in ends]}


@pytest.fixture
def settings():
    return load_config(ROOT / "ebsconet_config.json")["ongoing"]


def test_defaults_documented_values(settings):
    assert settings == {"default_order_type": "Ongoing",
                        "interval_days": 365, "is_subscription": True,
                        "manual_renewal": False,
                        "renewal_date_source": "latest_subscription_to"}


def test_build_ongoing(settings):
    o = order(ends=("2026-06-30T00:00:00.000+00:00", "2026-12-31T00:00:00.000+00:00"))
    new = ong.build_ongoing(o, settings)
    assert new["orderType"] == "Ongoing"
    assert new["ongoing"] == {"interval": 365, "isSubscription": True,
                              "manualRenewal": False,
                              "renewalDate": "2026-12-31T00:00:00.000+00:00"}
    assert o["orderType"] == "One-Time"          # original untouched


def test_build_ongoing_drops_empty_product_ids(settings):
    o = order()
    o["compositePoLines"][0]["details"]["productIds"] = [
        {"productId": "1234-5678", "productIdType": "t"}, {}, {"productIdType": "t"}]
    new = ong.build_ongoing(o, settings)
    assert new["compositePoLines"][0]["details"]["productIds"] == [
        {"productId": "1234-5678", "productIdType": "t"}]
    assert len(o["compositePoLines"][0]["details"]["productIds"]) == 3   # untouched
    assert new["compositePoLines"][0]["details"]["subscriptionTo"]      # rest kept


def test_renewal_date_sources():
    o = order(ends=("2026-06-30", "2026-12-31"))
    assert ong.renewal_date(o, "earliest_subscription_to") == "2026-06-30"
    assert ong.renewal_date(o, "none") is None
    assert ong.renewal_date(order(ends=()), "latest_subscription_to") is None


def test_convert_po_dry_run_does_not_put(settings):
    c = FakeClient({"U1": order()})
    assert ong.convert_po(c, "U1", settings, live=False)[0] == "dry-run"
    assert c.puts == []


def test_convert_po_live_puts(settings):
    c = FakeClient({"U1": order()})
    assert ong.convert_po(c, "U1", settings, live=True)[0] == "converted"
    path, payload = c.puts[0]
    assert path == "/orders/composite-orders/id-U1"
    assert payload["orderType"] == "Ongoing"


@pytest.mark.parametrize("o,expect", [
    (order(otype="Ongoing"), "already Ongoing"),
    (order(status="Open"), "status is Open, not Pending")])
def test_convert_po_skips(settings, o, expect):
    c = FakeClient({"U1": o})
    status, note = ong.convert_po(c, "U1", settings, live=True)
    assert (status, note) == ("skipped", expect)
    assert c.puts == []


def test_convert_all_not_found_and_errors(settings):
    c = FakeClient({"U1": order()})
    res = ong.convert_all(c, ["U1", "NOPE", 'BAD"'], settings, live=False)
    assert [r[1] for r in res] == ["dry-run", "not-found", "error"]


def test_read_po_numbers_header_and_plain(tmp_path):
    a = tmp_path / "a.csv"
    a.write_text("Name,PO number\nx,U1\ny,U2\nz,U1\n", encoding="utf-8")
    assert ong.read_po_numbers(a) == ["U1", "U2"]
    b = tmp_path / "b.csv"
    b.write_text("U1\nU2\n\n", encoding="utf-8")
    assert ong.read_po_numbers(b) == ["U1", "U2"]


def test_write_log(tmp_path):
    ong.write_log(tmp_path / "l.csv", [("U1", "converted", "n")])
    rows = list(csv.reader(open(tmp_path / "l.csv", encoding="utf-8")))
    assert rows == [["po_number", "status", "note"], ["U1", "converted", "n"]]


LINES = [
    {"id": "a", "poLineNumber": "E1-1", "titleOrPackage": "T1",
     "details": {"subscriptionTo": "2026-12-31"}},
    {"id": "b", "poLineNumber": "E1-2", "titleOrPackage": "T2"},
    {"id": "c", "poLineNumber": "U9-1", "titleOrPackage": "T3"},
]


def test_export_rows_flags_non_first_lines():
    rows = exp.export_rows(LINES)
    assert [r["matches_po_plus_1"] for r in rows] == ["yes", "NO - line 2", "yes"]
    assert rows[0]["po_number"] == "E1" and rows[0]["subscription_to"] == "2026-12-31"


def test_fetch_lines_by_prefix_and_by_po():
    c = FakeClient(lines=LINES)
    assert len(list(exp.fetch_lines(c, prefix="E"))) == 2
    assert [ln["id"] for ln in exp.fetch_lines(c, po_numbers=["U9"])] == ["c"]
    assert c.queries[-1] == 'poLineNumber=="U9-*"'
    with pytest.raises(ValueError):
        list(exp.fetch_lines(c, po_numbers=['X"']))


def test_read_ini_and_ssl(tmp_path):
    ini = tmp_path / "t.ini"
    ini.write_text('; c\nname\t= "T"\r\nokapiUrl = "https://x/"\r\n'
                   'tenant_id = fs1\nusername = u\npassword = p\nsslVerify = false\n',
                   encoding="utf-8")
    v = folio_common.read_ini(ini)
    assert v["okapiUrl"] == "https://x/" and v["tenant_id"] == "fs1"
    assert folio_common.ssl_setting(v["sslVerify"]) is False
    assert folio_common.ssl_setting(None) is True
    assert folio_common.ssl_setting("missing/ca.pem") is True


class ConfigClient:
    def __init__(self, entries, fail=False):
        self.entries, self.fail, self.queries = entries, fail, []

    def folio_get(self, path, key=None, query_params=None, **kw):
        if self.fail:
            raise RuntimeError("boom")
        name = query_params["query"].split("configName==")[1].rstrip(")")
        self.queries.append(name)
        return {"configs": [{"value": v} for n, v in self.entries if n == name]}


def test_order_lines_limit_reads_either_setting_name():
    assert folio_common.order_lines_limit(ConfigClient([("poLines-limit", "11")])) == (
        11, "poLines-limit")
    assert folio_common.order_lines_limit(ConfigClient([("order_lines_limit", " 3 ")])) == (
        3, "order_lines_limit")


def test_order_lines_limit_prefers_first_name_and_defaults_to_one():
    both = ConfigClient([("order_lines_limit", "5"), ("poLines-limit", "7")])
    assert folio_common.order_lines_limit(both) == (7, "poLines-limit")
    limit, where = folio_common.order_lines_limit(ConfigClient([]))
    assert limit == 1 and "default" in where
    assert folio_common.order_lines_limit(ConfigClient([("poLines-limit", "abc")]))[0] == 1


def test_order_lines_limit_unreadable_is_none_not_an_error():
    limit, where = folio_common.order_lines_limit(ConfigClient([], fail=True))
    assert limit is None and "could not read" in where


def test_convert_po_one_time_choice_leaves_the_po_alone(settings):
    c = FakeClient({"U1": order()})
    assert ong.convert_po(c, "U1", settings, live=True, choice=("One-Time", None))[0] \
        == "skipped"
    assert not c.puts


def test_convert_po_uses_the_customers_interval(settings):
    c = FakeClient({"U1": order()})
    assert ong.convert_po(c, "U1", settings, live=True, choice=("Ongoing", 180))[0] \
        == "converted"
    assert c.puts[0][1]["ongoing"]["interval"] == 180


def test_read_order_settings(tmp_path):
    f = tmp_path / "order_settings.csv"
    f.write_text("order_number,route,order_type,interval_days\n"
                 "U1,online,Ongoing,90\nU2,pe,One-Time,\n", encoding="utf-8")
    assert ong.read_order_settings(f) == {"U1": ("Ongoing", 90), "U2": ("One-Time", None)}
