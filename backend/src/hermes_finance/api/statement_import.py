"""Thin multipart API over the accepted R06-07/R06-08 statement services."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.statement_import_apply import (
    StatementApplyAction,
    StatementApplySelection,
    apply_income_report_preview,
)
from hermes_finance.services.statement_import_preparation import (
    StatementApplyPreparation,
    StatementApplyPreparationRow,
    _account_views,
    _instrument_views,
    prepare_income_report_apply,
)
from hermes_finance.statement_import import (
    AccountMappingInput,
    InstrumentMappingInput,
    preview_income_report,
)

router = APIRouter(prefix="/api/statement-import", tags=["statement-import"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
READ_CHUNK_BYTES = 256 * 1024


class StatementAccountMappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hermes_account_id: int = Field(gt=0)
    provider_account_ref: str = Field(min_length=1, max_length=128)


class StatementInstrumentMappingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hermes_instrument_id: int = Field(gt=0)
    isin: str = Field(min_length=1, max_length=32)


class StatementApplySelectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    natural_identity: str = Field(min_length=1, max_length=256)
    material_fingerprint: str = Field(min_length=1, max_length=128)
    expected_hermes_account_id: int = Field(gt=0)
    expected_hermes_instrument_id: int = Field(gt=0)
    action: StatementApplyAction | None = None
    existing_cash_flow_id: int | None = Field(default=None, gt=0)
    expected_candidate_ids: list[int] = Field(default_factory=list, max_length=200)


class StatementCandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investment_cash_flow_id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int | None
    flow_type: str
    event_date: date
    gross_amount_kopecks: int
    tax_amount_kopecks: int
    commission_amount_kopecks: int
    net_amount_kopecks: int
    currency: str
    source: str


class StatementRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    duplicate_class: str | None
    event_kind: str | None
    expected_hermes_account_id: int | None
    expected_hermes_instrument_id: int | None
    provider_account_ref: str | None = None
    isin: str | None
    record_date: date | None
    event_date: date | None
    quantity: str | None
    per_unit: str | None
    gross_amount: str | None
    gross_currency: str | None
    tax_amount: str | None
    tax_available: bool
    tax_rate: str | None
    net_amount: str | None
    net_currency: str | None
    natural_identity: str | None
    material_fingerprint: str | None
    expected_candidate_ids: list[int]
    candidates: list[StatementCandidateOut]
    reason: str | None


class StatementPreparationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    document_sha256: str
    status: str
    rows: list[StatementRowOut]
    warnings: list[str]
    reason: str | None


class StatementApplyItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    applied_statement_event_id: int
    investment_cash_flow_id: int
    natural_identity: str
    material_fingerprint: str
    revision_id: int | None


class StatementApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    selected_count: int
    items: list[StatementApplyItemOut]
    error_code: str | None
    message: str | None


class StatementInspectRowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    provider_account_ref: str | None
    isin: str | None
    event_kind: str | None
    record_date: date | None
    event_date: date | None
    reason: str | None


class StatementInspectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    document_sha256: str
    status: str
    rows: list[StatementInspectRowOut]
    warnings: list[str]
    reason: str | None


def _decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _read_json(value: str, adapter: TypeAdapter):
    try:
        return adapter.validate_python(json.loads(value or "[]"))
    except (json.JSONDecodeError, ValidationError, TypeError) as error:
        raise HTTPException(
            status_code=422, detail="mapping or selection JSON is invalid"
        ) from error


def _account_mappings(value: str) -> tuple[AccountMappingInput, ...]:
    rows = _read_json(value, TypeAdapter(list[StatementAccountMappingIn]))
    return tuple(
        AccountMappingInput(
            hermes_account_id=row.hermes_account_id,
            provider_account_ref=row.provider_account_ref.strip(),
        )
        for row in rows
    )


def _instrument_mappings(value: str) -> tuple[InstrumentMappingInput, ...]:
    rows = _read_json(value, TypeAdapter(list[StatementInstrumentMappingIn]))
    return tuple(
        InstrumentMappingInput(hermes_instrument_id=row.hermes_instrument_id, isin=row.isin.strip())
        for row in rows
    )


async def _document(upload: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await upload.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413, detail="statement PDF exceeds the upload limit"
                )
            chunks.append(chunk)
    finally:
        await upload.close()
    return b"".join(chunks)


def _candidate(candidate) -> StatementCandidateOut:
    return StatementCandidateOut(
        investment_cash_flow_id=candidate.investment_cash_flow_id,
        reporting_month_id=candidate.reporting_month_id,
        account_id=candidate.account_id,
        instrument_id=candidate.instrument_id,
        flow_type=candidate.flow_type,
        event_date=candidate.event_date,
        gross_amount_kopecks=candidate.gross_amount_kopecks,
        tax_amount_kopecks=candidate.tax_amount_kopecks,
        commission_amount_kopecks=candidate.commission_amount_kopecks,
        net_amount_kopecks=candidate.net_amount_kopecks,
        currency=candidate.currency,
        source=candidate.source,
    )


def _row(
    row: StatementApplyPreparationRow, *, provider_account_ref: str | None = None
) -> StatementRowOut:
    return StatementRowOut(
        status=row.status.value,
        duplicate_class=row.duplicate_class.value if row.duplicate_class is not None else None,
        event_kind=row.event_kind,
        expected_hermes_account_id=row.expected_hermes_account_id,
        expected_hermes_instrument_id=row.expected_hermes_instrument_id,
        provider_account_ref=provider_account_ref,
        isin=row.isin,
        record_date=row.record_date,
        event_date=row.event_date,
        quantity=_decimal(row.quantity),
        per_unit=_decimal(row.per_unit),
        gross_amount=_decimal(row.gross_amount),
        gross_currency=row.gross_currency,
        tax_amount=_decimal(row.tax_amount),
        tax_available=row.tax_available,
        tax_rate=_decimal(row.tax_rate),
        net_amount=_decimal(row.net_amount),
        net_currency=row.net_currency,
        natural_identity=row.natural_identity,
        material_fingerprint=row.material_fingerprint,
        expected_candidate_ids=list(row.expected_candidate_ids),
        candidates=[_candidate(candidate) for candidate in row.candidates],
        reason=row.reason,
    )


def _preparation_response(result: StatementApplyPreparation) -> StatementPreparationResponse:
    return StatementPreparationResponse(
        provider=result.provider,
        document_sha256=result.document_sha256,
        status=result.status.value,
        rows=[_row(row) for row in result.rows],
        warnings=list(result.warnings),
        reason=result.reason,
    )


def _selection(row: StatementApplySelectionIn) -> StatementApplySelection:
    return StatementApplySelection(
        natural_identity=row.natural_identity,
        material_fingerprint=row.material_fingerprint,
        expected_hermes_account_id=row.expected_hermes_account_id,
        expected_hermes_instrument_id=row.expected_hermes_instrument_id,
        action=row.action,
        existing_cash_flow_id=row.existing_cash_flow_id,
        expected_candidate_ids=tuple(row.expected_candidate_ids),
    )


@router.post("/inspect", response_model=StatementInspectResponse)
async def inspect_statement_endpoint(
    document: UploadFile = File(...),
    session: Session = Depends(session_for_request),
) -> StatementInspectResponse:
    payload = await _document(document)
    preview = preview_income_report(
        payload,
        hermes_accounts=_account_views(session),
        hermes_instruments=_instrument_views(session),
    )
    return StatementInspectResponse(
        provider=preview.provider,
        document_sha256=preview.document_sha256,
        status=preview.status.value,
        rows=[
            StatementInspectRowOut(
                status=row.status.value,
                provider_account_ref=row.provider_account_ref,
                isin=row.isin,
                event_kind=row.event_kind,
                record_date=row.record_date,
                event_date=row.event_date,
                reason=row.reason,
            )
            for row in preview.rows
        ],
        warnings=list(preview.warnings),
        reason=preview.reason,
    )


@router.post("/prepare", response_model=StatementPreparationResponse)
async def prepare_statement_endpoint(
    document: UploadFile = File(...),
    account_mappings: str = Form("[]"),
    instrument_mappings: str = Form("[]"),
    session: Session = Depends(session_for_request),
) -> StatementPreparationResponse:
    payload = await _document(document)
    result = prepare_income_report_apply(
        session,
        document=payload,
        account_mappings=_account_mappings(account_mappings),
        instrument_mappings=_instrument_mappings(instrument_mappings),
    )
    return _preparation_response(result)


@router.post("/apply", response_model=StatementApplyResponse)
async def apply_statement_endpoint(
    document: UploadFile = File(...),
    account_mappings: str = Form("[]"),
    instrument_mappings: str = Form("[]"),
    selections: str = Form("[]"),
    expected_document_sha256: str = Form(...),
    session: Session = Depends(session_for_request),
) -> StatementApplyResponse:
    payload = await _document(document)
    selection_rows = _read_json(selections, TypeAdapter(list[StatementApplySelectionIn]))
    result = apply_income_report_preview(
        session,
        document=payload,
        account_mappings=_account_mappings(account_mappings),
        instrument_mappings=_instrument_mappings(instrument_mappings),
        selections=tuple(_selection(row) for row in selection_rows),
        expected_document_sha256=expected_document_sha256,
    )
    return StatementApplyResponse(
        success=result.success,
        selected_count=result.selected_count,
        items=[
            StatementApplyItemOut(
                action=item.action.value,
                applied_statement_event_id=item.applied_statement_event_id,
                investment_cash_flow_id=item.investment_cash_flow_id,
                natural_identity=item.natural_identity,
                material_fingerprint=item.material_fingerprint,
                revision_id=item.revision_id,
            )
            for item in result.items
        ],
        error_code=result.error_code.value if result.error_code is not None else None,
        message=result.message,
    )
