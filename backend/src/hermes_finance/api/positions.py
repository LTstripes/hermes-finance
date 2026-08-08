"""Positions API (D05).

CRUD for position snapshots with optimistic concurrency via If-Match.
Server-side recalculation of market_value/cost_basis/unrealized_result
stays in the service layer (B09); this module only maps the HTTP boundary.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import PriceSource, RubleAmount
from hermes_finance.services.positions import (
    create_position_snapshot,
    delete_position_snapshot,
    get_position_snapshot_by_key,
    list_position_snapshots,
    update_position_snapshot,
)

router = APIRouter(prefix="/api/positions", tags=["positions"])


class PositionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int
    instrument_id: int
    quantity: str = Field(min_length=1)
    average_cost_per_unit: MoneyValue
    market_price_per_unit: MoneyValue
    accrued_interest: MoneyValue | None = None
    price_source: str = Field(default="manual", min_length=1, max_length=16)
    price_date: date
    notes: str | None = Field(default=None, max_length=2000)


class PositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: str | None = Field(default=None, min_length=1)
    average_cost_per_unit: MoneyValue | None = None
    market_price_per_unit: MoneyValue | None = None
    accrued_interest: MoneyValue | None = None
    price_source: str | None = Field(default=None, min_length=1, max_length=16)
    price_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int
    quantity: str
    average_cost_per_unit: MoneyValue
    market_price_per_unit: MoneyValue
    market_value: MoneyValue
    cost_basis: MoneyValue
    unrealized_result: MoneyValue
    accrued_interest: MoneyValue | None
    price_source: str
    price_date: date
    notes: str | None
    updated_at: datetime


def _validate_price_source(value: str) -> str:
    try:
        PriceSource(value)
    except ValueError as error:
        raise ValueError(f"unsupported price source: {value!r}") from error
    return value


def _money_from_kopecks(kopecks: int | None, currency: str = "RUB") -> MoneyValue | None:
    if kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency=currency)


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _response_from_snapshot(snapshot: object) -> PositionResponse:
    return PositionResponse(
        id=snapshot.id,
        reporting_month_id=snapshot.reporting_month_id,
        account_id=snapshot.account_id,
        instrument_id=snapshot.instrument_id,
        quantity=str(snapshot.quantity),
        average_cost_per_unit=MoneyValue(
            amount=RubleAmount(snapshot.average_cost_per_unit_kopecks).to_api(),
            currency="RUB",
        ),
        market_price_per_unit=MoneyValue(
            amount=RubleAmount(snapshot.market_price_per_unit_kopecks).to_api(),
            currency="RUB",
        ),
        market_value=MoneyValue(
            amount=RubleAmount(snapshot.market_value_kopecks).to_api(),
            currency="RUB",
        ),
        cost_basis=MoneyValue(
            amount=RubleAmount(snapshot.cost_basis_kopecks).to_api(),
            currency="RUB",
        ),
        unrealized_result=MoneyValue(
            amount=RubleAmount(snapshot.unrealized_result_kopecks).to_api(),
            currency="RUB",
        ),
        accrued_interest=_money_from_kopecks(snapshot.accrued_interest_kopecks),
        price_source=snapshot.price_source,
        price_date=snapshot.price_date,
        notes=snapshot.notes,
        updated_at=snapshot.updated_at,
    )


def _parse_if_match(if_match: str | None) -> datetime | None:
    if if_match is None:
        return None
    return datetime.fromisoformat(if_match)


@router.get("", response_model=list[PositionResponse])
def list_positions_endpoint(
    month_id: int = Query(...),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[PositionResponse]:
    snapshots = list_position_snapshots(session)
    snapshots = [s for s in snapshots if s.reporting_month_id == month_id]
    if account_id is not None:
        snapshots = [s for s in snapshots if s.account_id == account_id]
    return [_response_from_snapshot(s) for s in snapshots]


@router.post(
    "",
    response_model=PositionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_position_endpoint(
    payload: PositionCreate,
    session: Session = Depends(session_for_request),
) -> PositionResponse:
    _validate_price_source(payload.price_source)
    if (
        get_position_snapshot_by_key(
            session,
            reporting_month_id=payload.reporting_month_id,
            account_id=payload.account_id,
            instrument_id=payload.instrument_id,
        )
        is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="position snapshot already exists for month, account and instrument",
        )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=payload.reporting_month_id,
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        quantity=Decimal(payload.quantity),
        average_cost_per_unit=_amount(payload.average_cost_per_unit),
        market_price_per_unit=_amount(payload.market_price_per_unit),
        accrued_interest=_amount(payload.accrued_interest)
        if payload.accrued_interest is not None
        else None,
        price_date=payload.price_date,
        price_source=payload.price_source,
        notes=payload.notes,
    )
    return _response_from_snapshot(snapshot)


@router.patch("/{snapshot_id}", response_model=PositionResponse)
def update_position_endpoint(
    snapshot_id: int,
    payload: PositionUpdate,
    if_match: str | None = Header(default=None),
    session: Session = Depends(session_for_request),
) -> PositionResponse:
    if if_match is None:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="If-Match header is required for position updates",
        )
    expected_updated_at = _parse_if_match(if_match)
    if payload.price_source is not None:
        _validate_price_source(payload.price_source)
    snapshot = update_position_snapshot(
        session,
        snapshot_id,
        quantity=Decimal(payload.quantity) if payload.quantity is not None else None,
        average_cost_per_unit=_amount(payload.average_cost_per_unit)
        if payload.average_cost_per_unit is not None
        else None,
        market_price_per_unit=_amount(payload.market_price_per_unit)
        if payload.market_price_per_unit is not None
        else None,
        accrued_interest=_amount(payload.accrued_interest)
        if payload.accrued_interest is not None
        else None,
        price_date=payload.price_date,
        price_source=payload.price_source,
        notes=payload.notes,
        expected_updated_at=expected_updated_at,
    )
    return _response_from_snapshot(snapshot)


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position_endpoint(
    snapshot_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_position_snapshot(session, snapshot_id)
