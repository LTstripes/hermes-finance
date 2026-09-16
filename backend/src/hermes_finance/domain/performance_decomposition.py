"""Exact PERF04C account and internal-transfer decomposition contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from hermes_finance.domain.performance_attribution import (
    ExternalFlowSummary,
    Perf04aEvidence,
    PerformanceAttributionQuality,
)
from hermes_finance.domain.performance_availability import PerformanceAvailabilityStatus
from hermes_finance.domain.valuation_points import PerformanceScope
from hermes_finance.domain.values import RubleAmount


@dataclass(frozen=True, slots=True)
class TransferReconciliationEvidence:
    """Sanitized evidence attached to one transfer effect."""

    id: int
    kind: str
    amount: RubleAmount
    currency: str

    @property
    def amount_kopecks(self) -> int:
        """Return the exact persisted minor-unit amount."""

        return self.amount.kopecks


@dataclass(frozen=True, slots=True)
class AccountPerformanceComponent:
    """One exact account-scope PERF04A bridge inside a complete split."""

    account_id: int
    opening_value: RubleAmount
    closing_value: RubleAmount
    external_flow_summary: ExternalFlowSummary
    value: RubleAmount

    @property
    def bridge(self) -> RubleAmount:
        """Compatibility spelling for the account's PERF04A bridge amount."""

        return self.value

    @property
    def account_bridge(self) -> RubleAmount:
        """Return the account component without implying investment return."""

        return self.value

    @property
    def amount(self) -> RubleAmount:
        """Compatibility spelling for callers using generic component amounts."""

        return self.value


@dataclass(frozen=True, slots=True)
class InternalTransferEffect:
    """One eligible same-currency internal-transfer reconciliation component."""

    transfer_link_id: int
    source_flow_id: int
    destination_flow_id: int
    source_account_id: int
    destination_account_id: int
    source_date: date
    destination_date: date
    source_amount: RubleAmount
    destination_amount: RubleAmount
    effect: RubleAmount
    reconciliation_evidence: tuple[TransferReconciliationEvidence, ...] = ()

    @property
    def transfer_effect(self) -> RubleAmount:
        """Return ``T_internal_transfer`` without relabelling it as performance."""

        return self.effect

    @property
    def amount(self) -> RubleAmount:
        """Compatibility spelling for callers using generic component amounts."""

        return self.effect

    @property
    def amount_kopecks(self) -> int:
        """Return the exact effect in integer minor units."""

        return self.effect.kopecks


@dataclass(frozen=True, slots=True)
class PerformanceDecompositionResult:
    """Complete or fail-closed PERF04C portfolio decomposition."""

    scope: PerformanceScope
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    availability: PerformanceAvailabilityStatus
    quality: PerformanceAttributionQuality
    parent_value: RubleAmount | None
    value: RubleAmount | None
    account_components: tuple[AccountPerformanceComponent, ...]
    internal_transfer_effects: tuple[InternalTransferEffect, ...]
    parent_opening_value: RubleAmount | None
    parent_closing_value: RubleAmount | None
    parent_external_flow_summary: ExternalFlowSummary
    evidence: Perf04aEvidence
    reason_codes: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.availability is PerformanceAvailabilityStatus.AVAILABLE

    @property
    def parent_amount(self) -> RubleAmount | None:
        """Return the authoritative PERF04A parent amount, if present."""

        return self.parent_value

    @property
    def account_rows(self) -> tuple[AccountPerformanceComponent, ...]:
        """Compatibility spelling for the complete account component rows."""

        return self.account_components

    @property
    def transfer_effects(self) -> tuple[InternalTransferEffect, ...]:
        """Compatibility spelling for internal-transfer component rows."""

        return self.internal_transfer_effects


# Discoverable aliases keep the bounded read-model vocabulary easy to find for
# downstream backend consumers without creating a second financial metric.
PerformanceComponentDecompositionResult = PerformanceDecompositionResult
Perf04cDecompositionResult = PerformanceDecompositionResult
AccountDecompositionComponent = AccountPerformanceComponent
InternalTransferComponent = InternalTransferEffect


__all__ = [
    "AccountDecompositionComponent",
    "AccountPerformanceComponent",
    "InternalTransferComponent",
    "InternalTransferEffect",
    "Perf04cDecompositionResult",
    "PerformanceComponentDecompositionResult",
    "PerformanceDecompositionResult",
    "TransferReconciliationEvidence",
]
