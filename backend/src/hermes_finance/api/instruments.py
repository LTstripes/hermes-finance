"""Instruments API (D04).

CRUD for the instruments reference dictionary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.services.instruments import (
    InstrumentCleanupResult,
    create_instrument,
    delete_instrument,
    get_instrument,
    get_instrument_by_isin,
    get_instrument_cleanup,
    list_instruments,
    update_instrument,
)

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


class InstrumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    instrument_type: str = Field(min_length=1, max_length=16)
    isin: str | None = Field(default=None, max_length=12)
    ticker: str | None = Field(default=None, max_length=32)
    moex_secid: str | None = Field(default=None, max_length=32)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    nominal_value: MoneyValue | None = None
    is_active: bool = True
    manual_price_allowed: bool = True
    notes: str | None = Field(default=None, max_length=2000)


class InstrumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    instrument_type: str | None = Field(default=None, min_length=1, max_length=16)
    isin: str | None = Field(default=None, max_length=12)
    ticker: str | None = Field(default=None, max_length=32)
    moex_secid: str | None = Field(default=None, max_length=32)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    nominal_value: MoneyValue | None = None
    is_active: bool | None = None
    manual_price_allowed: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class InstrumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    instrument_type: str
    isin: str | None
    ticker: str | None
    moex_secid: str | None
    currency: str
    nominal_value: MoneyValue | None
    is_active: bool
    manual_price_allowed: bool
    notes: str | None


class InstrumentCleanupReferenceResponse(BaseModel):
    kind: str
    lifecycle: str
    count: int
    month_labels: list[str]


class InstrumentCleanupDuplicateResponse(BaseModel):
    instrument_id: int
    name: str
    basis: str


class InstrumentCleanupResponse(BaseModel):
    instrument_id: int
    can_delete: bool
    status: str
    reason_code: str
    message: str
    references: list[InstrumentCleanupReferenceResponse]
    active_duplicates: list[InstrumentCleanupDuplicateResponse]


def _validate_instrument_type(value: str) -> str:
    try:
        InstrumentType(value)
    except ValueError as error:
        raise ValueError(f"unsupported instrument type: {value!r}") from error
    return value


def _nominal_amount(model: object | None) -> RubleAmount | None:
    if model is None:
        return None
    return RubleAmount.from_api(model.amount)


def _response_from_instrument(instrument: object) -> InstrumentResponse:
    nominal = None
    if instrument.nominal_value_kopecks is not None:
        nominal = MoneyValue(
            amount=RubleAmount(instrument.nominal_value_kopecks).to_api(),
            currency=instrument.currency,
        )
    return InstrumentResponse(
        id=instrument.id,
        name=instrument.name,
        instrument_type=instrument.instrument_type,
        isin=instrument.isin,
        ticker=instrument.ticker,
        moex_secid=instrument.moex_secid,
        currency=instrument.currency,
        nominal_value=nominal,
        is_active=instrument.is_active,
        manual_price_allowed=instrument.manual_price_allowed,
        notes=instrument.notes,
    )


def _cleanup_response(cleanup: InstrumentCleanupResult) -> InstrumentCleanupResponse:
    return InstrumentCleanupResponse(
        instrument_id=cleanup.instrument_id,
        can_delete=cleanup.can_delete,
        status=cleanup.status,
        reason_code=cleanup.reason_code,
        message=cleanup.message,
        references=[
            InstrumentCleanupReferenceResponse(
                kind=reference.kind,
                lifecycle=reference.lifecycle,
                count=reference.count,
                month_labels=list(reference.month_labels),
            )
            for reference in cleanup.references
        ],
        active_duplicates=[
            InstrumentCleanupDuplicateResponse(
                instrument_id=duplicate.instrument_id,
                name=duplicate.name,
                basis=duplicate.basis,
            )
            for duplicate in cleanup.active_duplicates
        ],
    )


@router.get("", response_model=list[InstrumentResponse])
def list_instruments_endpoint(
    active: bool | None = Query(default=None),
    instrument_type: str | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[InstrumentResponse]:
    instruments = list_instruments(session)
    if active is not None:
        instruments = [i for i in instruments if i.is_active == active]
    if instrument_type is not None:
        _validate_instrument_type(instrument_type)
        instruments = [i for i in instruments if i.instrument_type == instrument_type]
    return [_response_from_instrument(i) for i in instruments]


@router.post(
    "",
    response_model=InstrumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_instrument_endpoint(
    payload: InstrumentCreate,
    session: Session = Depends(session_for_request),
) -> InstrumentResponse:
    _validate_instrument_type(payload.instrument_type)
    if payload.isin is not None:
        existing = get_instrument_by_isin(session, payload.isin)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"isin '{payload.isin}' already exists",
            )
    instrument = create_instrument(
        session,
        name=payload.name,
        instrument_type=payload.instrument_type,
        isin=payload.isin,
        ticker=payload.ticker,
        moex_secid=payload.moex_secid,
        currency=payload.currency,
        nominal_value=_nominal_amount(payload.nominal_value),
        is_active=payload.is_active,
        manual_price_allowed=payload.manual_price_allowed,
        notes=payload.notes,
    )
    return _response_from_instrument(instrument)


@router.get("/{instrument_id}/cleanup", response_model=InstrumentCleanupResponse)
def inspect_instrument_cleanup_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> InstrumentCleanupResponse:
    return _cleanup_response(get_instrument_cleanup(session, instrument_id))


@router.get("/{instrument_id}", response_model=InstrumentResponse)
def get_instrument_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> InstrumentResponse:
    return _response_from_instrument(get_instrument(session, instrument_id))


@router.patch("/{instrument_id}", response_model=InstrumentResponse)
def update_instrument_endpoint(
    instrument_id: int,
    payload: InstrumentUpdate,
    session: Session = Depends(session_for_request),
) -> InstrumentResponse:
    if payload.instrument_type is not None:
        _validate_instrument_type(payload.instrument_type)
    if payload.isin is not None:
        existing = get_instrument_by_isin(session, payload.isin)
        if existing is not None and existing.id != instrument_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"isin '{payload.isin}' already exists",
            )
    instrument = update_instrument(
        session,
        instrument_id,
        name=payload.name,
        instrument_type=payload.instrument_type,
        isin=payload.isin,
        ticker=payload.ticker,
        moex_secid=payload.moex_secid,
        currency=payload.currency,
        nominal_value=_nominal_amount(payload.nominal_value),
        is_active=payload.is_active,
        manual_price_allowed=payload.manual_price_allowed,
        notes=payload.notes,
    )
    return _response_from_instrument(instrument)


@router.delete("/{instrument_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_instrument_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_instrument(session, instrument_id)
