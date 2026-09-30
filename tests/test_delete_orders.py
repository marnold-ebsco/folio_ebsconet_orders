import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folio_delete_orders as dl  # noqa: E402


class FakeClient:
    def __init__(self, orders=None):
        self.orders = orders or {}        # poNumber -> composite order
        self.deleted = []

    def _line_owner(self, number):
        for o in self.orders.values():
            for ln in o["compositePoLines"]:
                if ln["poLineNumber"] == number:
                    return o, ln
        return None, None

    def folio_get(self, path, key=None, query_params=None, **kw):
        if query_params and "query" in query_params:
            number = query_params["query"].split('"')[1]
            if path == "/orders/composite-orders":
                return [self.orders[number]] if number in self.orders else []
            o, ln = self._line_owner(number)
            return [ln] if ln else []
        if path.startswith("/orders/composite-orders/"):
            oid = path.rsplit("/", 1)[1]
            return next(o for o in self.orders.values() if o["id"] == oid)
        oid = path.rsplit("/", 1)[1]
        return next(ln for o in self.orders.values() for ln in o["compositePoLines"]
                    if ln["id"] == oid)

    def folio_delete(self, path, **kw):
        self.deleted.append(path)


def order(po, status="Pending", lines=1):
    return {"id": "id-" + po, "poNumber": po, "workflowStatus": status,
            "compositePoLines": [{"id": "l%d-%s" % (i, po), "poLineNumber": "%s-%d" % (po, i),
                                  "purchaseOrderId": "id-" + po}
                                 for i in range(1, lines + 1)]}


def test_read_targets(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("# comment\ntype,number,note\nPO,U1,bad fund\n# skip\npol,U1-2,\nPO,U1,dup\n",
                 encoding="utf-8")
    assert dl.read_targets(f) == [("PO", "U1", "bad fund"), ("POL", "U1-2", "")]


def test_read_targets_template_is_empty():
    assert dl.read_targets(Path(__file__).resolve().parent.parent
                           / "orders_to_delete.csv") == []


@pytest.mark.parametrize("body", ["type,number\nXX,U1\n", "type,number\nPO,\n",
                                  'type,number\nPO,U"1\n'])
def test_read_targets_rejects_bad_rows(tmp_path, body):
    f = tmp_path / "t.csv"
    f.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        dl.read_targets(f)


def test_delete_po_dry_run_then_live(tmp_path):
    c = FakeClient({"U1": order("U1", lines=2)})
    assert dl.delete_po(c, "U1", False, tmp_path) == ("dry-run", "2 line(s)")
    assert c.deleted == []
    assert dl.delete_po(c, "U1", True, tmp_path) == ("deleted", "2 line(s)")
    assert c.deleted == ["/orders/composite-orders/id-U1"]
    saved = json.loads((tmp_path / "PO_U1.json").read_text(encoding="utf-8"))
    assert saved["poNumber"] == "U1"


def test_delete_po_skips_non_pending_and_missing(tmp_path):
    c = FakeClient({"U1": order("U1", status="Open")})
    assert dl.delete_po(c, "U1", True, tmp_path)[0] == "skipped"
    assert dl.delete_po(c, "NOPE", True, tmp_path) == ("not-found", "")
    assert c.deleted == []


def test_delete_pol(tmp_path):
    c = FakeClient({"U1": order("U1", lines=2)})
    assert dl.delete_pol(c, "U1-2", False, tmp_path) == (
        "dry-run", "PO keeps 1 other line(s)")
    assert dl.delete_pol(c, "U1-2", True, tmp_path)[0] == "deleted"
    assert c.deleted == ["/orders/order-lines/l2-U1"]
    assert (tmp_path / "POL_U1-2.json").exists()


def test_delete_pol_last_line_warns_and_open_po_skipped(tmp_path):
    c = FakeClient({"U1": order("U1"), "U2": order("U2", status="Open")})
    assert "LAST line" in dl.delete_pol(c, "U1-1", False, tmp_path)[1]
    assert dl.delete_pol(c, "U2-1", True, tmp_path)[0] == "skipped"
    assert c.deleted == []


def test_run_continues_after_error_and_logs(tmp_path):
    c = FakeClient({"U1": order("U1")})
    res = dl.run(c, [("PO", "U1", "n"), ("PO", "GONE", "")], False, tmp_path)
    assert [r[2] for r in res] == ["dry-run", "not-found"]
    dl.write_log(tmp_path / "log.csv", res)
    rows = list(csv.reader(open(tmp_path / "log.csv", encoding="utf-8")))
    assert rows[0] == ["type", "number", "status", "detail", "note"] and len(rows) == 3
