"""Exact T-Invest Quotation / MoneyValue conversion. No binary-float arithmetic."""

from __future__ import annotations

from decimal import Decimal

NANO_SCALE = Decimal(1_000_000_000)
NANO_LIMIT = 1_000_000_000


class QuotationError(ValueError):
    """units + nano cannot be interpreted as an exact decimal."""


def _require_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or value is None:
        raise QuotationError(f"{name} is missing or not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text[0] == "+" or "." in text or "e" in text.lower():
            raise QuotationError(f"{name} is not an integer")
        try:
            return int(text)
        except ValueError as error:
            raise QuotationError(f"{name} is not an integer") from error
    raise QuotationError(f"{name} is not an integer")


def quotation_to_decimal(*, units: object, nano: object) -> Decimal:
    """Exact official conversion: units + nano / 1_000_000_000."""

    units_i = _require_int(units, name="units")
    nano_i = _require_int(nano, name="nano")
    if abs(nano_i) >= NANO_LIMIT:
        raise QuotationError("nano is outside the official 10^-9 scale")
    return Decimal(units_i) + (Decimal(nano_i) / NANO_SCALE)
