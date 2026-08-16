"""Pure provider-neutral payout domain contract for R05-02."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from hermes_finance.market_data.dto import RUB_COMPATIBLE_UNITS
from hermes_finance.market_data.moscow import moscow_calendar_date


class PayoutDomainError(ValueError):
    """A provider-neutral payout value violates the canonical R05 contract."""


class PayoutEventKind(StrEnum):
    COUPON = "coupon"
    DIVIDEND = "dividend"
    REDEMPTION = "redemption"


class PayoutEventStatus(StrEnum):
    OK = "ok"
    TENTATIVE = "tentative"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    identity_key: str | None
    status: PayoutEventStatus
    reason: str | None = None

    def __post_init__(self) -> None:
        try:
            normalized_status = PayoutEventStatus(self.status)
        except (TypeError, ValueError) as error:
            raise PayoutDomainError("unknown identity resolution status") from error
        object.__setattr__(self, "status", normalized_status)
        if self.status not in {PayoutEventStatus.OK, PayoutEventStatus.AMBIGUOUS_IDENTITY}:
            raise PayoutDomainError("identity resolution status must be ok or ambiguous_identity")
        if self.status is PayoutEventStatus.OK and not _clean_text(self.identity_key):
            raise PayoutDomainError("ok identity resolution requires identity_key")
        if self.status is PayoutEventStatus.AMBIGUOUS_IDENTITY and self.identity_key is not None:
            raise PayoutDomainError("ambiguous identity resolution must not expose identity_key")


@dataclass(frozen=True, slots=True)
class PayoutIdentity:
    provider: str
    instrument_uid: str
    event_kind: PayoutEventKind
    identity_key: str

    def __post_init__(self) -> None:
        try:
            normalized_kind = PayoutEventKind(self.event_kind)
        except (TypeError, ValueError) as error:
            raise PayoutDomainError("unknown payout event kind") from error
        object.__setattr__(self, "event_kind", normalized_kind)
        object.__setattr__(self, "provider", _require_text(self.provider, name="provider"))
        object.__setattr__(
            self,
            "instrument_uid",
            _require_text(self.instrument_uid, name="instrument_uid"),
        )
        object.__setattr__(
            self,
            "identity_key",
            _require_text(self.identity_key, name="identity_key"),
        )


@dataclass(frozen=True, slots=True)
class PayoutEvent:
    provider: str
    instrument_uid: str
    event_kind: PayoutEventKind
    identity_key: str | None
    status: PayoutEventStatus
    payment_date: date | None
    per_unit_amount: Decimal | None
    currency: str | None
    source_method: str | None
    provider_filter_basis: str | None
    provider_filter_date: date | None
    provider_status: str | None = None

    def __post_init__(self) -> None:
        try:
            normalized_kind = PayoutEventKind(self.event_kind)
            normalized_status = PayoutEventStatus(self.status)
        except (TypeError, ValueError) as error:
            raise PayoutDomainError("unknown payout event kind or status") from error
        object.__setattr__(self, "event_kind", normalized_kind)
        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "provider", _require_text(self.provider, name="provider"))
        object.__setattr__(
            self,
            "instrument_uid",
            _require_text(self.instrument_uid, name="instrument_uid"),
        )
        if self.identity_key is not None:
            object.__setattr__(
                self,
                "identity_key",
                _require_text(self.identity_key, name="identity_key"),
            )
        if self.source_method is not None:
            object.__setattr__(
                self,
                "source_method",
                _require_text(self.source_method, name="source_method"),
            )
        if self.provider_filter_basis is not None:
            object.__setattr__(
                self,
                "provider_filter_basis",
                _require_text(self.provider_filter_basis, name="provider_filter_basis"),
            )
        if self.provider_status is not None:
            object.__setattr__(
                self,
                "provider_status",
                _require_text(self.provider_status, name="provider_status"),
            )

        normalized_payment = normalize_payout_date(self.payment_date)
        normalized_filter = normalize_payout_date(self.provider_filter_date)
        object.__setattr__(self, "payment_date", normalized_payment)
        object.__setattr__(self, "provider_filter_date", normalized_filter)

        amount = normalize_exact_decimal(self.per_unit_amount)
        object.__setattr__(self, "per_unit_amount", amount)

        currency = normalize_currency(self.currency)
        object.__setattr__(self, "currency", currency)

        if amount is not None and amount < 0:
            raise PayoutDomainError("per_unit_amount must not be negative")
        if currency is not None and currency not in RUB_COMPATIBLE_UNITS:
            if self.status is not PayoutEventStatus.UNSUPPORTED:
                raise PayoutDomainError("non-RUB payout must be marked unsupported")
        if amount is not None and currency is None:
            raise PayoutDomainError("per_unit_amount requires currency")
        if self.status is PayoutEventStatus.OK:
            if self.identity_key is None:
                raise PayoutDomainError("ok payout event requires stable identity")
            if self.payment_date is None:
                raise PayoutDomainError("ok payout event requires payment_date")
            if self.per_unit_amount is None:
                raise PayoutDomainError("ok payout event requires per_unit_amount")
            if self.currency not in RUB_COMPATIBLE_UNITS:
                raise PayoutDomainError("ok payout event requires RUB-compatible currency")
        if self.status is PayoutEventStatus.AMBIGUOUS_IDENTITY and self.identity_key is not None:
            raise PayoutDomainError("ambiguous payout event must not expose identity_key")
        if (self.provider_filter_basis is None) != (self.provider_filter_date is None):
            raise PayoutDomainError(
                "provider_filter_basis and provider_filter_date must be present together"
            )

    @property
    def identity(self) -> PayoutIdentity | None:
        if self.identity_key is None:
            return None
        return PayoutIdentity(
            provider=self.provider,
            instrument_uid=self.instrument_uid,
            event_kind=self.event_kind,
            identity_key=self.identity_key,
        )


@dataclass(frozen=True, slots=True)
class PayoutCoverage:
    provider: str
    method: str
    instrument_uid: str
    requested_from: date
    requested_to: date
    provider_filter_basis: str
    successful: bool
    structurally_valid: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _require_text(self.provider, name="provider"))
        object.__setattr__(self, "method", _require_text(self.method, name="method"))
        object.__setattr__(
            self,
            "instrument_uid",
            _require_text(self.instrument_uid, name="instrument_uid"),
        )
        object.__setattr__(
            self,
            "provider_filter_basis",
            _require_text(self.provider_filter_basis, name="provider_filter_basis"),
        )
        if isinstance(self.requested_from, datetime) or isinstance(self.requested_to, datetime):
            raise PayoutDomainError("coverage bounds must be date-only values")
        if self.requested_from > self.requested_to:
            raise PayoutDomainError("coverage requested_from must not be after requested_to")
        if self.structurally_valid and not self.successful:
            raise PayoutDomainError("structurally_valid coverage requires a successful fetch")


@dataclass(frozen=True, slots=True)
class ProviderFingerprintMaterial:
    provider: str
    instrument_uid: str
    event_kind: str
    identity_key: str | None
    normalized_status: str
    payment_date: str | None
    per_unit_amount: str | None
    currency: str | None
    provider_status: str | None


def normalize_payout_date(value: date | datetime | None) -> date | None:
    """Normalize instants through Europe/Moscow; never invent a missing date."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return moscow_calendar_date(value)
    if isinstance(value, date):
        return value
    raise PayoutDomainError("payout date must be date, datetime, or None")


