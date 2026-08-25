"""Pure domain expense-coverage and goal-progress calculator (framework-independent).

Implements MASTER_SPEC §10.7-§10.8:

    passive_income_goal_progress_pct =
        forecast_monthly_net_passive_income / goal_target * 100

    mandatory_expense_coverage_pct =
        forecast_monthly_net_passive_income / mandatory_expenses * 100

    actual_mandatory_expense_coverage_pct =
        passive_income_average / mandatory_expenses * 100

    passive_income_minus_mandatory_expenses =
        forecast_monthly_net_passive_income - mandatory_expenses

Zero denominators return ``None`` so the UI never shows infinity — the same
safe-denominator pattern as ``mortgage_coverage`` (services/properties.py).

Progress is built on the forecast monthly figure by default; the actual
average is returned alongside (MASTER_SPEC §10.7: "рядом показывается
фактическое среднее").

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.  Percentages are
:class:`decimal.Decimal` quantized to two decimal places with
``ROUND_HALF_UP``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount

_PERCENT_SCALE = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class CoverageGoalsInput:
    """Pure-domain input for the coverage/goal calculator.

    ``forecast_warnings`` and ``is_approximate`` come from the C04 forecast
    (they describe the quality of the monthly passive-income figure).
    """

    forecast_monthly: RubleAmount
    actual_average: RubleAmount
    mandatory_expenses: RubleAmount
    goal_target: RubleAmount
    is_approximate: bool = False
    forecast_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageGoalsResult:
    """Pure-domain output of the coverage/goal calculator."""

    forecast_monthly: RubleAmount
    actual_average: RubleAmount
    mandatory_expenses: RubleAmount
    coverage_pct: Decimal | None
    actual_mandatory_expense_coverage_pct: Decimal | None
    passive_income_minus_mandatory_expenses: RubleAmount
    goal_target: RubleAmount
    goal_progress_pct: Decimal | None
    is_approximate: bool
    warnings: tuple[str, ...]


def _percent(numerator_kopecks: int, denominator_kopecks: int) -> Decimal | None:
    """``numerator / denominator * 100`` quantized to 0.01; ``None`` on zero denominator."""
    if denominator_kopecks == 0:
        return None
    return (Decimal(numerator_kopecks) / Decimal(denominator_kopecks) * Decimal(100)).quantize(
        _PERCENT_SCALE, rounding=FINANCIAL_ROUNDING
    )


def calculate_coverage_goals(input_data: CoverageGoalsInput) -> CoverageGoalsResult:
    """Calculate expense coverage and goal progress from pure-domain input.

    No division by zero, no binary ``float``.  Zero denominators yield
    ``None`` plus an explanatory warning.
    """
    coverage_pct = _percent(
        input_data.forecast_monthly.kopecks, input_data.mandatory_expenses.kopecks
    )
    actual_mandatory_expense_coverage_pct = _percent(
        input_data.actual_average.kopecks, input_data.mandatory_expenses.kopecks
    )
    goal_progress_pct = _percent(
        input_data.forecast_monthly.kopecks, input_data.goal_target.kopecks
    )

    warnings = list(input_data.forecast_warnings)
    if coverage_pct is None:
        warnings.append("Обязательные расходы равны нулю — покрытие не рассчитывается")
    if goal_progress_pct is None:
        warnings.append("Цель равна нулю — прогресс не рассчитывается")

    return CoverageGoalsResult(
        forecast_monthly=input_data.forecast_monthly,
        actual_average=input_data.actual_average,
        mandatory_expenses=input_data.mandatory_expenses,
        coverage_pct=coverage_pct,
        actual_mandatory_expense_coverage_pct=actual_mandatory_expense_coverage_pct,
        passive_income_minus_mandatory_expenses=RubleAmount(
            input_data.forecast_monthly.kopecks - input_data.mandatory_expenses.kopecks
        ),
        goal_target=input_data.goal_target,
        goal_progress_pct=goal_progress_pct,
        is_approximate=input_data.is_approximate,
        warnings=tuple(warnings),
    )
