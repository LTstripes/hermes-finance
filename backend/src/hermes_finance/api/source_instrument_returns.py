"""Read-only provisional instrument returns for one native source account."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
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
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    return read_instrument_returns(session, source_account=source_account).to_dict()
