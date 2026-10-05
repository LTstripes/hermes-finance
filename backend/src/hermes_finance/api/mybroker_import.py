"""Owner-uploaded MyBroker S1: read-only Preview, atomic source-only Apply."""

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


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    covered_from: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    covered_to: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    mappings: list[Binding] = Field(max_length=10000)


async def _bytes(file: UploadFile) -> bytes:
    document = bytearray()
    while chunk := await file.read(256 * 1024):
        document.extend(chunk)
        if len(document) > MAX_BYTES:
            raise HTTPException(413, "document_size_invalid")
    return bytes(document)


@router.post("/preview")
async def preview(file: UploadFile = File(...), session: Session = Depends(session_for_request)):
    try:
        return preview_mybroker(session, document=await _bytes(file), filename=file.filename or "")
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
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/lineage")
def lineage(session: Session = Depends(session_for_request)):
    return read_mybroker_lineage(session)


@router.get("/{import_id}")
def readback(import_id: int, session: Session = Depends(session_for_request)):
    try:
        return read_mybroker_import(session, import_id)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
