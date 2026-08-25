"""Natural identity and material fingerprints.

There is no stable provider operation id. Row ordinal is not identity.
Mutable payment date/amounts/quantity must not enter natural identity.
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from hermes_finance.domain import FINANCIAL_ROUNDING

_QUANT = Decimal("0.00000001")


def document_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalize_isin(isin: str | None) -> str | None:
    if not isin:
        return None
    normalized = isin.strip().upper()
    return normalized or None


def source_identity_key(
    *,
    provider_account_ref: str | None,
    event_kind: str | None,
    isin: str | None,
    record_date: date | None,
) -> str | None:
    if not provider_account_ref or not event_kind or not isin or record_date is None:
        return None
    return f"{provider_account_ref}|{event_kind}|{isin}|{record_date.isoformat()}"


def mapped_identity_key(
    *,
    hermes_account_id: int | None,
    event_kind: str | None,
    isin: str | None,
    record_date: date | None,
) -> str | None:
    if hermes_account_id is None or not event_kind or not isin or record_date is None:
        return None
    return f"{hermes_account_id}|{event_kind}|{isin}|{record_date.isoformat()}"


def _canon_decimal(value: Decimal | None) -> str:
    if value is None:
        return ""
    quantized = value.quantize(_QUANT, rounding=FINANCIAL_ROUNDING)
    return format(quantized, "f")


def material_fingerprint(
    *,
    event_date: date | None,
    quantity: Decimal | None,
    per_unit: Decimal | None,
    gross_amount: Decimal | None,
    gross_currency: str | None,
    tax_available: bool,
    tax_amount: Decimal | None,
    tax_rate: Decimal | None,
    net_amount: Decimal | None,
    net_currency: str | None,
) -> str | None:
    if (
        event_date is None
        or quantity is None
        or per_unit is None
        or gross_amount is None
        or not gross_currency
        or net_amount is None
        or not net_currency
    ):
        return None
    payload = "|".join(
        (
            f"event_date={event_date.isoformat()}",
            f"quantity={_canon_decimal(quantity)}",
            f"per_unit={_canon_decimal(per_unit)}",
            f"gross={_canon_decimal(gross_amount)}",
            f"gross_currency={gross_currency}",
            f"tax_available={'1' if tax_available else '0'}",
            f"tax={_canon_decimal(tax_amount) if tax_available else ''}",
            f"tax_rate={_canon_decimal(tax_rate)}",
            f"net={_canon_decimal(net_amount)}",
            f"net_currency={net_currency}",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
