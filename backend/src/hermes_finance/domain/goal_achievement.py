"""Pure-domain result and exact semantics for goal achievement v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount

GOAL_ACHIEVEMENT_METHOD_VERSION = "goal_achievement_v1"


@dataclass(frozen=True, slots=True)
class GoalAchievementForecastResult:
    goal_id: int
    reporting_month_id: int
    as_of_date: date
    method_version: str
    source_forecast_version: str | None
    status: str
    reason_code: str | None
    current_value: RubleAmount | None
    target_value: RubleAmount
    remaining_amount: RubleAmount | None
    progress_pct: Decimal | None
    estimated_achievement_date: date | None
    is_approximate: bool
    warnings: tuple[str, ...]


def calculate_goal_achievement_forecast(
    *,
    goal_id: int,
    reporting_month_id: int,
    as_of_date: date,
    current_value: RubleAmount,
    target_value: RubleAmount,
    source_forecast_version: str | None,
    is_approximate: bool = False,
    warnings: tuple[str, ...] = (),
) -> GoalAchievementForecastResult:
    """Evaluate one supported active goal at a reporting snapshot.

    This deliberately performs only a current-state comparison.  It does not
    infer a trajectory or a future date when the current value is below target.
    """
    remaining_kopecks = max(target_value.kopecks - current_value.kopecks, 0)
    progress_pct = None
    if target_value.kopecks != 0:
        progress_pct = (
            Decimal(current_value.kopecks) / Decimal(target_value.kopecks) * Decimal(100)
        ).quantize(Decimal("0.01"), rounding=FINANCIAL_ROUNDING)

    achieved = current_value.kopecks >= target_value.kopecks
    return GoalAchievementForecastResult(
        goal_id=goal_id,
        reporting_month_id=reporting_month_id,
        as_of_date=as_of_date,
        method_version=GOAL_ACHIEVEMENT_METHOD_VERSION,
        source_forecast_version=source_forecast_version,
        status="achieved" if achieved else "not_projectable",
        reason_code=None if achieved else "no_trajectory_model",
        current_value=current_value,
        target_value=target_value,
        remaining_amount=RubleAmount(remaining_kopecks),
        progress_pct=progress_pct,
        estimated_achievement_date=as_of_date if achieved else None,
        is_approximate=is_approximate,
        warnings=warnings,
    )
