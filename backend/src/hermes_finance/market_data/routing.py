"""Production market-data routing. Direct MOEX ISS is not the live source."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime

import httpx2

from hermes_finance.market_data.dto import (
    MOEX_ISS_PROVIDER,
    T_INVEST_PROVIDER,
    DiscoverResult,
    MarketIdentity,
    QuoteFailure,
    QuoteResult,
    QuoteStatus,
)
from hermes_finance.market_data.t_invest import TInvestClient

MOEX_PRODUCTION_DISABLED_MESSAGE = "MOEX ISS mapping — production provider disabled"


class ProductionMarketDataProvider:
    """Route t_invest identities to T-Invest; keep MOEX offline in production."""

    def __init__(self, t_invest: TInvestClient) -> None:
        self._t_invest = t_invest

    def close(self) -> None:
        self._t_invest.close()

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
    ) -> DiscoverResult:
        return self._t_invest.discover_candidates(
            query=query,
            provider_instrument_id=provider_instrument_id,
            isin=isin,
        )

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        if identity.provider == T_INVEST_PROVIDER:
            return self._t_invest.fetch_quote(identity, target_date)
        if identity.provider == MOEX_ISS_PROVIDER:
            return QuoteFailure(
                status=QuoteStatus.UNSUPPORTED,
                message=MOEX_PRODUCTION_DISABLED_MESSAGE,
                identity=identity,
            )
        return QuoteFailure(
            status=QuoteStatus.UNSUPPORTED,
            message=f"unsupported market-data provider: {identity.provider}",
            identity=identity,
        )

    def fetch_quotes(self, items: Sequence[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


class DisabledMoexVerificationProvider:
    """verify=true for moex_iss must not open a live MOEX connection."""

    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        return DiscoverResult(
            status=QuoteStatus.UNSUPPORTED,
            message=MOEX_PRODUCTION_DISABLED_MESSAGE,
        )

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        return QuoteFailure(
            status=QuoteStatus.UNSUPPORTED,
            message=MOEX_PRODUCTION_DISABLED_MESSAGE,
            identity=identity,
        )

    def fetch_quotes(self, items: Sequence[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]


def read_t_invest_token(settings: object) -> str | None:
    secret = getattr(settings, "t_invest_read_only_token", None)
    if secret is None:
        return None
    getter = getattr(secret, "get_secret_value", None)
    raw = getter() if callable(getter) else secret
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    return cleaned or None


def production_market_data_provider(
    *,
    token: str | None,
    client: httpx2.Client | None = None,
    clock: Callable[[], date] | None = None,
    utcnow: Callable[[], datetime] | None = None,
) -> ProductionMarketDataProvider:
    return ProductionMarketDataProvider(
        TInvestClient(
            token=token,
            client=client,
            clock=clock,
            utcnow=utcnow,
        )
    )
