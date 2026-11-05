"""Read-only provisional instrument returns for one native source account."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.returns_view import AccountLink
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.instrument_return import AccountReconciliation, InstrumentEvent
from hermes_finance.services.source_instrument_returns import (
    InstrumentIncome,
    InstrumentReturnGap,
    ReturnBreakdown,
    SourceInstrumentReturn,
    read_instrument_returns,
)

router = APIRouter(prefix="/api/source-returns", tags=["source-returns"])


class SourceInstrumentReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account: str
    account_link: AccountLink | None
    native_source_account: str | None
    unresolved_events: tuple[InstrumentEvent, ...]
    account_reconciliation_events: tuple[InstrumentEvent, ...]
    reconciliation: AccountReconciliation | None
    breakdown: ReturnBreakdown | None
    instruments: tuple[SourceInstrumentReturn, ...]
    income: tuple[InstrumentIncome, ...]
    gaps: tuple[InstrumentReturnGap, ...]
    authority: Literal["provisional"]
    financial_authority: Literal["none"]
    currency: Literal["RUB"]


class CleanMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[str | None, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
    status: Literal["supported", "provisional", "partial", "unavailable"]
    reason_codes: tuple[str, ...]
    assumptions: tuple[str, ...]


class CleanInstrument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isin: Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")]
    name: str | None
    instrument_type: str | None
    opening_date: date
    closing_date: date
    opening_value: CleanMetric
    closing_value: CleanMetric
    buys: CleanMetric
    sells: CleanMetric
    coupons: CleanMetric
    dividends: CleanMetric
    payouts: CleanMetric
    redemption: CleanMetric
    valuation_and_trades: CleanMetric
    known_result: CleanMetric
    pnl: CleanMetric
    modified_dietz: CleanMetric


class CleanGap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    month: date | None
    isin: str | None


class CleanInstrumentReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["clean_instrument_return_v1"]
    authority: Literal["provisional"]
    financial_authority: Literal["none"]
    source_account: str
    native_source_account: str | None
    currency: Literal["RUB"]
    instruments: tuple[CleanInstrument, ...]
    gaps: tuple[CleanGap, ...]


@router.get("/instruments", response_model=SourceInstrumentReturnsResponse)
def instrument_returns(
    response: Response,
    source_account: Annotated[str, Query(min_length=1, max_length=256, pattern=r"^\S+$")],
    isin: Annotated[str | None, Query(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] = None,
    opening_date: date | None = None,
    closing_date: date | None = None,
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    if (opening_date is None) != (closing_date is None) or (
        opening_date is not None and opening_date >= closing_date
    ):
        raise HTTPException(422, "both dates are required, with opening_date < closing_date")
    return read_instrument_returns(
        session,
        source_account=source_account,
        isin=isin,
        opening_date=opening_date,
        closing_date=closing_date,
    ).to_dict()


@router.get("/clean-instruments", response_model=CleanInstrumentReturnsResponse)
def clean_instrument_returns(
    response: Response,
    source_account: Annotated[str, Query(min_length=1, max_length=256, pattern=r"^\S+$")],
    opening_date: date,
    closing_date: date,
    isin: Annotated[str | None, Query(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")] = None,
    session: Session = Depends(session_for_request),
):
    """Versioned clean projection; the legacy cash-economic endpoint is unchanged."""
    from hermes_finance.services.clean_instrument_return import read_clean_account

    response.headers["Cache-Control"] = "no-store"
    if opening_date >= closing_date:
        raise HTTPException(422, "opening_date must precede closing_date")
    return read_clean_account(session, source_account, opening_date, closing_date, isin=isin)
