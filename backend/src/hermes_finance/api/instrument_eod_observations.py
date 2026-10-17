"""Read-only EOD pair plus unchanged known payouts, one committed snapshot."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.instrument_cash_income import KnownPayouts, Ref
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.instrument_eod_observations import instrument_eod_observations

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


class HistoricalIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    isin: str
    instrument_type: Literal["stock", "bond"]
    denomination: Literal["RUB"]


class EodObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    account_id: int
    instrument_id: int
    availability: Literal["available", "unavailable"]
    quantity: str | None
    market_value: str | None
    currency: Literal["RUB"]
    historical_identity: HistoricalIdentity | None
    bond_nkd_basis: Literal["unknown", "included", "excluded", "not_applicable"] | None
    price_date: date | None
    position_id: int | None
    price_source: str | None
    source_import_id: int | None
    source_row_key: str | None
    receipt_ids: list[str]
    revision_generation: int | None
    proof_state: Literal["source_accepted", "unavailable"]
    currentness: Literal["current", "unavailable"]
    dependency_fingerprint: str | None
    reason_codes: list[str]


class InstrumentObservations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["persisted-instrument-eod-pair"]
    version: Literal[1]
    account: Ref
    instrument: Ref
    t0: date
    t1: date
    currency: Literal["RUB"]
    opening: EodObservation
    closing: EodObservation
    comparable: bool | None
    observed_position_value_difference: str | None
    reason_codes: list[str]
    dependency_fingerprint: str | None
    known_payouts: KnownPayouts
    valuation_dependency_fingerprint: str | None


@router.get("/{instrument_id}/eod-observations", response_model=InstrumentObservations)
def read_observations(
    instrument_id: int,
    account_id: int = Query(gt=0),
    t0: date = Query(),
    t1: date = Query(),
    session: Session = Depends(session_for_request),
):
    try:
        return instrument_eod_observations(session, account_id, instrument_id, t0, t1)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
