"""Replaceable read-only market-data provider protocol."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.capabilities import ProviderCapabilities
from hermes_finance.market_data.dto import DiscoverResult, MarketIdentity, QuoteResult


class MarketDataProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
        instrument_kind: InstrumentType | None = None,
    ) -> DiscoverResult: ...

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult: ...

    def fetch_quotes(self, items: Sequence[tuple[MarketIdentity, date]]) -> list[QuoteResult]: ...
