"""Pure domain passive-income average calculator (framework-independent)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount


@dataclass(frozen=True, slots=True)
class MonthlyPassiveIncome:
    """Net passive income for a single reporting month."""

    year: int
    month: int
    amount: RubleAmount


@dataclass(frozen=True, slots=True)
class PassiveIncomeAverageInput:
    """Pure-domain input for the rolling-average calculator."""

    months: tuple[MonthlyPassiveIncome, ...] = ()
    history_start_month: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class PassiveIncomeAverageResult:
    """Pure-domain output and backend-derived history metadata."""

    sum_total: RubleAmount
    average: RubleAmount
    count_months: int
    is_complete_12m: bool
    months: tuple[MonthlyPassiveIncome, ...]
    configured_start_month: str | None = None
    months_used: tuple[str, ...] = ()


def eligible_passive_income_months(
    months: tuple[MonthlyPassiveIncome, ...],
    *,
    start_month: tuple[int, int] | None,
) -> tuple[MonthlyPassiveIncome, ...]:
    """Keep months on or after the configured inclusive history boundary."""
    if start_month is None:
        return months
    return tuple(month for month in months if (month.year, month.month) >= start_month)


def calculate_passive_income_average(
    input_data: PassiveIncomeAverageInput,
) -> PassiveIncomeAverageResult:
    """Calculate the latest 12 eligible closed-month records."""
    eligible_months = eligible_passive_income_months(
        input_data.months,
        start_month=input_data.history_start_month,
    )
    configured_start_month = (
        None
        if input_data.history_start_month is None
        else f"{input_data.history_start_month[0]:04d}-{input_data.history_start_month[1]:02d}"
    )
    if not eligible_months:
        return PassiveIncomeAverageResult(
            sum_total=RubleAmount(0),
            average=RubleAmount(0),
            count_months=0,
            is_complete_12m=False,
            months=(),
            configured_start_month=configured_start_month,
            months_used=(),
        )

    sorted_months = sorted(eligible_months, key=lambda item: (item.year, item.month))
    window = sorted_months[-12:]
    count = len(window)
    sum_kopecks = sum(item.amount.kopecks for item in window)
    average_kopecks = (Decimal(sum_kopecks) / Decimal(count)).to_integral_value(
        rounding=FINANCIAL_ROUNDING
    )

    return PassiveIncomeAverageResult(
        sum_total=RubleAmount(sum_kopecks),
        average=RubleAmount(int(average_kopecks)),
        count_months=count,
        is_complete_12m=count == 12,
        months=tuple(window),
        configured_start_month=configured_start_month,
        months_used=tuple(f"{item.year:04d}-{item.month:02d}" for item in window),
    )
