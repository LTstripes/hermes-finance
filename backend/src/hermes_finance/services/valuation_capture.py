"""Supported read/capture adapter for observed PRE/POST valuation boundaries.

Issue #533 exposes the accepted ``valuation_boundaries`` persistence service as
a narrow capture contract.  It discovers explicit targets from the canonical
availability read, reports the exact missing or stale side with its observed
provenance/coverage, and publishes one actually observed value bound to the
capture-start material signature.  It never derives a value from a flow, a
month snapshot, an interpolation, or an implicit group.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import (
    AvailabilityReasonCode,
    CoverageStatus,
    PerformanceAvailability,
    PerformanceScope,
    RubleAmount,
    ValuationBoundaryRelation,
    ValuationQuality,
)
from hermes_finance.persistence import (
    Account,
    ExternalFlow,
    ExternalFlowBoundaryGroup,
    ObservedValuationPoint,
    ReportingMonth,
)
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.performance_availability import (
    _performance_currency,
    performance_availability_for_interval,
)
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError
from hermes_finance.services.valuation_boundaries import (
    boundary_group_flows,
    stage_create_observed_valuation_point,
    validate_external_flow_boundary_group_members,
)
from hermes_finance.services.valuation_material_signature import material_signature_for_boundary

CaptureCapability = Literal["available", "requires_reopen", "not_implemented", "unsupported"]
CaptureSideState = Literal["captured", "missing", "stale", "ambiguous"]
CaptureBlockedReason = Literal[
    "target_missing",
    "target_identity_unavailable",
    "group_membership_changed",
    "ambiguous_sides",
]

_RELATIONS = (
    ValuationBoundaryRelation.PRE_EXTERNAL_FLOW,
    ValuationBoundaryRelation.POST_EXTERNAL_FLOW,
)


@dataclass(frozen=True, slots=True)
class CaptureSide:
    """One persisted observation side for a capture target."""

    id: int
    relation: ValuationBoundaryRelation
    observed_date: date
    total_value: RubleAmount
    performance_currency: str
    coverage: CoverageStatus
    quality: ValuationQuality
    provenance_kind: str
    provenance_reference: str | None
    material_signature: str | None
    bound: bool


@dataclass(frozen=True, slots=True)
class CaptureTarget:
    """One explicit flow/group target and its observable capture state."""

    boundary_group_id: int | None
    flow_ids: tuple[int, ...]
    event_date: date
    reporting_month_id: int | None
    reporting_month_status: str | None
    scope: PerformanceScope
    account_id: int | None
    performance_currency: str
    material_signature: str | None
    pre_sides: tuple[CaptureSide, ...]
    post_sides: tuple[CaptureSide, ...]
    pre_state: CaptureSideState
    post_state: CaptureSideState
    reason_codes: tuple[str, ...]
    capture_capability: CaptureCapability | None
    blocked_reason: CaptureBlockedReason | None

    @property
    def needs_capture(self) -> tuple[ValuationBoundaryRelation, ...]:
        return tuple(
            relation
            for relation, state in (
                (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, self.pre_state),
                (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, self.post_state),
            )
            if state in {"missing", "stale"}
        )


@dataclass(frozen=True, slots=True)
class ValuationCaptureProjection:
    """One committed capture-target snapshot for the selected context."""

    scope: PerformanceScope
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    targets: tuple[CaptureTarget, ...]


@dataclass(frozen=True, slots=True)
class ResolvedCaptureTarget:
    """Server-resolved canonical identity for one capture submission."""

    scope: PerformanceScope
    account_id: int | None
    reporting_month_id: int
    reporting_month_status: str
    boundary_date: date
    external_flow_id: int | None
    boundary_group_id: int | None


def _coerce_scope(scope: PerformanceScope | str) -> PerformanceScope:
    try:
        return PerformanceScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported performance scope: {scope!r}") from error


def _coerce_relation(
    relation: ValuationBoundaryRelation | str,
) -> ValuationBoundaryRelation:
    try:
        return ValuationBoundaryRelation(relation)
    except ValueError as error:
        raise ValueError(f"unsupported valuation boundary relation: {relation!r}") from error


def _target_rows(
    session: Session,
    *,
    target: CaptureTarget,
    scope: PerformanceScope,
    account_id: int | None,
) -> list[ObservedValuationPoint]:
    """Read the persisted sides for one target at the selected scope.

    This mirrors the availability read's target selection but keeps the write
    form's per-side state (captured/stale/missing/ambiguous) explicit.
    """

    statement = select(ObservedValuationPoint).where(ObservedValuationPoint.scope == scope.value)
    if scope is PerformanceScope.ACCOUNT:
        statement = statement.where(ObservedValuationPoint.account_id == account_id)
    else:
        statement = statement.where(ObservedValuationPoint.account_id.is_(None))
    if target.boundary_group_id is None:
        statement = statement.where(
            ObservedValuationPoint.external_flow_id == target.flow_ids[0],
            ObservedValuationPoint.boundary_group_id.is_(None),
        )
    else:
        statement = statement.where(
            ObservedValuationPoint.boundary_group_id == target.boundary_group_id,
            ObservedValuationPoint.external_flow_id.is_(None),
        )
    return list(session.scalars(statement.order_by(ObservedValuationPoint.id)))


def _capture_side(
    point: ObservedValuationPoint,
    *,
    current_signature: str | None,
) -> CaptureSide:
    return CaptureSide(
        id=point.id,
        relation=ValuationBoundaryRelation(point.relation),
        observed_date=point.observed_date,
        total_value=RubleAmount(point.total_value_kopecks),
        performance_currency=point.performance_currency,
        coverage=CoverageStatus(point.coverage_status),
        quality=ValuationQuality(point.quality),
        provenance_kind=point.provenance_kind,
        provenance_reference=point.provenance_reference,
        material_signature=point.material_signature,
        bound=current_signature is not None and point.material_signature == current_signature,
    )


def _side_state(sides: tuple[CaptureSide, ...]) -> CaptureSideState:
    if not sides:
        return "missing"
    if len(sides) > 1:
        return "ambiguous"
    return "captured" if sides[0].bound else "stale"


def _capture_target(
    session: Session,
    *,
    boundary_group_id: int | None,
    flow_ids: tuple[int, ...],
    event_date: date,
    reason_codes: tuple[str, ...],
    scope: PerformanceScope,
    account_id: int | None,
    performance_currency: str,
) -> CaptureTarget:
    """Enrich one canonical boundary target with capture-side state."""

    reporting_month_id: int | None = None
    reporting_month_status: str | None = None
    blocked_reason: CaptureBlockedReason | None = None

    if boundary_group_id is None:
        flow = session.get(ExternalFlow, flow_ids[0], populate_existing=True)
        if flow is None:
            blocked_reason = "target_missing"
        else:
            reporting_month_id = flow.reporting_month_id
            event_date = flow.event_date
    else:
        group = session.get(ExternalFlowBoundaryGroup, boundary_group_id, populate_existing=True)
        if group is None:
            blocked_reason = "target_missing"
        else:
            reporting_month_id = group.reporting_month_id
            event_date = group.boundary_date
            try:
                validate_external_flow_boundary_group_members(
                    group, boundary_group_flows(session, group.id)
                )
            except ValueError:
                blocked_reason = "group_membership_changed"

    if reporting_month_id is not None:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            blocked_reason = blocked_reason or "target_missing"
            reporting_month_id = None
        else:
            reporting_month_status = month.status

    current_signature = material_signature_for_boundary(
        session,
        scope=scope.value,
        account_id=account_id,
        external_flow_id=flow_ids[0] if boundary_group_id is None else None,
        boundary_group_id=boundary_group_id,
    )
    if current_signature is None and blocked_reason is None:
        blocked_reason = "target_identity_unavailable"

    provisional = CaptureTarget(
        boundary_group_id=boundary_group_id,
        flow_ids=flow_ids,
        event_date=event_date,
        reporting_month_id=reporting_month_id,
        reporting_month_status=reporting_month_status,
        scope=scope,
        account_id=account_id,
        performance_currency=performance_currency,
        material_signature=current_signature,
        pre_sides=(),
        post_sides=(),
        pre_state="missing",
        post_state="missing",
        reason_codes=reason_codes,
        capture_capability=None,
        blocked_reason=blocked_reason,
    )
    rows = _target_rows(session, target=provisional, scope=scope, account_id=account_id)
    pre_sides = tuple(
        _capture_side(row, current_signature=current_signature)
        for row in rows
        if row.relation == ValuationBoundaryRelation.PRE_EXTERNAL_FLOW.value
    )
    post_sides = tuple(
        _capture_side(row, current_signature=current_signature)
        for row in rows
        if row.relation == ValuationBoundaryRelation.POST_EXTERNAL_FLOW.value
    )
    pre_state = _side_state(pre_sides)
    post_state = _side_state(post_sides)
    if blocked_reason is None and (pre_state == "ambiguous" or post_state == "ambiguous"):
        blocked_reason = "ambiguous_sides"

    needs_capture = pre_state in {"missing", "stale"} or post_state in {"missing", "stale"}
    capability: CaptureCapability | None
    if blocked_reason is not None:
        capability = "unsupported" if blocked_reason == "ambiguous_sides" else "not_implemented"
    elif not needs_capture:
        capability = None
    elif reporting_month_status == "draft":
        capability = "available"
    else:
        capability = "requires_reopen"

    return CaptureTarget(
        boundary_group_id=boundary_group_id,
        flow_ids=flow_ids,
        event_date=event_date,
        reporting_month_id=reporting_month_id,
        reporting_month_status=reporting_month_status,
        scope=scope,
        account_id=account_id,
        performance_currency=performance_currency,
        material_signature=current_signature,
        pre_sides=pre_sides,
        post_sides=post_sides,
        pre_state=pre_state,
        post_state=post_state,
        reason_codes=reason_codes,
        capture_capability=capability,
        blocked_reason=blocked_reason,
    )


def _capture_targets_for_evidence(
    session: Session,
    *,
    evidence: PerformanceAvailability,
) -> tuple[CaptureTarget, ...]:
    return tuple(
        _capture_target(
            session,
            boundary_group_id=boundary.boundary_group_id,
            flow_ids=boundary.flow_ids,
            event_date=boundary.event_date,
            reason_codes=boundary.reason_codes,
            scope=evidence.scope,
            account_id=evidence.account_id,
            performance_currency=evidence.performance_currency,
        )
        for boundary in evidence.external_flow_boundaries
    )


@coherent_read_operation
def valuation_capture_projection_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> ValuationCaptureProjection:
    """Read capture targets in one coherent snapshot; never write or infer."""

    normalized_scope = _coerce_scope(scope)
    evidence = performance_availability_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=normalized_scope,
        account_id=account_id,
    )
    return ValuationCaptureProjection(
        scope=evidence.scope,
        account_id=evidence.account_id,
        start_date=evidence.start_date,
        end_date=evidence.end_date,
        performance_currency=evidence.performance_currency,
        targets=_capture_targets_for_evidence(session, evidence=evidence),
    )


def capture_capability_for_evidence(
    session: Session,
    *,
    evidence: PerformanceAvailability,
) -> CaptureCapability | None:
    """Fold target capabilities for the readiness diagnostic, without guessing.

    ``None`` means no boundary target with the valuation-missing code needs a
    supported capture action; callers keep their existing limitation state.
    """

    missing_code = AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value
    capabilities = [
        target.capture_capability if target.capture_capability is not None else "not_implemented"
        for target in _capture_targets_for_evidence(session, evidence=evidence)
        if missing_code in target.reason_codes
    ]
    for candidate in ("available", "requires_reopen", "unsupported", "not_implemented"):
        if candidate in capabilities:
            return candidate
    return None


def _resolve_capture_target(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    external_flow_id: int | None,
    boundary_group_id: int | None,
) -> ResolvedCaptureTarget:
    if (external_flow_id is None) == (boundary_group_id is None):
        raise ValueError("exactly one capture target is required")
    if scope is PerformanceScope.ACCOUNT:
        if account_id is None:
            raise ValueError("account_id is required for account capture")
        if session.get(Account, account_id) is None:
            raise AccountNotFoundError(f"account {account_id} was not found")
    elif account_id is not None:
        raise ValueError("account_id must be omitted for portfolio capture")

    if external_flow_id is not None:
        flow = session.get(ExternalFlow, external_flow_id, populate_existing=True)
        if flow is None:
            raise ValueError(f"external flow {external_flow_id} was not found")
        if scope is PerformanceScope.ACCOUNT and flow.account_id != account_id:
            raise ValueError("the external flow must belong to the selected account")
        month = session.get(ReportingMonth, flow.reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(
                f"reporting month {flow.reporting_month_id} was not found"
            )
        return ResolvedCaptureTarget(
            scope=scope,
            account_id=account_id,
            reporting_month_id=flow.reporting_month_id,
            reporting_month_status=month.status,
            boundary_date=flow.event_date,
            external_flow_id=flow.id,
            boundary_group_id=None,
        )

    assert boundary_group_id is not None
    group = session.get(ExternalFlowBoundaryGroup, boundary_group_id, populate_existing=True)
    if group is None:
        raise ValueError(f"external flow boundary group {boundary_group_id} was not found")
    if group.scope != scope.value or group.account_id != account_id:
        raise ValueError("the boundary group scope does not match the capture")
    month = session.get(ReportingMonth, group.reporting_month_id)
    if month is None:
        raise ReportingMonthNotFoundError(
            f"reporting month {group.reporting_month_id} was not found"
        )
    return ResolvedCaptureTarget(
        scope=scope,
        account_id=account_id,
        reporting_month_id=group.reporting_month_id,
        reporting_month_status=month.status,
        boundary_date=group.boundary_date,
        external_flow_id=None,
        boundary_group_id=group.id,
    )


def stage_observed_valuation_capture(
    session: Session,
    *,
    scope: PerformanceScope | str,
    account_id: int | None,
    relation: ValuationBoundaryRelation | str,
    expected_material_signature: str,
    total_value: RubleAmount | str,
    performance_currency: str,
    coverage: CoverageStatus | str,
    quality: ValuationQuality | str,
    provenance_kind: str,
    external_flow_id: int | None = None,
    boundary_group_id: int | None = None,
    provenance_reference: str | None = None,
    notes: str | None = None,
) -> ObservedValuationPoint:
    """Reserve, revalidate and stage one observed side; never derive a value.

    The caller supplies the material signature read when the capture form was
    opened.  The writer reservation is acquired before the authoritative
    reread, so a concurrent correction or close deterministically wins or
    loses.  Duplicate or ambiguous same-relation sides fail closed instead of
    publishing an unresolvable pair.

    Only authoritative evidence is persisted: the canonical service has no
    observation correction path, so an incomplete, inexact or foreign-currency
    side would permanently consume the target without ever making the pair
    usable.  Such submissions are rejected before any mutation; source-less
    situations must remain a displayed limitation instead of a write.
    """

    normalized_scope = _coerce_scope(scope)
    normalized_relation = _coerce_relation(relation)
    try:
        normalized_coverage = CoverageStatus(coverage)
    except ValueError as error:
        raise ValueError("coverage must be complete for a supported capture") from error
    if normalized_coverage is not CoverageStatus.COMPLETE:
        raise ValueError("coverage must be complete for a supported capture")
    try:
        normalized_quality = ValuationQuality(quality)
    except ValueError as error:
        raise ValueError("quality must be exact for a supported capture") from error
    if normalized_quality is not ValuationQuality.EXACT:
        raise ValueError("quality must be exact for a supported capture")
    normalized_currency = performance_currency.strip().upper()
    target_currency, _reasons = _performance_currency(session)
    if normalized_currency != target_currency:
        raise ValueError("observation currency must equal the target performance currency")

    # Resolve identity first (read-only), then hold SQLite's writer reservation
    # through the authoritative reread, publication and the caller's commit.
    target = _resolve_capture_target(
        session,
        scope=normalized_scope,
        account_id=account_id,
        external_flow_id=external_flow_id,
        boundary_group_id=boundary_group_id,
    )
    month = require_editable_reporting_month(session, target.reporting_month_id)
    session.expire_all()

    current_signature = material_signature_for_boundary(
        session,
        scope=normalized_scope.value,
        account_id=account_id,
        external_flow_id=target.external_flow_id,
        boundary_group_id=target.boundary_group_id,
    )
    if current_signature is None or current_signature != expected_material_signature:
        raise ValueError("valuation capture target changed materially")

    statement = select(ObservedValuationPoint).where(
        ObservedValuationPoint.reporting_month_id == month.id,
        ObservedValuationPoint.scope == normalized_scope.value,
        ObservedValuationPoint.account_id == account_id,
        ObservedValuationPoint.external_flow_id == target.external_flow_id,
        ObservedValuationPoint.boundary_group_id == target.boundary_group_id,
    )
    rows = list(session.scalars(statement.order_by(ObservedValuationPoint.id)))
    relation_rows = [row for row in rows if row.relation == normalized_relation.value]
    if any(row.material_signature == current_signature for row in relation_rows):
        raise ValueError("this observation side is already recorded for the current material state")
    if len(relation_rows) > 1:
        raise ValueError("this observation side is ambiguous; capture is blocked")
    if any(sum(1 for row in rows if row.relation == other.value) > 1 for other in _RELATIONS):
        raise ValueError("the boundary already has ambiguous sides; capture is blocked")

    return stage_create_observed_valuation_point(
        session,
        reporting_month_id=month.id,
        observed_date=target.boundary_date,
        total_value=total_value,
        performance_currency=normalized_currency,
        provenance_kind=provenance_kind,
        relation=normalized_relation,
        scope=normalized_scope,
        account_id=account_id,
        coverage=normalized_coverage,
        quality=normalized_quality,
        provenance_reference=provenance_reference,
        external_flow_id=target.external_flow_id,
        boundary_group_id=target.boundary_group_id,
        notes=notes,
        expected_material_signature=expected_material_signature,
    )


__all__ = [
    "CaptureTarget",
    "CaptureSide",
    "ValuationCaptureProjection",
    "capture_capability_for_evidence",
    "stage_observed_valuation_capture",
    "valuation_capture_projection_for_interval",
]
