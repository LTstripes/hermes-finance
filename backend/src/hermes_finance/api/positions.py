"""Positions API (D05).

CRUD for position snapshots with optimistic concurrency via If-Match.
Server-side recalculation of market_value/cost_basis/unrealized_result
stays in the service layer (B09); this module only maps the HTTP boundary.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.read_cache import cached_read_endpoint
from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import InstrumentType, PriceSource, RubleAmount
from hermes_finance.services.instrument_names import instrument_names
from hermes_finance.services.month_position_returns import month_position_returns
from hermes_finance.services.positions import (
    UNCHANGED_IDENTITY,
    create_position_snapshot,
    delete_position_snapshot,
    get_position_snapshot_by_key,
    list_position_snapshots,
    update_position_snapshot,
)
from hermes_finance.services.source_monthly_returns import source_read_snapshot

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
    historical_instrument_type: InstrumentType | None = None


class PositionAllTimeResult(BaseModel):
    short_name: str | None = None
    amount: MoneyValue | None
    as_of: date | None
    period_start: date | None
    status: Literal["supported", "provisional", "partial", "unavailable"]
    reason_codes: list[str]


class PositionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int
    short_name: str | None = None
    historical_instrument_type: InstrumentType | None
    quantity: str
    average_cost_per_unit: MoneyValue | None
    market_price_per_unit: MoneyValue | None
    market_value: MoneyValue
    cost_basis: MoneyValue | None
    unrealized_result: MoneyValue | None
    all_time_result: PositionAllTimeResult | None = None
    accrued_interest: MoneyValue | None
    price_source: str
    price_date: date
    notes: str | None
    updated_at: datetime

    native_contract_version: int | None
    source_import_id: int | None
    source_row_key: str | None
    bond_nkd_basis: str


def _validate_price_source(value: str) -> str:
    try:
        PriceSource(value)
    except ValueError as error:
        raise ValueError("unsupported price source") from error
    return value


def _money_from_kopecks(kopecks: int | None, currency: str = "RUB") -> MoneyValue | None:
    if kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency=currency)


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _response_from_snapshot(snapshot: object, *, names=None) -> PositionResponse:
    return PositionResponse(
        short_name=names.name(instrument_id=snapshot.instrument_id) if names else None,
        id=snapshot.id,
        reporting_month_id=snapshot.reporting_month_id,
        account_id=snapshot.account_id,
        instrument_id=snapshot.instrument_id,
        historical_instrument_type=snapshot.historical_instrument_type,
        quantity=str(snapshot.quantity),
        average_cost_per_unit=_money_from_kopecks(snapshot.average_cost_per_unit_kopecks),
        market_price_per_unit=_money_from_kopecks(snapshot.market_price_per_unit_kopecks),
        market_value=MoneyValue(
            amount=RubleAmount(snapshot.market_value_kopecks).to_api(),
            currency="RUB",
        ),
        cost_basis=_money_from_kopecks(snapshot.cost_basis_kopecks),
        unrealized_result=_money_from_kopecks(snapshot.unrealized_result_kopecks),
        accrued_interest=_money_from_kopecks(snapshot.accrued_interest_kopecks),
        price_source=snapshot.price_source,
        price_date=snapshot.price_date,
        notes=snapshot.notes,
        updated_at=snapshot.updated_at,
        native_contract_version=snapshot.native_contract_version,
        source_import_id=snapshot.source_import_id,
        source_row_key=snapshot.source_row_key,
        bond_nkd_basis=snapshot.bond_nkd_basis,
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
    from hermes_finance.services.instrument_names import instrument_names

    snapshots = list_position_snapshots(session)
    names = instrument_names(session)
    return [
        _response_from_snapshot(s).model_copy(
            update={"short_name": names.name(instrument_id=s.instrument_id)}
        )
        for s in snapshots
        if s.reporting_month_id == month_id and (account_id is None or s.account_id == account_id)
    ]


@router.get("/all-time-results", response_model=dict[int, PositionAllTimeResult])
@cached_read_endpoint
def position_all_time_results(
    month_id: int = Query(...),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> dict[int, PositionAllTimeResult]:
    with source_read_snapshot(session):
        snapshots = [
            s
            for s in list_position_snapshots(session)
            if s.reporting_month_id == month_id
            and (account_id is None or s.account_id == account_id)
        ]
        results = month_position_returns(session, month_id, snapshots)
        from hermes_finance.services.instrument_names import instrument_names

        names = instrument_names(session)
        by_id = {row.id: row.instrument_id for row in snapshots}
        responses = {}
        for snapshot_id, value in results.items():
            result = dict(value)
            result["short_name"] = names.name(instrument_id=by_id[snapshot_id])
            result["amount"] = _money_from_kopecks(result.pop("amount_kopecks"))
            responses[snapshot_id] = PositionAllTimeResult(**result)
        return responses


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
        quantity=payload.quantity,
        average_cost_per_unit=_amount(payload.average_cost_per_unit),
        market_price_per_unit=_amount(payload.market_price_per_unit),
        accrued_interest=_amount(payload.accrued_interest)
        if payload.accrued_interest is not None
        else None,
        price_date=payload.price_date,
        price_source=payload.price_source,
        notes=payload.notes,
    )
    return _response_from_snapshot(snapshot, names=instrument_names(session))


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
        quantity=payload.quantity if payload.quantity is not None else None,
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
        historical_instrument_type=payload.historical_instrument_type
        if "historical_instrument_type" in payload.model_fields_set
        else UNCHANGED_IDENTITY,
    )
    return _response_from_snapshot(snapshot, names=instrument_names(session))


@router.delete("/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_position_endpoint(
    snapshot_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_position_snapshot(session, snapshot_id)
