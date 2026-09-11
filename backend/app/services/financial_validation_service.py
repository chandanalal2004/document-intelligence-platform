"""
Financial calculation validation (case study section 4.4).

Each document type gets its own set of checks. A check runs only if ALL
the fields it needs are present and numeric -- otherwise its status is
NOT_APPLICABLE (never invented). Numeric tolerance is used because OCR'd
figures can be off by rounding.
"""
from typing import Any, Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

# Absolute tolerance for "approximately equal" (handles rounding in source
# documents). Also applies a relative 0.5% tolerance for larger figures.
ABS_TOLERANCE = 1.0
REL_TOLERANCE = 0.005


def _num(fields: Dict[str, Any], key: str) -> Optional[float]:
    """Pulls a numeric value out of an extracted-fields dict, else None."""
    entry = fields.get(key)
    if not entry:
        return None
    val = entry.get("value") if isinstance(entry, dict) else entry
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _check(
    name: str, formula: str, operands: Dict[str, Optional[float]],
    calculated: Optional[float], reported: Optional[float], period: Optional[str] = None,
) -> Dict[str, Any]:
    if calculated is None or reported is None or any(v is None for v in operands.values()):
        return {
            "name": name, "formula": formula, "operands": operands,
            "calculated_value": calculated, "reported_value": reported,
            "variance": None, "status": "NOT_APPLICABLE", "period": period,
        }
    variance = round(calculated - reported, 2)
    tolerance = max(ABS_TOLERANCE, abs(reported) * REL_TOLERANCE)
    status = "PASS" if abs(variance) <= tolerance else "FAIL"
    return {
        "name": name, "formula": formula, "operands": operands,
        "calculated_value": round(calculated, 2), "reported_value": round(reported, 2),
        "variance": variance, "status": status, "period": period,
    }


def _overall_status(checks: List[Dict[str, Any]]) -> str:
    statuses = {c["status"] for c in checks}
    if not checks or statuses <= {"NOT_APPLICABLE"}:
        return "NOT_APPLICABLE"
    if "FAIL" in statuses:
        return "FAIL"
    return "PASS"


