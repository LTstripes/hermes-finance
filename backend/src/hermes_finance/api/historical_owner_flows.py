"""Source-only H2-A1 API with strict requests and fresh committed readback."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.historical_owner_flows import OwnerFlowApplyRequest, OwnerFlowIntent
from hermes_finance.services.historical_owner_flows import (
    apply_historical_owner_flow,
    preview_historical_owner_flow,
    read_historical_owner_flow,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/historical-owner-flows", tags=["historical-owner-flows"])


@router.post("/preview")
def preview(request: OwnerFlowIntent, session: Session = Depends(session_for_request)):
    try:
        return preview_historical_owner_flow(session, request)
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
def apply(request: OwnerFlowApplyRequest, session: Session = Depends(session_for_request)):
    intent = OwnerFlowIntent.model_validate(
        request.model_dump(exclude={"request_id", "confirmation_digest"})
    )
    try:
        return apply_historical_owner_flow(
            session,
            intent,
            confirmation_digest=request.confirmation_digest,
            request_id=request.request_id,
        )
    except MyBrokerError as error:
        raise HTTPException(409, str(error)) from None


@router.get("/{flow_id}")
def readback(flow_id: str, session: Session = Depends(session_for_request)):
    try:
        return read_historical_owner_flow(session, flow_id)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
