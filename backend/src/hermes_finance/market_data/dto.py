"""Provider-agnostic market-data DTOs for the R04-02 read-only boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from hermes_finance.domain import InstrumentType

MOEX_ISS_PROVIDER = "moex_iss"

RUB_COMPATIBLE_UNITS = frozenset({"RUB", "SUR", "RUR"})


class QuoteStatus(StrEnum):
    OK = "ok"
    STALE = "stale"
    UNMAPPED = "unmapped"
    EXCLUDED = "excluded"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"
    NETWORK_ERROR = "network_error"
    MALFORMED_RESPONSE = "malformed_response"


class RawPriceBasis(StrEnum):
    CASH_PER_UNIT = "R"
    PERCENT_OF_FACE = "F"


class QuoteKind(StrEnum):
    LAST = "last"
    HISTORY = "history"


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    provider: str
    engine: str
    market: str
    boardid: str
    secid: str
    isin: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoverCandidate:
    identity: MarketIdentity
    instrument_kind: InstrumentType


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    secid: str
    candidate_isin: str
    expected_isin: str
    reason: str = "isin_mismatch"


@dataclass(frozen=True, slots=True)
class DiscoverResult:
    status: QuoteStatus
    candidates: tuple[DiscoverCandidate, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    message: str | None = None


@dataclass(frozen=True, slots=True)
class QuoteSuccess:
    identity: MarketIdentity
    instrument_kind: InstrumentType
    raw_price: str
    raw_price_basis: RawPriceBasis
    proposed_price_kopecks: int
    price_date: date
    quote_kind: QuoteKind
    fetched_at_utc: datetime
    freshness_status: QuoteStatus

    @property
    def status(self) -> QuoteStatus:
        return self.freshness_status


@dataclass(frozen=True, slots=True)
class QuoteFailure:
    status: QuoteStatus
    message: str
    identity: MarketIdentity | None = None


QuoteResult = QuoteSuccess | QuoteFailure
