"""Read-only interval availability for exact portfolio performance.

R08-01C assembles evidence for downstream XIRR and TWRR consumers.  It does
not calculate either metric, refresh a provider, write defaults, or infer a
valuation/flow from another date.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    AvailabilityReasonCode,
    CoverageStatus,
    ExternalFlowClassification,
    ExternalFlowCoverage,
    ExternalFlowEvidence,
    ExternalFlowScope,
    ExternalFlowScopeMembership,
    ExternalTransferStatus,
    PerformanceAvailability,
    PerformanceAvailabilityStatus,
    PerformanceMetricPrerequisites,
    PerformanceScope,
    ScopeMembershipCoverage,
    ValuationBoundaryEvidence,
    ValuationPointStatus,
)
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_BASE_CURRENCY,
    Account,
    AccountPerformanceScopeMembership,
    AppSettings,
    ExternalFlow,
    InvestmentCashFlow,
    ReportingMonth,
)
from hermes_finance.services.external_flows import (
    classify_external_flow,
    external_flow_transfer_status,
)
from hermes_finance.services.valuation_points import valuation_point_for_month

_LEGACY_BOUNDARY_FLOW_TYPES = ("deposit", "withdrawal")
_TWRR_ONLY_REASON = AvailabilityReasonCode.VALUATION_BOUNDARY_ORDER_UNKNOWN.value


def _coerce_scope(scope: PerformanceScope | str) -> PerformanceScope:
    try:
        return PerformanceScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported performance scope: {scope!r}") from error


def _validate_request(
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
) -> None:
    if type(start_date) is not date or type(end_date) is not date:
        raise TypeError("start_date and end_date must be dates")
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date")
    if scope is PerformanceScope.ACCOUNT and account_id is None:
        raise ValueError("account_id is required for account performance scope")
    if scope is PerformanceScope.PORTFOLIO and account_id is not None:
        raise ValueError("account_id must be omitted for portfolio performance scope")


def _normalise_currency(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _performance_currency(session: Session) -> tuple[str, set[str]]:
    settings = session.get(AppSettings, APP_SETTINGS_ID)
    if settings is None:
        return DEFAULT_BASE_CURRENCY, set()
    currency = _normalise_currency(settings.base_currency)
    reasons: set[str] = set()
    if len(currency) != 3 or not currency.isalpha():
        reasons.add(AvailabilityReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)
        # Keep the response deterministic while never treating the malformed
        # setting as a valid conversion target.
        return currency or DEFAULT_BASE_CURRENCY, reasons
    if currency != DEFAULT_BASE_CURRENCY:
        reasons.add(AvailabilityReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)
    return currency, reasons


def _membership_rows(
    session: Session,
    account_ids: tuple[int, ...],
) -> dict[int, list[AccountPerformanceScopeMembership]]:
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]] = defaultdict(list)
    if not account_ids:
        return rows_by_account
    rows = session.scalars(
        select(AccountPerformanceScopeMembership)
        .where(AccountPerformanceScopeMembership.account_id.in_(account_ids))
        .order_by(
            AccountPerformanceScopeMembership.account_id,
            AccountPerformanceScopeMembership.effective_from,
            AccountPerformanceScopeMembership.id,
        )
    )
    for row in rows:
        rows_by_account[row.account_id].append(row)
    return rows_by_account


def _history_covers_interval(
    rows: list[AccountPerformanceScopeMembership],
    *,
    start_date: date,
    end_date: date,
) -> bool:
    """Return true only for a gap-free, non-overlapping effective-date history."""

    relevant = [
        row
        for row in rows
        if row.effective_from <= end_date
        and (row.effective_to is None or row.effective_to >= start_date)
    ]
    if not relevant:
        return False

    previous_end: date | None = None
    for row in relevant:
        row_end = row.effective_to or date.max
        if previous_end is not None and row.effective_from <= previous_end:
            return False
        previous_end = row_end

    cursor = start_date
    for row in relevant:
        row_end = row.effective_to or date.max
        if row_end < cursor:
            continue
        if row.effective_from > cursor:
            return False
        if row_end >= end_date:
            return True
        cursor = row_end + timedelta(days=1)
    return False


def _membership_at(
    rows: list[AccountPerformanceScopeMembership],
    observed_date: date,
) -> bool | None:
    matches = [
        row
        for row in rows
        if row.effective_from <= observed_date
        and (row.effective_to is None or row.effective_to >= observed_date)
    ]
    if len(matches) != 1:
        return None
    return matches[0].include_in_returns


def _scope_membership_coverage(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
) -> tuple[ScopeMembershipCoverage, dict[int, list[AccountPerformanceScopeMembership]]]:
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"account {account_id} was not found")
        account_ids = (account_id,)
    else:
        account_ids = tuple(session.scalars(select(Account.id).order_by(Account.id)))

    rows_by_account = _membership_rows(session, account_ids)
    missing_or_ambiguous: list[int] = []
    reasons: set[str] = set()
    for current_account_id in account_ids:
        rows = rows_by_account.get(current_account_id, [])
        if not _history_covers_interval(rows, start_date=start_date, end_date=end_date):
            missing_or_ambiguous.append(current_account_id)
            reasons.add(AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)

        if scope is PerformanceScope.ACCOUNT and any(
            not row.include_in_returns
            and row.effective_from <= end_date
            and (row.effective_to is None or row.effective_to >= start_date)
            for row in rows
        ):
            reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    if scope is PerformanceScope.PORTFOLIO and not account_ids:
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

    if not reasons:
        status = CoverageStatus.COMPLETE.value
    elif AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value in reasons:
        status = CoverageStatus.UNKNOWN.value
    else:
        status = CoverageStatus.UNAVAILABLE.value
    return (
        ScopeMembershipCoverage(
            status=status,
            account_ids=account_ids,
            missing_or_ambiguous_account_ids=tuple(sorted(missing_or_ambiguous)),
            reason_codes=tuple(sorted(reasons)),
        ),
        rows_by_account,
    )


def _boundary_reason(role: str) -> str:
    if role == "opening":
        return AvailabilityReasonCode.OPENING_VALUATION_MISSING.value
    if role == "closing":
        return AvailabilityReasonCode.CLOSING_VALUATION_MISSING.value
    return AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value


def _resolve_boundary(
    session: Session,
    *,
    role: str,
    requested_date: date,
    scope: PerformanceScope,
    account_id: int | None,
) -> ValuationBoundaryEvidence:
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(ReportingMonth.snapshot_date == requested_date)
            .order_by(ReportingMonth.id)
        )
    )
    reason = _boundary_reason(role)
    if len(months) != 1:
        return ValuationBoundaryEvidence(
            role=role,
            requested_date=requested_date,
            reporting_month_id=None,
            point=None,
            reason_codes=(reason,),
        )

    month = months[0]
    point = valuation_point_for_month(
        session,
        month.id,
        scope=scope,
        account_id=account_id,
    )
    reasons = set(point.coverage.reason_codes)
    if point.status is not ValuationPointStatus.AVAILABLE and not reasons:
        reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
    return ValuationBoundaryEvidence(
        role=role,
        requested_date=requested_date,
        reporting_month_id=month.id,
        point=point,
        reason_codes=tuple(sorted(reasons)),
    )


def _safe_scope_membership(value: object) -> ExternalFlowScopeMembership:
    try:
        return ExternalFlowScopeMembership(value)
    except (TypeError, ValueError):
        return ExternalFlowScopeMembership.UNKNOWN


def _safe_classification(
    session: Session,
    flow: ExternalFlow,
    *,
    scope: PerformanceScope,
    account_id: int | None,
) -> tuple[ExternalFlowClassification, ExternalTransferStatus | None, set[str]]:
    reasons: set[str] = set()
    normalized_scope = (
        ExternalFlowScope.ACCOUNT
        if scope is PerformanceScope.ACCOUNT
        else ExternalFlowScope.PORTFOLIO
    )
    try:
        classification = classify_external_flow(
            session,
            flow.id,
            scope=normalized_scope,
            account_id=account_id,
        )
    except (LookupError, ValueError):
        classification = ExternalFlowClassification.UNRESOLVED
        reasons.add(AvailabilityReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)

    try:
        transfer_status = external_flow_transfer_status(session, flow)
    except LookupError:
        transfer_status = ExternalTransferStatus.UNRESOLVED
        reasons.add(AvailabilityReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)

    if classification is ExternalFlowClassification.NOT_AUTHORITATIVE:
        reasons.add(AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)
    if classification is ExternalFlowClassification.UNRESOLVED:
        reasons.add(AvailabilityReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)
    return classification, transfer_status, reasons


def _flow_is_relevant(
    classification: ExternalFlowClassification,
) -> bool:
    return classification is not ExternalFlowClassification.NOT_IN_SCOPE


def _legacy_flow_ids(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]],
) -> tuple[int, ...]:
    statement = select(InvestmentCashFlow).where(
        InvestmentCashFlow.event_date >= start_date,
        InvestmentCashFlow.event_date <= end_date,
        InvestmentCashFlow.flow_type.in_(_LEGACY_BOUNDARY_FLOW_TYPES),
    )
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        statement = statement.where(InvestmentCashFlow.account_id == account_id)

    ids: list[int] = []
    for row in session.scalars(
        statement.order_by(InvestmentCashFlow.event_date, InvestmentCashFlow.id)
    ):
        if scope is PerformanceScope.PORTFOLIO:
            membership = _membership_at(rows_by_account.get(row.account_id, []), row.event_date)
            if membership is False:
                continue
        ids.append(row.id)
    return tuple(ids)


def _external_flow_coverage(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    performance_currency: str,
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]],
) -> ExternalFlowCoverage:
    flows = list(
        session.scalars(
            select(ExternalFlow)
            .where(
                ExternalFlow.event_date >= start_date,
                ExternalFlow.event_date <= end_date,
            )
            .order_by(ExternalFlow.event_date, ExternalFlow.id)
        )
    )
    reasons: set[str] = set()
    evidence: list[ExternalFlowEvidence] = []
    for flow in flows:
        classification, transfer_status, flow_reasons = _safe_classification(
            session,
            flow,
            scope=scope,
            account_id=account_id,
        )
        if not _flow_is_relevant(classification):
            continue

        flow_reasons = set(flow_reasons)
        membership = _safe_scope_membership(flow.scope_membership)
        if membership is ExternalFlowScopeMembership.UNKNOWN:
            flow_reasons.add(AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)
        if (
            not isinstance(flow.boundary_amount_kopecks, int)
            or isinstance(flow.boundary_amount_kopecks, bool)
            or flow.boundary_amount_kopecks < 0
        ):
            flow_reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)

        currency = _normalise_currency(flow.currency)
        if len(currency) != 3 or not currency.isalpha() or currency != performance_currency:
            flow_reasons.add(AvailabilityReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)

        parent_month = session.get(ReportingMonth, flow.reporting_month_id)
        if parent_month is None or parent_month.status != "closed":
            flow_reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
            flow_reasons.add(AvailabilityReasonCode.REPORTING_MONTH_NOT_CLOSED.value)

        reasons.update(flow_reasons)
        evidence.append(
            ExternalFlowEvidence(
                id=flow.id,
                reporting_month_id=flow.reporting_month_id,
                account_id=flow.account_id,
                event_date=flow.event_date,
                boundary_amount_kopecks=flow.boundary_amount_kopecks,
                direction=flow.direction,
                kind=flow.kind,
                currency=currency,
                scope_membership=membership,
                classification=classification,
                transfer_link_id=flow.transfer_link_id,
                transfer_status=transfer_status,
                source=flow.source,
            )
        )

    legacy_ids = _legacy_flow_ids(
        session,
        scope=scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
    )
    if legacy_ids:
        reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)

    if not reasons:
        status = CoverageStatus.COMPLETE.value
    elif reasons == {AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value}:
        status = CoverageStatus.UNKNOWN.value
    else:
        status = CoverageStatus.UNAVAILABLE.value
    return ExternalFlowCoverage(
        status=status,
        flows=tuple(evidence),
        legacy_unclassified_flow_ids=legacy_ids,
        reason_codes=tuple(sorted(reasons)),
    )


def _boundary_point_for_date(
    session: Session,
    *,
    observed_date: date,
    scope: PerformanceScope,
    account_id: int | None,
    cache: dict[date, ValuationBoundaryEvidence],
) -> ValuationBoundaryEvidence:
    cached = cache.get(observed_date)
    if cached is not None:
        return cached
    evidence = _resolve_boundary(
        session,
        role="intermediate",
        requested_date=observed_date,
        scope=scope,
        account_id=account_id,
    )
    cache[observed_date] = evidence
    return evidence


def _twrr_boundary_reasons(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    flows: ExternalFlowCoverage,
    boundary_cache: dict[date, ValuationBoundaryEvidence],
) -> set[str]:
    reasons: set[str] = set()
    for flow in flows.flows:
        if flow.classification not in {
            ExternalFlowClassification.EXTERNAL_CONTRIBUTION,
            ExternalFlowClassification.EXTERNAL_WITHDRAWAL,
        }:
            continue
        boundary = _boundary_point_for_date(
            session,
            observed_date=flow.event_date,
            scope=scope,
            account_id=account_id,
            cache=boundary_cache,
        )
        if boundary.is_available:
            # The persisted model is date-only and carries no explicit
            # pre/post-flow relation.  A same-day observation is therefore
            # not enough for exact TWRR, even when it is otherwise trusted.
            reasons.add(_TWRR_ONLY_REASON)
        else:
            reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)
            reasons.update(
                reason for reason in boundary.reason_codes if reason != _TWRR_ONLY_REASON
            )
    return reasons


def _metric(
    metric: str,
    reasons: set[str],
) -> PerformanceMetricPrerequisites:
    return PerformanceMetricPrerequisites(
        metric=metric,
        availability=(
            PerformanceAvailabilityStatus.AVAILABLE
            if not reasons
            else PerformanceAvailabilityStatus.NOT_COMPUTABLE
        ),
        reason_codes=tuple(sorted(reasons)),
    )


def performance_availability_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> PerformanceAvailability:
    """Assemble exact-performance prerequisites for one requested interval."""

    normalized_scope = _coerce_scope(scope)
    _validate_request(
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )
    performance_currency, currency_reasons = _performance_currency(session)
    membership, rows_by_account = _scope_membership_coverage(
        session,
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
    )

    boundary_cache: dict[date, ValuationBoundaryEvidence] = {}
    opening = _resolve_boundary(
        session,
        role="opening",
        requested_date=start_date,
        scope=normalized_scope,
        account_id=account_id,
    )
    closing = _resolve_boundary(
        session,
        role="closing",
        requested_date=end_date,
        scope=normalized_scope,
        account_id=account_id,
    )
    boundary_cache[start_date] = opening
    boundary_cache[end_date] = closing

    flows = _external_flow_coverage(
        session,
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        performance_currency=performance_currency,
        rows_by_account=rows_by_account,
    )

    xirr_reasons = set(currency_reasons)
    xirr_reasons.update(membership.reason_codes)
    xirr_reasons.update(opening.reason_codes)
    xirr_reasons.update(closing.reason_codes)
    xirr_reasons.update(flows.reason_codes)
    # Date-only boundary ordering is a TWRR-only limitation under #145 v2.
    xirr_reasons.discard(_TWRR_ONLY_REASON)

    xirr = _metric("xirr", xirr_reasons)
    twrr_reasons = set(xirr_reasons)
    twrr_reasons.update(
        _twrr_boundary_reasons(
            session,
            scope=normalized_scope,
            account_id=account_id,
            flows=flows,
            boundary_cache=boundary_cache,
        )
    )
    twrr = _metric("twrr", twrr_reasons)

    all_reasons = set(xirr_reasons) | set(twrr.reason_codes)
    availability = (
        PerformanceAvailabilityStatus.AVAILABLE
        if not all_reasons
        else PerformanceAvailabilityStatus.NOT_COMPUTABLE
    )
    return PerformanceAvailability(
        scope=normalized_scope,
        account_id=account_id if normalized_scope is PerformanceScope.ACCOUNT else None,
        start_date=start_date,
        end_date=end_date,
        performance_currency=performance_currency,
        availability=availability,
        reason_codes=tuple(sorted(all_reasons)),
        opening_valuation=opening,
        closing_valuation=closing,
        scope_membership=membership,
        external_flows=flows,
        xirr=xirr,
        twrr=twrr,
    )


# Public aliases keep the interval wording discoverable for downstream tasks.
get_performance_availability = performance_availability_for_interval
build_performance_availability = performance_availability_for_interval
