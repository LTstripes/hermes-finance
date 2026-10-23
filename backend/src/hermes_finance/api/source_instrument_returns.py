"""Read-only provisional instrument returns for one native source account."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.instrument_return import AccountReconciliation, InstrumentEvent
from hermes_finance.services.source_instrument_returns import (
    InstrumentIncome,
    InstrumentReturnGap,
    SourceInstrumentReturn,
    read_instrument_returns,
)

router = APIRouter(prefix="/api/source-returns", tags=["source-returns"])


class SourceInstrumentReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account: str
    native_source_account: str | None
    unresolved_events: tuple[InstrumentEvent, ...]
    account_reconciliation_events: tuple[InstrumentEvent, ...]
    reconciliation: AccountReconciliation | None
    instruments: tuple[SourceInstrumentReturn, ...]
    income: tuple[InstrumentIncome, ...]
    gaps: tuple[InstrumentReturnGap, ...]
    authority: Literal["provisional"]
    financial_authority: Literal["none"]
    currency: Literal["RUB"]


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
