"""Read-only hypothetical evaluation, freshly recomputed for every request."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.instrument_cash_income import KnownPayouts, Ref
from hermes_finance.api.instrument_eod_observations import EodObservation
from hermes_finance.api.instrument_trades import KnownTrades
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.instrument_what_if import instrument_what_if

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assumptions(StrictModel):
    no_unobserved_movements: bool
    no_unobserved_payouts: bool
    no_other_costs_or_taxes: bool


class Observed(StrictModel):
    opening: EodObservation
    closing: EodObservation
    comparable: bool | None


class AcceptedKnown(StrictModel):
    payouts: KnownPayouts | None
    trades: KnownTrades | None


class HypotheticalResult(StrictModel):
    conditional_result: str | None
    conditional_period_fraction: str | None
    conditional_period_percent: str | None
    percent_unit: Literal["percentage_points"]
    annualized: Literal[False]
    formula: Literal["V1-V0+P"]
    decimal_precision: Literal[100]


class SourceCheck(StrictModel):
    source_import_id: int
    reason_codes: list[str]


class InstrumentWhatIf(StrictModel):
    method: Literal["hypothetical-fixed-stock-hpr"]
    version: Literal[1]
    authority: Literal["hypothetical"]
    request_nonce: str
    account: Ref
    instrument: Ref
    t0: date
    t1: date
    interval: Literal["(t0,t1]"]
    currency: Literal["RUB"]
    observed: Observed | None
    accepted_known: AcceptedKnown
    chosen_assumptions: Assumptions
    missing_assumptions: list[str]
    hard_blockers: list[str]
    source_checks: list[SourceCheck]
    hypothetical_result: HypotheticalResult
    actual_instrument_return: None
    whole_period_completeness: Literal["unknown"]
    dependency_fingerprint: None


@router.get("/{instrument_id}/conditional-return", response_model=InstrumentWhatIf)
def evaluate(
    instrument_id: int,
    response: Response,
    account_id: int = Query(gt=0),
    t0: date = Query(),
    t1: date = Query(),
    request_nonce: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    no_unobserved_movements: bool = Query(False),
    no_unobserved_payouts: bool = Query(False),
    no_other_costs_or_taxes: bool = Query(False),
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return instrument_what_if(
            session,
            account_id,
            instrument_id,
            t0,
            t1,
            {
                "no_unobserved_movements": no_unobserved_movements,
                "no_unobserved_payouts": no_unobserved_payouts,
                "no_other_costs_or_taxes": no_other_costs_or_taxes,
            },
            request_nonce,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
