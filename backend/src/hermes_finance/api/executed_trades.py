"""Canonical execution Preview/Apply, independently of reporting months."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.executed_trades import (
    apply_executed_trades,
    preview_executed_trades,
    read_executed_trades,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/executed-trades", tags=["executed-trades"])


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identities: list[str] = Field(min_length=1, max_length=1000)


class Confirmation(Selection):
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.post("/preview")
def preview(request: Selection, session: Session = Depends(session_for_request)):
    try:
        return preview_executed_trades(session, request.identities)
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
def apply(request: Confirmation, session: Session = Depends(session_for_request)):
    try:
        return apply_executed_trades(
            session,
            identities=request.identities,
            confirmation_digest=request.confirmation_digest,
            request_id=request.request_id,
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("")
def read_all(session: Session = Depends(session_for_request)):
    return read_executed_trades(session)


@router.get("/{trade_id}")
def read_one(trade_id: int, session: Session = Depends(session_for_request)):
    try:
        return read_executed_trades(session, [trade_id])["trades"][0]
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
