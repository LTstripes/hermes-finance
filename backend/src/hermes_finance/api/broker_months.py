"""Bounded original upload API. Client amounts or normalized rows are forbidden."""

import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import BrokerMonthApply
from hermes_finance.services.broker_months import (
    apply_broker_month,
    preview_broker_month,
    read_broker_month,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/broker-months", tags=["broker-months"])


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reporting_month_id: int = Field(gt=0, strict=True)
    account_id: int = Field(gt=0, strict=True)


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
    session: Session = Depends(session_for_request),
):
    try:
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
    except (ValidationError, MyBrokerError) as error:
        raise HTTPException(
            422, "broker_month_intent_invalid" if isinstance(error, ValidationError) else str(error)
        ) from None


@router.post("/apply")
async def apply(
    file: UploadFile = File(...),
    confirmation: str = Form(...),
    supporting: list[UploadFile] = File(default=[]),
    session: Session = Depends(session_for_request),
):
    try:
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
    except ValidationError:
        raise HTTPException(422, "broker_month_confirmation_invalid") from None
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


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
        return [read_broker_month(session, request_id) for request_id in ids]


@router.get("/{request_id}")
def readback(request_id: str, session: Session = Depends(session_for_request)):
    try:
        return read_broker_month(session, request_id)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
