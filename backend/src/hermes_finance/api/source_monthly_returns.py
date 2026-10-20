"""Read-only provisional monthly returns for one native source account."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.monthly_return_chain import PeriodReturnTotals
from hermes_finance.services.source_monthly_returns import (
    SourceReturnFlow,
    SourceReturnGap,
    read_monthly_returns,
)

router = APIRouter(prefix="/api/source-returns", tags=["source-returns"])


class MonthlyReturnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_date: date
    closing_date: date
    opening_kopecks: int | None
    closing_kopecks: int | None
    contributions_kopecks: int | None
    withdrawals_kopecks: int | None
    growth_kopecks: int | None
    modified_dietz_return: Decimal | None
    assumptions_used: bool
    missing_endpoint: bool
    reason_codes: tuple[str, ...]
    approximate: Literal[True]
    intake_ids: tuple[int, ...]
    flags: tuple[str, ...]
    previous_closing_kopecks: int | None


class SourceMonthlyReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account: str
    months: tuple[MonthlyReturnResponse, ...]
    period: PeriodReturnTotals
    flows: tuple[SourceReturnFlow, ...]
    defaults_applied: tuple[SourceReturnFlow, ...]
    gaps: tuple[SourceReturnGap, ...]
    authority: Literal["provisional"]
    financial_authority: Literal["none"]
    currency: Literal["RUB"]
    approximate: Literal[True]


@router.get("/monthly", response_model=SourceMonthlyReturnsResponse)
def monthly_returns(
    response: Response,
    source_account: Annotated[str, Query(min_length=1, max_length=256, pattern=r"^\S+$")],
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    return read_monthly_returns(session, source_account=source_account).to_dict()
