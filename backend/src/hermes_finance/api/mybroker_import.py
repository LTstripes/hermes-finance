"""Owner-uploaded MyBroker S1: read-only Preview, atomic source-only Apply."""

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.mybroker_import import (
    apply_mybroker,
    preview_mybroker,
    read_mybroker_import,
    read_mybroker_lineage,
)
from hermes_finance.statement_import.mybroker import MAX_BYTES, MyBrokerError

router = APIRouter(prefix="/api/mybroker-import", tags=["mybroker-import"])


class Binding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    identity: str = Field(min_length=1, max_length=128)
    mapping_id: int = Field(gt=0)
    hermes_id: int = Field(gt=0)


class SkipReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skipped_isins: list[str] = Field(default_factory=list, max_length=10000)
    owner_reviewed: bool = Field(default=False, strict=True)


class DispositionIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    import_id: int = Field(gt=0, strict=True)
    isin: str = Field(min_length=1, max_length=128)
    operation: Literal["revoke", "reaffirm"]
    expected_revision: int = Field(gt=0, strict=True)


class DispositionApply(DispositionIntent):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class Confirmation(SkipReview):
    model_config = ConfigDict(extra="forbid")
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    covered_from: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    covered_to: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    mappings: list[Binding] = Field(max_length=10000)
    request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


async def _bytes(file: UploadFile) -> bytes:
    document = bytearray()
    while chunk := await file.read(256 * 1024):
        document.extend(chunk)
        if len(document) > MAX_BYTES:
            raise HTTPException(413, "document_size_invalid")
    return bytes(document)


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    decisions: str = Form("{}"),
    session: Session = Depends(session_for_request),
):
    try:
        try:
            reviewed = SkipReview.model_validate_json(decisions)
        except ValidationError:
            raise HTTPException(422, "instrument_decisions_invalid") from None
        return preview_mybroker(
            session,
            document=await _bytes(file),
            filename=file.filename or "",
            skipped_isins=tuple(reviewed.skipped_isins),
            owner_reviewed=reviewed.owner_reviewed,
        )
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
async def apply(
    file: UploadFile = File(...),
    confirmation: str = Form(...),
    session: Session = Depends(session_for_request),
):
    try:
        reviewed = Confirmation.model_validate_json(confirmation)
    except ValidationError:
        # Do not echo invalid confirmation/provider input into logs or responses.
        raise HTTPException(422, "confirmation_invalid") from None
    try:
        return apply_mybroker(
            session,
            document=await _bytes(file),
            filename=file.filename or "",
            confirmation_digest=reviewed.confirmation_digest,
            confirmed_range=(reviewed.covered_from, reviewed.covered_to),
            confirmed_mappings=[m.model_dump() for m in reviewed.mappings],
            skipped_isins=tuple(reviewed.skipped_isins),
            owner_reviewed=reviewed.owner_reviewed,
            request_id=reviewed.request_id,
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/lineage")
def lineage(session: Session = Depends(session_for_request)):
    return read_mybroker_lineage(session)


@router.post("/dispositions/preview")
def preview_disposition(intent: DispositionIntent, session: Session = Depends(session_for_request)):
    from hermes_finance.database import coherent_read_snapshot
    from hermes_finance.services.mybroker_dispositions import lifecycle_preview

    try:
        with coherent_read_snapshot(session):
            return lifecycle_preview(session, **intent.model_dump())
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.post("/dispositions/apply")
def apply_disposition(intent: DispositionApply, session: Session = Depends(session_for_request)):
    from hermes_finance.services.mybroker_dispositions import apply_lifecycle

    try:
        return apply_lifecycle(session, **intent.model_dump())
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/{import_id}")
def readback(import_id: int, session: Session = Depends(session_for_request)):
    try:
        return read_mybroker_import(session, import_id)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
