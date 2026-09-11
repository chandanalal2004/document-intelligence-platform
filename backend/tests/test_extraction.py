"""
Unit tests for the financial validation formulas. These use hand-built
field dicts (as the LLM extraction service would return them) so they
run without any external API calls.
"""
from app.services.financial_validation_service import run_validation


def _f(**kwargs):
    """Helper: builds a {"field": {"value": x}} dict from kwargs."""
    return {k: {"value": v} for k, v in kwargs.items()}


def test_invoice_total_check_passes():
    fields = _f(subtotal=100.0, tax_amount=5.0, discount=0.0, total_amount=105.0)
    result = run_validation("invoice", fields, [], [])
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "PASS"
    assert result["overall_status"] == "PASS"


def test_invoice_total_check_fails_on_mismatch():
    fields = _f(subtotal=100.0, tax_amount=5.0, discount=0.0, total_amount=999.0)
    result = run_validation("invoice", fields, [], [])
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "FAIL"
    assert result["overall_status"] == "FAIL"


def test_invoice_missing_fields_are_not_applicable():
    fields = _f(subtotal=100.0)  # tax_amount / total_amount missing
    result = run_validation("invoice", fields, [], [])
    assert result["overall_status"] == "NOT_APPLICABLE"


def test_balance_sheet_check():
    fields = _f(total_assets=1000.0, total_liabilities=600.0, total_equity=400.0)
    result = run_validation("balance_sheet", fields, [], [])
    check = result["checks"][0]
    assert check["status"] == "PASS"


def test_cash_flow_checks():
    fields = _f(
        operating_cash_flow=200.0, investing_cash_flow=-50.0, financing_cash_flow=-20.0,
        net_change_in_cash=130.0, opening_cash=500.0, closing_cash=630.0,
    )
    result = run_validation("cash_flow_statement", fields, [], [])
    assert result["overall_status"] == "PASS"
    assert len(result["checks"]) == 2
