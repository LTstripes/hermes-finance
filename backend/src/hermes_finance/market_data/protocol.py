"""Replaceable read-only market-data provider protocol."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from hermes_finance.market_data.dto import DiscoverResult, MarketIdentity, QuoteResult


class MarketDataProvider(Protocol):
    def discover_candidates(
        self,
        *,
        query: str | None = None,
        secid: str | None = None,
        isin: str | None = None,
    ) -> DiscoverResult: ...

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult: ...

    def fetch_quotes(self, items: Sequence[tuple[MarketIdentity, date]]) -> list[QuoteResult]: ...
