import csv
import sys
from pathlib import Path

from pymarc import Field, MARCReader, Record, Subfield

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import folio_import as imp  # noqa: E402
import folio_retry_failed as rt  # noqa: E402


class FakeClient:
    """POs: {number: number_of_lines}. Log pages for job_log tests."""

    def __init__(self, pos=None, log_total=0):
        self.pos = pos or {}
        self.log_total = log_total
        self.calls = []

    def folio_get(self, path, key=None, query_params=None, **kw):
        q = (query_params or {}).get("query", "")
        val = q.split('"')[1] if '"' in q else ""
        if key == "purchaseOrders":
            return [{"workflowStatus": "Pending"}] if val in self.pos else []
        if key == "poLines":
            po = val.rsplit("-", 1)[0]
            return [{}] * self.pos.get(po, 0)
        if path.startswith("/metadata-provider/jobLogEntries/"):
            off, lim = query_params["offset"], query_params["limit"]
            self.calls.append((off, lim))
            n = max(0, min(lim, self.log_total - off))
            return {"entries": [{"sourceRecordOrder": off + i} for i in range(n)],
                    "totalRecords": self.log_total}
        raise AssertionError((path, key, q))


def test_po_results():
    c = FakeClient({"A": 1, "B": 0})
    res = imp.po_results(c, ["A", "B", "C"])
    assert [(r["po"], r["exists"], r["lines"], r["ok"]) for r in res] == [
        ("A", True, 1, True), ("B", True, 0, False), ("C", False, 0, False)]


def test_job_log_pages_through_all_entries():
    c = FakeClient(log_total=250)
    assert len(imp.job_log(c, "j", page=100)) == 250
    assert c.calls == [(0, 100), (100, 100), (200, 100)]
    assert imp.job_log(FakeClient(log_total=0), "j") == []


def test_log_rows_and_summary_and_write(tmp_path):
    jobs = [{"id": "j1", "hrId": 7, "status": "COMMITTED",
             "subordinationType": "COMPOSITE_CHILD", "progress": {"current": 2}}]
    entries = {"j1": [
        {"sourceRecordOrder": 0, "sourceRecordTitle": "Good",
         "relatedPoLineInfo": {"actionStatus": "CREATED"}},
        {"sourceRecordOrder": 1, "sourceRecordTitle": "Bad",
         "relatedPoLineInfo": {"actionStatus": "DISCARDED", "error": "boom"}}]}
    results = [{"po": "A", "exists": True, "lines": 1, "status": "Pending", "ok": True},
               {"po": "B", "exists": True, "lines": 0, "status": "Pending", "ok": False}]
    rows = imp.log_rows(jobs, entries, results)
    assert rows[0][:3] == ("job", 7, "COMMITTED")
    assert ("record", "job 7 record 1: Bad", "DISCARDED", "boom") in rows
    assert ("po", "B", "PROBLEM", "status Pending, 0 line(s)") in rows
    text = imp.summary(jobs, entries, results)
    assert "POs with a PO line: 1 of 2" in text and "Bad" in text and "boom" in text
    assert "Good" not in text                     # successes are not listed
    imp.write_audit(tmp_path / "logs" / "a.csv", rows)
    got = list(csv.reader(open(tmp_path / "logs" / "a.csv", encoding="utf-8")))
    assert got[0] == ["kind", "ref", "status", "detail"] and len(got) == len(rows) + 1


def test_classify():
    res = [{"po": "A", "exists": True, "lines": 1, "ok": True},
           {"po": "B", "exists": True, "lines": 0, "ok": False},
           {"po": "C", "exists": False, "lines": 0, "ok": False}]
    assert rt.classify(res) == (["A"], ["C"], ["B"])


def make_mrc(path, pos):
    with open(path, "wb") as out:
        for po in pos:
            r = Record(force_utf8=True)
            r.leader = "00000nas a2200000   4500"
            r.add_field(Field(tag="001", data=po))
            r.add_field(Field(tag="990", indicators=[" ", " "],
                              subfields=[Subfield("o", po)]))
            out.write(r.as_marc())


def test_write_retry_mrc_and_delete_csv(tmp_path):
    src = tmp_path / "in.mrc"
    make_mrc(src, ["A", "B", "C"])
    n = rt.write_retry_mrc(src, ["B", "C"], tmp_path / "r" / "in_retry.mrc")
    assert n == 2
    with open(tmp_path / "r" / "in_retry.mrc", "rb") as fh:
        assert [r["001"].data for r in MARCReader(fh)] == ["B", "C"]
    rt.write_delete_csv(tmp_path / "r" / "d.csv", ["B"])
    rows = list(csv.reader(open(tmp_path / "r" / "d.csv", encoding="utf-8")))
    assert rows[0] == ["type", "number", "note"] and rows[1][:2] == ["PO", "B"]
