"""Ephemeral multi-original Preview; no Apply or ReportingMonth intent."""

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from hermes_finance.api.mybroker_import import IdentityAccountBinding, _bytes
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.mybroker_preflight import MAX_BATCH_BYTES, MAX_DOCUMENTS, preview_batch
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/mybroker-preflight", tags=["mybroker-preflight"])


class BatchIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_bindings: list[IdentityAccountBinding] = Field(default_factory=list, max_length=100)
    requested_from: date | None = None
    requested_to: date | None = None


@router.post("/preview")
async def preview(
    files: list[UploadFile] = File(...),
    intent: str = Form("{}"),
    session: Session = Depends(session_for_request),
):
    try:
        requested = BatchIntent.model_validate_json(intent)
    except ValidationError:
        raise HTTPException(422, "preflight_intent_invalid") from None
    if not 1 <= len(files) <= MAX_DOCUMENTS:
        raise HTTPException(422, "preflight_batch_size_invalid")
    originals = []
    total = 0
    for file in files:
        raw = await _bytes(file)
        total += len(raw)
        if total > MAX_BATCH_BYTES:
            raise HTTPException(413, "document_size_invalid")
        originals.append((file.filename or "", raw))
    try:
        return preview_batch(
            session,
            originals=originals,
            account_bindings=[b.model_dump() for b in requested.account_bindings],
            requested_from=requested.requested_from,
            requested_to=requested.requested_to,
        )
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None
