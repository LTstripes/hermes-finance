"""Provider-neutral DTOs for read-only market-data refresh."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class InstrumentKind(StrEnum):
    STOCK = "stock"
    FUND = "fund"
    BOND = "bond"


class MarketDataStatus(StrEnum):
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


class MoexQuoteKind(StrEnum):
    CURRENT_LAST = "current_last"
    HISTORICAL_RESULT = "historical_result"


@dataclass(frozen=True, slots=True)
class MarketIdentity:
    """Canonical provider identity plus discovery metadata needed for quote normalization."""

    provider: str
    engine: str
    market: str
    boardid: str
    secid: str
    instrument_kind: str
    isin: str | None = None
    quote_basis: str | None = None
    quote_currency: str | None = None
    face_value: Decimal | None = None
    face_currency: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("provider", "engine", "market", "boardid", "secid", "instrument_kind"):
            value = getattr(self, field_name).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)

        if self.isin is not None:
            isin = self.isin.strip().upper()
            object.__setattr__(self, "isin", isin or None)
        if self.quote_basis is not None:
            basis = self.quote_basis.strip().upper()
            object.__setattr__(self, "quote_basis", basis or None)
        for field_name in ("quote_currency", "face_currency"):
            value = getattr(self, field_name)
            if value is not None:
                normalized = value.strip().upper()
                object.__setattr__(self, field_name, normalized or None)
        if self.face_value is not None:
            face_value = Decimal(str(self.face_value))
            if not face_value.is_finite():
                raise ValueError("face_value must be finite")
            object.__setattr__(self, "face_value", face_value)


@dataclass(frozen=True, slots=True)
class CandidateDiscoveryResult:
    status: MarketDataStatus
    candidates: tuple[MarketIdentity, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedQuote:
    """Normalized quote proposal; it has no persistence or application-side effects."""

    status: MarketDataStatus
    identity: MarketIdentity
    instrument_kind: str
    raw_price: Decimal | None
    raw_price_basis: RawPriceBasis | None
    proposed_price_kopecks: int | None
    price_date: date | None
    quote_kind: MoexQuoteKind | None
    fetched_at_utc: datetime
    freshness_status: MarketDataStatus | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        fetched_at = self.fetched_at_utc
        if fetched_at.tzinfo is None:
            raise ValueError("fetched_at_utc must be timezone-aware")
        object.__setattr__(self, "fetched_at_utc", fetched_at.astimezone(UTC))
        if self.raw_price is not None:
            raw_price = Decimal(str(self.raw_price))
            if not raw_price.is_finite():
                raise ValueError("raw_price must be finite")
            object.__setattr__(self, "raw_price", raw_price)


@dataclass(frozen=True, slots=True)
class MarketDataBatchResult:
    """Per-identity results are preserved even when another request fails."""

    results: tuple[NormalizedQuote, ...]
    error: str | None = None
