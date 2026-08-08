"""Saving allocations API (D06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.services.expenses import (
    create_saving_allocation,
    delete_saving_allocation,
    get_saving_allocation,
    list_saving_allocations,
    update_saving_allocation,
)

router = APIRouter(prefix="/api/savings", tags=["savings"])


class SavingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    destination: str = Field(min_length=1, max_length=128)
    amount: MoneyValue
    notes: str | None = Field(default=None, max_length=2000)


class SavingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination: str | None = Field(default=None, min_length=1, max_length=128)
    amount: MoneyValue | None = None
    notes: str | None = Field(default=None, max_length=2000)


class SavingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    destination: str
    amount: MoneyValue
    notes: str | None


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(allocation: object) -> SavingResponse:
    return SavingResponse(
        id=allocation.id,
        reporting_month_id=allocation.reporting_month_id,
        destination=allocation.destination,
        amount=_money(allocation.amount_kopecks),
        notes=allocation.notes,
    )


@router.get("", response_model=list[SavingResponse])
def list_savings(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[SavingResponse]:
    allocations = [
        item for item in list_saving_allocations(session) if item.reporting_month_id == month_id
    ]
    return [_response(item) for item in allocations]


@router.post("", response_model=SavingResponse, status_code=status.HTTP_201_CREATED)
def create_saving(
    payload: SavingCreate,
    session: Session = Depends(session_for_request),
) -> SavingResponse:
    allocation = create_saving_allocation(
        session,
        reporting_month_id=payload.reporting_month_id,
        destination=payload.destination,
        amount=_amount(payload.amount),
        notes=payload.notes,
    )
    return _response(allocation)


@router.get("/{allocation_id}", response_model=SavingResponse)
def get_saving(
    allocation_id: int,
    session: Session = Depends(session_for_request),
) -> SavingResponse:
    return _response(get_saving_allocation(session, allocation_id))


@router.patch("/{allocation_id}", response_model=SavingResponse)
def update_saving(
    allocation_id: int,
    payload: SavingUpdate,
    session: Session = Depends(session_for_request),
) -> SavingResponse:
    allocation = update_saving_allocation(
        session,
        allocation_id,
        destination=payload.destination,
        amount=_amount(payload.amount) if payload.amount is not None else None,
        notes=payload.notes,
    )
    return _response(allocation)


@router.delete("/{allocation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saving(
    allocation_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_saving_allocation(session, allocation_id)