def normalize_exact_decimal(value: Decimal | int | str | None) -> Decimal | None:
    """Normalize exact numeric inputs and reject binary floats."""

    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise PayoutDomainError("binary float/bool is forbidden for payout amounts")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise PayoutDomainError("payout amount is empty")
        try:
            amount = Decimal(text)
        except InvalidOperation as error:
            raise PayoutDomainError("payout amount is not an exact decimal") from error
    else:
        raise PayoutDomainError("payout amount must be Decimal, int, str, or None")
    if not amount.is_finite():
        raise PayoutDomainError("payout amount must be finite")
    return amount


def normalize_currency(value: str | None) -> str | None:
    if value is None:
        return None
    return _require_text(value, name="currency").upper()


def resolve_coupon_identity(
    *,
    coupon_number: int | str | None,
    coupon_start_date: date | datetime | None,
    coupon_end_date: date | datetime | None,
    period_is_unique: bool,
) -> IdentityResolution:
    number = _positive_int(coupon_number, name="coupon_number")
    if number is not None:
        return IdentityResolution(f"n:{number}", PayoutEventStatus.OK)
    start = normalize_payout_date(coupon_start_date)
    end = normalize_payout_date(coupon_end_date)
    if start is not None and end is not None and period_is_unique:
        return IdentityResolution(
            f"p:{start.isoformat()}:{end.isoformat()}",
            PayoutEventStatus.OK,
        )
    return IdentityResolution(
        None,
        PayoutEventStatus.AMBIGUOUS_IDENTITY,
        "coupon_number unavailable and coupon period is not proven unique",
    )


