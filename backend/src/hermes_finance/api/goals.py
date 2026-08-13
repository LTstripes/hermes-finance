from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.services.goal_achievement import (
    GoalAchievementSummaryItem,
    build_goal_achievement_summary,
)
from hermes_finance.services.goals import (
    create_goal,
    delete_goal,
    get_goal,
    get_or_create_main_goal,
    list_goals,
    update_goal,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION

router = APIRouter(prefix="/api/goals", tags=["goals"])


class GoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    goal_type: str = Field(min_length=1, max_length=32)
    target_value: MoneyValue
    target_date: date | None = None
    is_active: bool = True
    is_main: bool = False
    calculation_mode: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class GoalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    goal_type: str | None = Field(default=None, min_length=1, max_length=32)
    target_value: MoneyValue | None = None
    target_date: date | None = None
    is_active: bool | None = None
    is_main: bool | None = None
    calculation_mode: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    goal_type: str
    target_value: MoneyValue
    target_date: date | None
    is_active: bool
    is_main: bool
    calculation_mode: str
    notes: str | None


class GoalAchievementForecastResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: int
    reporting_month_id: int
    as_of_date: date
    method_version: Literal["goal_achievement_v1"]
    source_forecast_version: str | None
    status: Literal["achieved", "not_projectable", "inactive", "unsupported"]
    reason_code: str | None
    current_value: MoneyValue | None
    target_value: MoneyValue
    remaining_amount: MoneyValue | None
    progress_pct: str | None
    estimated_achievement_date: date | None
    is_approximate: bool
    warnings: list[str]
    passive_income_history_start_month: str | None
    passive_income_months_used: list[str]
    passive_income_months_count: int
    passive_income_months_complete: bool


class GoalSummaryResponse(GoalResponse):
    model_config = ConfigDict(extra="forbid")

    achievement_forecast: GoalAchievementForecastResponse


def _response(goal: object) -> GoalResponse:
    return GoalResponse(
        id=goal.id,
        name=goal.name,
        goal_type=goal.goal_type,
        target_value=MoneyValue(
            amount=RubleAmount(goal.target_value_kopecks).to_api(),
            currency="RUB",
        ),
        target_date=goal.target_date,
        is_active=goal.is_active,
        is_main=goal.is_main,
        calculation_mode=goal.calculation_mode,
        notes=goal.notes,
    )


def _money(amount: RubleAmount) -> MoneyValue:
    return MoneyValue(amount=amount.to_api(), currency="RUB")


def _money_optional(amount: RubleAmount | None) -> MoneyValue | None:
    return None if amount is None else _money(amount)


def _forecast_response(item: GoalAchievementSummaryItem) -> GoalSummaryResponse:
    goal_response = _response(item.goal)
    forecast = item.achievement_forecast
    return GoalSummaryResponse(
        **goal_response.model_dump(),
        achievement_forecast=GoalAchievementForecastResponse(
            goal_id=forecast.goal_id,
            reporting_month_id=forecast.reporting_month_id,
            as_of_date=forecast.as_of_date,
            method_version=forecast.method_version,
            source_forecast_version=forecast.source_forecast_version,
            status=forecast.status,
            reason_code=forecast.reason_code,
            current_value=_money_optional(forecast.current_value),
            target_value=_money(forecast.target_value),
            remaining_amount=_money_optional(forecast.remaining_amount),
            progress_pct=(
                None if forecast.progress_pct is None else format(forecast.progress_pct, "f")
            ),
            estimated_achievement_date=forecast.estimated_achievement_date,
            is_approximate=forecast.is_approximate,
            warnings=list(forecast.warnings),
            passive_income_history_start_month=forecast.configured_start_month,
            passive_income_months_used=list(forecast.months_used),
            passive_income_months_count=forecast.months_count,
            passive_income_months_complete=forecast.months_complete,
        ),
    )


@router.get("", response_model=list[GoalResponse])
def list_goals_endpoint(
    include_inactive: bool = Query(default=False),
    session: Session = Depends(session_for_request),
) -> list[GoalResponse]:
    get_or_create_main_goal(session)
    return [_response(goal) for goal in list_goals(session, include_inactive=include_inactive)]


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal_endpoint(
    payload: GoalCreate,
    session: Session = Depends(session_for_request),
) -> GoalResponse:
    goal = create_goal(
        session,
        name=payload.name,
        goal_type=payload.goal_type,
        target_value=RubleAmount.from_api(payload.target_value.amount),
        target_date=payload.target_date,
        is_active=payload.is_active,
        is_main=payload.is_main,
        calculation_mode=payload.calculation_mode,
        notes=payload.notes,
    )
    return _response(goal)


@router.get("/summary", response_model=list[GoalSummaryResponse])
def goal_summary_endpoint(
    reporting_month_id: int = Query(..., ge=1),
    include_inactive: bool = Query(default=False),
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    session: Session = Depends(session_for_request),
) -> list[GoalSummaryResponse]:
    return [
        _forecast_response(item)
        for item in build_goal_achievement_summary(
            session,
            reporting_month_id,
            include_inactive=include_inactive,
            forecast_version=forecast_version,
        )
    ]


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal_endpoint(
    goal_id: int,
    session: Session = Depends(session_for_request),
) -> GoalResponse:
    return _response(get_goal(session, goal_id))


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal_endpoint(
    goal_id: int,
    payload: GoalUpdate,
    session: Session = Depends(session_for_request),
) -> GoalResponse:
    goal = update_goal(
        session,
        goal_id,
        name=payload.name,
        goal_type=payload.goal_type,
        target_value=(
            RubleAmount.from_api(payload.target_value.amount)
            if payload.target_value is not None
            else None
        ),
        target_date=payload.target_date,
        is_active=payload.is_active,
        is_main=payload.is_main,
        calculation_mode=payload.calculation_mode,
        notes=payload.notes,
    )
    return _response(goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal_endpoint(
    goal_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_goal(session, goal_id)
