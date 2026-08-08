"""Expense entries API (D06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import ExpenseType, RubleAmount
from hermes_finance.services.expenses import (
    create_expense_entry,
    delete_expense_entry,
    get_expense_entry,
    list_expense_entries,
    update_expense_entry,
)

router = APIRouter(prefix="/api/expenses", tags=["expenses"])


class ExpenseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    category: str = Field(min_length=1, max_length=128)
    amount: MoneyValue
    expense_type: str = Field(min_length=1, max_length=32)
    is_recurring: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class ExpenseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, min_length=1, max_length=128)
    amount: MoneyValue | None = None
    expense_type: str | None = Field(default=None, min_length=1, max_length=32)
    is_recurring: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ExpenseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    category: str
    amount: MoneyValue
    expense_type: str
    is_recurring: bool
    notes: str | None


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


def _response(entry: object) -> ExpenseResponse:
    return ExpenseResponse(
        id=entry.id,
        reporting_month_id=entry.reporting_month_id,
        category=entry.category,
        amount=_money(entry.amount_kopecks),
        expense_type=entry.expense_type,
        is_recurring=entry.is_recurring,
        notes=entry.notes,
    )


@router.get("", response_model=list[ExpenseResponse])
def list_expenses(
    month_id: int = Query(...),
    expense_type: str | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[ExpenseResponse]:
    if expense_type is not None:
        _validate_expense_type(expense_type)
    entries = [
        entry
        for entry in list_expense_entries(session)
        if entry.reporting_month_id == month_id
        and (expense_type is None or entry.expense_type == expense_type)
    ]
    return [_response(entry) for entry in entries]


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    session: Session = Depends(session_for_request),
) -> ExpenseResponse:
    _validate_expense_type(payload.expense_type)
    entry = create_expense_entry(
        session,
        reporting_month_id=payload.reporting_month_id,
        category=payload.category,
        amount=_amount(payload.amount),
        expense_type=payload.expense_type,
        is_recurring=payload.is_recurring,
        notes=payload.notes,
    )
    return _response(entry)


@router.get("/{entry_id}", response_model=ExpenseResponse)
def get_expense(
    entry_id: int,
    session: Session = Depends(session_for_request),
) -> ExpenseResponse:
    return _response(get_expense_entry(session, entry_id))


@router.patch("/{entry_id}", response_model=ExpenseResponse)
def update_expense(
    entry_id: int,
    payload: ExpenseUpdate,
    session: Session = Depends(session_for_request),
) -> ExpenseResponse:
    if payload.expense_type is not None:
        _validate_expense_type(payload.expense_type)
    entry = update_expense_entry(
        session,
        entry_id,
        category=payload.category,
        amount=_amount(payload.amount) if payload.amount is not None else None,
        expense_type=payload.expense_type,
        is_recurring=payload.is_recurring,
        notes=payload.notes,
    )
    return _response(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    entry_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_expense_entry(session, entry_id)
