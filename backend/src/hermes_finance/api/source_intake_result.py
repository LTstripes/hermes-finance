"""Read-only source-intake-bound conditional instrument result endpoint.

The number is hypothetical and request-local: no write, no financial Apply and
no reusable completeness token. The journal original and its current revision
bind the response; the accepted #858/#862 readers are reused inside the same
coherent snapshot when an instrument identity exists.
"""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.instrument_cash_income import KnownPayouts, Ref
from hermes_finance.api.instrument_trades import KnownTrades
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.source_intake_result import source_intake_instrument_result
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/broker-months/intakes", tags=["source-intake"])

ISIN_PATTERN = r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Assumptions(StrictModel):
    no_unobserved_movements: bool
    no_unobserved_payouts: bool
    no_other_costs_or_taxes: bool


class IntakeRef(StrictModel):
    id: int
    head_seq: int
    manifest_digest: str
    document_sha256: str
    covered_from: date
    covered_to: date
    finance_link: Literal["present", "absent"]
    exceptions: list[str]


class InstrumentRef(StrictModel):
    isin: str
    instrument_type: Literal["stock", "bond"] | None
    hermes_id: int | None
    name: str | None


class CurrencyAssessment(StrictModel):
    observed_denomination: str | None
    effective_currency: str | None
    basis: str | None
    provisional: bool | None


class SourceRow(StrictModel):
    ordinal: int
    locator: str
    row_fingerprint: str


class Observed(StrictModel):
    availability: Literal["available", "unavailable"]
    quantity: str | None
    beginning_quantity: str | None
    forward_quantity: str | None
    beginning_value: str | None
    ending_value: str | None
    beginning_basis: Literal["previous_day_eod"]
    ending_basis: Literal["covered_to_eod"]
    value_change: str | None
    value_change_fraction: str | None
    value_change_percent: str | None
    bond_nkd_basis: Literal["unknown", "not_applicable"]
    source_row: SourceRow | None
    reason_codes: list[str]


class ConfirmedCostLeg(StrictModel):
    trade_id: int
    role: Literal["commission", "paid_nkd"]
    signed_rub: str
    effective_date: date | None
    in_interval: bool | None
    receipt_id: str | None


class Known(StrictModel):
    payouts: KnownPayouts | None
    trades: KnownTrades | None
    net_distributions: str | None
    confirmed_cost_legs: list[ConfirmedCostLeg]
    cost_coverage: Literal["unknown"]
    reason_codes: list[str]


class HypotheticalResult(StrictModel):
    conditional_result: str | None
    conditional_period_fraction: str | None
    conditional_period_percent: str | None
    percent_unit: Literal["percentage_points"]
    annualized: Literal[False]
    formula: Literal["V1-V0+P"]
    decimal_precision: Literal[100]


class SourceIntakeResult(StrictModel):
    method: Literal["source-intake-fixed-holding-result"]
    version: Literal[1]
    authority: Literal["hypothetical"]
    request_nonce: str
    intake: IntakeRef
    account: Ref | None
    instrument: InstrumentRef
    currency_assessment: CurrencyAssessment
    t0: date
    t1: date
    interval: Literal["(t0,t1]"]
    currency: Literal["RUB"]
    observed: Observed
    known: Known
    chosen_assumptions: Assumptions
    missing_assumptions: list[str]
    hard_blockers: list[str]
    hypothetical_result: HypotheticalResult
    actual_instrument_return: None
    whole_period_completeness: Literal["unknown"]
    dependency_fingerprint: None


@router.get("/{intake_id}/instrument-result", response_model=SourceIntakeResult)
def read_instrument_result(
    intake_id: int,
    response: Response,
    isin: str = Query(pattern=ISIN_PATTERN),
    request_nonce: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"),
    no_unobserved_movements: bool = Query(False),
    no_unobserved_payouts: bool = Query(False),
    no_other_costs_or_taxes: bool = Query(False),
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return source_intake_instrument_result(
            session,
            intake_id,
            isin,
            {
                "no_unobserved_movements": no_unobserved_movements,
                "no_unobserved_payouts": no_unobserved_payouts,
                "no_other_costs_or_taxes": no_other_costs_or_taxes,
            },
            request_nonce,
        )
    except MyBrokerError as error:
        raise HTTPException(
            404 if str(error) == "source_intake_not_found" else 409, str(error)
        ) from None
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
