"""Read-only owner portfolio-review package endpoint (R08-AI01 / issue #237)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.portfolio_review_package import (
    assemble_portfolio_review_package,
    canonical_json,
    portfolio_review_package_filename,
    render_portfolio_review_markdown,
)

router = APIRouter(prefix="/api/export", tags=["portfolio-review-package"])


def _assemble(
    request: Request,
    *,
    profile: Literal["concise", "full"],
    forecast_version: str,
    generated_at: datetime | None,
    session: Session = Depends(session_for_request),
) -> dict[str, object]:
    return assemble_portfolio_review_package(
        session,
        profile=profile,
        generated_at=generated_at,
        evaluated_on=moscow_today(request),
        forecast_version=forecast_version,
    )


def _as_of_date(package: dict[str, object]) -> date:
    metadata = package.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("package metadata is unavailable")
    return date.fromisoformat(str(metadata["as_of_date"]))


@router.get("/portfolio-review-package")
def get_portfolio_review_package(
    request: Request,
    profile: Literal["concise", "full"] = Query(default="full"),
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        package = _assemble(
            request,
            profile=profile,
            forecast_version=forecast_version,
            generated_at=generated_at,
            session=session,
        )
        return Response(
            content=canonical_json(package),
            media_type="application/json; charset=utf-8",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    finally:
        session.rollback()


@router.get("/portfolio-review-package/json")
def download_portfolio_review_package_json(
    request: Request,
    profile: Literal["concise", "full"] = Query(default="full"),
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        package = _assemble(
            request,
            profile=profile,
            forecast_version=forecast_version,
            generated_at=generated_at,
            session=session,
        )
        filename = portfolio_review_package_filename(
            as_of_date=_as_of_date(package), profile=profile, media="json"
        )
        return Response(
            content=canonical_json(package),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        session.rollback()


@router.get("/portfolio-review-package/markdown")
def download_portfolio_review_package_markdown(
    request: Request,
    profile: Literal["concise", "full"] = Query(default="full"),
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        package = _assemble(
            request,
            profile=profile,
            forecast_version=forecast_version,
            generated_at=generated_at,
            session=session,
        )
        filename = portfolio_review_package_filename(
            as_of_date=_as_of_date(package), profile=profile, media="markdown"
        )
        return Response(
            content=render_portfolio_review_markdown(package),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        session.rollback()
