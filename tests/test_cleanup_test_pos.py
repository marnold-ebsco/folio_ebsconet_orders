import sys
from pathlib import Path

from pymarc import Field, Record, Subfield

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folio_cleanup_test_pos as ct  # noqa: E402

VENDOR = "vendor-1"


class FakeClient:
    def __init__(self, orders):
        self.orders = orders            # poNumber -> composite order
        self.deleted = []

    def folio_get(self, path, key=None, query_params=None, **kw):
        if query_params and "query" in query_params:
            number = query_params["query"].split('"')[1]
            return [self.orders[number]] if number in self.orders else []
        oid = path.rsplit("/", 1)[1]
        return next(o for o in self.orders.values() if o["id"] == oid)

    def folio_delete(self, path, **kw):
        self.deleted.append(path)


def order(po, vendor=VENDOR, status="Pending"):
    return {"id": "id-" + po, "poNumber": po, "vendor": vendor,
            "workflowStatus": status, "compositePoLines": [{}]}


def make_mrc(path, pos):
    with open(path, "wb") as out:
        for po in pos:
            r = Record(force_utf8=True)
            r.leader = "00000nas a2200000   4500"
            r.add_field(Field(tag="001", data=po))
            r.add_field(Field(tag="990", indicators=[" ", " "],
                              subfields=[Subfield("o", po)]))
            out.write(r.as_marc())


def test_collect_numbers_dedupes_and_adds_extras(tmp_path):
    make_mrc(tmp_path / "a.mrc", ["A", "B"])
    make_mrc(tmp_path / "b.mrc", ["B", "C"])
    (tmp_path / "junk.mrc").write_bytes(b"")
    got = ct.collect_numbers([tmp_path / "a.mrc", tmp_path / "b.mrc",
                              tmp_path / "junk.mrc", tmp_path / "missing.mrc"],
                             extra=["C", "D"])
    assert got == ["A", "B", "C", "D"]


def test_cleanup_dry_run_deletes_nothing(tmp_path):
    c = FakeClient({"A": order("A")})
    res = ct.cleanup(c, ["A", "GONE"], VENDOR, False, tmp_path)
    assert res == [("A", "dry-run", "1 line(s)"), ("GONE", "not-found", "")]
    assert c.deleted == []


def test_cleanup_live_deletes_only_matching_pending_orders(tmp_path):
    c = FakeClient({"A": order("A"), "OTHER": order("OTHER", vendor="someone-else"),
                    "OPEN": order("OPEN", status="Open")})
    res = ct.cleanup(c, ["A", "OTHER", "OPEN", "GONE"], VENDOR, True, tmp_path)
    assert [r[1] for r in res] == ["deleted", "skipped", "skipped", "not-found"]
    assert "different vendor" in res[1][2]
    assert c.deleted == ["/orders/composite-orders/id-A"]
    assert (tmp_path / "PO_A.json").exists()
    assert not (tmp_path / "PO_OTHER.json").exists()


def test_cleanup_reports_errors_and_continues(tmp_path):
    class Boom(FakeClient):
        def folio_delete(self, path, **kw):
            raise RuntimeError("nope")

    c = Boom({"A": order("A"), "B": order("B")})
    res = ct.cleanup(c, ["A", "B"], VENDOR, True, tmp_path)
    assert [r[1] for r in res] == ["error", "error"] and "RuntimeError" in res[0][2]


def test_tally():
    assert ct.tally([("A", "deleted", ""), ("B", "deleted", ""), ("C", "skipped", "")]) \
        == "deleted: 2, skipped: 1"
