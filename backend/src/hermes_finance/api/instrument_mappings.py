"""Instrument market-data mapping API (R04-03 / R04-05B).

Nested under ``/api/instruments/{id}/market-mapping``. Mapping is reference
data: these endpoints never mutate PositionSnapshot or fetch quotes except
the explicit discover action, which also does not persist.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import close_owned_provider, resolve_verify_provider
from hermes_finance.api.settings import session_for_request
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.services.instrument_mappings import (
    InstrumentMappingView,
    clear_accepted_mapping,
    clear_instrument_mapping_exclusion,
    discover_instrument_candidates,
    exclude_instrument_mapping,
    get_instrument_mapping,
    set_accepted_mapping,
)

router = APIRouter(prefix="/api/instruments", tags=["instruments"])

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


class MarketIdentityWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    provider_instrument_id: str = Field(min_length=1, max_length=128)
    provider_venue_id: str | None = Field(default=None, max_length=96)
    isin: str | None = Field(default=None, max_length=12)


class MarketIdentityRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_instrument_id: str
    provider_venue_id: str | None


class MarketMappingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: int
    state: Literal["unmapped", "mapped", "excluded"]
    identity: MarketIdentityRead | None
    instrument_isin: str | None
    legacy_moex_secid: str | None


class MarketDiscoverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=32)
    query: str | None = Field(default=None, max_length=128)


class MarketDiscoverCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_instrument_id: str
    provider_venue_id: str | None
    instrument_kind: str
    isin: str | None
    name: str | None = None
    ticker: str | None = None
    class_code: str | None = None
    exchange: str | None = None
    api_trade_available: bool | None = None
    position_uid: str | None = None


class MarketDiscoverRejectedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_instrument_id: str
    candidate_isin: str
    expected_isin: str
    reason: str


class MarketDiscoverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: QuotePreviewStatus
    message: str | None
    candidates: list[MarketDiscoverCandidateResponse]
    rejected: list[MarketDiscoverRejectedResponse]


def _response(view: InstrumentMappingView) -> MarketMappingResponse:
    identity = None
    if view.identity is not None:
        identity = MarketIdentityRead(
            provider=view.identity.provider,
            provider_instrument_id=view.identity.provider_instrument_id,
            provider_venue_id=view.identity.provider_venue_id,
        )
    return MarketMappingResponse(
        instrument_id=view.instrument_id,
        state=view.state.value,
        identity=identity,
        instrument_isin=view.instrument_isin,
        legacy_moex_secid=view.legacy_moex_secid,
    )


@router.get("/{instrument_id}/market-mapping", response_model=MarketMappingResponse)
def get_instrument_mapping_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> MarketMappingResponse:
    return _response(get_instrument_mapping(session, instrument_id))


@router.put("/{instrument_id}/market-mapping", response_model=MarketMappingResponse)
def put_instrument_mapping_endpoint(
    instrument_id: int,
    payload: MarketIdentityWrite,
    request: Request,
    verify: bool = Query(default=False),
    session: Session = Depends(session_for_request),
) -> MarketMappingResponse:
    provider: MarketDataProvider | None = None
    owned = False
    if verify:
        provider, owned = resolve_verify_provider(request, payload_provider=payload.provider)
    try:
        view = set_accepted_mapping(
            session,
            instrument_id,
            provider=payload.provider,
            provider_instrument_id=payload.provider_instrument_id,
            provider_venue_id=payload.provider_venue_id,
            isin=payload.isin,
            verify_provider=provider,
        )
    finally:
        close_owned_provider(provider, owned)
    return _response(view)


@router.post(
    "/{instrument_id}/market-mapping/discover",
    response_model=MarketDiscoverResponse,
)
def discover_instrument_mapping_endpoint(
    instrument_id: int,
    payload: MarketDiscoverRequest,
    request: Request,
    session: Session = Depends(session_for_request),
) -> MarketDiscoverResponse:
    provider_name = payload.provider.strip().lower()
    if provider_name != T_INVEST_PROVIDER:
        raise ValueError(f"unsupported discovery provider: {provider_name}")
    provider, owned = resolve_verify_provider(request, payload_provider=provider_name)
    try:
        result = discover_instrument_candidates(
            session,
            instrument_id,
            provider=provider_name,
            query=payload.query,
            market_provider=provider,
        )
    finally:
        close_owned_provider(provider, owned)
    return MarketDiscoverResponse(
        status=result.status.value,
        message=result.message,
        candidates=[
            MarketDiscoverCandidateResponse(
                provider=item.identity.provider,
                provider_instrument_id=item.identity.provider_instrument_id,
                provider_venue_id=item.identity.provider_venue_id,
                instrument_kind=item.instrument_kind.value,
                isin=item.identity.isin,
                name=item.name,
                ticker=item.ticker,
                class_code=item.class_code,
                exchange=item.exchange,
                api_trade_available=item.api_trade_available,
                position_uid=item.position_uid,
            )
            for item in result.candidates
        ],
        rejected=[
            MarketDiscoverRejectedResponse(
                provider_instrument_id=item.provider_instrument_id,
                candidate_isin=item.candidate_isin,
                expected_isin=item.expected_isin,
                reason=item.reason,
            )
            for item in result.rejected
        ],
    )


@router.delete("/{instrument_id}/market-mapping", response_model=MarketMappingResponse)
def delete_instrument_mapping_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> MarketMappingResponse:
    return _response(clear_accepted_mapping(session, instrument_id))


@router.put("/{instrument_id}/market-mapping/exclusion", response_model=MarketMappingResponse)
def put_instrument_mapping_exclusion_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> MarketMappingResponse:
    return _response(exclude_instrument_mapping(session, instrument_id))


@router.delete("/{instrument_id}/market-mapping/exclusion", response_model=MarketMappingResponse)
def delete_instrument_mapping_exclusion_endpoint(
    instrument_id: int,
    session: Session = Depends(session_for_request),
) -> MarketMappingResponse:
    return _response(clear_instrument_mapping_exclusion(session, instrument_id))
