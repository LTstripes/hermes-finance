"""ORM application service for expense coverage and goal progress (C05).

Loads the C04 forecast monthly passive income, the C03 actual average,
mandatory expenses of the reporting month and the main passive-income goal,
maps them into the pure domain calculator, and returns the domain result
DTO.  No API, no Pydantic, no React.

Implements MASTER_SPEC §10.7-§10.8:

    mandatory_expense_coverage_pct =
        forecast_monthly_net_passive_income / mandatory_expenses * 100

    passive_income_goal_progress_pct =
        forecast_monthly_net_passive_income / goal_target * 100

    passive_income_minus_mandatory_expenses =
        forecast_monthly_net_passive_income - mandatory_expenses

Key facts:
- The goal source of truth is the ``goals`` table (B19-R2); the main goal is
  created/loaded via ``get_or_create_main_goal`` seeded from app settings.
- Only ``mandatory`` expenses participate (wiki §7; saving allocations are
  not expenses for this coverage).
- ``coverage_pct`` / ``goal_progress_pct`` are ``None`` on zero denominator
  (UI must not show infinity).
- Reads on closed months are allowed (B19-R2 guard is for writes only).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import GoalType
from hermes_finance.domain.coverage_goals import (
    CoverageGoalsInput,
    CoverageGoalsResult,
    calculate_coverage_goals,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS,
    AppSettings,
    Goal,
)
from hermes_finance.services.expenses import total_mandatory_expenses
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.goals import MainGoalSelectionError
from hermes_finance.services.passive_income_average import passive_income_average


def coverage_and_goals(
    session: Session,
    reporting_month_id: int,
    forecast_version: str,
) -> CoverageGoalsResult:
    """Calculate expense coverage and goal progress for a reporting month.

    1. Forecast monthly passive income (C04) — carries ``is_approximate``
       and forecast warnings.
    2. Actual average (C03) — shown alongside the forecast per §10.7.
    3. Mandatory expenses of the reporting month (only ``mandatory`` type).
    4. Main passive-income goal from the ``goals`` table (B19-R2 source of
       truth, seeded from app settings).
    """
    forecast = forecast_passive_income(session, reporting_month_id, forecast_version)
    actual_average = passive_income_average(session).average
    mandatory = total_mandatory_expenses(session, reporting_month_id)
    # Coverage is a dashboard read path. Resolve the persisted main goal (or
    # one unambiguous active passive-income goal) without seeding rows. A
    # fresh database keeps the same default target in-memory only.
    main_target = session.scalar(select(Goal.target_value_kopecks).where(Goal.is_main.is_(True)))
    if main_target is None:
        candidates = list(
            session.scalars(
                select(Goal.target_value_kopecks).where(
                    Goal.goal_type == GoalType.PASSIVE_INCOME.value,
                    Goal.is_active.is_(True),
                )
            )
        )
        if len(candidates) > 1:
            raise MainGoalSelectionError(
                "multiple active passive-income goals exist without a persisted main selection; "
                "choose exactly one main goal"
            )
        if candidates:
            main_target = candidates[0]
        else:
            main_target = session.scalar(
                select(AppSettings.passive_income_goal_kopecks).where(
                    AppSettings.id == APP_SETTINGS_ID
                )
            )
            if main_target is None:
                main_target = DEFAULT_PASSIVE_INCOME_GOAL_KOPECKS

    return calculate_coverage_goals(
        CoverageGoalsInput(
            forecast_monthly=forecast.monthly_total,
            actual_average=actual_average,
            mandatory_expenses=mandatory,
            goal_target=RubleAmount(main_target),
            is_approximate=forecast.is_approximate,
            forecast_warnings=forecast.warnings,
        )
    )