# ---------------------------------------------------------------- invoice
def validate_invoice(fields: Dict[str, Any], line_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    checks = []

    subtotal = _num(fields, "subtotal")
    tax = _num(fields, "tax_amount")
    discount = _num(fields, "discount") or 0.0
    total = _num(fields, "total_amount")

    if subtotal is not None and tax is not None and total is not None:
        calc = subtotal + tax - discount
        checks.append(_check(
            "invoice_total_check", "subtotal + tax_amount - discount",
            {"subtotal": subtotal, "tax_amount": tax, "discount": discount}, calc, total,
        ))

    if line_items:
        valid_items = [li for li in line_items if li.get("quantity") is not None and li.get("unit_price") is not None and li.get("amount") is not None]
        for idx, li in enumerate(valid_items):
            calc = li["quantity"] * li["unit_price"]
            checks.append(_check(
                f"line_item_{idx + 1}_qty_x_price", "quantity * unit_price",
                {"quantity": li["quantity"], "unit_price": li["unit_price"]}, calc, li["amount"],
            ))
        line_total_sum = sum(li["amount"] for li in line_items if li.get("amount") is not None)
        if subtotal is not None and line_total_sum:
            checks.append(_check(
                "line_items_sum_to_subtotal", "sum(line_totals)",
                {"sum_of_line_totals": line_total_sum}, line_total_sum, subtotal,
            ))

    cash_paid = _num(fields, "cash_paid")
    change = _num(fields, "change")
    if cash_paid is not None and total is not None and change is not None:
        calc = cash_paid - total
        checks.append(_check(
            "cash_change_check", "cash_paid - total_amount",
            {"cash_paid": cash_paid, "total_amount": total}, calc, change,
        ))

    return checks


# ------------------------------------------------------------ balance sheet
def validate_balance_sheet(fields: Dict[str, Any], periods: List[str]) -> List[Dict[str, Any]]:
    checks = []
    period_list = periods or [None]
    for period in period_list:
        suffix = f"_{period}" if period else ""
        assets = _num(fields, f"total_assets{suffix}") or _num(fields, "total_assets")
        liabilities = _num(fields, f"total_liabilities{suffix}") or _num(fields, "total_liabilities")
        equity = _num(fields, f"total_equity{suffix}") or _num(fields, "total_equity")

        calc = None
        if liabilities is not None and equity is not None:
            calc = liabilities + equity
        checks.append(_check(
            "assets_equals_liabilities_plus_equity",
            "total_liabilities + total_equity", {"total_liabilities": liabilities, "total_equity": equity},
            calc, assets, period=period,
        ))
        break  # single-period MVP; extend by looping distinct periods found by the LLM
    return checks


# --------------------------------------------------------------- P&L
def validate_profit_and_loss(fields: Dict[str, Any], periods: List[str]) -> List[Dict[str, Any]]:
    checks = []
    revenue = _num(fields, "revenue") or _num(fields, "total_income")
    cogs = _num(fields, "cost_of_sales")
    gross_profit = _num(fields, "gross_profit")
    opex = _num(fields, "operating_expenses")
    operating_profit = _num(fields, "operating_profit")
    tax = _num(fields, "tax")
    net_profit = _num(fields, "net_profit")

    if revenue is not None and cogs is not None:
        checks.append(_check(
            "gross_profit_check", "revenue - cost_of_sales",
            {"revenue": revenue, "cost_of_sales": cogs}, revenue - cogs, gross_profit,
        ))

    if gross_profit is not None and opex is not None:
        checks.append(_check(
            "operating_profit_check", "gross_profit - operating_expenses",
            {"gross_profit": gross_profit, "operating_expenses": opex}, gross_profit - opex, operating_profit,
        ))

    if operating_profit is not None and tax is not None:
        checks.append(_check(
            "net_profit_check", "operating_profit - tax",
            {"operating_profit": operating_profit, "tax": tax}, operating_profit - tax, net_profit,
        ))

    # Banking-style P&L check:
    # total income - total expenditure = net profit
    total_income = _num(fields, "total_income")
    total_expenditure = _num(fields, "total_expenditure")

    if total_income is not None and total_expenditure is not None:
        checks.append(_check(
            "banking_net_profit_check",
            "total_income - total_expenditure",
            {
                "total_income": total_income,
                "total_expenditure": total_expenditure,
            },
            total_income - total_expenditure,
            net_profit,
        ))

    return checks

# ------------------------------------------------------------- cash flow
def validate_cash_flow(fields: Dict[str, Any], periods: List[str]) -> List[Dict[str, Any]]:
    checks = []
    ocf = _num(fields, "operating_cash_flow")
    icf = _num(fields, "investing_cash_flow")
    fcf = _num(fields, "financing_cash_flow")
    fx = _num(fields, "fx_adjustment") or 0.0
    net_change = _num(fields, "net_change_in_cash")
    opening = _num(fields, "opening_cash")
    closing = _num(fields, "closing_cash")

    if ocf is not None and icf is not None and fcf is not None:
        calc = ocf + icf + fcf + fx
        checks.append(_check(
            "net_change_in_cash_check",
            "operating_cash_flow + investing_cash_flow + financing_cash_flow + fx_adjustment",
            {"operating_cash_flow": ocf, "investing_cash_flow": icf, "financing_cash_flow": fcf, "fx_adjustment": fx},
            calc, net_change,
        ))

    if opening is not None and net_change is not None:
        calc = opening + net_change
        checks.append(_check(
            "closing_cash_check", "opening_cash + net_change_in_cash",
            {"opening_cash": opening, "net_change_in_cash": net_change}, calc, closing,
        ))

    return checks


VALIDATORS = {
    "invoice": lambda fields, line_items, periods: validate_invoice(fields, line_items),
    "balance_sheet": lambda fields, line_items, periods: validate_balance_sheet(fields, periods),
    "profit_and_loss": lambda fields, line_items, periods: validate_profit_and_loss(fields, periods),
    "cash_flow_statement": lambda fields, line_items, periods: validate_cash_flow(fields, periods),
}


def run_validation(
    document_type: str, fields: Dict[str, Any], line_items: List[Dict[str, Any]], periods: List[str],
) -> Dict[str, Any]:
    validator = VALIDATORS.get(document_type)
    if validator is None:
        return {"checks": [], "overall_status": "NOT_APPLICABLE", "issues": [f"No validator for {document_type}"]}

    checks = validator(fields, line_items, periods)
    issues = [f"{c['name']} failed (variance={c['variance']})" for c in checks if c["status"] == "FAIL"]
    return {"checks": checks, "overall_status": _overall_status(checks), "issues": issues}
