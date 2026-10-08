"""Read-only presentation of canonical Performance evidence and final results."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.performance_availability import (
    AvailabilityReasonCode as R,
)
from hermes_finance.domain.performance_availability import (
    PerformanceAvailability,
)
from hermes_finance.domain.valuation_points import PerformanceScope
from hermes_finance.persistence import Account
from hermes_finance.services.cash_boundary_coverage import closed_month_for_cash_boundary_interval
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.portfolio_twrr import PortfolioTwrrResult, twrr_for_interval
from hermes_finance.services.portfolio_xirr import PortfolioXirrResult, xirr_for_interval
from hermes_finance.services.valuation_capture import capture_capability_for_evidence

Capability = Literal[
    "available", "requires_reopen", "not_implemented", "source_required", "unsupported"
]
ActionKind = Literal[
    "select_interval",
    "review_month",
    "review_scope",
    "review_cash_binding",
    "review_cash_history",
    "review_legacy_flows",
    "review_external_flows",
    "review_transfer",
    "review_in_kind_history",
    "review_in_kind_movement",
    "review_observations",
    "review_fx",
    "inspect_result",
]


@dataclass(frozen=True)
class DiagnosticRefs:
    account_ids: tuple[int, ...] = ()
    reporting_month_ids: tuple[int, ...] = ()
    external_flow_ids: tuple[int, ...] = ()
    legacy_flow_ids: tuple[int, ...] = ()
    movement_ids: tuple[int, ...] = ()
    boundary_group_ids: tuple[int, ...] = ()
    dates: tuple[date, ...] = ()


@dataclass(frozen=True)
class ReadinessAction:
    kind: ActionKind
    capability: Capability
    params: DiagnosticRefs
    verify: Literal["reread_readiness"] = "reread_readiness"


@dataclass(frozen=True)
class ReadinessDiagnostic:
    key: str
    reason_codes: tuple[str, ...]
    affected_metrics: tuple[Literal["xirr", "twrr"], ...]
    category: Literal["actionable", "limitation"]
    refs: DiagnosticRefs
    action: ReadinessAction


@dataclass(frozen=True)
class PerformanceReadiness:
    evidence: PerformanceAvailability
    xirr: PortfolioXirrResult
    twrr: PortfolioTwrrResult
    diagnostics: tuple[ReadinessDiagnostic, ...]


class ReadinessConsistencyError(RuntimeError):
    """A composite result cannot safely be presented as one financial answer."""


class ReadinessRequestError(ValueError):
    """The requested account is unavailable in the pinned snapshot."""


# Exact canonical codes only. These keys classify presentation, never availability.
_RULES: dict[str, tuple[str, ActionKind, Capability]] = {
    "mybroker_excluded_source_impact": ("excluded_source", "inspect_result", "source_required"),
    R.OPENING_VALUATION_MISSING: ("opening_valuation", "select_interval", "available"),
    R.CLOSING_VALUATION_MISSING: ("closing_valuation", "select_interval", "available"),
    R.REPORTING_MONTH_NOT_CLOSED: ("reporting_month", "review_month", "available"),
    R.SNAPSHOT_DATE_MISSING: ("snapshot_date", "review_month", "source_required"),
    R.UNSUPPORTED_POSITION_VALUATION: ("position_valuation", "review_month", "source_required"),
    R.SCOPE_MEMBERSHIP_HISTORY_MISSING: ("membership_history", "review_scope", "available"),
    R.SCOPE_MEMBERSHIP_CHANGED: ("membership_changed", "select_interval", "available"),
    R.SCOPE_CASH_UNCLASSIFIED: ("cash_binding", "review_cash_binding", "available"),
    R.SCOPE_COVERAGE_INCOMPLETE: ("scope_coverage", "review_scope", "available"),
    R.EXTERNAL_FLOWS_INCOMPLETE: ("external_flows", "review_external_flows", "available"),
    R.TRANSFER_IDENTITY_UNRESOLVED: ("transfer_identity", "review_transfer", "not_implemented"),
    R.TRANSFER_RECONCILIATION_INCOMPLETE: (
        "transfer_reconciliation",
        "review_transfer",
        "not_implemented",
    ),
    R.TRANSFER_IN_TRANSIT_UNVALUED: ("transfer_in_transit", "inspect_result", "unsupported"),
    R.IN_KIND_BOUNDARY_COVERAGE_UNKNOWN: ("in_kind_history", "review_in_kind_history", "available"),
    R.IN_KIND_MOVEMENT_UNVALUED: ("in_kind_valuation", "review_in_kind_movement", "unsupported"),
    R.VALUATION_BOUNDARY_MISSING: ("valuation_boundary", "review_observations", "not_implemented"),
    R.VALUATION_BOUNDARY_ORDER_UNKNOWN: (
        "valuation_order",
        "review_observations",
        "not_implemented",
    ),
    R.CURRENCY_CONVERSION_INCOMPLETE: ("historical_fx", "review_fx", "unsupported"),
    "not_computable_historical_endpoint_ineffective": (
        "historical_endpoint",
        "inspect_result",
        "source_required",
    ),
    "not_computable_historical_owner_flow_ineffective": (
        "historical_account_flow",
        "inspect_result",
        "source_required",
    ),
    "not_computable_historical_portfolio_flow_unknown": (
        "historical_portfolio_flow",
        "inspect_result",
        "source_required",
    ),
    "not_computable_xirr_no_valid_root": ("xirr_no_root", "inspect_result", "unsupported"),
    "not_computable_xirr_root_ambiguity": ("xirr_ambiguous", "inspect_result", "unsupported"),
    "not_computable_xirr_convergence_failed": ("xirr_convergence", "inspect_result", "unsupported"),
}


def _refs(evidence: PerformanceAvailability, code: str) -> DiagnosticRefs:
    """Only localize where the evidence explicitly associates a code with a target."""
    if code == R.SCOPE_MEMBERSHIP_HISTORY_MISSING:
        return DiagnosticRefs(
            account_ids=evidence.scope_membership.missing_or_ambiguous_account_ids
        )
    if code == R.IN_KIND_BOUNDARY_COVERAGE_UNKNOWN:
        return DiagnosticRefs(
            account_ids=evidence.in_kind_boundary_coverage.missing_or_incomplete_account_ids
        )
    if code == R.IN_KIND_MOVEMENT_UNVALUED:
        movements = evidence.in_kind_boundary_coverage.known_movements
        return DiagnosticRefs(
            movement_ids=tuple(item.id for item in movements),
            reporting_month_ids=tuple(sorted({item.reporting_month_id for item in movements})),
            dates=tuple(sorted({item.event_date for item in movements})),
        )
    boundaries = [
        b
        for b in (evidence.opening_valuation, evidence.closing_valuation)
        if code in b.reason_codes
    ]
    flow_boundaries = [b for b in evidence.external_flow_boundaries if code in b.reason_codes]
    return DiagnosticRefs(
        reporting_month_ids=tuple(
            sorted({b.reporting_month_id for b in boundaries if b.reporting_month_id is not None})
        ),
        dates=tuple(
            sorted({b.requested_date for b in boundaries} | {b.event_date for b in flow_boundaries})
        ),
        external_flow_ids=tuple(sorted({i for b in flow_boundaries for i in b.flow_ids})),
        boundary_group_ids=tuple(
            sorted(
                {b.boundary_group_id for b in flow_boundaries if b.boundary_group_id is not None}
            )
        ),
    )


def _diagnostics(
    session: Session,
    evidence: PerformanceAvailability,
    xirr: PortfolioXirrResult,
    twrr: PortfolioTwrrResult,
) -> tuple[ReadinessDiagnostic, ...]:
    diagnostics = []
    # Reuse the mutation guard's exact CLOSED predicate, within this read snapshot.
    # The guard itself reserves a writer and rolls back on CLOSED; neither action
    # belongs in a coherent read-only capability projection.
    coverage_capability: Capability = "available"
    if (
        closed_month_for_cash_boundary_interval(
            session, covered_from=evidence.start_date, covered_to=evidence.end_date
        )
        is not None
    ):
        coverage_capability = "requires_reopen"
    # The observation adapter is supported only where a concrete target needs
    # fresh evidence in an editable month with a current material identity.
    capture_capability: Capability | None = None
    capture_capability_computed = False

    for code in sorted(set(xirr.reason_codes) | set(twrr.reason_codes)):
        metrics = tuple(
            name for name, result in (("xirr", xirr), ("twrr", twrr)) if code in result.reason_codes
        )
        key, kind, capability = _RULES.get(
            code, ("unknown_reason", "inspect_result", "unsupported")
        )
        refs = _refs(evidence, code)
        variants = [(key, kind, capability, refs)]
        if code == R.EXTERNAL_FLOWS_INCOMPLETE:
            # A single financial code may carry several independent proven causes.
            missing = evidence.cash_boundary_coverage.missing_or_incomplete_account_ids
            legacy = evidence.external_flows.legacy_unclassified_flow_ids
            if not evidence.external_flows.flows and not legacy:
                # This says only that the considered ledger has no recorded flows;
                # completeness still comes exclusively from canonical coverage.
                variants[0] = (
                    "no_recorded_external_flows",
                    kind,
                    capability,
                    refs,
                )
            if missing:
                variants.append(
                    (
                        "cash_history",
                        "review_cash_history",
                        coverage_capability,
                        DiagnosticRefs(account_ids=missing),
                    )
                )
            if legacy:
                variants.append(
                    (
                        "legacy_flows",
                        "review_legacy_flows",
                        "not_implemented",
                        DiagnosticRefs(legacy_flow_ids=legacy),
                    )
                )
        if code == R.IN_KIND_BOUNDARY_COVERAGE_UNKNOWN:
            variants = [(key, kind, coverage_capability, refs)]
        if code == R.VALUATION_BOUNDARY_MISSING:
            if not capture_capability_computed:
                capture_capability = capture_capability_for_evidence(session, evidence=evidence)
                capture_capability_computed = True
            if capture_capability is not None:
                variants = [(key, kind, capture_capability, refs)]
        # No month ID means a section-level review, never an invented destination.
        for key, kind, capability, refs in variants:
            diagnostics.append(
                ReadinessDiagnostic(
                    key=key,
                    reason_codes=(code,),
                    affected_metrics=metrics,
                    category="actionable"
                    if capability in ("available", "requires_reopen")
                    else "limitation",
                    refs=refs,
                    action=ReadinessAction(kind, capability, refs),
                )
            )
    return tuple(diagnostics)


def _validate_result(
    evidence: PerformanceAvailability,
    result: PortfolioXirrResult | PortfolioTwrrResult,
) -> None:
    identity = ("scope", "account_id", "start_date", "end_date", "performance_currency")
    if any(getattr(evidence, field) != getattr(result, field) for field in identity):
        raise ReadinessConsistencyError("Performance result identity mismatch")
    if result.is_available:
        if (
            result.quality != "exact"
            or result.value is None
            or not result.value.is_finite()
            or result.reason_codes
        ):
            raise ReadinessConsistencyError("Inconsistent available Performance result")
    elif result.quality != "unavailable" or result.value is not None or not result.reason_codes:
        raise ReadinessConsistencyError("Inconsistent unavailable Performance result")


@coherent_read_operation
def readiness_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> PerformanceReadiness:
    if scope == PerformanceScope.ACCOUNT and session.get(Account, account_id) is None:
        raise ReadinessRequestError("Performance account was not found")
    kwargs = dict(start_date=start_date, end_date=end_date, scope=scope, account_id=account_id)
    evidence = performance_availability_for_interval(session, **kwargs)
    expected = (scope, account_id, start_date, end_date)
    if (evidence.scope, evidence.account_id, evidence.start_date, evidence.end_date) != expected:
        raise ReadinessConsistencyError("Performance evidence identity mismatch")
    xirr = xirr_for_interval(session, **kwargs)
    twrr = twrr_for_interval(session, **kwargs)
    _validate_result(evidence, xirr)
    _validate_result(evidence, twrr)
    return PerformanceReadiness(evidence, xirr, twrr, _diagnostics(session, evidence, xirr, twrr))
