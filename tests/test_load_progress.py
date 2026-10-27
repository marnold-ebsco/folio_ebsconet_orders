from folio_orders_loader import loader

from pipeline import folio_orders_adapter as adapter


def test_load_with_progress_batches_by_po_and_keeps_results(monkeypatch, capsys):
    calls = []

    def fake_load(client, lines, live=False, open_orders=False, check_budget=False):
        calls.append(sorted({line["po_number"] for line in lines}))
        assert check_budget and live is False
        return [(po, "dry-run", "") for po in dict.fromkeys(ln["po_number"] for ln in lines)]

    monkeypatch.setattr(loader, "load", fake_load)
    monkeypatch.setattr(adapter, "LOAD_BATCH", 2)
    lines = [{"po_number": p} for p in ("A", "A", "B", "C", "D")]
    results = adapter.load_with_progress(None, lines, False)
    assert calls == [["A", "B"], ["C", "D"]]
    assert [r[0] for r in results] == ["A", "B", "C", "D"]
    out = capsys.readouterr().out
    assert "loading POs: 4/4" in out


def test_show_progress_log_mode_prints_every_25_and_last(capsys):
    for done in range(1, 31):
        adapter.show_progress("x", done, 30)
    shown = capsys.readouterr().out.split("\n")
    assert [s for s in shown if s] == ["x: 25/30", "x: 30/30"]
