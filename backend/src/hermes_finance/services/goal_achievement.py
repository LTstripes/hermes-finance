"""Read-time goal achievement summary assembly for R02-12.

This service reuses canonical C04/C01 source metrics and computes each source
metric at most once per request.  It never persists an achievement date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from hermes_finance.domain import GoalType, RubleAmount
from hermes_finance.domain.goal_achievement import (
    GOAL_ACHIEVEMENT_METHOD_VERSION,
    GoalAchievementForecastResult,
    calculate_goal_achievement_forecast,
)
from hermes_finance.persistence import Goal
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.goals import list_goals
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.reporting_months import get_reporting_month

PASSIVE_INCOME_MODE = "monthly_net_passive_income"
LIQUID_CAPITAL_MODE = "liquid_capital_net"

_INACTIVE_WARNING = "Цель неактивна и не отслеживается"
_UNSUPPORTED_GOAL_TYPE_WARNING = "Тип цели не поддерживается прогнозом достижения"
_UNSUPPORTED_MODE_WARNING = "Режим расчёта цели не поддерживается прогнозом достижения"


@dataclass(frozen=True, slots=True)
class GoalAchievementSummaryItem:
    goal: Goal
    achievement_forecast: GoalAchievementForecastResult


def _inactive_forecast(
    goal: Goal, reporting_month_id: int, as_of_date: date
) -> GoalAchievementForecastResult:
    return GoalAchievementForecastResult(
        goal_id=goal.id,
        reporting_month_id=reporting_month_id,
        as_of_date=as_of_date,
        method_version=GOAL_ACHIEVEMENT_METHOD_VERSION,
        source_forecast_version=None,
        status="inactive",
        reason_code="goal_inactive",
        current_value=None,
        target_value=RubleAmount(goal.target_value_kopecks),
        remaining_amount=None,
        progress_pct=None,
        estimated_achievement_date=None,
        is_approximate=False,
        warnings=(_INACTIVE_WARNING,),
    )


def _unsupported_forecast(
    goal: Goal,
    reporting_month_id: int,
    as_of_date: date,
    *,
    reason_code: str,
    warning: str,
) -> GoalAchievementForecastResult:
    return GoalAchievementForecastResult(
        goal_id=goal.id,
        reporting_month_id=reporting_month_id,
        as_of_date=as_of_date,
        method_version=GOAL_ACHIEVEMENT_METHOD_VERSION,
        source_forecast_version=None,
        status="unsupported",
        reason_code=reason_code,
        current_value=None,
        target_value=RubleAmount(goal.target_value_kopecks),
        remaining_amount=None,
        progress_pct=None,
        estimated_achievement_date=None,
        is_approximate=False,
        warnings=(warning,),
    )


def build_goal_achievement_summary(
    session: Session,
    reporting_month_id: int,
    *,
    include_inactive: bool = False,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> list[GoalAchievementSummaryItem]:
    """Build the backend-derived goal summary for one reporting snapshot."""
    reporting_month = get_reporting_month(session, reporting_month_id)
    goals = list_goals(session, include_inactive=include_inactive)

    passive_goals = [
        goal
        for goal in goals
        if goal.is_active
        and goal.goal_type == GoalType.PASSIVE_INCOME.value
        and goal.calculation_mode == PASSIVE_INCOME_MODE
    ]
    capital_goals = [
        goal
        for goal in goals
        if goal.is_active
        and goal.goal_type == GoalType.CAPITAL.value
        and goal.calculation_mode == LIQUID_CAPITAL_MODE
    ]

    passive_forecast = (
        forecast_passive_income(session, reporting_month_id, forecast_version)
        if passive_goals
        else None
    )
    liquid_capital = (
        liquid_capital_for_month(session, reporting_month_id) if capital_goals else None
    )

    items: list[GoalAchievementSummaryItem] = []
    for goal in goals:
        if not goal.is_active:
            result = _inactive_forecast(goal, reporting_month_id, reporting_month.snapshot_date)
        elif goal.goal_type not in {
            GoalType.PASSIVE_INCOME.value,
            GoalType.CAPITAL.value,
        }:
            result = _unsupported_forecast(
                goal,
                reporting_month_id,
                reporting_month.snapshot_date,
                reason_code="unsupported_goal_type",
                warning=_UNSUPPORTED_GOAL_TYPE_WARNING,
            )
        elif (
            goal.goal_type == GoalType.PASSIVE_INCOME.value
            and goal.calculation_mode != PASSIVE_INCOME_MODE
        ):
            result = _unsupported_forecast(
                goal,
                reporting_month_id,
                reporting_month.snapshot_date,
                reason_code="unsupported_calculation_mode",
                warning=_UNSUPPORTED_MODE_WARNING,
            )
        elif (
            goal.goal_type == GoalType.CAPITAL.value
            and goal.calculation_mode != LIQUID_CAPITAL_MODE
        ):
            result = _unsupported_forecast(
                goal,
                reporting_month_id,
                reporting_month.snapshot_date,
                reason_code="unsupported_calculation_mode",
                warning=_UNSUPPORTED_MODE_WARNING,
            )
        elif goal.goal_type == GoalType.PASSIVE_INCOME.value:
            assert passive_forecast is not None
            result = calculate_goal_achievement_forecast(
                goal_id=goal.id,
                reporting_month_id=reporting_month_id,
                as_of_date=reporting_month.snapshot_date,
                current_value=passive_forecast.monthly_total,
                target_value=RubleAmount(goal.target_value_kopecks),
                source_forecast_version=forecast_version,
                is_approximate=passive_forecast.is_approximate,
                warnings=passive_forecast.warnings,
            )
        else:
            assert liquid_capital is not None
            result = calculate_goal_achievement_forecast(
                goal_id=goal.id,
                reporting_month_id=reporting_month_id,
                as_of_date=reporting_month.snapshot_date,
                current_value=liquid_capital.liquid_capital_net,
                target_value=RubleAmount(goal.target_value_kopecks),
                source_forecast_version=None,
            )
        items.append(GoalAchievementSummaryItem(goal=goal, achievement_forecast=result))

    return items
