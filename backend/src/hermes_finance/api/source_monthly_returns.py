"""Read-only provisional monthly returns for one native source account."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from hermes_finance.api.broker_statement_provisional import ProvisionalRoute
from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.monthly_return_chain import PeriodReturnTotals
from hermes_finance.services import source_investment_proofs as investment_proofs
from hermes_finance.services import source_return_proofs as proof_service
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


class SourceProofResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["absent", "current", "stale"]
    proof_id: int | None
    version: str
    confirmed_at: datetime | None
    currentness: str | None
    reason_codes: list[str]
    financial_authority: Literal["none"]


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
    source_proof: SourceProofResponse | None = None
    investment_reports: tuple[dict, ...] = ()


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


async def _original_request(request, files):
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
    return bound, documents, expected


async def monthly_returns_with_originals(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    session: Session = Depends(session_for_request),
):
    """Reattach exact originals for this read only. No Save or assumptions."""
    bound, documents, expected = await _original_request(request, files)
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


async def preview_source_proof(
    request: Request,
    response: Response,
    files: list[UploadFile] = File(...),
    session: Session = Depends(session_for_request),
):
    bound, documents, expected = await _original_request(request, files)
    try:
        result = proof_service.preview_proof(
            session,
            source_account=bound.source_account,
            documents=documents,
            expected_sources=expected,
        )
    except (MyBrokerError, ProvisionalStaleError, proof_service.ProofError) as error:
        raise HTTPException(409, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return result


class ConfirmSourceProof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_account: str = Field(min_length=1, max_length=256, pattern=r"^\S+$")
    form_token: str = Field(min_length=20, max_length=128)
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    attested: Literal[True]

    @field_validator("attested", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("attested must be JSON true")
        return value


def confirm_source_proof(
    payload: ConfirmSourceProof,
    request: Request,
    response: Response,
    session: Session = Depends(session_for_request),
):
    if request.query_params:
        raise HTTPException(422, "source_return_proof_request_invalid")
    try:
        result = proof_service.confirm_proof(session, **payload.model_dump(exclude={"attested"}))
    except proof_service.ProofError as error:
        raise HTTPException(409, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return result


def source_proof_request_status(
    request_id: str,
    response: Response,
    session: Session = Depends(session_for_request),
):
    try:
        result = proof_service.proof_request_status(session, request_id)
    except proof_service.ProofError as error:
        raise HTTPException(404, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return result


router.add_api_route(
    "/proofs/preview",
    preview_source_proof,
    methods=["POST"],
    route_class_override=ProvisionalRoute,
)
router.add_api_route(
    "/proofs/confirm",
    confirm_source_proof,
    methods=["POST"],
    route_class_override=ProvisionalRoute,
)
router.add_api_route(
    "/proofs/requests/{request_id}",
    source_proof_request_status,
    methods=["GET"],
    route_class_override=ProvisionalRoute,
)


class ConfirmInvestmentProof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    form_token: str = Field(min_length=20, max_length=128)
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
    replace_existing: bool = False
    attested: Literal[True]

    @field_validator("attested", mode="before")
    @classmethod
    def explicit_true(cls, value):
        if value is not True:
            raise ValueError("attested must be JSON true")
        return value


@router.get("/investment-reports")
def investment_reports(
    response: Response,
    source_account: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    session: Session = Depends(session_for_request),
):
    response.headers["Cache-Control"] = "no-store"
    return {"reports": investment_proofs.read_reports(session, source_account=source_account)}


def confirm_investment_report(
    payload: ConfirmInvestmentProof,
    request: Request,
    response: Response,
    session: Session = Depends(session_for_request),
):
    if request.query_params:
        raise HTTPException(422, "investment_proof_request_invalid")
    try:
        result = investment_proofs.confirm(session, **payload.model_dump(exclude={"attested"}))
    except proof_service.ProofError as error:
        raise HTTPException(409, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return result


def investment_report_request(
    request_id: str, response: Response, session: Session = Depends(session_for_request)
):
    if not __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", request_id):
        raise HTTPException(422, "investment_proof_request_invalid")
    try:
        result = investment_proofs.request_status(session, request_id)
    except proof_service.ProofError as error:
        raise HTTPException(404, str(error)) from None
    response.headers["Cache-Control"] = "no-store"
    return result


router.add_api_route(
    "/investment-reports/confirm",
    confirm_investment_report,
    methods=["POST"],
    route_class_override=ProvisionalRoute,
)
router.add_api_route(
    "/investment-reports/requests/{request_id}",
    investment_report_request,
    methods=["GET"],
    route_class_override=ProvisionalRoute,
)
