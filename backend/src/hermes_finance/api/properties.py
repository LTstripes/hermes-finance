"""Property snapshots API (D06)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import PercentageRate, RubleAmount
from hermes_finance.services.properties import (
    _UNSET,
    create_property_snapshot,
    delete_property_snapshot,
    get_property_snapshot,
    list_property_snapshots,
    update_property_snapshot,
)

router = APIRouter(prefix="/api/properties", tags=["properties"])


class PropertyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    name: str = Field(min_length=1, max_length=128)
    estimated_value: MoneyValue
    mortgage_balance: MoneyValue
    monthly_payment: MoneyValue
    mortgage_annual_rate: str | None = Field(default=None, min_length=1)
    notes: str | None = Field(default=None, max_length=2000)


class PropertyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    estimated_value: MoneyValue | None = None
    mortgage_balance: MoneyValue | None = None
    monthly_payment: MoneyValue | None = None
    mortgage_annual_rate: str | None = Field(default=None, min_length=1)
    notes: str | None = Field(default=None, max_length=2000)


class PropertyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    name: str
    estimated_value: MoneyValue
    mortgage_balance: MoneyValue
    monthly_payment: MoneyValue
    mortgage_annual_rate: str | None
    notes: str | None


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _rate(basis_points: int | None) -> str | None:
    if basis_points is None:
        return None
    return PercentageRate(basis_points).to_api()


def _response(snapshot: object) -> PropertyResponse:
    return PropertyResponse(
        id=snapshot.id,
        reporting_month_id=snapshot.reporting_month_id,
        name=snapshot.name,
        estimated_value=_money(snapshot.estimated_value_kopecks),
        mortgage_balance=_money(snapshot.mortgage_balance_kopecks),
        monthly_payment=_money(snapshot.monthly_payment_kopecks),
        mortgage_annual_rate=_rate(snapshot.mortgage_annual_rate_basis_points),
        notes=snapshot.notes,
    )


@router.get("", response_model=list[PropertyResponse])
def list_properties(
    month_id: int = Query(...),
    session: Session = Depends(session_for_request),
) -> list[PropertyResponse]:
    snapshots = [
        item for item in list_property_snapshots(session) if item.reporting_month_id == month_id
    ]
    return [_response(item) for item in snapshots]


@router.post("", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def create_property(
    payload: PropertyCreate,
    session: Session = Depends(session_for_request),
) -> PropertyResponse:
    snapshot = create_property_snapshot(
        session,
        reporting_month_id=payload.reporting_month_id,
        name=payload.name,
        estimated_value=_amount(payload.estimated_value),
        mortgage_balance=_amount(payload.mortgage_balance),
        monthly_payment=_amount(payload.monthly_payment),
        mortgage_annual_rate=payload.mortgage_annual_rate,
        notes=payload.notes,
    )
    return _response(snapshot)


@router.get("/{snapshot_id}", response_model=PropertyResponse)
def get_property(
    snapshot_id: int,
    session: Session = Depends(session_for_request),
) -> PropertyResponse:
    return _response(get_property_snapshot(session, snapshot_id))


@router.patch("/{snapshot_id}", response_model=PropertyResponse)
def update_property(
    snapshot_id: int,
    payload: PropertyUpdate,
    session: Session = Depends(session_for_request),
) -> PropertyResponse:
    snapshot = update_property_snapshot(
        session,
        snapshot_id,
        name=payload.name,
        estimated_value=_amount(payload.estimated_value)
        if payload.estimated_value is not None
        else None,
        mortgage_balance=_amount(payload.mortgage_balance)
        if payload.mortgage_balance is not None
        else None,
        monthly_payment=_amount(payload.monthly_payment)
        if payload.monthly_payment is not None
        else None,
        mortgage_annual_rate=payload.mortgage_annual_rate
        if "mortgage_annual_rate" in payload.model_fields_set
        else _UNSET,
        notes=payload.notes,
    )
    return _response(snapshot)


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    snapshot_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_property_snapshot(session, snapshot_id)
