"""Persistence services for observed external-flow valuation boundaries.

This module stores only explicitly observed values.  It never derives a value
from a month snapshot, a capital delta, a provider refresh, or an interpolation
and it contains no XIRR/TWRR calculation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, DecimalException

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    CoverageStatus,
    ExternalFlowClassification,
    ExternalFlowScope,
    ObservedValuationEvidence,
    PerformanceScope,
    RubleAmount,
    ValuationBoundaryRelation,
    ValuationQuality,
)
from hermes_finance.persistence import (
    Account,
    ExternalFlow,
    ExternalFlowBoundaryGroup,
    ExternalFlowBoundaryGroupMember,
    ObservedValuationPoint,
    ReportingMonth,
)
from hermes_finance.services._guard import require_editable_reporting_month
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.external_flows import classify_external_flow
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class ObservedValuationPointNotFoundError(LookupError):
    pass


class ExternalFlowBoundaryGroupNotFoundError(LookupError):
    pass


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


def _coerce_coverage(coverage: CoverageStatus | str) -> CoverageStatus:
    try:
        return CoverageStatus(coverage)
    except ValueError as error:
        raise ValueError(f"unsupported valuation coverage status: {coverage!r}") from error


def _coerce_quality(quality: ValuationQuality | str) -> ValuationQuality:
    try:
        return ValuationQuality(quality)
    except ValueError as error:
        raise ValueError(f"unsupported valuation quality: {quality!r}") from error


def _coerce_date(value: date, *, field: str) -> date:
    if type(value) is not date:
        raise TypeError(f"{field} must be a date")
    return value


def _normalize_exact_amount(value: RubleAmount | str, *, field: str) -> int:
    if isinstance(value, str):
        try:
            decimal_value = Decimal(value)
        except DecimalException as error:
            raise ValueError(f"{field} must be a finite decimal string") from error
        if not decimal_value.is_finite():
            raise ValueError(f"{field} must be finite")
        scaled = decimal_value * Decimal(100)
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{field} must have no more than two decimal places")
        value = RubleAmount.from_decimal(decimal_value)
    if not isinstance(value, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if value.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return value.kopecks


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("performance_currency must be a three-letter code")
    return normalized


def _normalize_text(value: str, *, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} must not exceed {max_length} characters")
    return normalized


def _require_month(session: Session, month_id: int) -> ReportingMonth:
    month = session.get(ReportingMonth, month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")
    return month


def _require_account(session: Session, account_id: int) -> Account:
    account = session.get(Account, account_id)
    if account is None:
        raise AccountNotFoundError(f"account {account_id} was not found")
    return account


def _require_flow(session: Session, flow_id: int) -> ExternalFlow:
    flow = session.get(ExternalFlow, flow_id)
    if flow is None:
        raise ValueError(f"external flow {flow_id} was not found")
    return flow


def _require_group(session: Session, group_id: int) -> ExternalFlowBoundaryGroup:
    group = session.get(ExternalFlowBoundaryGroup, group_id)
    if group is None:
        raise ExternalFlowBoundaryGroupNotFoundError(
            f"external flow boundary group {group_id} was not found"
        )
    return group


def boundary_group_flows(
    session: Session,
    group_id: int,
) -> list[ExternalFlow]:
    """Return a group's flow members in deterministic ID order."""

    _require_group(session, group_id)
    return list(
        session.scalars(
            select(ExternalFlow)
            .join(
                ExternalFlowBoundaryGroupMember,
                ExternalFlowBoundaryGroupMember.external_flow_id == ExternalFlow.id,
            )
            .where(ExternalFlowBoundaryGroupMember.boundary_group_id == group_id)
            .order_by(ExternalFlow.id)
        )
    )


def _scope_account_id(scope: PerformanceScope, account_id: int | None) -> int | None:
    if scope is PerformanceScope.ACCOUNT and account_id is None:
        raise ValueError("account_id is required for account valuation boundaries")
    if scope is PerformanceScope.PORTFOLIO and account_id is not None:
        raise ValueError("account_id must be omitted for portfolio valuation boundaries")
    return account_id


def _require_date_in_month(month: ReportingMonth, observed_date: date, *, field: str) -> None:
    if not month.period_start <= observed_date <= month.period_end:
        raise ValueError(f"{field} must be within the reporting month")


