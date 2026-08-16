"""Explicit selective quote apply API (R04-06)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import (
    close_owned_provider,
    moscow_today,
    resolve_production_provider,
)
from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import RubleAmount
from hermes_finance.market_data.dto import MarketIdentity
from hermes_finance.services.quote_apply import (
    QuoteApplyResult,
    QuoteApplySelection,
    apply_market_quotes,
)

router = APIRouter(prefix="/api/months", tags=["months"])


class QuoteApplyIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_instrument_id: str
    provider_venue_id: str | None = None


class QuoteApplyRowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_snapshot_id: int
    accept_stale: bool = False
    expected_market_price_per_unit: MoneyValue
    expected_price_date: date
    expected_identity: QuoteApplyIdentity
    expected_quote_kind: str | None = None


class QuoteApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[QuoteApplyRowRequest] = Field(min_length=1)


class QuoteApplyRowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_snapshot_id: int
    market_price_per_unit: MoneyValue
    market_value: MoneyValue
    unrealized_result: MoneyValue
    accrued_interest: MoneyValue | None
    price_date: date
    price_source: str
    freshness: str


class QuoteApplyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    applied_count: int
    rows: list[QuoteApplyRowResponse]


def _money(kopecks: int | None) -> MoneyValue | None:
    if kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _amount(value: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(value.amount)


def _selection(row: QuoteApplyRowRequest) -> QuoteApplySelection:
    return QuoteApplySelection(
        position_snapshot_id=row.position_snapshot_id,
        accept_stale=row.accept_stale,
        expected_market_price_kopecks=_amount(row.expected_market_price_per_unit).kopecks,
        expected_price_date=row.expected_price_date,
        expected_identity=MarketIdentity(
            provider=row.expected_identity.provider,
            provider_instrument_id=row.expected_identity.provider_instrument_id,
            provider_venue_id=row.expected_identity.provider_venue_id,
        ),
        expected_quote_kind=row.expected_quote_kind,
    )


def _response(result: QuoteApplyResult) -> QuoteApplyResponse:
    return QuoteApplyResponse(
        reporting_month_id=result.reporting_month_id,
        applied_count=result.applied_count,
        rows=[
            QuoteApplyRowResponse(
                position_snapshot_id=row.position_snapshot_id,
                market_price_per_unit=MoneyValue(
                    amount=RubleAmount(row.market_price_per_unit_kopecks).to_api(),
                    currency="RUB",
                ),
                market_value=MoneyValue(
                    amount=RubleAmount(row.market_value_kopecks).to_api(),
                    currency="RUB",
                ),
                unrealized_result=MoneyValue(
                    amount=RubleAmount(row.unrealized_result_kopecks).to_api(),
                    currency="RUB",
                ),
                accrued_interest=_money(row.accrued_interest_kopecks),
                price_date=row.price_date,
                price_source=row.price_source,
                freshness=row.freshness,
            )
            for row in result.rows
        ],
    )


@router.post("/{month_id}/quote-apply", response_model=QuoteApplyResponse)
def apply_month_quotes_endpoint(
    month_id: int,
    payload: QuoteApplyRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> QuoteApplyResponse:
    provider, owned = resolve_production_provider(request)
    try:
        result = apply_market_quotes(
            session,
            month_id,
            [_selection(row) for row in payload.rows],
            provider=provider,
            today=moscow_today(request),
        )
    finally:
        close_owned_provider(provider, owned)
    return _response(result)
