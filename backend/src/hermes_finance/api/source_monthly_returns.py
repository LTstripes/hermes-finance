"""Read-only provisional monthly returns for one native source account."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.broker_statement_provisional import ProvisionalRoute
from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.monthly_return_chain import PeriodReturnTotals
from hermes_finance.services.broker_statement_provisional import ProvisionalStaleError
from hermes_finance.services.source_monthly_returns import (
    SourceReturnFlow,
    SourceReturnGap,
    SourceReturnSegment,
    read_monthly_returns,
    read_monthly_returns_with_originals,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

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
    coupons_kopecks: int | None
    dividends_kopecks: int | None
    income_assumptions_used: bool


class SourceMonthlyReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_account: str
    months: tuple[MonthlyReturnResponse, ...]
    period: PeriodReturnTotals
    segments: list[SourceReturnSegment]
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


class OriginalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intake_id: int = Field(gt=0)
    manifest_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class OriginalMonthlyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_account: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")
    expected_sources: list[OriginalExpectation] = Field(min_length=1, max_length=32)


async def monthly_returns_with_originals(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    session: Session = Depends(session_for_request),
):
    """Reattach exact originals for this read only. No Save or assumptions."""
    form = await request.form()
    if (
        request.query_params
        or set(form) != {"request", "files"}
        or len(form.getlist("request")) != 1
    ):
        raise HTTPException(422, "source_return_original_request_invalid")
    try:
        bound = OriginalMonthlyRequest.model_validate_json(form["request"])
        expected = {row.intake_id: row.manifest_digest for row in bound.expected_sources}
        if len(expected) != len(bound.expected_sources):
            raise ValueError
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, "source_return_original_request_invalid") from None
    documents = [(await _bytes(file), file.filename or "") for file in files]
    try:
        result = read_monthly_returns_with_originals(
            session,
            source_account=bound.source_account,
            documents=documents,
            expected_sources=expected,
        )
    except (MyBrokerError, ProvisionalStaleError) as error:
        raise HTTPException(409, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return result.to_dict()


router.add_api_route(
    "/monthly/originals",
    monthly_returns_with_originals,
    methods=["POST"],
    response_model=SourceMonthlyReturnsResponse,
    route_class_override=ProvisionalRoute,
)
