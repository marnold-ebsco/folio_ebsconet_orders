from pipeline.folio_orders_adapter import check_dry_run_budgets


def line(po, fund):
    return {"po_number": po, "order_format": "Electronic Resource", "fund_code": fund,
            "expense_class_code": "GEN"}


def fake_check(lines, resolver):
    return ["fund BAD has no Active budget"] if lines[0]["fund_code"] == "BAD" else []


def test_dry_run_po_without_budget_becomes_invalid():
    lines = [line("P1", "OK"), line("P2", "BAD")]
    results = [("P1", "dry-run", "1 line(s)"), ("P2", "dry-run", "1 line(s)")]
    out = check_dry_run_budgets(results, lines, None, check=fake_check)
    assert out[0] == ("P1", "dry-run", "1 line(s)")
    assert out[1] == ("P2", "invalid", "fund BAD has no Active budget")


def test_other_statuses_are_not_checked():
    lines = [line("P1", "BAD"), line("P2", "BAD")]
    results = [("P1", "exists", ""), ("P2", "lookup-failed", "not found")]

    def boom(lines, resolver):
        raise AssertionError("must not be called")

    assert check_dry_run_budgets(results, lines, None, check=boom) == results
