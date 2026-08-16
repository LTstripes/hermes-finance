"""Provider-neutral payout retrieval protocol for R05-02."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from hermes_finance.market_data.payout import (
    PayoutCoverage,
    PayoutDomainError,
    PayoutEvent,
    PayoutEventStatus,
)


@dataclass(frozen=True, slots=True)
class PayoutFetchRequest:
    instrument_uid: str
    calendar_from: date
    calendar_to: date

    def __post_init__(self) -> None:
        uid = self.instrument_uid.strip()
        if not uid:
            raise PayoutDomainError("instrument_uid must not be empty")
        object.__setattr__(self, "instrument_uid", uid)
        if isinstance(self.calendar_from, datetime) or isinstance(self.calendar_to, datetime):
            raise PayoutDomainError("calendar bounds must be date-only values")
        if self.calendar_from > self.calendar_to:
            raise PayoutDomainError("calendar_from must not be after calendar_to")


@dataclass(frozen=True, slots=True)
class PayoutFailure:
    status: PayoutEventStatus
    message: str
    method: str | None = None

    def __post_init__(self) -> None:
        try:
            normalized_status = PayoutEventStatus(self.status)
        except (TypeError, ValueError) as error:
            raise PayoutDomainError("unknown payout failure status") from error
        object.__setattr__(self, "status", normalized_status)
        if self.status not in {
            PayoutEventStatus.UNSUPPORTED,
            PayoutEventStatus.UNAVAILABLE,
            PayoutEventStatus.ERROR,
        }:
            raise PayoutDomainError(
                "payout failure status must be unsupported, unavailable, or error"
            )
        message = self.message.strip()
        if not message:
            raise PayoutDomainError("payout failure message must not be empty")
        object.__setattr__(self, "message", message)
        if self.method is not None:
            method = self.method.strip()
            if not method:
                raise PayoutDomainError("payout failure method must not be empty")
            object.__setattr__(self, "method", method)


@dataclass(frozen=True, slots=True)
class PayoutFetchResult:
    provider: str
    instrument_uid: str
    events: tuple[PayoutEvent, ...] = ()
    coverage: tuple[PayoutCoverage, ...] = ()
    failures: tuple[PayoutFailure, ...] = ()

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        uid = self.instrument_uid.strip()
        if not provider or not uid:
            raise PayoutDomainError("fetch result provider/instrument_uid must not be empty")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "instrument_uid", uid)
        if any(event.provider != provider or event.instrument_uid != uid for event in self.events):
            raise PayoutDomainError(
                "fetch result contains an event from another provider/instrument"
            )
        if any(item.provider != provider or item.instrument_uid != uid for item in self.coverage):
            raise PayoutDomainError(
                "fetch result contains coverage from another provider/instrument"
            )


class PayoutProvider(Protocol):
    def fetch_payouts(self, request: PayoutFetchRequest) -> PayoutFetchResult: ...
