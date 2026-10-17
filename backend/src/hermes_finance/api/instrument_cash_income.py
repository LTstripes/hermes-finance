"""On-demand read-only known instrument payouts endpoint."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.instrument_cash_income import known_instrument_cash_income

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


class Ref(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str


class PayoutEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cash_flow_id: int
    kind: Literal["coupon", "dividend"]
    date: date
    booked_net: str | None
    included_in_known_net: bool
    proof_state: Literal[
        "manual_booked", "source_accepted", "retired_or_unmatched", "incomplete_unknown"
    ]
    currentness: Literal["current", "unavailable"]
    gross: str | None
    tax: str | None
    fee: str | None
    tax_available: bool
    receipt_ids: list[str]
    provenance: list[str]
    reason_codes: list[str]


class KnownNet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    coupon: str | None
    dividend: str | None


class KnownPayouts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["known-booked-net-payouts"]
    version: Literal[1]
    account: Ref
    instrument: Ref
    t0: date
    t1: date
    currency: Literal["RUB"]
    coverage: Literal["unknown"]
    completeness: Literal["unknown"]
    known_booked_net: KnownNet
    event_count: int
    known_event_count: int
    events: list[PayoutEvent]
    reason_codes: list[str]
    dependency_fingerprint: str | None


@router.get("/{instrument_id}/cash-income", response_model=KnownPayouts)
def read_known_payouts(
    instrument_id: int,
    account_id: int = Query(gt=0),
    t0: date = Query(),
    t1: date = Query(),
    session: Session = Depends(session_for_request),
):
    try:
        return known_instrument_cash_income(session, account_id, instrument_id, t0, t1)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
