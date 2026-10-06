"""Endpoint acceptance API. Apply returns a fresh committed-session readback."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.historical_endpoints import EndpointApplyRequest, EndpointIntent
from hermes_finance.services.historical_endpoints import (
    apply_historical_endpoint,
    preview_historical_endpoint,
    read_historical_endpoint,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/historical-endpoints", tags=["historical-endpoints"])


@router.post("/preview")
def preview(request: EndpointIntent, session: Session = Depends(session_for_request)):
    try:
        return preview_historical_endpoint(session, request)
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
def apply(request: EndpointApplyRequest, session: Session = Depends(session_for_request)):
    intent = EndpointIntent.model_validate(
        request.model_dump(exclude={"request_id", "confirmation_digest"})
    )
    try:
        return apply_historical_endpoint(
            session,
            intent,
            confirmation_digest=request.confirmation_digest,
            request_id=request.request_id,
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/{endpoint_key}")
def readback(endpoint_key: str, session: Session = Depends(session_for_request)):
    try:
        return read_historical_endpoint(session, endpoint_key)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
