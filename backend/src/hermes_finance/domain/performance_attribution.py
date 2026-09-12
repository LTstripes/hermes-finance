"""Exact PERF04A selected-scope value-bridge read-model contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from hermes_finance.domain.cash_boundary_coverage import CashBoundaryCoverage
from hermes_finance.domain.in_kind_boundary_coverage import InKindBoundaryCoverage
from hermes_finance.domain.performance_availability import (
    ExternalFlowCoverage,
    PerformanceAvailabilityStatus,
    ScopeMembershipCoverage,
    ValuationBoundaryEvidence,
)
from hermes_finance.domain.valuation_points import PerformanceScope
from hermes_finance.domain.values import RubleAmount


class PerformanceAttributionQuality(StrEnum):
    """Quality vocabulary for the exact PERF04A aggregate result."""

    EXACT = "exact"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Perf04aValuationEvidence:
    """Sanitized evidence state for one bridge valuation endpoint."""

    availability: PerformanceAvailabilityStatus
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Perf04aCoverageEvidence:
    """Sanitized evidence state for one non-valuation bridge prerequisite."""

    status: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Perf04aEvidence:
    """Evidence projection exposed alongside the aggregate bridge."""

    opening_valuation: Perf04aValuationEvidence
    closing_valuation: Perf04aValuationEvidence
    scope_membership: Perf04aCoverageEvidence
    cash_boundary_coverage: Perf04aCoverageEvidence
    in_kind_boundary_coverage: Perf04aCoverageEvidence
    external_flows: Perf04aCoverageEvidence


@dataclass(frozen=True, slots=True)
class Perf04aBridgePrerequisites:
    """Dedicated PERF04A gate assembled from shared R08 evidence.

    This projection intentionally has its own availability and reason set.  It
    is not the top-level R08 availability union and does not contain a return
    solver result.
    """

    scope: PerformanceScope
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    availability: PerformanceAvailabilityStatus
    reason_codes: tuple[str, ...]
    opening_valuation: ValuationBoundaryEvidence
    closing_valuation: ValuationBoundaryEvidence
    scope_membership: ScopeMembershipCoverage
    cash_boundary_coverage: CashBoundaryCoverage
    in_kind_boundary_coverage: InKindBoundaryCoverage
    external_flows: ExternalFlowCoverage
    evidence: Perf04aEvidence

    @property
    def is_available(self) -> bool:
        return self.availability is PerformanceAvailabilityStatus.AVAILABLE


@dataclass(frozen=True, slots=True)
class ExternalFlowSummary:
    """Exact selected-scope contribution/withdrawal magnitudes."""

    contributions: RubleAmount | None
    withdrawals: RubleAmount | None
    signed_total: RubleAmount | None


@dataclass(frozen=True, slots=True)
class PerformanceAttributionResult:
    """One exact PERF04A aggregate result for one scope and interval."""

    scope: PerformanceScope
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    availability: PerformanceAvailabilityStatus
    quality: PerformanceAttributionQuality
    opening_value: RubleAmount | None
    closing_value: RubleAmount | None
    value: RubleAmount | None
    external_flow_summary: ExternalFlowSummary
    evidence: Perf04aEvidence
    reason_codes: tuple[str, ...] = ()
    bridge_prerequisites: Perf04aBridgePrerequisites | None = None

    @property
    def is_available(self) -> bool:
        return self.availability is PerformanceAvailabilityStatus.AVAILABLE


__all__ = [
    "ExternalFlowSummary",
    "Perf04aBridgePrerequisites",
    "Perf04aCoverageEvidence",
    "Perf04aEvidence",
    "Perf04aValuationEvidence",
    "PerformanceAttributionQuality",
    "PerformanceAttributionResult",
]
