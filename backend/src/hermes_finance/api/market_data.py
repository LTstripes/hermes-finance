"""Request-scoped production market-data wiring. No startup/network on import."""

from __future__ import annotations

import os
from datetime import date, datetime

from fastapi import Request

from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.moscow import MOSCOW_TZ
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.market_data.routing import (
    DisabledMoexVerificationProvider,
    production_market_data_provider,
    read_t_invest_token,
)
from hermes_finance.settings import Settings


def _runtime_settings(request: Request) -> Settings:
    existing = getattr(request.app.state, "settings", None)
    if existing is not None:
        return existing
    if "PYTEST_CURRENT_TEST" in os.environ:
        return Settings(_env_file=None)
    return Settings()


def resolve_production_provider(request: Request) -> tuple[MarketDataProvider, bool]:
    existing = getattr(request.app.state, "market_data_provider", None)
    if existing is not None:
        return existing, False
    http = getattr(request.app.state, "t_invest_http_client", None)
    clock = getattr(request.app.state, "quote_preview_clock", None)
    utcnow = getattr(request.app.state, "t_invest_utcnow", None)
    return (
        production_market_data_provider(
            token=read_t_invest_token(_runtime_settings(request)),
            client=http,
            clock=clock,
            utcnow=utcnow,
        ),
        True,
    )


def resolve_verify_provider(
    request: Request, *, payload_provider: str
) -> tuple[MarketDataProvider, bool]:
    existing = getattr(request.app.state, "market_data_provider", None)
    if existing is not None:
        return existing, False
    if payload_provider == T_INVEST_PROVIDER:
        return resolve_production_provider(request)
    return DisabledMoexVerificationProvider(), False


def close_owned_provider(provider: object, owned: bool) -> None:
    if owned:
        closer = getattr(provider, "close", None)
        if callable(closer):
            closer()


def moscow_today(request: Request) -> date:
    clock = getattr(request.app.state, "quote_preview_clock", None)
    if clock is not None:
        return clock()
    return datetime.now(MOSCOW_TZ).date()
