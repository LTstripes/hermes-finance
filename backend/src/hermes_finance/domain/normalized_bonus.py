"""Pure domain normalized-bonus calculator (framework-independent).

Implements MASTER_SPEC §10.15:

    normalized_bonus_monthly = sum(bonuses for selected 12m period) / 12

The result is an analytical monthly average used only for analytics; it is
never mixed into the actual cash flow of other months.

The 12-month window logic (sort by year/month, keep at most the last 12
months, divide with ROUND_HALF_UP) is reused from the C03 rolling-average
calculator (:func:`calculate_passive_income_average`) — the formula is
identical, only the source rows differ (BONUS income entries instead of
passive income).

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermes_finance.domain.passive_income_average import (
    MonthlyPassiveIncome,
    PassiveIncomeAverageInput,
    calculate_passive_income_average,
)
from hermes_finance.domain.values import RubleAmount


@dataclass(frozen=True, slots=True)
class NormalizedBonusResult:
    """Pure-domain output of the normalized-bonus calculator.

    ``months`` is the window actually used, sorted ascending by year/month
    (at most the last 12).
    """

    monthly_average: RubleAmount
    sum_total: RubleAmount
    count_months: int
    is_complete_12m: bool
    months: tuple[MonthlyPassiveIncome, ...]
    warnings: tuple[str, ...]


def calculate_normalized_bonus(months: tuple[MonthlyPassiveIncome, ...]) -> NormalizedBonusResult:
    """Calculate the normalized monthly bonus over the available window.

    * Reuses the C03 rolling-average calculator: sorts ascending by
      ``(year, month)``, keeps at most the last 12 months, averages with
      ``ROUND_HALF_UP``.
    * Empty input yields a zero average with an explanatory warning.
    * Never divides by zero; no binary ``float``.
    """
    avg_result = calculate_passive_income_average(PassiveIncomeAverageInput(months=months))

    warnings: list[str] = []
    count = avg_result.count_months
    if count == 0:
        warnings.append("Нет закрытых месяцев для оценки нормализованной премии")
    elif count < 12:
        warnings.append(f"Премия оценена по {count} месяцев из 12")

    return NormalizedBonusResult(
        monthly_average=avg_result.average,
        sum_total=avg_result.sum_total,
        count_months=count,
        is_complete_12m=avg_result.is_complete_12m,
        months=avg_result.months,
        warnings=tuple(warnings),
    )