def resolve_dividend_identity(
    *,
    stable_provider_event_id: str | None,
    record_date: date | datetime | None,
    record_date_is_unique: bool,
) -> IdentityResolution:
    provider_id = _clean_text(stable_provider_event_id)
    if provider_id is not None:
        return IdentityResolution(f"id:{provider_id}", PayoutEventStatus.OK)
    record = normalize_payout_date(record_date)
    if record is not None and record_date_is_unique:
        return IdentityResolution(f"r:{record.isoformat()}", PayoutEventStatus.OK)
    return IdentityResolution(
        None,
        PayoutEventStatus.AMBIGUOUS_IDENTITY,
        "no stable provider event id and record_date is unavailable or colliding",
    )


def resolve_redemption_identity(
    *,
    event_number: int | str | None,
    event_date: date | datetime | None,
    event_date_is_unique: bool,
) -> IdentityResolution:
    number = _positive_int(event_number, name="event_number")
    if number is not None:
        return IdentityResolution(f"mty:{number}", PayoutEventStatus.OK)
    normalized = normalize_payout_date(event_date)
    if normalized is not None and event_date_is_unique:
        return IdentityResolution(
            f"mty-date:{normalized.isoformat()}",
            PayoutEventStatus.OK,
        )
    return IdentityResolution(
        None,
        PayoutEventStatus.AMBIGUOUS_IDENTITY,
        "MTY event number unavailable and event_date is not proven unique",
    )


def coverage_proves_event_absence(event: PayoutEvent, coverage: PayoutCoverage) -> bool:
    """True only when this exact successful provider window could prove omission."""

    if not coverage.successful or not coverage.structurally_valid:
        return False
    if coverage.provider != event.provider:
        return False
    if coverage.instrument_uid != event.instrument_uid:
        return False
    if event.source_method is None or coverage.method != event.source_method:
        return False
    if event.provider_filter_basis is None or event.provider_filter_date is None:
        return False
    if coverage.provider_filter_basis != event.provider_filter_basis:
        return False
    return coverage.requested_from <= event.provider_filter_date <= coverage.requested_to


def provider_fingerprint_material(event: PayoutEvent) -> ProviderFingerprintMaterial:
    return ProviderFingerprintMaterial(
        provider=event.provider,
        instrument_uid=event.instrument_uid,
        event_kind=event.event_kind.value,
        identity_key=event.identity_key,
        normalized_status=event.status.value,
        payment_date=event.payment_date.isoformat() if event.payment_date is not None else None,
        per_unit_amount=_canonical_decimal(event.per_unit_amount),
        currency=event.currency,
        provider_status=event.provider_status,
    )


def provider_event_fingerprint(event: PayoutEvent) -> str:
    material = provider_fingerprint_material(event)
    payload = {
        "provider": material.provider,
        "instrument_uid": material.instrument_uid,
        "event_kind": material.event_kind,
        "identity_key": material.identity_key,
        "normalized_status": material.normalized_status,
        "payment_date": material.payment_date,
        "per_unit_amount": material.per_unit_amount,
        "currency": material.currency,
        "provider_status": material.provider_status,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _positive_int(value: int | str | None, *, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise PayoutDomainError(f"{name} must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or text[0] == "+" or not text.isdigit():
            raise PayoutDomainError(f"{name} must be an integer")
        number = int(text)
    else:
        raise PayoutDomainError(f"{name} must be an integer")
    return number if number > 0 else None


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_text(value: str, *, name: str) -> str:
    text = _clean_text(value)
    if text is None:
        raise PayoutDomainError(f"{name} must not be empty")
    return text
