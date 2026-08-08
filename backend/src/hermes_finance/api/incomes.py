"""Income entries API (D06)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import IncomeType, RubleAmount
from hermes_finance.services.incomes import (
    create_income_entry,
    delete_income_entry,
    get_income_entry,
    list_income_entries,
    update_income_entry,
)

router = APIRouter(prefix="/api/incomes", tags=["incomes"])


class IncomeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    income_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    gross_amount: MoneyValue
    tax_amount: MoneyValue
    net_amount: MoneyValue
    received_at: date | None = None
    is_recurring: bool = False
    include_in_cash_flow: bool = True
    include_in_passive_income: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class IncomeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    income_type: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=128)
    gross_amount: MoneyValue | None = None
    tax_amount: MoneyValue | None = None
    net_amount: MoneyValue | None = None
    received_at: date | None = None
    is_recurring: bool | None = None
    include_in_cash_flow: bool | None = None
    include_in_passive_income: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class IncomeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    income_type: str
    name: str
    gross_amount: MoneyValue
    tax_amount: MoneyValue
    net_amount: MoneyValue
    received_at: date | None
    is_recurring: bool
    include_in_cash_flow: bool
    include_in_passive_income: bool
    notes: str | None


def _validate_income_type(value: str) -> str:
    try:
        IncomeType(value)
    except ValueError as error:
        raise ValueError(f"unsupported income type: {value!r}") from error
    return value


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(entry: object) -> IncomeResponse:
    return IncomeResponse(
        id=entry.id,
        reporting_month_id=entry.reporting_month_id,
        income_type=entry.income_type,
        name=entry.name,
        gross_amount=_money(entry.gross_amount_kopecks),
        tax_amount=_money(entry.tax_amount_kopecks),
        net_amount=_money(entry.net_amount_kopecks),
        received_at=entry.received_at,
        is_recurring=entry.is_recurring,
        include_in_cash_flow=entry.include_in_cash_flow,
        include_in_passive_income=entry.include_in_passive_income,
        notes=entry.notes,
    )


@router.get("", response_model=list[IncomeResponse])
def list_incomes(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[IncomeResponse]:
    entries = [
        entry for entry in list_income_entries(session) if entry.reporting_month_id == month_id
    ]
    return [_response(entry) for entry in entries]


@router.post("", response_model=IncomeResponse, status_code=status.HTTP_201_CREATED)
def create_income(
    payload: IncomeCreate,
    session: Session = Depends(session_for_request),
) -> IncomeResponse:
    _validate_income_type(payload.income_type)
    entry = create_income_entry(
        session,
        reporting_month_id=payload.reporting_month_id,
        income_type=payload.income_type,
        name=payload.name,
        gross_amount=_amount(payload.gross_amount),
        tax_amount=_amount(payload.tax_amount),
        net_amount=_amount(payload.net_amount),
        received_at=payload.received_at,
        is_recurring=payload.is_recurring,
        include_in_cash_flow=payload.include_in_cash_flow,
        include_in_passive_income=payload.include_in_passive_income,
        notes=payload.notes,
    )
    return _response(entry)


@router.get("/{entry_id}", response_model=IncomeResponse)
def get_income(
    entry_id: int,
    session: Session = Depends(session_for_request),
) -> IncomeResponse:
    return _response(get_income_entry(session, entry_id))


@router.patch("/{entry_id}", response_model=IncomeResponse)
def update_income(
    entry_id: int,
    payload: IncomeUpdate,
    session: Session = Depends(session_for_request),
) -> IncomeResponse:
    if payload.income_type is not None:
        _validate_income_type(payload.income_type)
    entry = update_income_entry(
        session,
        entry_id,
        income_type=payload.income_type,
        name=payload.name,
        gross_amount=_amount(payload.gross_amount) if payload.gross_amount is not None else None,
        tax_amount=_amount(payload.tax_amount) if payload.tax_amount is not None else None,
        net_amount=_amount(payload.net_amount) if payload.net_amount is not None else None,
        received_at=payload.received_at,
        is_recurring=payload.is_recurring,
        include_in_cash_flow=payload.include_in_cash_flow,
        include_in_passive_income=payload.include_in_passive_income,
        notes=payload.notes,
    )
    return _response(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_income(
    entry_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_income_entry(session, entry_id)
