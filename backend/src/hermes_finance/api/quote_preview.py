"""Quote refresh preview API (R04-04).

Explicit owner-triggered read-only preview for one reporting month.
Never mutates snapshots, mappings, or month status.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal  # datetime kept for QuotePreviewRowResponse fetched_at_utc

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import (
    close_owned_provider,
    moscow_today,
    resolve_production_provider,
)
from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.services.quote_preview import QuotePreviewResult, preview_market_quotes

router = APIRouter(prefix="/api/months", tags=["months"])

QuotePreviewStatus = Literal[
    "ok",
    "stale",
    "unmapped",
    "excluded",
    "unsupported",
    "ambiguous",
    "unavailable",
    "network_error",
    "malformed_response",
]

QuoteFailureReason = Literal[
    "token_unavailable",
    "provider_network",
    "quote_unavailable",
    "unsupported",
    "malformed",
    "unmapped",
    "excluded",
    "ambiguous",
]


class MarketIdentityRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_instrument_id: str
    provider_venue_id: str | None


class QuotePreviewRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_snapshot_id: int
    account_id: int
    instrument_id: int
    instrument_name: str
    instrument_type: str
    mapping_state: Literal["unmapped", "mapped", "excluded"]
    identity: MarketIdentityRead | None
    current_market_price_per_unit: MoneyValue
    current_price_date: date
    current_price_source: str
    proposed_market_price_per_unit: MoneyValue | None
    proposed_price_date: date | None
    proposed_quote_kind: Literal["last", "history"] | None
    proposed_raw_price: str | None
    proposed_raw_price_basis: Literal["R", "F"] | None
    fetched_at_utc: datetime | None
    freshness_status: QuotePreviewStatus | None
    status: QuotePreviewStatus
    failure_reason: QuoteFailureReason | None
    message: str | None
    apply_allowed: bool


class QuotePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    month_status: Literal["draft", "closed"]
    target_date: date
    month_editable: bool
    batch_error: str | None
    batch_error_reason: QuoteFailureReason | None
    rows: list[QuotePreviewRowResponse]


def _money(kopecks: int | None) -> MoneyValue | None:
    if kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _identity(identity: object | None) -> MarketIdentityRead | None:
    if identity is None:
        return None
    return MarketIdentityRead(
        provider=identity.provider,
        provider_instrument_id=identity.provider_instrument_id,
        provider_venue_id=identity.provider_venue_id,
    )


def _response(result: QuotePreviewResult) -> QuotePreviewResponse:
    rows = [
        QuotePreviewRowResponse(
            position_snapshot_id=row.position_snapshot_id,
            account_id=row.account_id,
            instrument_id=row.instrument_id,
            instrument_name=row.instrument_name,
            instrument_type=row.instrument_type,
            mapping_state=row.mapping_state.value,
            identity=_identity(row.identity),
            current_market_price_per_unit=_money(row.current_market_price_kopecks),
            current_price_date=row.current_price_date,
            current_price_source=row.current_price_source,
            proposed_market_price_per_unit=_money(row.proposed_market_price_kopecks),
            proposed_price_date=row.proposed_price_date,
            proposed_quote_kind=row.proposed_quote_kind.value if row.proposed_quote_kind else None,
            proposed_raw_price=row.proposed_raw_price,
            proposed_raw_price_basis=(
                row.proposed_raw_price_basis.value if row.proposed_raw_price_basis else None
            ),
            fetched_at_utc=row.fetched_at_utc,
            freshness_status=row.freshness_status.value if row.freshness_status else None,
            status=row.status.value,
            failure_reason=row.failure_reason.value if row.failure_reason else None,
            message=row.message,
            apply_allowed=row.apply_allowed,
        )
        for row in result.rows
    ]
    return QuotePreviewResponse(
        reporting_month_id=result.reporting_month_id,
        month_status=result.month_status.value,
        target_date=result.target_date,
        month_editable=result.month_editable,
        batch_error=result.batch_error,
        batch_error_reason=result.batch_error_reason.value if result.batch_error_reason else None,
        rows=rows,
    )


@router.post("/{month_id}/quote-preview", response_model=QuotePreviewResponse)
def preview_month_quotes_endpoint(
    month_id: int,
    request: Request,
    session: Session = Depends(session_for_request),
) -> QuotePreviewResponse:
    provider, owned = resolve_production_provider(request)
    try:
        result = preview_market_quotes(
            session,
            month_id,
            provider=provider,
            today=moscow_today(request),
        )
    finally:
        close_owned_provider(provider, owned)
    return _response(result)
