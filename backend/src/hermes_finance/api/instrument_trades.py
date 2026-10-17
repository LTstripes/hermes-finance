"""Strict GET-only known execution evidence."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.instrument_cash_income import Ref
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.instrument_trades import known_instrument_trades

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Occurrence(Strict):
    import_id: int
    section: str
    ordinal: int
    row_fingerprint: str


class HistoricalIdentity(Strict):
    isin: str
    instrument_type: Literal["stock", "bond"]
    denomination: Literal["RUB"]


class CashLeg(Strict):
    role: Literal["settlement", "paid_nkd", "commission"]
    proof_class: Literal["effective_cash_leg_authority", "unavailable"]
    signed_rub: str | None
    signed_kopecks: str | None
    effective_date: date | None
    in_interval: bool | None
    basis: str | None
    receipt_id: str | None
    occurrences: list[Occurrence]
    reason_codes: list[str]


class KnownTrade(Strict):
    trade_id: int
    account_id: int
    instrument_id: int
    source_identity: str
    native_ids: list[str]
    proof_class: Literal["observed_native_execution"]
    revision: int | None
    currentness: Literal["current", "unavailable"]
    historical_identity: HistoricalIdentity | None
    side: Literal["BUY", "SELL"] | None
    signed_quantity: str | None
    execution_date: date | None
    execution_in_interval: bool | None
    settlement_date: date | None
    settlement_in_interval: bool | None
    depository_date: date | None
    depository_in_interval: bool | None
    planned_settlement_date: date | None
    lifecycle: Literal["settled", "pending"] | None
    source_occurrences: list[Occurrence]
    cash_legs: list[CashLeg]
    reason_codes: list[str]


class KnownTrades(Strict):
    method: Literal["known-instrument-trades"]
    version: Literal[1]
    account: Ref
    instrument: Ref
    t0: date
    t1: date
    currency: Literal["RUB"]
    trade_history_completeness: Literal["unknown"]
    financial_coverage: Literal["unknown"]
    status: Literal["available", "capacity_exceeded"]
    capacity: int
    known_count: int | None
    events: list[KnownTrade]
    dependency_digest: str
    dependency_fingerprint: str | None
    currentness: Literal["unavailable"]
    reason_codes: list[str]


@router.get("/{instrument_id}/known-trades", response_model=KnownTrades)
def read_known_trades(
    instrument_id: int,
    account_id: int = Query(gt=0),
    t0: date = Query(),
    t1: date = Query(),
    session: Session = Depends(session_for_request),
):
    try:
        return known_instrument_trades(session, account_id, instrument_id, t0, t1)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
