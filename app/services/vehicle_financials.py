from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable


def _latest_applied_installment(installments: Iterable[Any], reference: date) -> Any | None:
    candidates = [
        installment
        for installment in installments
        if getattr(installment, "period_end", None)
        and installment.period_end <= reference
        and getattr(installment, "amortization_amount", None) is not None
    ]
    return max(
        candidates,
        key=lambda item: (item.period_end, getattr(item, "period_number", 0)),
        default=None,
    )


def _date_value(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def canonical_vehicle_financial_values(
    *,
    cost_context: dict[str, Any],
    plan: Any | None,
    installments: Iterable[Any] = (),
    current_value_calculator: Callable[..., Decimal | None],
    reference: date | None = None,
) -> dict[str, Any]:
    """Return the shared financial truth used by sheet, audit and sale.

    The existing 96-month calculation is intentionally delegated to the
    supplied calculator.  This function only selects the amortization period
    and exposes its date separately from the lender's debt reference date.
    """

    as_of = reference or date.today()
    installment_list = list(installments)
    applied_installment = _latest_applied_installment(installment_list, as_of)
    amortization_month = cost_context.get("amortization_month")
    current_value_date = None

    # Accounting amortization is independent from the lender's rental plan.
    # It advances once per calendar month and is effective on day one.
    calculation_start = _date_value(cost_context.get("purchase_date")) or (
        getattr(plan, "start_date", None) if plan else None
    )
    if calculation_start:
        amortization_month = max(
            1,
            min(
                96,
                (as_of.year - calculation_start.year) * 12
                + (as_of.month - calculation_start.month)
                + 1,
            ),
        )
    if amortization_month:
        current_value_date = as_of.replace(day=1)

    current_value = current_value_calculator(
        cost_context.get("initial_cost_with_vat"),
        getattr(plan, "initial_amount", None) if plan else None,
        getattr(plan, "outstanding_amount", None) if plan else None,
        cost_context.get("current_cost_with_vat"),
        getattr(plan, "start_date", None) if plan else None,
        getattr(plan, "amount_reference_date", None) if plan else None,
        amortization_month,
    )
    return {
        "initial_cost_with_vat": cost_context.get("initial_cost_with_vat"),
        "current_value_with_vat": current_value,
        "current_value_date": current_value_date,
        "amortization_month": amortization_month,
        "outstanding_with_vat": getattr(plan, "outstanding_amount", None) if plan else None,
        "debt_reference_date": getattr(plan, "amount_reference_date", None) if plan else None,
        "applied_installment": applied_installment,
        "installment_count": len(installment_list),
    }
