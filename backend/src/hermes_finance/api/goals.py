from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.services.goals import (
    create_goal,
    delete_goal,
    get_goal,
    get_or_create_main_goal,
    list_goals,
    update_goal,
)

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
