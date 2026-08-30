"""Owner-triggered local AI Analysis Bundle export (R07-02 / issue #129)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.services.ai_analysis_bundle import (
    assemble_ai_analysis_bundle,
    bundle_filename,
    canonical_json,
    render_bundle_markdown,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION

router = APIRouter(prefix="/api/export", tags=["ai-analysis-bundle"])


def _export_response(
    session: Session,
    *,
    media: str,
    forecast_version: str,
    generated_at: datetime | None,
) -> Response:
    bundle = assemble_ai_analysis_bundle(
        session,
        generated_at=generated_at,
        forecast_version=forecast_version,
    )
    as_of = datetime.fromisoformat(str(bundle["metadata"]["as_of_date"])).date()
    filename = bundle_filename(as_of_date=as_of, media=media)
    if media == "markdown":
        return Response(
            content=render_bundle_markdown(bundle),
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    return Response(
        content=canonical_json(bundle),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "application/json; charset=utf-8",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/ai-analysis-bundle")
@router.post("/ai-analysis-bundle/json")
def export_ai_analysis_bundle_json(
    media: str = Query(default="json", pattern="^(json|markdown)$"),
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        return _export_response(
            session,
            media=media,
            forecast_version=forecast_version,
            generated_at=generated_at,
        )
    finally:
        session.rollback()


@router.post("/ai-analysis-bundle/markdown")
def export_ai_analysis_bundle_markdown(
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        return _export_response(
            session,
            media="markdown",
            forecast_version=forecast_version,
            generated_at=generated_at,
        )
    finally:
        session.rollback()