def _validate_external_flow_for_scope(
    session: Session,
    flow: ExternalFlow,
    *,
    scope: PerformanceScope,
    account_id: int | None,
) -> None:
    classification = classify_external_flow(
        session,
        flow.id,
        scope=(
            ExternalFlowScope.ACCOUNT
            if scope is PerformanceScope.ACCOUNT
            else ExternalFlowScope.PORTFOLIO
        ),
        account_id=account_id,
    )
    if classification in {
        ExternalFlowClassification.INTERNAL_TRANSFER,
        ExternalFlowClassification.NOT_IN_SCOPE,
    }:
        raise ValueError(
            "portfolio-internal or out-of-scope flows cannot create valuation boundaries"
        )


def _validate_group_members(
    session: Session,
    *,
    month: ReportingMonth,
    scope: PerformanceScope,
    account_id: int | None,
    boundary_date: date,
    flow_ids: list[int],
) -> list[ExternalFlow]:
    flows = [_require_flow(session, flow_id) for flow_id in flow_ids]
    for flow in flows:
        if flow.reporting_month_id != month.id:
            raise ValueError("all boundary-group flows must belong to the reporting month")
        if flow.event_date != boundary_date:
            raise ValueError("all boundary-group flows must share the same event date")
        if scope is PerformanceScope.ACCOUNT and flow.account_id != account_id:
            raise ValueError("account boundary-group flows must belong to the selected account")
        _validate_external_flow_for_scope(
            session,
            flow,
            scope=scope,
            account_id=account_id,
        )
    return flows


