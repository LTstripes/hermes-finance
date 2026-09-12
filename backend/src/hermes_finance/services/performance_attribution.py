"""Read-only PERF04A aggregate value bridge (issue #354)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy.orm import Session

from hermes_finance.domain import (
    AvailabilityReasonCode,
    ExternalFlowClassification,
    ExternalFlowSummary,
    Perf04aBridgePrerequisites,
    Perf04aCoverageEvidence,
    Perf04aEvidence,
    Perf04aValuationEvidence,
    PerformanceAttributionQuality,
    PerformanceAttributionResult,
    PerformanceAvailability,
    PerformanceAvailabilityStatus,
    PerformanceScope,
    RubleAmount,
)
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)

PERF04A_CONTRACT = "PERF04A"
PERF04A_CONTRACT_VERSION = 1
PERF04A_METRIC = "value_change_after_external_flows"

_TWRR_ONLY_REASONS = frozenset(
    {
        AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value,
        AvailabilityReasonCode.VALUATION_BOUNDARY_ORDER_UNKNOWN.value,
    }
)
_SELECTED_EXTERNAL_FLOW_CLASSIFICATIONS = frozenset(
    {
        ExternalFlowClassification.EXTERNAL_CONTRIBUTION,
        ExternalFlowClassification.EXTERNAL_WITHDRAWAL,
    }
)


def _without_twrr_only_reasons(reasons: Iterable[str]) -> set[str]:
    return set(reasons) - _TWRR_ONLY_REASONS


def _has_endpoint_external_flow(availability: PerformanceAvailability) -> bool:
    """Return whether a selected external flow is consumed at an endpoint.

    R08's order-unknown reason is TWRR-only for strictly interior flows.  The
    accepted PERF04A contract makes it bridge-blocking for a canonical
    selected external flow on either consumed endpoint because the current
    persistence does not bind an observed flow relation to the monthly V0/V1
    valuation.
    """

    endpoint_dates = {availability.start_date, availability.end_date}
    return any(
        flow.classification in _SELECTED_EXTERNAL_FLOW_CLASSIFICATIONS
        and flow.event_date in endpoint_dates
        for flow in availability.external_flows.flows
    )


def _has_portfolio_endpoint_transfer_order_unknown(
    availability: PerformanceAvailability,
) -> bool:
    """Reuse R08 transfer-safety order evidence for consumed portfolio endpoints.

    ``performance_availability_for_interval`` adds this reason to the XIRR
    prerequisite only when a linked internal portfolio transfer has same-day
    legs at one of the consumed endpoint dates.  Intermediate TWRR-only
    same-day gaps are reported only by TWRR and therefore must not reach this
    bridge gate.
    """

    return (
        availability.scope is PerformanceScope.PORTFOLIO
        and AvailabilityReasonCode.VALUATION_BOUNDARY_ORDER_UNKNOWN.value
        in availability.xirr.reason_codes
    )


def _valuation_evidence(
    availability: PerformanceAvailability,
    *,
    role: str,
) -> Perf04aValuationEvidence:
    boundary = (
        availability.opening_valuation if role == "opening" else availability.closing_valuation
    )
    return Perf04aValuationEvidence(
        availability=(
            PerformanceAvailabilityStatus.AVAILABLE
            if boundary.is_available
            else PerformanceAvailabilityStatus.NOT_COMPUTABLE
        ),
        # Evidence retains TWRR-only reasons even though the dedicated bridge
        # gate below deliberately excludes them.
        reason_codes=tuple(boundary.reason_codes),
    )


def _coverage_evidence(status: str, reason_codes: Iterable[str]) -> Perf04aCoverageEvidence:
    return Perf04aCoverageEvidence(
        status=status,
        reason_codes=tuple(sorted(set(reason_codes))),
    )


def _evidence_projection(availability: PerformanceAvailability) -> Perf04aEvidence:
    return Perf04aEvidence(
        opening_valuation=_valuation_evidence(availability, role="opening"),
        closing_valuation=_valuation_evidence(availability, role="closing"),
        scope_membership=_coverage_evidence(
            availability.scope_membership.status,
            availability.scope_membership.reason_codes,
        ),
        cash_boundary_coverage=_coverage_evidence(
            availability.cash_boundary_coverage.status,
            availability.cash_boundary_coverage.reason_codes,
        ),
        in_kind_boundary_coverage=_coverage_evidence(
            availability.in_kind_boundary_coverage.status,
            availability.in_kind_boundary_coverage.reason_codes,
        ),
        external_flows=_coverage_evidence(
            availability.external_flows.status,
            availability.external_flows.reason_codes,
        ),
    )


def _bridge_reason_codes(availability: PerformanceAvailability) -> tuple[str, ...]:
    """Build the dedicated bridge gate from evidence, not a return result.

    R08's XIRR prerequisite is an evidence-only projection: it carries the
    shared valuation/scope/cash/in-kind/flow reasons and the endpoint-only
    transfer safety reasons, but no solver outcome.  Only its reason codes are
    reused here; neither the top-level availability nor ``xirr.availability``
    is consumed as the PERF04A gate. TWRR-only boundary reasons are removed
    for interior flows; endpoint-flow order is reintroduced as the dedicated
    bridge gate below.
    """

    reasons = _without_twrr_only_reasons(availability.xirr.reason_codes)
    for extra_reasons in (
        availability.opening_valuation.reason_codes,
        availability.closing_valuation.reason_codes,
        availability.scope_membership.reason_codes,
        availability.cash_boundary_coverage.reason_codes,
        availability.in_kind_boundary_coverage.reason_codes,
        availability.external_flows.reason_codes,
    ):
        reasons.update(_without_twrr_only_reasons(extra_reasons))
    if _has_endpoint_external_flow(availability) or _has_portfolio_endpoint_transfer_order_unknown(
        availability
    ):
        reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_ORDER_UNKNOWN.value)
    return tuple(sorted(reasons))


def perf04a_bridge_prerequisites(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> Perf04aBridgePrerequisites:
    """Return the dedicated PERF04A prerequisite projection.

    The shared R08 service assembles the persisted evidence.  This function
    owns the separate bridge reason set and intentionally ignores TWRR
    observed-boundary evidence and any calculated return availability.
    """

    r08 = performance_availability_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        account_id=account_id,
    )
    reason_codes = _bridge_reason_codes(r08)
    return Perf04aBridgePrerequisites(
        scope=r08.scope,
        account_id=r08.account_id,
        start_date=r08.start_date,
        end_date=r08.end_date,
        performance_currency=r08.performance_currency,
        availability=(
            PerformanceAvailabilityStatus.AVAILABLE
            if not reason_codes
            else PerformanceAvailabilityStatus.NOT_COMPUTABLE
        ),
        reason_codes=reason_codes,
        opening_valuation=r08.opening_valuation,
        closing_valuation=r08.closing_valuation,
        scope_membership=r08.scope_membership,
        cash_boundary_coverage=r08.cash_boundary_coverage,
        in_kind_boundary_coverage=r08.in_kind_boundary_coverage,
        external_flows=r08.external_flows,
        evidence=_evidence_projection(r08),
    )


def _empty_flow_summary() -> ExternalFlowSummary:
    return ExternalFlowSummary(contributions=None, withdrawals=None, signed_total=None)


def _external_flow_summary(
    availability: Perf04aBridgePrerequisites,
) -> tuple[ExternalFlowSummary, set[str]]:
    """Aggregate only complete, canonical selected-scope flow evidence."""

    if not availability.external_flows.is_complete:
        return _empty_flow_summary(), set()

    contributions = 0
    withdrawals = 0
    reasons: set[str] = set()
    for flow in availability.external_flows.flows:
        amount = flow.boundary_amount_kopecks
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
            continue
        if flow.classification is ExternalFlowClassification.EXTERNAL_CONTRIBUTION:
            contributions += amount
        elif flow.classification is ExternalFlowClassification.EXTERNAL_WITHDRAWAL:
            withdrawals += amount
        elif flow.classification is ExternalFlowClassification.INTERNAL_TRANSFER:
            # A linked in-scope portfolio transfer has C=0.  Its evidence is
            # still retained by the shared R08 coverage projection.
            continue
        else:
            reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)

    if reasons:
        return _empty_flow_summary(), reasons
    return (
        ExternalFlowSummary(
            contributions=RubleAmount(contributions),
            withdrawals=RubleAmount(withdrawals),
            signed_total=RubleAmount(contributions - withdrawals),
        ),
        reasons,
    )


def _boundary_value(
    boundary: object,
    *,
    performance_currency: str,
) -> RubleAmount | None:
    point = getattr(boundary, "point", None)
    if (
        point is None
        or not getattr(boundary, "is_available", False)
        or point.total_value is None
        or point.performance_currency != performance_currency
    ):
        return None
    return point.total_value


def performance_attribution_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> PerformanceAttributionResult:
    """Calculate the exact PERF04A value bridge for one selected scope."""

    prerequisites = perf04a_bridge_prerequisites(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        account_id=account_id,
    )
    flow_summary, summary_reasons = _external_flow_summary(prerequisites)
    reason_codes = set(prerequisites.reason_codes)
    reason_codes.update(summary_reasons)

    opening_value = _boundary_value(
        prerequisites.opening_valuation,
        performance_currency=prerequisites.performance_currency,
    )
    closing_value = _boundary_value(
        prerequisites.closing_valuation,
        performance_currency=prerequisites.performance_currency,
    )
    value: RubleAmount | None = None
    if (
        not reason_codes
        and opening_value is not None
        and closing_value is not None
        and flow_summary.signed_total is not None
    ):
        bridge_kopecks = (
            closing_value.kopecks - opening_value.kopecks - flow_summary.signed_total.kopecks
        )
        # Keep this identity explicit even though all operands are integer
        # minor units and the expression is algebraically exact.
        if (
            opening_value.kopecks + flow_summary.signed_total.kopecks + bridge_kopecks
            == closing_value.kopecks
        ):
            value = RubleAmount(bridge_kopecks)
        else:  # pragma: no cover - defensive guard against future arithmetic changes
            reason_codes.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    availability = (
        PerformanceAvailabilityStatus.AVAILABLE
        if value is not None and not reason_codes
        else PerformanceAvailabilityStatus.NOT_COMPUTABLE
    )
    return PerformanceAttributionResult(
        scope=prerequisites.scope,
        account_id=prerequisites.account_id,
        start_date=prerequisites.start_date,
        end_date=prerequisites.end_date,
        performance_currency=prerequisites.performance_currency,
        availability=availability,
        quality=(
            PerformanceAttributionQuality.EXACT
            if availability is PerformanceAvailabilityStatus.AVAILABLE
            else PerformanceAttributionQuality.UNAVAILABLE
        ),
        opening_value=opening_value,
        closing_value=closing_value,
        value=value,
        external_flow_summary=flow_summary,
        evidence=prerequisites.evidence,
        reason_codes=tuple(sorted(reason_codes)),
        bridge_prerequisites=prerequisites,
    )


# Discoverable aliases for downstream API and test callers.
get_performance_attribution = performance_attribution_for_interval
build_performance_attribution = performance_attribution_for_interval
attribution_for_interval = performance_attribution_for_interval
perf04a_bridge_prerequisites_for_interval = perf04a_bridge_prerequisites
get_perf04a_bridge_prerequisites = perf04a_bridge_prerequisites


__all__ = [
    "PERF04A_CONTRACT",
    "PERF04A_CONTRACT_VERSION",
    "PERF04A_METRIC",
    "attribution_for_interval",
    "build_performance_attribution",
    "get_perf04a_bridge_prerequisites",
    "get_performance_attribution",
    "perf04a_bridge_prerequisites",
    "perf04a_bridge_prerequisites_for_interval",
    "performance_attribution_for_interval",
]
