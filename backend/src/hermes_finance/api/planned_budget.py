"""Planned budget lines API (#336)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import ExpenseType, RubleAmount
from hermes_finance.services.planned_budget import (
    create_planned_budget_line,
    delete_planned_budget_line,
    get_planned_budget_line,
    list_planned_budget_lines,
    plan_vs_actual,
    update_planned_budget_line,
)

router = APIRouter(prefix="/api/planned-budget", tags=["planned-budget"])


class PlannedBudgetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    category: str = Field(min_length=1, max_length=128)
    planned_amount: MoneyValue
    expense_type: str = Field(min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)


class PlannedBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, min_length=1, max_length=128)
    planned_amount: MoneyValue | None = None
    expense_type: str | None = Field(default=None, min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=2000)


class PlannedBudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    category: str
    planned_amount: MoneyValue
    expense_type: str
    notes: str | None


class PlanVsActualRow(BaseModel):
    category: str
    expense_type: str
    planned: MoneyValue
    actual: MoneyValue


def _validate_expense_type(value: str) -> str:
    try:
        ExpenseType(value)
    except ValueError as error:
        raise ValueError(f"unsupported expense type: {value!r}") from error
    return value


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(line: object) -> PlannedBudgetResponse:
    return PlannedBudgetResponse(
        id=line.id,
        reporting_month_id=line.reporting_month_id,
        category=line.category,
        planned_amount=_money(line.planned_amount_kopecks),
        expense_type=line.expense_type,
        notes=line.notes,
    )


@router.get("", response_model=list[PlannedBudgetResponse])
def list_planned_budget_endpoint(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[PlannedBudgetResponse]:
    lines = [
        line for line in list_planned_budget_lines(session) if line.reporting_month_id == month_id
    ]
    return [_response(line) for line in lines]


@router.get("/comparison", response_model=list[PlanVsActualRow])
def planned_vs_actual_endpoint(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[PlanVsActualRow]:
    return [
        PlanVsActualRow(
            category=row.category,
            expense_type=row.expense_type,
            planned=_money(row.planned.kopecks),
            actual=_money(row.actual.kopecks),
        )
        for row in plan_vs_actual(session, month_id)
    ]


@router.post("", response_model=PlannedBudgetResponse, status_code=status.HTTP_201_CREATED)
def create_planned_budget_endpoint(
    payload: PlannedBudgetCreate,
    session: Session = Depends(session_for_request),
) -> PlannedBudgetResponse:
    _validate_expense_type(payload.expense_type)
    line = create_planned_budget_line(
        session,
        reporting_month_id=payload.reporting_month_id,
        category=payload.category,
        planned_amount=_amount(payload.planned_amount),
        expense_type=payload.expense_type,
        notes=payload.notes,
    )
    return _response(line)


@router.get("/{line_id}", response_model=PlannedBudgetResponse)
def get_planned_budget_endpoint(
    line_id: int,
    session: Session = Depends(session_for_request),
) -> PlannedBudgetResponse:
    return _response(get_planned_budget_line(session, line_id))


@router.patch("/{line_id}", response_model=PlannedBudgetResponse)
def update_planned_budget_endpoint(
    line_id: int,
    payload: PlannedBudgetUpdate,
    session: Session = Depends(session_for_request),
) -> PlannedBudgetResponse:
    if payload.expense_type is not None:
        _validate_expense_type(payload.expense_type)
    line = update_planned_budget_line(
        session,
        line_id,
        category=payload.category,
        planned_amount=_amount(payload.planned_amount)
        if payload.planned_amount is not None
        else None,
        expense_type=payload.expense_type,
        notes=payload.notes,
    )
    return _response(line)


@router.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_planned_budget_endpoint(
    line_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_planned_budget_line(session, line_id)