def stage_create_external_flow_boundary_group(
    session: Session,
    *,
    reporting_month_id: int,
    boundary_date: date,
    flow_ids: Iterable[int],
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> ExternalFlowBoundaryGroup:
    """Stage an explicit same-date group without inferring flow membership."""

    month = require_editable_reporting_month(session, reporting_month_id)
    normalized_scope = _coerce_scope(scope)
    normalized_account_id = _scope_account_id(normalized_scope, account_id)
    normalized_date = _coerce_date(boundary_date, field="boundary_date")
    _require_date_in_month(month, normalized_date, field="boundary_date")
    ids = sorted(flow_ids)
    if not ids:
        raise ValueError("flow_ids must contain at least one external flow")
    if len(ids) != len(set(ids)):
        raise ValueError("flow_ids must not contain duplicates")
    flows = _validate_group_members(
        session,
        month=month,
        scope=normalized_scope,
        account_id=normalized_account_id,
        boundary_date=normalized_date,
        flow_ids=ids,
    )
    if normalized_scope is PerformanceScope.ACCOUNT:
        _require_account(session, normalized_account_id)  # type: ignore[arg-type]

    existing = session.scalar(
        select(ExternalFlowBoundaryGroup).where(
            ExternalFlowBoundaryGroup.reporting_month_id == month.id,
            ExternalFlowBoundaryGroup.scope == normalized_scope.value,
            ExternalFlowBoundaryGroup.account_id == normalized_account_id,
            ExternalFlowBoundaryGroup.boundary_date == normalized_date,
        )
    )
    if existing is not None:
        raise ValueError("a boundary group already exists for this scope and event date")

    group = ExternalFlowBoundaryGroup(
        reporting_month_id=month.id,
        scope=normalized_scope.value,
        account_id=normalized_account_id,
        boundary_date=normalized_date,
    )
    session.add(group)
    session.flush()
    session.add_all(
        [
            ExternalFlowBoundaryGroupMember(
                boundary_group_id=group.id,
                external_flow_id=flow.id,
            )
            for flow in flows
        ]
    )
    session.flush()
    return group


def create_external_flow_boundary_group(
    session: Session,
    *,
    reporting_month_id: int,
    boundary_date: date,
    flow_ids: Iterable[int],
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> ExternalFlowBoundaryGroup:
    group = stage_create_external_flow_boundary_group(
        session,
        reporting_month_id=reporting_month_id,
        boundary_date=boundary_date,
        flow_ids=flow_ids,
        scope=scope,
        account_id=account_id,
    )
    session.commit()
    session.refresh(group)
    return group


def get_external_flow_boundary_group(
    session: Session,
    group_id: int,
) -> ExternalFlowBoundaryGroup:
    return _require_group(session, group_id)


def list_external_flow_boundary_groups(
    session: Session,
    *,
    reporting_month_id: int | None = None,
    scope: PerformanceScope | str | None = None,
    account_id: int | None = None,
) -> list[ExternalFlowBoundaryGroup]:
    statement = select(ExternalFlowBoundaryGroup)
    if reporting_month_id is not None:
        statement = statement.where(
            ExternalFlowBoundaryGroup.reporting_month_id == reporting_month_id
        )
    if scope is not None:
        statement = statement.where(ExternalFlowBoundaryGroup.scope == _coerce_scope(scope).value)
    if account_id is not None:
        statement = statement.where(ExternalFlowBoundaryGroup.account_id == account_id)
    return list(
        session.scalars(
            statement.order_by(
                ExternalFlowBoundaryGroup.boundary_date,
                ExternalFlowBoundaryGroup.id,
            )
        )
    )


def stage_create_observed_valuation_point(
    session: Session,
    *,
    reporting_month_id: int,
    observed_date: date,
    total_value: RubleAmount | str,
    performance_currency: str,
    provenance_kind: str,
    relation: ValuationBoundaryRelation | str,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
    coverage: CoverageStatus | str = CoverageStatus.COMPLETE,
    quality: ValuationQuality | str = ValuationQuality.EXACT,
    provenance_reference: str | None = None,
    external_flow_id: int | None = None,
    boundary_group_id: int | None = None,
    notes: str | None = None,
) -> ObservedValuationPoint:
    """Stage an explicitly related observed valuation point."""

    month = require_editable_reporting_month(session, reporting_month_id)
    normalized_scope = _coerce_scope(scope)
    normalized_account_id = _scope_account_id(normalized_scope, account_id)
    normalized_observed_date = _coerce_date(observed_date, field="observed_date")
    normalized_relation = _coerce_relation(relation)
    normalized_coverage = _coerce_coverage(coverage)
    normalized_quality = _coerce_quality(quality)
    normalized_currency = _normalize_currency(performance_currency)
    normalized_kind = _normalize_text(
        provenance_kind,
        field="provenance_kind",
        max_length=64,
    )
    normalized_reference = (
        None
        if provenance_reference is None
        else _normalize_text(
            provenance_reference,
            field="provenance_reference",
            max_length=128,
        )
    )
    amount_kopecks = _normalize_exact_amount(total_value, field="total_value")

    if (external_flow_id is None) == (boundary_group_id is None):
        raise ValueError("exactly one external_flow_id or boundary_group_id is required")

    boundary_date: date
    if external_flow_id is not None:
        flow = _require_flow(session, external_flow_id)
        if flow.reporting_month_id != month.id:
            raise ValueError("the external flow must belong to the reporting month")
        if (
            normalized_scope is PerformanceScope.ACCOUNT
            and flow.account_id != normalized_account_id
        ):
            raise ValueError("the external flow must belong to the selected account")
        _validate_external_flow_for_scope(
            session,
            flow,
            scope=normalized_scope,
            account_id=normalized_account_id,
        )
        boundary_date = flow.event_date
        _require_date_in_month(month, boundary_date, field="external flow event_date")
        existing_group = session.scalar(
            select(ExternalFlowBoundaryGroup.id)
            .join(
                ExternalFlowBoundaryGroupMember,
                ExternalFlowBoundaryGroupMember.boundary_group_id == ExternalFlowBoundaryGroup.id,
            )
            .where(
                ExternalFlowBoundaryGroup.reporting_month_id == month.id,
                ExternalFlowBoundaryGroup.scope == normalized_scope.value,
                ExternalFlowBoundaryGroup.account_id == normalized_account_id,
                ExternalFlowBoundaryGroup.boundary_date == boundary_date,
                ExternalFlowBoundaryGroupMember.external_flow_id == flow.id,
            )
        )
        if existing_group is not None:
            raise ValueError("the external flow already belongs to a boundary group")
    else:
        assert boundary_group_id is not None
        group = _require_group(session, boundary_group_id)
        if group.reporting_month_id != month.id:
            raise ValueError("the boundary group must belong to the reporting month")
        if group.scope != normalized_scope.value or group.account_id != normalized_account_id:
            raise ValueError("the boundary group scope does not match the observed point")
        if not boundary_group_flows(session, group.id):
            raise ValueError("the boundary group must contain at least one external flow")
        boundary_date = group.boundary_date

    _require_date_in_month(month, normalized_observed_date, field="observed_date")

    if normalized_observed_date != boundary_date:
        raise ValueError(
            f"{normalized_relation.value} observed_date must equal the flow boundary date"
        )

    point = ObservedValuationPoint(
        reporting_month_id=month.id,
        scope=normalized_scope.value,
        account_id=normalized_account_id,
        observed_date=normalized_observed_date,
        total_value_kopecks=amount_kopecks,
        performance_currency=normalized_currency,
        coverage_status=normalized_coverage.value,
        quality=normalized_quality.value,
        provenance_kind=normalized_kind,
        provenance_reference=normalized_reference,
        relation=normalized_relation.value,
        external_flow_id=external_flow_id,
        boundary_group_id=boundary_group_id,
        notes=notes,
    )
    session.add(point)
    session.flush()
    return point


def create_observed_valuation_point(
    session: Session,
    **kwargs: object,
) -> ObservedValuationPoint:
    point = stage_create_observed_valuation_point(session, **kwargs)  # type: ignore[arg-type]
    session.commit()
    session.refresh(point)
    return point


def get_observed_valuation_point(
    session: Session,
    point_id: int,
) -> ObservedValuationPoint:
    point = session.get(ObservedValuationPoint, point_id)
    if point is None:
        raise ObservedValuationPointNotFoundError(
            f"observed valuation point {point_id} was not found"
        )
    return point


def list_observed_valuation_points(
    session: Session,
    *,
    reporting_month_id: int | None = None,
    scope: PerformanceScope | str | None = None,
    account_id: int | None = None,
    observed_date: date | None = None,
    external_flow_id: int | None = None,
    boundary_group_id: int | None = None,
) -> list[ObservedValuationPoint]:
    statement = select(ObservedValuationPoint)
    if reporting_month_id is not None:
        statement = statement.where(ObservedValuationPoint.reporting_month_id == reporting_month_id)
    if scope is not None:
        statement = statement.where(ObservedValuationPoint.scope == _coerce_scope(scope).value)
    if account_id is not None:
        statement = statement.where(ObservedValuationPoint.account_id == account_id)
    if observed_date is not None:
        statement = statement.where(ObservedValuationPoint.observed_date == observed_date)
    if external_flow_id is not None:
        statement = statement.where(ObservedValuationPoint.external_flow_id == external_flow_id)
    if boundary_group_id is not None:
        statement = statement.where(ObservedValuationPoint.boundary_group_id == boundary_group_id)
    return list(
        session.scalars(
            statement.order_by(
                ObservedValuationPoint.observed_date,
                ObservedValuationPoint.relation,
                ObservedValuationPoint.id,
            )
        )
    )


def to_observed_valuation_evidence(
    point: ObservedValuationPoint,
) -> ObservedValuationEvidence:
    return ObservedValuationEvidence(
        id=point.id,
        scope=PerformanceScope(point.scope),
        account_id=point.account_id,
        observed_date=point.observed_date,
        total_value=RubleAmount(point.total_value_kopecks),
        performance_currency=point.performance_currency,
        coverage=CoverageStatus(point.coverage_status),
        quality=ValuationQuality(point.quality),
        provenance_kind=point.provenance_kind,
        provenance_reference=point.provenance_reference,
        relation=ValuationBoundaryRelation(point.relation),
        external_flow_id=point.external_flow_id,
        boundary_group_id=point.boundary_group_id,
    )


# Public aliases keep the task vocabulary easy to discover for future capture
# adapters without introducing another persistence implementation.
create_valuation_boundary_group = create_external_flow_boundary_group
stage_create_valuation_boundary_group = stage_create_external_flow_boundary_group
create_observed_valuation_boundary = create_observed_valuation_point
stage_create_observed_valuation_boundary = stage_create_observed_valuation_point
list_valuation_boundary_points = list_observed_valuation_points
