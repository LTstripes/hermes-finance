"""Read-only canonical AI financial review export (#331 Slice A / issue #351)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.ai_financial_review import (
    ai_financial_review_filename,
    assemble_ai_financial_review,
    canonical_json,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION

router = APIRouter(prefix="/api/export", tags=["ai-financial-review"])


def _assemble(
    request: Request,
    *,
    forecast_version: str,
    generated_at: datetime | None,
    session: Session = Depends(session_for_request),
) -> dict[str, object]:
    return assemble_ai_financial_review(
        session,
        generated_at=generated_at,
        evaluated_on=moscow_today(request),
        forecast_version=forecast_version,
    )


def _as_of_date(report: dict[str, object]) -> date:
    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("report metadata is unavailable")
    return date.fromisoformat(str(metadata["as_of_date"]))


@router.get("/ai-financial-review")
def get_ai_financial_review(
    request: Request,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        report = _assemble(
            request,
            forecast_version=forecast_version,
            generated_at=generated_at,
            session=session,
        )
        return Response(
            content=canonical_json(report),
            media_type="application/json; charset=utf-8",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    finally:
        session.rollback()


@router.get("/ai-financial-review/json")
def download_ai_financial_review_json(
    request: Request,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        report = _assemble(
            request,
            forecast_version=forecast_version,
            generated_at=generated_at,
            session=session,
        )
        filename = ai_financial_review_filename(as_of_date=_as_of_date(report), media="json")
        return Response(
            content=canonical_json(report),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        session.rollback()
