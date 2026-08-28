"""Immutable current-state broker snapshot DTOs. Transient observations only."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from hermes_finance.alfa_pro_diagnostics import (
    AlfaCompatibilityState,
    AlfaDiagnosticFailureClass,
    AlfaDiagnosticReport,
)

ALFA_PRO_PROVIDER = "alfa_pro"


class SnapshotStatus(StrEnum):
    COMPLETE = "complete"
    STALE = "stale"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    AUTH_UNRESOLVED = "auth_unresolved"
    AUTH_NOT_AUTHORIZED = "auth_not_authorized"
    COMPATIBILITY_ERROR = "compatibility_error"
    MALFORMED_RESPONSE = "malformed_response"
    INCOMPLETE = "incomplete"


class TimestampProvenance(StrEnum):
    LOCAL_OBSERVATION = "local_observation"
    PROVIDER_SUPPLIED = "provider_supplied"


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    provider: str
    api_doc_version: str
    captured_at: datetime
    timestamp_provenance: TimestampProvenance
    auth_status: int | None
    ready_to_sign: bool | None
    channels_invoked: tuple[str, ...]
    entity_query_status: tuple[str, ...]
    eligible_for_apply: bool
    compatibility_state: AlfaCompatibilityState = AlfaCompatibilityState.UNKNOWN
    compatibility_fingerprint: str | None = None
    failure_class: AlfaDiagnosticFailureClass = AlfaDiagnosticFailureClass.NONE


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    provider_account_id: str


@dataclass(frozen=True, slots=True)
class BrokerSubAccount:
    provider_subaccount_id: str
    provider_account_id: str | None


@dataclass(frozen=True, slots=True)
class BrokerSection:
    provider_section_id: str
    provider_account_id: str | None
    provider_subaccount_id: str | None
    section_group: int | None
    section_code: str | None


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    provider_account_id: str | None
    provider_subaccount_id: str | None
    provider_section_id: str | None
    provider_instrument_id: str | None
    isin: str | None
    ticker: str | None
    display_name: str | None
    quantity: Decimal | None
    broker_unit_price: Decimal | None
    market_value: Decimal | None
    accounting_price: Decimal | None
    accrued_interest_nkd: Decimal | None
    unrealized_result: Decimal | None
    is_money: bool | None
    mapped_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BrokerCashBalance:
    provider_account_id: str | None
    provider_subaccount_id: str | None
    currency: str | None
    amount: Decimal | None
    section_group: int | None
    mapped_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BrokerSnapshot:
    provider: str
    status: SnapshotStatus
    source_as_of: datetime | None
    accounts: tuple[BrokerAccount, ...]
    subaccounts: tuple[BrokerSubAccount, ...]
    sections: tuple[BrokerSection, ...]
    positions: tuple[BrokerPosition, ...]
    cash_balances: tuple[BrokerCashBalance, ...]
    warnings: tuple[str, ...]
    provenance: SnapshotProvenance
    message: str | None = None
    diagnostics: AlfaDiagnosticReport = field(default_factory=AlfaDiagnosticReport)
