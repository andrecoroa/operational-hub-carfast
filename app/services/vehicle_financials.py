from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable


MONEY = Decimal("0.01")
STANDARD_VAT_MULTIPLIER = Decimal("1.23")


def _money(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(MONEY)
    except (ValueError, TypeError):
        return None


def _outstanding_with_vat(plan: Any | None, installment: Any | None) -> Decimal | None:
    if not plan:
        return None
    explicit = _money(getattr(installment, "outstanding_with_vat", None))
    if explicit is not None:
        return explicit
    outstanding = _money(getattr(plan, "outstanding_amount", None))
    if outstanding is None:
        return None
    return (outstanding * STANDARD_VAT_MULTIPLIER).quantize(MONEY)


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


def _installment_for_calendar_month(
    installments: Iterable[Any], reference: date
) -> Any | None:
    """Return the rental-plan line applicable to the current calendar month.

    The commercial debt position is set at the start of the month.  A rental
    collected on (for example) day 10 still belongs to that month, so it must
    be reflected on day 1 instead of waiting for its collection date.
    """

    month_start = reference.replace(day=1)
    if reference.month == 12:
        next_month = date(reference.year + 1, 1, 1)
    else:
        next_month = date(reference.year, reference.month + 1, 1)

    matches = []
    for installment in installments:
        period_start = getattr(installment, "period_start", None)
        period_end = getattr(installment, "period_end", None)
        if period_end is None:
            continue
        starts_before_next_month = period_start is None or period_start < next_month
        ends_in_or_after_month = period_end >= month_start
        if starts_before_next_month and ends_in_or_after_month:
            matches.append(installment)
    return min(
        matches,
        key=lambda item: (getattr(item, "period_end", date.max), getattr(item, "period_number", 0)),
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
    # Financial debt is the forecast for the whole calendar month, not the
    # latest rental already collected. This makes it available on day one.
    monthly_installment = _installment_for_calendar_month(installment_list, as_of)
    applied_installment = monthly_installment
    if applied_installment is None:
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
        "outstanding_with_vat": _outstanding_with_vat(plan, applied_installment),
        "debt_reference_date": (
            as_of.replace(day=1)
            if monthly_installment
            else getattr(plan, "amount_reference_date", None) if plan else None
        ),
        "applied_installment": applied_installment,
        "installment_count": len(installment_list),
    }
