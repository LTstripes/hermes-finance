"""MOEX-specific market identity codec.

Canonical generic identity never carries engine/market/boardid/secid.
This module is the only place that encodes or decodes MOEX venue context.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermes_finance.market_data.dto import MOEX_ISS_PROVIDER, MarketIdentity


class InvalidMoexIdentityError(ValueError):
    """Raised when a MOEX venue or SECID cannot be encoded or decoded strictly."""


@dataclass(frozen=True, slots=True)
class MoexIdentityParts:
    engine: str
    market: str
    boardid: str
    secid: str


def normalize_moex_secid(secid: str) -> str:
    normalized = secid.strip().upper()
    if not normalized:
        raise InvalidMoexIdentityError("MOEX SECID is required")
    return normalized


def encode_moex_venue(*, engine: str, market: str, boardid: str) -> str:
    engine_n = engine.strip().lower()
    market_n = market.strip().lower()
    boardid_n = boardid.strip().upper()
    if not engine_n or not market_n or not boardid_n:
        raise InvalidMoexIdentityError("MOEX venue requires non-empty engine, market and boardid")
    if "/" in engine_n or "/" in market_n or "/" in boardid_n:
        raise InvalidMoexIdentityError("MOEX venue components cannot contain '/'")
    return f"{engine_n}/{market_n}/{boardid_n}"


def decode_moex_venue(venue_id: str) -> tuple[str, str, str]:
    if not venue_id.strip():
        raise InvalidMoexIdentityError("MOEX provider_venue_id is required")
    parts = venue_id.split("/")
    if len(parts) != 3:
        raise InvalidMoexIdentityError("MOEX provider_venue_id must be engine/market/boardid")
    engine, market, boardid = (part.strip() for part in parts)
    if not engine or not market or not boardid:
        raise InvalidMoexIdentityError(
            "MOEX provider_venue_id must have three non-empty components"
        )
    return engine.lower(), market.lower(), boardid.upper()


def market_identity_from_moex(
    *,
    engine: str,
    market: str,
    boardid: str,
    secid: str,
    isin: str | None = None,
) -> MarketIdentity:
    return MarketIdentity(
        provider=MOEX_ISS_PROVIDER,
        provider_instrument_id=normalize_moex_secid(secid),
        provider_venue_id=encode_moex_venue(engine=engine, market=market, boardid=boardid),
        isin=_normalize_isin(isin),
    )


def moex_parts_from_identity(identity: MarketIdentity) -> MoexIdentityParts:
    if identity.provider != MOEX_ISS_PROVIDER:
        raise InvalidMoexIdentityError(f"not a moex_iss identity: {identity.provider}")
    if identity.provider_venue_id is None:
        raise InvalidMoexIdentityError("moex_iss identity requires provider_venue_id")
    engine, market, boardid = decode_moex_venue(identity.provider_venue_id)
    return MoexIdentityParts(
        engine=engine,
        market=market,
        boardid=boardid,
        secid=normalize_moex_secid(identity.provider_instrument_id),
    )


def _normalize_isin(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None
