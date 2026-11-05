"""Read-only canonical AI financial review export (#331 Slice A / issue #351)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import session_for_request
from hermes_finance.api.source_instrument_returns import CleanGap, CleanInstrument
from hermes_finance.services.ai_financial_review import (
    ai_financial_review_filename,
    assemble_ai_financial_review,
    canonical_json,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION

router = APIRouter(prefix="/api/export", tags=["ai-financial-review"])


class CleanExportPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date


class CleanExportAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_ref: str
    period: CleanExportPeriod
    instruments: list[CleanInstrument]
    gaps: list[CleanGap]


class CleanExportUnits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    money: Literal["integer_kopecks"]
    modified_dietz: Literal["fraction_of_weighted_capital"]
    period: Literal["opening_eod_exclusive_closing_eod_inclusive"]


class CleanReturnsExport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: Literal["hermes.finance.clean_returns"]
    schema_version: Literal["1.0.0"]
    source_contract: Literal["clean_returns_overview_v1"]
    basis: Literal["clean_principal_and_valuation_with_received_cash"]
    authority: Literal["provisional"]
    currency: Literal["RUB"]
    units: CleanExportUnits
    accounts: list[CleanExportAccount]


@router.get("/clean-returns/json")
def download_clean_returns(session: Session = Depends(session_for_request)) -> Response:
    """Export the exact clean overview with file-local account references."""
    from hermes_finance.services.clean_instrument_return import read_clean_overview

    try:
        overview = read_clean_overview(session)
        accounts = [
            {
                "account_ref": f"source-account-{index}",
                "period": account["period"],
                # Free-form source labels may contain account or personal data;
                # exact ISIN remains the file's security identity.
                "instruments": [
                    {**instrument, "name": None} for instrument in account["result"]["instruments"]
                ],
                "gaps": account["result"]["gaps"],
            }
            for index, account in enumerate(overview["accounts"], 1)
        ]
        payload = jsonable_encoder(
            CleanReturnsExport.model_validate(
                {
                    "contract": "hermes.finance.clean_returns",
                    "schema_version": "1.0.0",
                    "source_contract": overview["contract_version"],
                    "basis": "clean_principal_and_valuation_with_received_cash",
                    "authority": "provisional",
                    "currency": "RUB",
                    "units": {
                        "money": "integer_kopecks",
                        "modified_dietz": "fraction_of_weighted_capital",
                        "period": "opening_eod_exclusive_closing_eod_inclusive",
                    },
                    "accounts": accounts,
                }
            )
        )
        return Response(
            content=canonical_json(payload),
            media_type="application/json; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": 'attachment; filename="hermes-clean-returns.json"',
            },
        )
    finally:
        session.rollback()


def _assemble(
    request: Request,
    *,
    forecast_version: str,
    generated_at: datetime | None,
    format_version: Literal["1.5.0", "1.6.0", "2.0.0", "2.1.0"],
    session: Session = Depends(session_for_request),
) -> dict[str, object]:
    return assemble_ai_financial_review(
        session,
        generated_at=generated_at,
        evaluated_on=moscow_today(request),
        forecast_version=forecast_version,
        format_version=format_version,
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
    format_version: Literal["1.5.0", "1.6.0", "2.0.0", "2.1.0"] = Query(default="1.6.0"),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        report = _assemble(
            request,
            forecast_version=forecast_version,
            generated_at=generated_at,
            format_version=format_version,
            session=session,
        )
        return Response(
            content=canonical_json(report),
            media_type="application/json; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        session.rollback()


@router.get("/ai-financial-review/json")
def download_ai_financial_review_json(
    request: Request,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    generated_at: datetime | None = Query(default=None),
    format_version: Literal["1.5.0", "1.6.0", "2.0.0", "2.1.0"] = Query(default="1.6.0"),
    session: Session = Depends(session_for_request),
) -> Response:
    try:
        report = _assemble(
            request,
            forecast_version=forecast_version,
            generated_at=generated_at,
            format_version=format_version,
            session=session,
        )
        filename = ai_financial_review_filename(as_of_date=_as_of_date(report), media="json")
        return Response(
            content=canonical_json(report),
            media_type="application/json; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    finally:
        session.rollback()
