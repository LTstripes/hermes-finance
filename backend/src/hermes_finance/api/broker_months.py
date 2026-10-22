"""Bounded original upload API. Client amounts or normalized rows are forbidden."""

import hashlib
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.api.source_intake import router as intake_router
from hermes_finance.api.uploads import BoundedUploadRoute
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain.broker_money import MoneyConfirmation, MoneyIntent
from hermes_finance.domain.broker_sections import SectionConfirmation, SectionIntent
from hermes_finance.persistence import BrokerMonthApply
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services import broker_sections
from hermes_finance.services.broker_money import apply_money, preview_money
from hermes_finance.services.broker_months import (
    apply_broker_month,
    preview_broker_month,
    read_broker_month,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(
    route_class=BoundedUploadRoute, prefix="/api/broker-months", tags=["broker-months"]
)

router.include_router(intake_router)


class InstrumentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    isin: str = Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    hermes_id: int | None = Field(default=None, gt=0, strict=True)
    proof_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PublicLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool = Field(strict=True)
    isins: list[str] = Field(min_length=1, max_length=32)


@router.post("/public-identity-lookup")
def public_identity_lookup(request: PublicLookup):
    from hermes_finance.services.public_security_registry import lookup_public

    try:
        return lookup_public(request.isins, consent=request.consent)
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reporting_month_id: int = Field(gt=0, strict=True)
    account_id: int = Field(gt=0, strict=True)
    instrument_decisions: list[InstrumentDecision] = Field(default_factory=list, max_length=1000)


class AccountBindingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str = Field(min_length=1)
    hermes_id: int = Field(gt=0, strict=True)


class Confirmation(Intent):
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    reviewed_account_bindings: list[AccountBindingDecision] = Field(default_factory=list)


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    intent: str = Form(...),
    supporting: list[UploadFile] = File(default=[]),
    originals: list[UploadFile] = File(default=[]),
    session: Session = Depends(session_for_request),
):
    try:
        if json.loads(intent).get("contract_version") == broker_sections.CONTRACT:
            requested_sections = SectionIntent.model_validate_json(intent)
            if supporting or originals:
                raise MyBrokerError("section_originals_invalid")
            return broker_sections.preview_sections(
                session, requested_sections, await _bytes(file), file.filename or ""
            )
        if json.loads(intent).get("contract_version") == "broker_money_v1":
            requested_money = MoneyIntent.model_validate_json(intent)
            if supporting or len(originals) > 31:
                raise MyBrokerError("money_originals_invalid")
            return preview_money(
                session,
                requested_money,
                [(f.filename or "", await _bytes(f)) for f in [file, *originals]],
            )
        if originals:
            raise MyBrokerError("money_intent_required")
        requested = Intent.model_validate_json(intent)
        if len(supporting) > 3:
            raise MyBrokerError("optional_document_limit")
        hashes = sorted([hashlib.sha256(await _bytes(f)).hexdigest() for f in supporting])
        return preview_broker_month(
            session,
            document=await _bytes(file),
            filename=file.filename or "",
            optional_hashes=hashes,
            **requested.model_dump(),
        )
    except (ValidationError, MyBrokerError, ValueError, AttributeError) as error:
        raise HTTPException(
            422, "broker_month_intent_invalid" if isinstance(error, ValidationError) else str(error)
        ) from None


@router.post("/apply")
async def apply(
    file: UploadFile = File(...),
    confirmation: str = Form(...),
    supporting: list[UploadFile] = File(default=[]),
    originals: list[UploadFile] = File(default=[]),
    session: Session = Depends(session_for_request),
):
    try:
        if json.loads(confirmation).get("contract_version") == broker_sections.CONTRACT:
            requested_sections = SectionConfirmation.model_validate_json(confirmation)
            if supporting or originals:
                raise MyBrokerError("section_originals_invalid")
            return broker_sections.apply_sections(
                session,
                SectionIntent.model_validate(
                    requested_sections.model_dump(exclude={"request_id", "confirmation_digest"})
                ),
                await _bytes(file),
                file.filename or "",
                confirmation_digest=requested_sections.confirmation_digest,
                request_id=requested_sections.request_id,
            )
        if json.loads(confirmation).get("contract_version") == "broker_money_v1":
            requested_money = MoneyConfirmation.model_validate_json(confirmation)
            if supporting or len(originals) > 31:
                raise MyBrokerError("money_originals_invalid")
            return apply_money(
                session,
                MoneyIntent.model_validate(
                    requested_money.model_dump(exclude={"request_id", "confirmation_digest"})
                ),
                [(f.filename or "", await _bytes(f)) for f in [file, *originals]],
                confirmation_digest=requested_money.confirmation_digest,
                request_id=requested_money.request_id,
            )
        if originals:
            raise MyBrokerError("money_intent_required")
        requested = Confirmation.model_validate_json(confirmation)
        if len(supporting) > 3:
            raise MyBrokerError("optional_document_limit")
        hashes = sorted([hashlib.sha256(await _bytes(f)).hexdigest() for f in supporting])
        return apply_broker_month(
            session,
            document=await _bytes(file),
            filename=file.filename or "",
            optional_hashes=hashes,
            **requested.model_dump(),
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None
    except (ValidationError, ValueError, AttributeError):
        raise HTTPException(422, "broker_month_confirmation_invalid") from None


@router.get("")
def batches(reporting_month_id: int, session: Session = Depends(session_for_request)):
    with coherent_read_snapshot(session):
        ids = list(
            session.scalars(
                select(BrokerMonthApply.request_id)
                .where(BrokerMonthApply.reporting_month_id == reporting_month_id)
                .order_by(BrokerMonthApply.accepted_at)
            )
        )
        return [
            read_broker_month(session, request_id)
            for request_id in ids
            if journal.kind(session.get(BrokerMonthApply, request_id))
            in {journal.SOURCE, "invalid"}
        ]


@router.get("/{request_id}")
def readback(request_id: str, session: Session = Depends(session_for_request)):
    try:
        return read_broker_month(session, request_id)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
