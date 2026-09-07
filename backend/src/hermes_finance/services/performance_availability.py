"""Read-only interval availability for exact portfolio performance.

R08-01C assembles evidence for downstream XIRR and TWRR consumers.  It does
not calculate either metric, refresh a provider, write defaults, or infer a
valuation/flow from another date.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    AvailabilityReasonCode,
    CoverageStatus,
    ExternalFlowBoundaryEvidence,
    ExternalFlowClassification,
    ExternalFlowCoverage,
    ExternalFlowEvidence,
    ExternalFlowScope,
    ExternalFlowScopeMembership,
    ExternalTransferStatus,
    ObservedValuationEvidence,
    PerformanceAvailability,
    PerformanceAvailabilityStatus,
    PerformanceMetricPrerequisites,
    PerformanceScope,
    ScopeMembershipCoverage,
    ValuationBoundaryEvidence,
    ValuationBoundaryRelation,
    ValuationPointStatus,
    ValuationQuality,
)
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_BASE_CURRENCY,
    Account,
    AccountPerformanceScopeMembership,
    AppliedProviderPayout,
    AppSettings,
    ExpectedCashFlow,
    ExternalFlow,
    ExternalFlowBoundaryGroup,
    ExternalFlowBoundaryGroupMember,
    ExternalTransferReconciliationEvidence,
    InvestmentCashFlow,
    ObservedValuationPoint,
    ReportingMonth,
)
from hermes_finance.services.cash_boundary_coverage import (
    cash_boundary_coverage_for_interval,
)
from hermes_finance.services.external_flows import (
    classify_external_flow,
    external_flow_transfer_status,
)
from hermes_finance.services.in_kind_boundary_coverage import (
    in_kind_boundary_coverage_for_interval,
)
from hermes_finance.services.transfer_reconciliation import (
    iter_transfer_reconciliation_evidence,
)
from hermes_finance.services.valuation_boundaries import to_observed_valuation_evidence
from hermes_finance.services.valuation_points import valuation_point_for_month

_LEGACY_BOUNDARY_FLOW_TYPES = ("deposit", "withdrawal")
_RECONCILIATION_COST_FLOW_TYPES = ("tax", "commission")
_REALIZED_INCOME_FLOW_TYPES = ("coupon", "dividend")
_CALENDAR_PAYOUT_FLOW_TYPES = ("coupon", "dividend")
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


def _has_membership_transition_inside(
    rows: list[AccountPerformanceScopeMembership],
    *,
    start_date: date,
    end_date: date,
) -> bool:
    """Return True when include_in_returns changes on a date in [start_date, end_date]."""

    if not rows:
        return False
    ordered = sorted(rows, key=lambda row: (row.effective_from, row.id))
    for index, row in enumerate(ordered):
        if row.effective_from < start_date or row.effective_from > end_date:
            continue
        if index == 0:
            continue
        previous = ordered[index - 1]
        if previous.include_in_returns != row.include_in_returns:
            return True
    return False


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

        if scope is PerformanceScope.PORTFOLIO and _has_membership_transition_inside(
            rows, start_date=start_date, end_date=end_date
        ):
            reasons.add(AvailabilityReasonCode.SCOPE_MEMBERSHIP_CHANGED.value)

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


def _selected_investment_cash_flows(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]],
    flow_types: tuple[str, ...],
) -> tuple[InvestmentCashFlow, ...]:
    statement = select(InvestmentCashFlow).where(
        InvestmentCashFlow.event_date >= start_date,
        InvestmentCashFlow.event_date <= end_date,
        InvestmentCashFlow.flow_type.in_(flow_types),
    )
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        statement = statement.where(InvestmentCashFlow.account_id == account_id)

    selected: list[InvestmentCashFlow] = []
    for row in session.scalars(
        statement.order_by(InvestmentCashFlow.event_date, InvestmentCashFlow.id)
    ):
        if scope is PerformanceScope.PORTFOLIO:
            membership = _membership_at(rows_by_account.get(row.account_id, []), row.event_date)
            if membership is False:
                continue
        selected.append(row)
    return tuple(selected)


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _valid_nonnegative_investment_flow(row: InvestmentCashFlow) -> bool:
    gross = _nonnegative_int(row.gross_amount_kopecks)
    tax = _nonnegative_int(row.tax_amount_kopecks)
    commission = _nonnegative_int(row.commission_amount_kopecks)
    net = row.net_amount_kopecks
    return (
        gross is not None
        and tax is not None
        and commission is not None
        and not isinstance(net, bool)
        and isinstance(net, int)
        and net >= 0
        and net == gross - tax - commission
    )


def _internal_cost_amount(row: InvestmentCashFlow) -> int | None:
    """Return one explicitly typed standalone cost, or None when malformed."""

    gross = _nonnegative_int(row.gross_amount_kopecks)
    tax = _nonnegative_int(row.tax_amount_kopecks)
    commission = _nonnegative_int(row.commission_amount_kopecks)
    net = row.net_amount_kopecks
    if (
        gross is None
        or tax is None
        or commission is None
        or isinstance(net, bool)
        or not isinstance(net, int)
        or net != gross - tax - commission
    ):
        return None
    if gross != 0:
        return None
    if row.flow_type == "tax":
        if tax <= 0 or commission != 0 or net != -tax:
            return None
        return tax
    if row.flow_type == "commission":
        if commission <= 0 or tax != 0 or net != -commission:
            return None
        return commission
    return None


def _withdrawal_boundary_amounts(
    row: InvestmentCashFlow,
    *,
    standalone_costs: tuple[InvestmentCashFlow, ...],
) -> tuple[int, ...]:
    """Return only amounts supported by explicit withdrawal/cost arithmetic.

    The canonical boundary remains the already-persisted ``ExternalFlow``.
    A legacy withdrawal is used only as corroborating evidence.  Embedded
    tax/commission is authoritative for that row; separately persisted costs
    are accepted only when the primary row carries no embedded costs and every
    same-account/date cost is explicitly typed and valid.
    """

    if not _valid_nonnegative_investment_flow(row):
        return ()
    embedded_cost = row.tax_amount_kopecks + row.commission_amount_kopecks
    if embedded_cost:
        if standalone_costs:
            return ()
        return (row.net_amount_kopecks,)
    if not standalone_costs:
        return (row.net_amount_kopecks,)

    costs: list[int] = []
    for cost_row in standalone_costs:
        amount = _internal_cost_amount(cost_row)
        if amount is None:
            return ()
        costs.append(amount)
    boundary_amount = row.net_amount_kopecks - sum(costs)
    if boundary_amount < 0:
        return ()
    return (boundary_amount,)


def _external_withdrawals_by_key(
    flows: tuple[ExternalFlowEvidence, ...],
) -> dict[tuple[int, date, str], list[ExternalFlowEvidence]]:
    by_key: dict[tuple[int, date, str], list[ExternalFlowEvidence]] = defaultdict(list)
    for flow in flows:
        if (
            flow.classification is ExternalFlowClassification.EXTERNAL_WITHDRAWAL
            and flow.scope_membership is ExternalFlowScopeMembership.STABLE_IN_SCOPE
            and _nonnegative_int(flow.boundary_amount_kopecks) is not None
        ):
            by_key[(flow.account_id, flow.event_date, flow.currency)].append(flow)
    return by_key


def _legacy_flow_ids(
    *,
    investment_rows: tuple[InvestmentCashFlow, ...],
    external_flows: tuple[ExternalFlowEvidence, ...],
) -> tuple[int, ...]:
    legacy_rows = tuple(
        row for row in investment_rows if row.flow_type in _LEGACY_BOUNDARY_FLOW_TYPES
    )
    costs_by_key: dict[tuple[int, date, str], list[InvestmentCashFlow]] = defaultdict(list)
    withdrawals_by_key: dict[tuple[int, date, str], list[InvestmentCashFlow]] = defaultdict(list)
    for row in investment_rows:
        key = (row.account_id, row.event_date, _normalise_currency(row.currency))
        if row.flow_type in _RECONCILIATION_COST_FLOW_TYPES:
            costs_by_key[key].append(row)
        elif row.flow_type == "withdrawal":
            withdrawals_by_key[key].append(row)

    external_by_key = _external_withdrawals_by_key(external_flows)
    ids: list[int] = []
    for row in legacy_rows:
        if row.flow_type == "deposit":
            ids.append(row.id)
            continue

        key = (row.account_id, row.event_date, _normalise_currency(row.currency))
        withdrawal_rows = withdrawals_by_key[key]
        candidate_flows = external_by_key.get(key, [])
        if len(withdrawal_rows) != 1 or len(candidate_flows) != 1:
            ids.append(row.id)
            continue
        amounts = _withdrawal_boundary_amounts(
            row,
            standalone_costs=tuple(costs_by_key[key]),
        )
        if len(amounts) != 1 or amounts[0] != candidate_flows[0].boundary_amount_kopecks:
            ids.append(row.id)
    return tuple(ids)


def _valid_income_evidence(row: InvestmentCashFlow) -> bool:
    return (
        row.flow_type in _REALIZED_INCOME_FLOW_TYPES
        and row.instrument_id is not None
        and isinstance(row.source, str)
        and bool(row.source.strip())
        and _valid_nonnegative_investment_flow(row)
    )


def _direct_payout_reason_codes(
    *,
    external_flows: tuple[ExternalFlowEvidence, ...],
    income_rows: tuple[InvestmentCashFlow, ...],
) -> set[str]:
    """Validate direct-payout corroboration without creating another flow.

    An explicit external withdrawal remains the only performance boundary.  A
    same-account/date/currency income row may corroborate it only when its
    validated net amount equals that boundary and its account/holding source
    is unambiguous.  Gross is never substituted for net.
    """

    income_by_key: dict[tuple[int, date, str], list[InvestmentCashFlow]] = defaultdict(list)
    for row in income_rows:
        income_by_key[(row.account_id, row.event_date, _normalise_currency(row.currency))].append(
            row
        )

    reasons: set[str] = set()
    for flow in external_flows:
        if flow.classification is not ExternalFlowClassification.EXTERNAL_WITHDRAWAL:
            continue
        key = (flow.account_id, flow.event_date, flow.currency)
        same_key = income_by_key.get(key, [])
        exact = [
            row
            for row in same_key
            if _valid_income_evidence(row)
            and row.net_amount_kopecks == flow.boundary_amount_kopecks
        ]
        if same_key:
            if len(same_key) != 1 or len(exact) != 1:
                reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
            continue

        # If the only matching economic income is attached to another
        # selected account, the withdrawal cannot be assigned to its
        # generating holding from the available provenance.
        elsewhere = [
            row
            for row in income_rows
            if row.account_id != flow.account_id
            and row.event_date == flow.event_date
            and _normalise_currency(row.currency) == flow.currency
            and _valid_income_evidence(row)
            and row.net_amount_kopecks == flow.boundary_amount_kopecks
        ]
        if elsewhere:
            reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
    return reasons


def _calendar_payout_reason_codes(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]],
    actual_income_rows: tuple[InvestmentCashFlow, ...],
) -> set[str]:
    """Require independent actual income evidence for payout calendar rows.

    Expected/provider rows are never converted into ``ExternalFlow``.  A
    calendar row is considered reconciled only by one valid actual event with
    the same account, holding, kind and settlement date; calendar amounts are
    not interpreted as gross or net.
    """

    expected_statement = select(ExpectedCashFlow).where(
        ExpectedCashFlow.expected_date >= start_date,
        ExpectedCashFlow.expected_date <= end_date,
        ExpectedCashFlow.flow_type.in_(_CALENDAR_PAYOUT_FLOW_TYPES),
    )
    provider_statement = select(AppliedProviderPayout).where(
        AppliedProviderPayout.payment_date >= start_date,
        AppliedProviderPayout.payment_date <= end_date,
        AppliedProviderPayout.event_kind.in_(_CALENDAR_PAYOUT_FLOW_TYPES),
        AppliedProviderPayout.lifecycle == "active",
    )
    if scope is PerformanceScope.ACCOUNT:
        assert account_id is not None
        expected_statement = expected_statement.where(ExpectedCashFlow.account_id == account_id)
        provider_statement = provider_statement.where(
            AppliedProviderPayout.account_id == account_id
        )

    actual_by_key: dict[tuple[int, int | None, str, date, str], list[InvestmentCashFlow]] = (
        defaultdict(list)
    )
    for row in actual_income_rows:
        if not _valid_income_evidence(row):
            continue
        actual_by_key[
            (
                row.account_id,
                row.instrument_id,
                row.flow_type,
                row.event_date,
                _normalise_currency(row.currency),
            )
        ].append(row)

    reasons: set[str] = set()
    for row in session.scalars(
        expected_statement.order_by(ExpectedCashFlow.expected_date, ExpectedCashFlow.id)
    ):
        if scope is PerformanceScope.PORTFOLIO:
            membership = _membership_at(rows_by_account.get(row.account_id, []), row.expected_date)
            if membership is False:
                continue
        actuals = actual_by_key.get(
            (
                row.account_id,
                row.instrument_id,
                row.flow_type,
                row.expected_date,
                _normalise_currency(row.currency),
            ),
            [],
        )
        if len(actuals) != 1:
            reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)

    for row in session.scalars(
        provider_statement.order_by(AppliedProviderPayout.payment_date, AppliedProviderPayout.id)
    ):
        if scope is PerformanceScope.PORTFOLIO:
            membership = _membership_at(rows_by_account.get(row.account_id, []), row.payment_date)
            if membership is False:
                continue
        actuals = actual_by_key.get(
            (
                row.account_id,
                row.instrument_id,
                row.event_kind,
                row.payment_date,
                _normalise_currency(row.currency),
            ),
            [],
        )
        if len(actuals) != 1:
            reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
    return reasons


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
        # Validate flow-level scope_membership against effective membership before
        # deciding relevance: a contradiction must fail closed even when the
        # classifier would otherwise report NOT_IN_SCOPE (e.g. stable_out_of_scope
        # while effective membership is true).
        membership = _safe_scope_membership(flow.scope_membership)
        stable_contradiction: set[str] = set()
        if (
            membership is not ExternalFlowScopeMembership.UNKNOWN
            and flow.account_id in rows_by_account
        ):
            effective = _membership_at(rows_by_account.get(flow.account_id, []), flow.event_date)
            if membership is ExternalFlowScopeMembership.STABLE_IN_SCOPE and effective is not True:
                stable_contradiction.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
            elif (
                membership is ExternalFlowScopeMembership.STABLE_OUT_OF_SCOPE
                and effective is not False
            ):
                stable_contradiction.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

        # Skip flows that are not in scope only when there is no stable
        # membership contradiction to report; otherwise the inconsistency itself
        # must make the interval fail closed. UNKNOWN remains non-authoritative
        # only when the flow is otherwise relevant.
        if not _flow_is_relevant(classification) and not stable_contradiction:
            continue

        flow_reasons = set(flow_reasons)
        if membership is ExternalFlowScopeMembership.UNKNOWN:
            flow_reasons.add(AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)
        flow_reasons.update(stable_contradiction)
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

    investment_rows = _selected_investment_cash_flows(
        session,
        scope=scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
        flow_types=(
            _LEGACY_BOUNDARY_FLOW_TYPES
            + _RECONCILIATION_COST_FLOW_TYPES
            + _REALIZED_INCOME_FLOW_TYPES
        ),
    )
    legacy_ids = _legacy_flow_ids(
        investment_rows=investment_rows,
        external_flows=tuple(evidence),
    )
    if legacy_ids:
        reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)

    actual_income_rows = tuple(
        row for row in investment_rows if row.flow_type in _REALIZED_INCOME_FLOW_TYPES
    )
    reasons.update(
        _direct_payout_reason_codes(
            external_flows=tuple(evidence),
            income_rows=actual_income_rows,
        )
    )
    reasons.update(
        _calendar_payout_reason_codes(
            session,
            scope=scope,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            rows_by_account=rows_by_account,
            actual_income_rows=actual_income_rows,
        )
    )

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


@dataclass(frozen=True, slots=True)
class _BoundaryTarget:
    """One explicit flow or same-date group requiring pre/post evidence."""

    boundary_group_id: int | None
    flow_ids: tuple[int, ...]
    event_date: date
    explicit_group: bool
    invalid_group_membership: bool = False


def _external_flow_boundary_targets(
    session: Session,
    *,
    flows: ExternalFlowCoverage,
    scope: PerformanceScope,
    account_id: int | None,
) -> tuple[_BoundaryTarget, ...]:
    """Resolve deterministic explicit groups without treating same-day IDs as order."""

    external_flows = [
        flow
        for flow in flows.flows
        if flow.classification
        in {
            ExternalFlowClassification.EXTERNAL_CONTRIBUTION,
            ExternalFlowClassification.EXTERNAL_WITHDRAWAL,
        }
    ]
    if not external_flows:
        return ()

    external_flow_ids = {flow.id for flow in external_flows}
    group_statement = (
        select(ExternalFlowBoundaryGroup, ExternalFlowBoundaryGroupMember)
        .join(
            ExternalFlowBoundaryGroupMember,
            ExternalFlowBoundaryGroupMember.boundary_group_id == ExternalFlowBoundaryGroup.id,
        )
        .where(
            ExternalFlowBoundaryGroupMember.external_flow_id.in_(external_flow_ids),
            ExternalFlowBoundaryGroup.scope == scope.value,
        )
    )
    if scope is PerformanceScope.ACCOUNT:
        group_statement = group_statement.where(ExternalFlowBoundaryGroup.account_id == account_id)
    else:
        group_statement = group_statement.where(ExternalFlowBoundaryGroup.account_id.is_(None))
    group_rows = session.execute(
        group_statement.order_by(
            ExternalFlowBoundaryGroup.boundary_date, ExternalFlowBoundaryGroup.id
        )
    )
    groups: dict[int, ExternalFlowBoundaryGroup] = {}
    for group, _member in group_rows:
        groups[group.id] = group

    assigned_flow_ids: set[int] = set()
    targets: list[_BoundaryTarget] = []
    for group_id in sorted(
        groups,
        key=lambda candidate: (groups[candidate].boundary_date, candidate),
    ):
        group = groups[group_id]
        all_member_ids = set(
            session.scalars(
                select(ExternalFlowBoundaryGroupMember.external_flow_id).where(
                    ExternalFlowBoundaryGroupMember.boundary_group_id == group_id
                )
            )
        )
        selected_member_ids = all_member_ids & external_flow_ids
        if not selected_member_ids:
            continue
        invalid_membership = (
            group.scope != scope.value
            or group.account_id != (account_id if scope is PerformanceScope.ACCOUNT else None)
            or not all_member_ids.issubset(external_flow_ids)
        )
        targets.append(
            _BoundaryTarget(
                boundary_group_id=group_id,
                flow_ids=tuple(sorted(all_member_ids)),
                event_date=group.boundary_date,
                explicit_group=True,
                invalid_group_membership=invalid_membership,
            )
        )
        assigned_flow_ids.update(selected_member_ids)

    flow_by_id = {flow.id: flow for flow in external_flows}
    for flow_id in sorted(external_flow_ids - assigned_flow_ids):
        flow = flow_by_id[flow_id]
        targets.append(
            _BoundaryTarget(
                boundary_group_id=None,
                flow_ids=(flow_id,),
                event_date=flow.event_date,
                explicit_group=False,
            )
        )

    return tuple(
        sorted(
            targets,
            key=lambda target: (
                target.event_date,
                target.boundary_group_id is None,
                target.boundary_group_id or target.flow_ids[0],
            ),
        )
    )


def _observed_points_for_target(
    session: Session,
    *,
    target: _BoundaryTarget,
    scope: PerformanceScope,
    account_id: int | None,
) -> list[ObservedValuationPoint]:
    statement = select(ObservedValuationPoint).where(
        ObservedValuationPoint.scope == scope.value,
    )
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
    return list(
        session.scalars(
            statement.order_by(
                ObservedValuationPoint.relation,
                ObservedValuationPoint.observed_date,
                ObservedValuationPoint.id,
            )
        )
    )


def _observed_boundary_for_target(
    session: Session,
    *,
    target: _BoundaryTarget,
    scope: PerformanceScope,
    account_id: int | None,
    performance_currency: str,
    boundary_cache: dict[date, ValuationBoundaryEvidence],
) -> ExternalFlowBoundaryEvidence:
    rows = _observed_points_for_target(
        session,
        target=target,
        scope=scope,
        account_id=account_id,
    )
    reasons: set[str] = set()
    pre_rows = [
        row for row in rows if row.relation == ValuationBoundaryRelation.PRE_EXTERNAL_FLOW.value
    ]
    post_rows = [
        row for row in rows if row.relation == ValuationBoundaryRelation.POST_EXTERNAL_FLOW.value
    ]

    pre: ObservedValuationEvidence | None = None
    post: ObservedValuationEvidence | None = None
    pre_ambiguous = len(pre_rows) > 1
    post_ambiguous = len(post_rows) > 1
    if len(pre_rows) == 1:
        pre = to_observed_valuation_evidence(pre_rows[0])
    elif pre_ambiguous:
        reasons.add(_TWRR_ONLY_REASON)
    if len(post_rows) == 1:
        post = to_observed_valuation_evidence(post_rows[0])
    elif post_ambiguous:
        reasons.add(_TWRR_ONLY_REASON)

    if target.invalid_group_membership:
        reasons.add(_TWRR_ONLY_REASON)

    for evidence in (pre, post):
        if evidence is None:
            continue
        if evidence.observed_date != target.event_date:
            reasons.add(_TWRR_ONLY_REASON)
        if evidence.performance_currency != performance_currency:
            reasons.add(AvailabilityReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)
        if evidence.coverage is not CoverageStatus.COMPLETE:
            reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
        if evidence.quality is not ValuationQuality.EXACT:
            reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)

    if not rows:
        derived = _boundary_point_for_date(
            session,
            observed_date=target.event_date,
            scope=scope,
            account_id=account_id,
            cache=boundary_cache,
        )
        if derived.point is not None and derived.point.status is ValuationPointStatus.AVAILABLE:
            # A monthly/date-only observation on the flow date does not prove
            # whether it is pre- or post-flow under the accepted contract.
            reasons.add(_TWRR_ONLY_REASON)
        else:
            reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)
            reasons.update(derived.reason_codes)
    elif (pre is None and not pre_ambiguous) or (post is None and not post_ambiguous):
        reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)

    return ExternalFlowBoundaryEvidence(
        boundary_group_id=target.boundary_group_id,
        flow_ids=target.flow_ids,
        event_date=target.event_date,
        pre_external_flow=pre,
        post_external_flow=post,
        reason_codes=tuple(sorted(reasons)),
    )


def _twrr_boundary_reasons(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    flows: ExternalFlowCoverage,
    performance_currency: str,
    boundary_cache: dict[date, ValuationBoundaryEvidence],
    targets: tuple[_BoundaryTarget, ...] | None = None,
) -> tuple[tuple[ExternalFlowBoundaryEvidence, ...], set[str]]:
    if targets is None:
        targets = _external_flow_boundary_targets(
            session,
            flows=flows,
            scope=scope,
            account_id=account_id,
        )
    evidence = [
        _observed_boundary_for_target(
            session,
            target=target,
            scope=scope,
            account_id=account_id,
            performance_currency=performance_currency,
            boundary_cache=boundary_cache,
        )
        for target in targets
    ]

    # A same-date group is deterministic only when it is the sole boundary
    # target for that selected scope.  A leftover standalone flow, a second
    # group, or duplicated/corrupt group membership leaves inter-boundary
    # ordering unproven; IDs and query order are not financial evidence.
    same_day_target_counts: dict[date, int] = defaultdict(int)
    for target in targets:
        same_day_target_counts[target.event_date] += 1
    reasons: set[str] = set()
    for target_evidence in evidence:
        if same_day_target_counts[target_evidence.event_date] > 1:
            reasons.add(_TWRR_ONLY_REASON)
        reasons.update(target_evidence.reason_codes)
    return tuple(evidence), reasons


def _normalise_currency(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper()


def _transfer_reconciliation_complete(
    *,
    source: ExternalFlow,
    destination: ExternalFlow,
    evidence: tuple[ExternalTransferReconciliationEvidence, ...],
) -> bool:
    """Check only exact, explicitly transfer-bound evidence.

    Same-currency legs reconcile by exact minor-unit arithmetic.  For a
    currency-changing transfer, an explicit FX explanation is sufficient for
    this reconciliation check, while the normal performance-currency gate
    remains authoritative for metric availability.
    """

    source_currency = _normalise_currency(source.currency)
    destination_currency = _normalise_currency(destination.currency)
    kinds = {
        "internal_fee",
        "internal_commission",
        "internal_tax",
        "fx_conversion_spread",
    }
    accepted = tuple(item for item in evidence if item.kind in kinds)
    if source_currency != destination_currency:
        return any(item.kind == "fx_conversion_spread" for item in accepted)

    if destination.boundary_amount_kopecks > source.boundary_amount_kopecks:
        return False
    expected_difference = source.boundary_amount_kopecks - destination.boundary_amount_kopecks
    if expected_difference == 0:
        return True
    return (
        all(_normalise_currency(item.currency) == source_currency for item in accepted)
        and sum(item.amount_kopecks for item in accepted) == expected_difference
    )


def _portfolio_transfer_safety(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    xirr_required_dates: set[date],
    twrr_required_dates: set[date],
    rows_by_account: dict[int, list[AccountPerformanceScopeMembership]],
) -> tuple[set[str], set[str], set[str]]:
    """Return (shared, xirr-only, twrr-only) transfer availability reasons.

    The query intentionally loads links independently of the requested flow
    interval.  A transfer is relevant when a leg is in the interval or its
    transit intersects a valuation consumed by the selected metric.
    """

    if not xirr_required_dates and not twrr_required_dates:
        return set(), set(), set()

    rows = list(
        session.scalars(
            select(ExternalFlow)
            .where(ExternalFlow.transfer_link_id.is_not(None))
            .order_by(ExternalFlow.transfer_link_id, ExternalFlow.id)
        )
    )
    legs_by_link: dict[int, list[ExternalFlow]] = defaultdict(list)
    for row in rows:
        assert row.transfer_link_id is not None
        legs_by_link[row.transfer_link_id].append(row)

    shared_reasons: set[str] = set()
    xirr_reasons: set[str] = set()
    twrr_reasons: set[str] = set()
    evidence_by_link = iter_transfer_reconciliation_evidence(session, legs_by_link)
    for link_id, legs in legs_by_link.items():
        if len(legs) != 2:
            continue
        first, second = legs
        if first.account_id == second.account_id or first.direction == second.direction:
            continue

        source = next(leg for leg in legs if leg.direction == "withdrawal")
        destination = next(leg for leg in legs if leg.direction == "contribution")
        transit_dates: set[date] = set()
        if source.event_date < destination.event_date:
            transit_dates = {
                candidate
                for candidate in xirr_required_dates | twrr_required_dates
                if source.event_date <= candidate <= destination.event_date
            }

        leg_in_interval = any(start_date <= leg.event_date <= end_date for leg in legs)
        if not leg_in_interval and not transit_dates:
            continue

        # Legs outside the requested interval can still make a transfer
        # transit-relevant.  Reuse H2a's effective-dated cross-check for those
        # legs because interval flow coverage does not inspect them.
        if transit_dates:
            for leg in legs:
                if start_date <= leg.event_date <= end_date:
                    continue
                membership = _safe_scope_membership(leg.scope_membership)
                if membership is ExternalFlowScopeMembership.UNKNOWN:
                    shared_reasons.add(
                        AvailabilityReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value
                    )
                    continue
                if leg.account_id not in rows_by_account:
                    continue
                effective = _membership_at(rows_by_account[leg.account_id], leg.event_date)
                if (
                    membership is ExternalFlowScopeMembership.STABLE_IN_SCOPE
                    and effective is not True
                ):
                    shared_reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)
                elif (
                    membership is ExternalFlowScopeMembership.STABLE_OUT_OF_SCOPE
                    and effective is not False
                ):
                    shared_reasons.add(AvailabilityReasonCode.SCOPE_COVERAGE_INCOMPLETE.value)

        classifications = [
            classify_external_flow(
                session,
                leg.id,
                scope=ExternalFlowScope.PORTFOLIO,
            )
            for leg in legs
        ]
        if any(
            classification is not ExternalFlowClassification.INTERNAL_TRANSFER
            for classification in classifications
        ):
            continue

        if not _transfer_reconciliation_complete(
            source=source,
            destination=destination,
            evidence=evidence_by_link.get(link_id, ()),
        ):
            shared_reasons.add(AvailabilityReasonCode.TRANSFER_RECONCILIATION_INCOMPLETE.value)

        if transit_dates:
            if transit_dates & xirr_required_dates:
                xirr_reasons.add(AvailabilityReasonCode.TRANSFER_IN_TRANSIT_UNVALUED.value)
            if transit_dates & twrr_required_dates:
                twrr_reasons.add(AvailabilityReasonCode.TRANSFER_IN_TRANSIT_UNVALUED.value)

    return shared_reasons, xirr_reasons, twrr_reasons


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
    cash_boundary_coverage = cash_boundary_coverage_for_interval(
        session,
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
    )
    in_kind_boundary_coverage = in_kind_boundary_coverage_for_interval(
        session,
        scope=normalized_scope,
        account_id=account_id,
        start_date=start_date,
        end_date=end_date,
        rows_by_account=rows_by_account,
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
    xirr_reasons.update(cash_boundary_coverage.reason_codes)
    xirr_reasons.update(in_kind_boundary_coverage.reason_codes)
    xirr_reasons.update(opening.reason_codes)
    xirr_reasons.update(closing.reason_codes)
    xirr_reasons.update(flows.reason_codes)
    # Date-only boundary ordering is a TWRR-only limitation under #145 v2.
    xirr_reasons.discard(_TWRR_ONLY_REASON)

    twrr_targets: tuple[_BoundaryTarget, ...] | None = None
    if normalized_scope is PerformanceScope.PORTFOLIO:
        twrr_targets = _external_flow_boundary_targets(
            session,
            flows=flows,
            scope=normalized_scope,
            account_id=account_id,
        )
    shared_transfer_reasons: set[str] = set()
    xirr_transfer_reasons: set[str] = set()
    twrr_transfer_reasons: set[str] = set()
    if normalized_scope is PerformanceScope.PORTFOLIO:
        (
            shared_transfer_reasons,
            xirr_transfer_reasons,
            twrr_transfer_reasons,
        ) = _portfolio_transfer_safety(
            session,
            start_date=start_date,
            end_date=end_date,
            xirr_required_dates={start_date, end_date},
            twrr_required_dates={
                start_date,
                end_date,
                *((target.event_date for target in twrr_targets) if twrr_targets else ()),
            },
            rows_by_account=rows_by_account,
        )
    xirr_reasons.update(shared_transfer_reasons)
    xirr_reasons.update(xirr_transfer_reasons)

    xirr = _metric("xirr", xirr_reasons)
    twrr_reasons = set(xirr_reasons)
    external_flow_boundaries, boundary_reasons = _twrr_boundary_reasons(
        session,
        scope=normalized_scope,
        account_id=account_id,
        flows=flows,
        performance_currency=performance_currency,
        boundary_cache=boundary_cache,
        targets=twrr_targets,
    )
    twrr_reasons.update(boundary_reasons)
    twrr_reasons.update(shared_transfer_reasons)
    twrr_reasons.update(twrr_transfer_reasons)
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
        cash_boundary_coverage=cash_boundary_coverage,
        in_kind_boundary_coverage=in_kind_boundary_coverage,
        external_flows=flows,
        external_flow_boundaries=external_flow_boundaries,
        xirr=xirr,
        twrr=twrr,
    )


# Public aliases keep the interval wording discoverable for downstream tasks.
get_performance_availability = performance_availability_for_interval
build_performance_availability = performance_availability_for_interval
