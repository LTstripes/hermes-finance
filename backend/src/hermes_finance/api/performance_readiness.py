"""Versioned coherent Performance read projection; no write actions are executed."""

from dataclasses import asdict
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.errors import ErrorResponse, _error_response
from hermes_finance.api.performance_availability import (
    PerformanceAvailabilityResponse,
)
from hermes_finance.api.performance_availability import (
    _response as availability_response,
)
from hermes_finance.api.portfolio_twrr import PortfolioTwrrResponse
from hermes_finance.api.portfolio_twrr import _response as twrr_response
from hermes_finance.api.portfolio_xirr import PortfolioXirrResponse
from hermes_finance.api.portfolio_xirr import _response as xirr_response
from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.valuation_points import PerformanceScope
from hermes_finance.services.performance_availability import _validate_request
from hermes_finance.services.performance_readiness import (
    ReadinessDiagnostic,
    ReadinessRequestError,
    readiness_for_interval,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


class PerformanceReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    scope: Literal["portfolio", "account"]
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    xirr: PortfolioXirrResponse
    twrr: PortfolioTwrrResponse
    evidence: PerformanceAvailabilityResponse
    diagnostics: list[ReadinessDiagnostic]


@router.get(
    "/readiness",
    response_model=PerformanceReadinessResponse,
    responses={503: {"model": ErrorResponse}},
)
def read_performance_readiness(
    request: Request,
    start_date: date = Query(...),
    end_date: date = Query(...),
    scope: PerformanceScope = Query(default=PerformanceScope.PORTFOLIO),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
):
    # Reject context errors before the protected projection; never silently default.
    for name in ("start_date", "end_date", "scope", "account_id"):
        if len(request.query_params.getlist(name)) > 1:
            raise ValueError("Performance query parameters must not be repeated")
    _validate_request(scope=scope, account_id=account_id, start_date=start_date, end_date=end_date)
    try:
        result = readiness_for_interval(
            session,
            start_date=start_date,
            end_date=end_date,
            scope=scope,
            account_id=account_id,
        )
        evidence = availability_response(result.evidence)
        # Free-form provenance references can contain paths/provider text. Keep local
        # IDs and typed evidence, but never echo those references in this projection.
        for item in (
            *evidence.cash_boundary_coverage.evidence,
            *evidence.in_kind_boundary_coverage.evidence,
            *evidence.in_kind_boundary_coverage.known_movements,
        ):
            item.provenance_reference = None
            if item.provenance_kind != "owner_attestation":
                item.provenance_kind = "omitted"
        for flow in evidence.external_flows.flows:
            if flow.source != "manual":
                flow.source = "omitted"
        for boundary in evidence.external_flow_boundaries:
            for observation in (boundary.pre_external_flow, boundary.post_external_flow):
                if observation is not None:
                    observation.provenance_reference = None
                    observation.provenance_kind = "omitted"
        return PerformanceReadinessResponse(
            scope=evidence.scope,
            account_id=evidence.account_id,
            start_date=evidence.start_date,
            end_date=evidence.end_date,
            performance_currency=evidence.performance_currency,
            evidence=evidence,
            xirr=xirr_response(result.xirr),
            twrr=twrr_response(result.twrr),
            diagnostics=[asdict(item) for item in result.diagnostics],
        )
    except ReadinessRequestError:
        raise
    except Exception:
        # No exception text or guessed financial reason; a fresh read is the only
        # supported recovery. Failed snapshots have already been rolled back.
        return _error_response(
            503,
            "performance_readiness_technical_error",
            "Performance check did not complete. Retry the read.",
        )
