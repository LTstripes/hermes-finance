"""Pure domain passive-income average calculator (framework-independent).

Implements MASTER_SPEC §10.5:

    Before 12 months accumulate:

        actual_passive_income_avg =
            sum(actual_net_passive_income for available months)
            / count(available months)

    After 12 months: rolling window of the last 12 reporting months.

The UI should show a warning when fewer than 12 months are available:

    "Среднее за доступный период. Учтено N месяцев из 12."

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.  Division uses
:class:`decimal.Decimal` with ``ROUND_HALF_UP`` to round to whole kopecks.
"""

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
    """Pure-domain input for the rolling-average calculator.

    Months may arrive in any order; the calculator sorts them ascending
    by ``(year, month)`` and keeps at most the last 12.
    """

    months: tuple[MonthlyPassiveIncome, ...] = ()


@dataclass(frozen=True, slots=True)
class PassiveIncomeAverageResult:
    """Pure-domain output of the rolling-average calculator.

    ``months`` is the window actually used, sorted ascending by year/month.
    """

    sum_total: RubleAmount
    average: RubleAmount
    count_months: int
    is_complete_12m: bool
    months: tuple[MonthlyPassiveIncome, ...]


def calculate_passive_income_average(
    input_data: PassiveIncomeAverageInput,
) -> PassiveIncomeAverageResult:
    """Calculate the rolling 12-month average of actual net passive income.

    * Sort months ascending by ``(year, month)`` — input order is not
      guaranteed.
    * Keep at most the LAST 12 months (the most recent ones).
    * ``sum_total`` — integer sum of kopecks over the window.
    * ``average`` — ``Decimal(sum_kopecks) / Decimal(count_months)`` rounded
      to whole kopecks with ``ROUND_HALF_UP``.  Never divides by 12 blindly;
      never divides by zero.
    * Empty input returns all-zero result with ``is_complete_12m=False``.
    * Negative amounts are allowed (net income can be negative).
    """
    if not input_data.months:
        return PassiveIncomeAverageResult(
            sum_total=RubleAmount(0),
            average=RubleAmount(0),
            count_months=0,
            is_complete_12m=False,
            months=(),
        )

    sorted_months = sorted(input_data.months, key=lambda m: (m.year, m.month))

    # Keep at most the last 12 (most recent) months.
    window = sorted_months[-12:]
    count = len(window)

    sum_kopecks = sum(m.amount.kopecks for m in window)

    average_kopecks = (Decimal(sum_kopecks) / Decimal(count)).to_integral_value(
        rounding=FINANCIAL_ROUNDING
    )

    return PassiveIncomeAverageResult(
        sum_total=RubleAmount(sum_kopecks),
        average=RubleAmount(int(average_kopecks)),
        count_months=count,
        is_complete_12m=(count == 12),
        months=tuple(window),
    )
