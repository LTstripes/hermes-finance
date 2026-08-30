"""Cash balances API (E05 gap fill).

CRUD for month-scoped cash rows. Domain service lives in ``services.cash``;
this module is the HTTP boundary only.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.services.cash import (
    _UNSET,
    create_cash_balance,
    delete_cash_balance,
    get_cash_balance,
    list_cash_balances,
    total_cash,
    update_cash_balance,
)

router = APIRouter(prefix="/api/cash-balances", tags=["cash-balances"])


class CashBalanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int | None = None
    name: str = Field(min_length=1, max_length=128)
    amount: MoneyValue
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    include_in_capital: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class CashBalanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    account_id: int | None = None
    amount: MoneyValue | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    include_in_capital: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CashBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    account_id: int | None
    name: str
    amount: MoneyValue
    currency: str
    include_in_capital: bool
    notes: str | None


class CashTotalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    total: MoneyValue
    total_in_capital: MoneyValue


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int, currency: str = "RUB") -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency=currency)


def _response(balance: object) -> CashBalanceResponse:
    return CashBalanceResponse(
        id=balance.id,
        reporting_month_id=balance.reporting_month_id,
        account_id=balance.account_id,
        name=balance.name,
        amount=_money(balance.amount_kopecks, balance.currency),
        currency=balance.currency,
        include_in_capital=balance.include_in_capital,
        notes=balance.notes,
    )


@router.get("", response_model=list[CashBalanceResponse])
def list_cash_balances_endpoint(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[CashBalanceResponse]:
    rows = [row for row in list_cash_balances(session) if row.reporting_month_id == month_id]
    return [_response(row) for row in rows]


@router.get("/total", response_model=CashTotalResponse)
def cash_total_endpoint(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> CashTotalResponse:
    total = total_cash(session, month_id)
    in_capital = total_cash(session, month_id, include_in_capital_only=True)
    return CashTotalResponse(
        reporting_month_id=month_id,
        total=_money(total.kopecks),
        total_in_capital=_money(in_capital.kopecks),
    )


@router.post("", response_model=CashBalanceResponse, status_code=status.HTTP_201_CREATED)
def create_cash_balance_endpoint(
    payload: CashBalanceCreate,
    session: Session = Depends(session_for_request),
) -> CashBalanceResponse:
    balance = create_cash_balance(
        session,
        reporting_month_id=payload.reporting_month_id,
        account_id=payload.account_id,
        name=payload.name,
        amount=_amount(payload.amount),
        currency=payload.currency,
        include_in_capital=payload.include_in_capital,
        notes=payload.notes,
    )
    return _response(balance)


@router.get("/{balance_id}", response_model=CashBalanceResponse)
def get_cash_balance_endpoint(
    balance_id: int,
    session: Session = Depends(session_for_request),
) -> CashBalanceResponse:
    return _response(get_cash_balance(session, balance_id))


@router.patch("/{balance_id}", response_model=CashBalanceResponse)
def update_cash_balance_endpoint(
    balance_id: int,
    payload: CashBalanceUpdate,
    session: Session = Depends(session_for_request),
) -> CashBalanceResponse:
    balance = update_cash_balance(
        session,
        balance_id,
        account_id=(payload.account_id if "account_id" in payload.model_fields_set else _UNSET),
        name=payload.name,
        amount=_amount(payload.amount) if payload.amount is not None else None,
        currency=payload.currency,
        include_in_capital=payload.include_in_capital,
        notes=payload.notes,
    )
    return _response(balance)


@router.delete("/{balance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cash_balance_endpoint(
    balance_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_cash_balance(session, balance_id)
