"""Pure domain normalized-bonus calculator (framework-independent).

Implements MASTER_SPEC §10.15:

    normalized_bonus_monthly = sum(bonuses for selected 12m period) / 12

The result is an analytical monthly average used only for analytics; it is
never mixed into the actual cash flow of other months.

The selected period is always twelve calendar months ending at the latest
observed closed month. Only observed closed rows inside that period count;
missing calendar months are not inferred. Partial evidence is reported with
coverage metadata and the exact ``sum / 12`` normalized value.

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome
from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount


@dataclass(frozen=True, slots=True)
class NormalizedBonusResult:
    """Pure-domain output of the normalized-bonus calculator.

    ``months`` is the observed portion of the selected calendar 12-month
    period, sorted ascending by year/month.
    """

    monthly_average: RubleAmount | None
    sum_total: RubleAmount | None
    count_months: int
    is_complete_12m: bool
    months: tuple[MonthlyPassiveIncome, ...]
    warnings: tuple[str, ...]


def calculate_normalized_bonus(months: tuple[MonthlyPassiveIncome, ...]) -> NormalizedBonusResult:
    """Calculate the normalized monthly bonus over the available window.

    * Uses the latest observed closed reporting month as the end of the
      selected calendar 12-month period and keeps only observed rows inside
      that period. Missing calendar months remain missing.
    * The selected period is always normalized to twelve months.  A partial
      window therefore reports ``sum / 12`` and explicit coverage metadata;
      it must never silently become ``sum / available_month_count``.
    * Empty input yields unavailable values with an explanatory warning. No
      missing calendar month is inferred as an observed zero.
    * Never divides by zero; no binary ``float``.
    """
    ordered_months = tuple(sorted(months, key=lambda item: (item.year, item.month)))
    if ordered_months:
        latest = ordered_months[-1]
        latest_index = latest.year * 12 + latest.month
        first_index = latest_index - 11
        window = tuple(
            item
            for item in ordered_months
            if first_index <= item.year * 12 + item.month <= latest_index
        )
    else:
        window = ()
    count = len(window)
    sum_kopecks = sum(item.amount.kopecks for item in window)
    monthly_average = (
        RubleAmount(
            int((Decimal(sum_kopecks) / Decimal(12)).to_integral_value(rounding=FINANCIAL_ROUNDING))
        )
        if count
        else RubleAmount(0)
    )

    warnings: list[str] = []
    if count == 0:
        warnings.append("Нет закрытых месяцев для оценки нормализованной премии")
    elif count < 12:
        warnings.append(f"Премия оценена по {count} месяцев из 12")

    return NormalizedBonusResult(
        monthly_average=monthly_average if count else None,
        sum_total=RubleAmount(sum_kopecks) if count else None,
        count_months=count,
        is_complete_12m=count == 12,
        months=window,
        warnings=tuple(warnings),
    )
