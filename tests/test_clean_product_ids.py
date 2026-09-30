import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import folio_clean_product_ids as cp  # noqa: E402

ISSN = {"productId": "1234-5678", "productIdType": "issn-id"}
TN = {"productId": "PC1", "productIdType": "pub-id"}


def line(po, ids, status="Pending"):
    return {"id": "l-" + po, "poLineNumber": po + "-1", "purchaseOrderId": "o-" + po,
            "status": status, "details": {"productIds": ids, "subscriptionTo": "2026-12-31"}}


class FakeClient:
    def __init__(self, lines, status="Pending"):
        self.lines = {ln["id"]: ln for ln in lines}
        self.status = status
        self.puts = []

    def folio_get(self, path, key=None, query_params=None, **kw):
        if key == "poLines":
            po = query_params["query"].split('"')[1].rsplit("-", 1)[0]
            return [ln for ln in self.lines.values()
                    if ln["poLineNumber"].startswith(po + "-")]
        if path.startswith("/orders/composite-orders/"):
            return {"workflowStatus": self.status}
        return self.lines[path.rsplit("/", 1)[1]]

    def folio_put(self, path, payload, **kw):
        self.puts.append((path, payload))


def test_has_empty_entry():
    assert cp.has_empty_entry(line("A", [ISSN, {}]))
    assert cp.has_empty_entry(line("A", [{"productIdType": "issn-id"}, TN]))
    assert not cp.has_empty_entry(line("A", [ISSN, TN]))
    assert not cp.has_empty_entry(line("A", []))


def test_dry_run_changes_nothing():
    c = FakeClient([line("A", [ISSN, {}])])
    assert cp.clean_lines(c, ["A"], False) == [("A-1", "would-clean", "1 product ID(s) kept")]
    assert c.puts == []


def test_live_removes_only_the_empty_entries():
    c = FakeClient([line("A", [{"productIdType": "issn-id"}, TN]),
                    line("B", [ISSN, TN]), line("C", [{"productIdType": "x"}, {}])])
    res = cp.clean_lines(c, ["A", "B", "C"], True)
    assert [(r[0], r[1]) for r in res] == [("A-1", "cleaned"), ("C-1", "cleaned")]
    assert [p[0] for p in c.puts] == ["/orders/order-lines/l-A", "/orders/order-lines/l-C"]
    sent = {p[0]: p[1] for p in c.puts}
    assert sent["/orders/order-lines/l-A"]["details"]["productIds"] == [TN]
    assert sent["/orders/order-lines/l-C"]["details"]["productIds"] == []
    assert sent["/orders/order-lines/l-A"]["details"]["subscriptionTo"] == "2026-12-31"


def test_non_pending_orders_are_left_alone():
    c = FakeClient([line("A", [ISSN, {}])], status="Open")
    res = cp.clean_lines(c, ["A"], True)
    assert res[0][1] == "skipped" and "Open" in res[0][2]
    assert c.puts == []
