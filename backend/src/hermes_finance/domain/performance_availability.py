"""Deterministic performance-availability contract.

The contract stops at data availability.  It deliberately contains no XIRR or
TWRR calculation and no inferred valuation.  Persisted money stays in integer
minor units; API adapters are responsible for rendering exact decimal strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from hermes_finance.domain.external_flows import (
    ExternalFlowClassification,
    ExternalFlowScopeMembership,
    ExternalTransferStatus,
)
from hermes_finance.domain.valuation_points import (
    PerformanceScope,
    ValuationPoint,
    ValuationPointStatus,
)


class PerformanceAvailabilityStatus(StrEnum):
    """Whether a downstream exact performance metric may consume the evidence."""

    AVAILABLE = "available"
    NOT_COMPUTABLE = "not_computable"


class PerformanceAvailabilityReasonCode(StrEnum):
    """Stable fail-closed reasons exposed by R08-01C."""

    OPENING_VALUATION_MISSING = "not_computable_opening_valuation_missing"
    CLOSING_VALUATION_MISSING = "not_computable_closing_valuation_missing"
    EXTERNAL_FLOWS_INCOMPLETE = "not_computable_external_flows_incomplete"
    SCOPE_COVERAGE_INCOMPLETE = "not_computable_scope_coverage_incomplete"
    SCOPE_CASH_UNCLASSIFIED = "not_computable_scope_cash_unclassified"
    SCOPE_MEMBERSHIP_HISTORY_MISSING = "not_computable_scope_membership_history_missing"
    CURRENCY_CONVERSION_INCOMPLETE = "not_computable_currency_conversion_incomplete"
    TRANSFER_IDENTITY_UNRESOLVED = "not_computable_transfer_identity_unresolved"
    VALUATION_BOUNDARY_MISSING = "not_computable_valuation_boundary_missing"
    VALUATION_BOUNDARY_ORDER_UNKNOWN = "not_computable_valuation_boundary_order_unknown"

    # Existing R08-01B point-level reasons remain part of the read contract.
    SNAPSHOT_DATE_MISSING = "not_computable_snapshot_date_missing"
    REPORTING_MONTH_NOT_CLOSED = "not_computable_reporting_month_not_closed"
    UNSUPPORTED_POSITION_VALUATION = "not_computable_unsupported_position_valuation"


# Short vocabulary alias for callers that use the generic availability name.
AvailabilityReasonCode = PerformanceAvailabilityReasonCode


@dataclass(frozen=True, slots=True)
class PerformanceMetricPrerequisites:
    """Availability of one downstream metric, without a metric value."""

    metric: str
    availability: PerformanceAvailabilityStatus
    reason_codes: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.availability is PerformanceAvailabilityStatus.AVAILABLE


@dataclass(frozen=True, slots=True)
class ValuationBoundaryEvidence:
    """A requested boundary and its exact persisted valuation evidence."""

    role: str
    requested_date: date
    reporting_month_id: int | None
    point: ValuationPoint | None
    reason_codes: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.point is not None and self.point.status is ValuationPointStatus.AVAILABLE


@dataclass(frozen=True, slots=True)
class ExternalFlowEvidence:
    """Sanitized, exact metadata for one flow considered at the selected scope."""

    id: int
    reporting_month_id: int
    account_id: int
    event_date: date
    boundary_amount_kopecks: int
    direction: str
    kind: str
    currency: str
    scope_membership: ExternalFlowScopeMembership
    classification: ExternalFlowClassification
    transfer_link_id: int | None
    transfer_status: ExternalTransferStatus | None
    source: str


@dataclass(frozen=True, slots=True)
class ExternalFlowCoverage:
    """Exact flow evidence and any reason why it cannot be consumed."""

    status: str
    flows: tuple[ExternalFlowEvidence, ...]
    legacy_unclassified_flow_ids: tuple[int, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.reason_codes


@dataclass(frozen=True, slots=True)
class ScopeMembershipCoverage:
    """Effective-dated membership evidence for the requested interval."""

    status: str
    account_ids: tuple[int, ...]
    missing_or_ambiguous_account_ids: tuple[int, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PerformanceAvailability:
    """Complete R08-01C result for one scope and date interval."""

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
    external_flows: ExternalFlowCoverage
    xirr: PerformanceMetricPrerequisites
    twrr: PerformanceMetricPrerequisites

    @property
    def is_available(self) -> bool:
        return self.availability is PerformanceAvailabilityStatus.AVAILABLE
