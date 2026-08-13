"""Instrument market-data mapping API (R04-03).

Nested under ``/api/instruments/{id}/market-mapping``. Mapping is reference
data: these endpoints never mutate PositionSnapshot or fetch quotes.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.market_data.moex_iss import MoexIssClient
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.services.instrument_mappings import (
    InstrumentMappingView,
    clear_accepted_mapping,
    clear_instrument_mapping_exclusion,
    exclude_instrument_mapping,
    get_instrument_mapping,
    set_accepted_mapping,
)

router = APIRouter(prefix="/api/instruments", tags=["instruments"])


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


def _provider_for_verify(request: Request) -> tuple[MarketDataProvider, bool]:
    existing = getattr(request.app.state, "market_data_provider", None)
    if existing is not None:
        return existing, False
    return MoexIssClient(), True


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
        provider, owned = _provider_for_verify(request)
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
        if owned and isinstance(provider, MoexIssClient):
            provider.close()
    return _response(view)


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
