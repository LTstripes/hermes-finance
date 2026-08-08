"""Debts API (D06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import DebtType, RubleAmount
from hermes_finance.services.debts import (
    create_debt,
    delete_debt,
    get_debt,
    list_debts,
    update_debt,
)

router = APIRouter(prefix="/api/debts", tags=["debts"])


class DebtCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    debt_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    current_balance: MoneyValue
    include_in_liquid_capital: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class DebtUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    debt_type: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    current_balance: MoneyValue | None = None
    include_in_liquid_capital: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DebtResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    debt_type: str
    name: str
    current_balance: MoneyValue
    include_in_liquid_capital: bool
    notes: str | None


def _validate_debt_type(value: str) -> str:
    try:
        DebtType(value)
    except ValueError as error:
        raise ValueError(f"unsupported debt type: {value!r}") from error
    return value


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(debt: object) -> DebtResponse:
    return DebtResponse(
        id=debt.id,
        reporting_month_id=debt.reporting_month_id,
        debt_type=debt.debt_type,
        name=debt.name,
        current_balance=_money(debt.current_balance_kopecks),
        include_in_liquid_capital=debt.include_in_liquid_capital,
        notes=debt.notes,
    )


@router.get("", response_model=list[DebtResponse])
def list_debts_endpoint(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[DebtResponse]:
    debts = [debt for debt in list_debts(session) if debt.reporting_month_id == month_id]
    return [_response(debt) for debt in debts]


@router.post("", response_model=DebtResponse, status_code=status.HTTP_201_CREATED)
def create_debt_endpoint(
    payload: DebtCreate,
    session: Session = Depends(session_for_request),
) -> DebtResponse:
    _validate_debt_type(payload.debt_type)
    debt = create_debt(
        session,
        reporting_month_id=payload.reporting_month_id,
        debt_type=payload.debt_type,
        name=payload.name,
        current_balance=_amount(payload.current_balance),
        include_in_liquid_capital=payload.include_in_liquid_capital,
        notes=payload.notes,
    )
    return _response(debt)


@router.get("/{debt_id}", response_model=DebtResponse)
def get_debt_endpoint(
    debt_id: int,
    session: Session = Depends(session_for_request),
) -> DebtResponse:
    return _response(get_debt(session, debt_id))


@router.patch("/{debt_id}", response_model=DebtResponse)
def update_debt_endpoint(
    debt_id: int,
    payload: DebtUpdate,
    session: Session = Depends(session_for_request),
) -> DebtResponse:
    if payload.debt_type is not None:
        _validate_debt_type(payload.debt_type)
    debt = update_debt(
        session,
        debt_id,
        debt_type=payload.debt_type,
        name=payload.name,
        current_balance=_amount(payload.current_balance)
        if payload.current_balance is not None
        else None,
        include_in_liquid_capital=payload.include_in_liquid_capital,
        notes=payload.notes,
    )
    return _response(debt)


@router.delete("/{debt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_debt_endpoint(
    debt_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_debt(session, debt_id)
