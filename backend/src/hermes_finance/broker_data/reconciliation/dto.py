"""Immutable provider-neutral reconciliation/preview DTOs (R06-04).

Pure, framework-independent. No web framework, ORM, network or persistence.
Every value is preserved with provenance; nothing is synthesized.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState
from hermes_finance.broker_data.dto import SnapshotStatus


class ReconciliationStatus(StrEnum):
    APPLICABLE = "applicable"
    NON_APPLICABLE = "non_applicable"
    CONFLICTS = "conflicts"


class AccountMatchStatus(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    CONFLICT = "conflict"


class InstrumentMatchStatus(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"


class PositionRowStatus(StrEnum):
    MATCHED = "matched"
    PROVIDER_ONLY = "provider_only"
    HERMES_ONLY = "hermes_only"
    CONFLICT = "conflict"


class NormalizedRowState(StrEnum):
    """Canonical position state for the R07-08 reconciliation read model."""

    MATCHED = "matched"
    DIFFERS = "differs"
    MISSING_LOCAL = "missing_local"
    MISSING_PROVIDER = "missing_provider"
    UNRESOLVED = "unresolved"


class CashRowStatus(StrEnum):
    NON_COMPARABLE = "non_comparable"
    COMPARED = "compared"


class ValueComparability(StrEnum):
    COMPARABLE = "comparable"
    NON_COMPARABLE = "non_comparable"


@dataclass(frozen=True, slots=True)
class HermesAccountView:
    account_id: int
    name: str
    account_type: str
    external_code: str | None
    status: str


@dataclass(frozen=True, slots=True)
class HermesInstrumentView:
    instrument_id: int
    name: str
    instrument_type: str
    isin: str | None
    ticker: str | None


@dataclass(frozen=True, slots=True)
class HermesPositionView:
    account_id: int
    instrument_id: int
    quantity: Decimal
    market_price_per_unit_kopecks: int
    accrued_interest_kopecks: int | None
    market_value_kopecks: int
    unrealized_result_kopecks: int


@dataclass(frozen=True, slots=True)
class HermesCashView:
    name: str
    amount_kopecks: int
    currency: str


@dataclass(frozen=True, slots=True)
class HermesStateView:
    """Read-only snapshot of relevant Hermes state for one reporting month."""

    month_id: int
    month_status: str
    accounts: tuple[HermesAccountView, ...]
    instruments: tuple[HermesInstrumentView, ...]
    positions: tuple[HermesPositionView, ...]
    cash_balances: tuple[HermesCashView, ...]


@dataclass(frozen=True, slots=True)
class AccountMappingInput:
    hermes_account_id: int
    provider_account_id: str


@dataclass(frozen=True, slots=True)
class InstrumentMappingInput:
    hermes_instrument_id: int
    provider_instrument_id: str


@dataclass(frozen=True, slots=True)
class OwnerMappingInput:
    """Explicit, owner-controlled transient reconciliation mapping only.

    Never inferred from names, IIAType, ticker, section codes or numeric
    similarity. Persisted mappings are out of scope for R06-04.
    """

    accounts: tuple[AccountMappingInput, ...] = ()
    instruments: tuple[InstrumentMappingInput, ...] = ()


@dataclass(frozen=True, slots=True)
class AccountObservedInstrument:
    """Display-only instrument observations attached to a provider account.

    These values never participate in identity matching. They exist so an owner
    can recognize an unmatched account without inspecting another table.
    """

    display_name: str | None
    isin: str | None
    ticker: str | None


@dataclass(frozen=True, slots=True)
class AccountReconciliationRow:
    provider_account_id: str
    hermes_account_id: int | None
    status: AccountMatchStatus
    reason: str | None
    section_codes: tuple[str, ...] = ()
    observed_instruments: tuple[AccountObservedInstrument, ...] = ()


@dataclass(frozen=True, slots=True)
class InstrumentReconciliationRow:
    provider_instrument_id: str | None
    isin: str | None
    ticker: str | None
    display_name: str | None
    hermes_instrument_id: int | None
    status: InstrumentMatchStatus
    reason: str | None


@dataclass(frozen=True, slots=True)
class PositionReconciliationRow:
    account_id: int
    instrument_id: int
    status: PositionRowStatus
    hermes_quantity: Decimal | None
    provider_quantity: Decimal | None
    quantity_difference: Decimal | None
    quantity_equal: bool | None
    hermes_market_price_per_unit_kopecks: int | None
    provider_broker_unit_price: Decimal | None
    price_comparable: ValueComparability
    hermes_accrued_interest_kopecks: int | None
    provider_accrued_interest_nkd: Decimal | None
    nkd_comparable: ValueComparability
    hermes_unrealized_result_kopecks: int | None
    provider_unrealized_result: Decimal | None
    unrealized_comparable: ValueComparability
    reason: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CashReconciliationRow:
    provider_account_id: str
    hermes_account_id: int | None
    currency: str | None
    provider_amount: Decimal | None
    status: CashRowStatus
    reason: str | None


@dataclass(frozen=True, slots=True)
class ReconciliationPreview:
    status: ReconciliationStatus
    provider: str
    source_as_of: datetime | None
    captured_at: datetime
    eligible_for_apply: bool
    snapshot_status: SnapshotStatus
    month_id: int | None
    month_status: str | None
    month_closed: bool
    would_touch_closed_month: bool
    accounts: tuple[AccountReconciliationRow, ...]
    instruments: tuple[InstrumentReconciliationRow, ...]
    positions: tuple[PositionReconciliationRow, ...]
    cash: tuple[CashReconciliationRow, ...]
    warnings: tuple[str, ...]
    conflict_count: int


COMPARISON_ONLY_PROVIDER_FIELDS = (
    "provider_broker_unit_price",
    "provider_accounting_price",
    "provider_market_value",
    "provider_accrued_interest_nkd",
    "provider_unrealized_result",
)


@dataclass(frozen=True, slots=True)
class NormalizedReconciliationRow:
    """One safe, provider-vs-Hermes position row.

    Provider valuation fields are observations only. They are deliberately
    carried alongside their ``non_comparable`` markers and never become
    write instructions or replacements for Hermes values.
    """

    state: NormalizedRowState
    account_id: int | None
    instrument_id: int | None
    account_name: str | None
    instrument_name: str | None
    instrument_isin: str | None
    instrument_ticker: str | None
    provider_account_id: str | None
    provider_instrument_id: str | None
    hermes_quantity: Decimal | None
    provider_quantity: Decimal | None
    quantity_difference: Decimal | None
    quantity_equal: bool | None
    hermes_market_price_per_unit_kopecks: int | None
    provider_broker_unit_price: Decimal | None
    provider_accounting_price: Decimal | None
    provider_market_value: Decimal | None
    price_comparable: ValueComparability
    hermes_accrued_interest_kopecks: int | None
    provider_accrued_interest_nkd: Decimal | None
    nkd_comparable: ValueComparability
    hermes_unrealized_result_kopecks: int | None
    provider_unrealized_result: Decimal | None
    unrealized_comparable: ValueComparability
    reason: str | None
    warnings: tuple[str, ...]
    comparison_only_fields: tuple[str, ...] = COMPARISON_ONLY_PROVIDER_FIELDS
    fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedReconciliationResult:
    """Normalized read-only reconciliation result for one reporting month."""

    status: ReconciliationStatus
    provider: str
    source_as_of: datetime | None
    captured_at: datetime
    snapshot_status: SnapshotStatus
    compatibility_state: AlfaCompatibilityState
    compatibility_fingerprint: str | None
    month_id: int
    month_status: str
    month_closed: bool
    rows: tuple[NormalizedReconciliationRow, ...]
    accounts: tuple[AccountReconciliationRow, ...]
    instruments: tuple[InstrumentReconciliationRow, ...]
    cash: tuple[CashReconciliationRow, ...]
    warnings: tuple[str, ...]
    snapshot_fingerprint: str | None
    stale: bool = False
    read_only: bool = True
    eligible_for_apply: bool = False
