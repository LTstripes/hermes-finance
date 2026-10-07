"""Portfolio-only H2-B1 API with strict requests and fresh committed readback."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.historical_portfolio_flows import (
    PortfolioFlowApplyRequest,
    PortfolioFlowIntent,
)
from hermes_finance.services.historical_portfolio_flows import (
    apply_historical_portfolio_flow,
    preview_historical_portfolio_flow,
    read_historical_portfolio_flow,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

router = APIRouter(prefix="/api/historical-portfolio-flows", tags=["historical-portfolio-flows"])


@router.post("/preview")
def preview(request: PortfolioFlowIntent, session: Session = Depends(session_for_request)):
    try:
        return preview_historical_portfolio_flow(session, request)
    except MyBrokerError as error:
        raise HTTPException(422, str(error)) from None


@router.post("/apply")
def apply(request: PortfolioFlowApplyRequest, session: Session = Depends(session_for_request)):
    intent = PortfolioFlowIntent.model_validate(
        request.model_dump(exclude={"request_id", "confirmation_digest"})
    )
    try:
        return apply_historical_portfolio_flow(
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
        return read_historical_portfolio_flow(session, flow_id)
    except MyBrokerError as error:
        raise HTTPException(404, str(error)) from None
