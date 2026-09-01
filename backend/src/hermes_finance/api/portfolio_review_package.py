"""Read-only owner portfolio-review package endpoint (R08-AI01 / issue #237)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.portfolio_review_package import (
    assemble_portfolio_review_package,
    canonical_json,
)

router = APIRouter(prefix="/api/export", tags=["portfolio-review-package"])


@router.get("/portfolio-review-package")
@router.get("/portfolio-review-package/json")
def get_portfolio_review_package(
    request: Request,
    profile: Literal["concise", "full"] = Query(default="full"),
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        package = assemble_portfolio_review_package(
            session,
            profile=profile,
            generated_at=generated_at,
            evaluated_on=moscow_today(request),
            forecast_version=forecast_version,
        )
        return Response(
            content=canonical_json(package),
            media_type="application/json; charset=utf-8",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    finally:
        session.rollback()
