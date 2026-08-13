"""Quote freshness and RUB-per-unit conversion. No HTTP, no persistence."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.market_data.dto import (
    RUB_COMPATIBLE_UNITS,
    QuoteStatus,
    RawPriceBasis,
)

MAX_LOOKBACK_DAYS = 30
FRESH_MAX_DAYS = 7

SUPPORTED_KINDS = frozenset({InstrumentType.STOCK, InstrumentType.FUND, InstrumentType.BOND})


class NormalizeError(ValueError):
    def __init__(self, status: QuoteStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def is_rub_compatible(unit: str | None) -> bool:
    if unit is None:
        return False
    return unit.strip().upper() in RUB_COMPATIBLE_UNITS


def _unknown_or_rub_compatible(unit: str | None) -> bool:
    return unit is None or is_rub_compatible(unit)


def discovery_board_is_rub_compatible(
    *,
    instrument_kind: InstrumentType,
    quote_basis: str | None,
    board_currency: str | None,
    face_unit: str | None,
) -> bool:
    """Whether a discovered board may enter the candidate/ambiguity set.

    Unknown units are not a rejection. Known non-RUB units are.
    Bond ``F`` must check quote/board currency and FACEUNIT independently.
    """

    if instrument_kind in {InstrumentType.STOCK, InstrumentType.FUND}:
        return _unknown_or_rub_compatible(board_currency)
    if instrument_kind is InstrumentType.BOND:
        basis = quote_basis.strip().upper() if quote_basis else None
        if basis == RawPriceBasis.PERCENT_OF_FACE:
            return _unknown_or_rub_compatible(board_currency) and _unknown_or_rub_compatible(
                face_unit
            )
        return _unknown_or_rub_compatible(board_currency)
    return False


def classify_freshness(target_date: date, price_date: date) -> QuoteStatus:
    if price_date > target_date:
        raise NormalizeError(
            QuoteStatus.MALFORMED_RESPONSE,
            "price_date is after target_date",
        )
    age_days = (target_date - price_date).days
    if age_days > MAX_LOOKBACK_DAYS:
        return QuoteStatus.UNAVAILABLE
    if age_days > FRESH_MAX_DAYS:
        return QuoteStatus.STALE
    return QuoteStatus.OK


def lookback_start(target_date: date) -> date:
    return target_date - timedelta(days=MAX_LOOKBACK_DAYS)


def current_last_price_date(*, session_date: date, target_date: date) -> date | None:
    """Trading date for a live ISS ``LAST``.

    Documented shares ``marketdata`` carries ``LAST`` / ``TIME`` / ``SYSTIME`` and
    does not include ``TRADEDATE`` or ``LASTTRADEDATE``. ``TIME`` has no date;
    ``SYSTIME`` is the ISS server clock, not the trade date. ``LAST`` is the last
    trade of the current Moscow session, so ``price_date`` is that session date —
    never SYSTIME and never the local HTTP fetch timestamp.
    """

    if session_date > target_date:
        return None
    return session_date


def convert_to_kopecks(
    *,
    raw_price: Decimal,
    basis: RawPriceBasis,
    face_value: Decimal | None,
    currency_unit: str | None,
    shares_schema_cash_default: bool,
) -> int:
    if isinstance(raw_price, float) or isinstance(face_value, float):  # type: ignore[unreachable]
        raise TypeError("financial conversion cannot use float")
    if not raw_price.is_finite() or raw_price <= 0:
        raise NormalizeError(QuoteStatus.MALFORMED_RESPONSE, "quote is not a positive amount")

    currency_ok = is_rub_compatible(currency_unit)
    if not currency_ok and not (shares_schema_cash_default and currency_unit is None):
        raise NormalizeError(QuoteStatus.UNSUPPORTED, "quote is not RUB-compatible")

    if basis is RawPriceBasis.PERCENT_OF_FACE:
        if face_value is None:
            raise NormalizeError(
                QuoteStatus.MALFORMED_RESPONSE,
                "percent-of-face quote is missing FACEVALUE",
            )
        if not face_value.is_finite() or face_value <= 0:
            raise NormalizeError(
                QuoteStatus.MALFORMED_RESPONSE, "FACEVALUE is not a positive amount"
            )
        if not is_rub_compatible(currency_unit):
            raise NormalizeError(QuoteStatus.UNSUPPORTED, "bond face unit is not RUB-compatible")
        amount = face_value * raw_price / Decimal(100)
    elif basis is RawPriceBasis.CASH_PER_UNIT:
        amount = raw_price
    else:
        raise NormalizeError(QuoteStatus.UNSUPPORTED, "unknown quote basis")

    return RubleAmount.from_decimal(amount).kopecks


def resolve_quote_basis(
    *,
    quoted_basis: str | None,
    market: str,
    instrument_kind: InstrumentType,
) -> RawPriceBasis:
    if quoted_basis:
        code = quoted_basis.strip().upper()
        if code == RawPriceBasis.CASH_PER_UNIT:
            return RawPriceBasis.CASH_PER_UNIT
        if code == RawPriceBasis.PERCENT_OF_FACE:
            return RawPriceBasis.PERCENT_OF_FACE
        raise NormalizeError(QuoteStatus.UNSUPPORTED, f"unknown QUOTEBASIS={quoted_basis}")
    if instrument_kind in {InstrumentType.STOCK, InstrumentType.FUND} and market == "shares":
        return RawPriceBasis.CASH_PER_UNIT
    raise NormalizeError(QuoteStatus.UNSUPPORTED, "QUOTEBASIS is missing")
