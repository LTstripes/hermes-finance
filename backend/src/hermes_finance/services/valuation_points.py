"""Read-only valuation-point assembly for R08-01B.

The service promotes existing persisted monthly valuations into a strict
performance boundary. It does not refresh providers, write defaults, infer
cash ownership, or calculate a return metric.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from hermes_finance.domain import (
    ComponentStatus,
    CoverageStatus,
    ExternalFlowClassification,
    ExternalFlowScope,
    ExternalFlowScopeMembership,
    PerformanceScope,
    RubleAmount,
    ValuationComponent,
    ValuationPoint,
    ValuationProvenance,
    ValuationQuality,
    ValuationReasonCode,
    build_valuation_point,
)
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    DEFAULT_BASE_CURRENCY,
    Account,
    AccountPerformanceScopeMembership,
    AppSettings,
    CashBalance,
    DepositSnapshot,
    ExternalFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.external_flows import classify_external_flow
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


def _coerce_scope(scope: PerformanceScope | str) -> PerformanceScope:
    try:
        return PerformanceScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported performance scope: {scope!r}") from error


def _valid_amount(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _component(
    name: str,
    *,
    status: ComponentStatus,
    amount: int | None,
    source_kind: str,
    source_ids: list[int] | tuple[int, ...] = (),
    reason_codes: tuple[str, ...] = (),
) -> ValuationComponent:
    return ValuationComponent(
        name=name,
        status=status,
        amount=RubleAmount(amount) if amount is not None else None,
        source_kind=source_kind,
        source_ids=tuple(sorted(source_ids)),
        reason_codes=reason_codes,
    )


def _provenance(
    source_kind: str,
    source_ids: list[int] | tuple[int, ...],
    observed_date: date | None,
) -> ValuationProvenance:
    return ValuationProvenance(
        source_kind=source_kind,
        source_ids=tuple(sorted(source_ids)),
        observed_date=observed_date,
        quality=ValuationQuality.EXACT,
    )


def _selected_accounts(
    session: Session,
    *,
    scope: PerformanceScope,
    account_id: int | None,
    valuation_date: date | None,
) -> tuple[list[Account], tuple[int, ...], tuple[str, ...]]:
    def membership_rows(account: Account) -> list[AccountPerformanceScopeMembership]:
        if valuation_date is None:
            return []
        return list(
            session.scalars(
                select(AccountPerformanceScopeMembership)
                .where(
                    AccountPerformanceScopeMembership.account_id == account.id,
                    AccountPerformanceScopeMembership.effective_from <= valuation_date,
                    or_(
                        AccountPerformanceScopeMembership.effective_to.is_(None),
                        AccountPerformanceScopeMembership.effective_to >= valuation_date,
                    ),
                )
                .order_by(
                    AccountPerformanceScopeMembership.effective_from,
                    AccountPerformanceScopeMembership.id,
                )
            )
        )

    if scope is PerformanceScope.ACCOUNT:
        if account_id is None:
            raise ValueError("account_id is required for account performance scope")
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f"account {account_id} was not found")
        rows = membership_rows(account)
        if len(rows) != 1:
            return [account], (account.id,), ()
        if not rows[0].include_in_returns:
            return [account], (), (ValuationReasonCode.SCOPE_COVERAGE_INCOMPLETE.value,)
        return [account], (), ()

    accounts = list(session.scalars(select(Account).order_by(Account.id)))
    selected: list[Account] = []
    unknown_membership_ids: list[int] = []
    for account in accounts:
        rows = membership_rows(account)
        if len(rows) != 1:
            unknown_membership_ids.append(account.id)
        elif rows[0].include_in_returns:
            selected.append(account)
    return selected, tuple(unknown_membership_ids), ()


def _scope_membership_coverage(
    session: Session,
    *,
    month_id: int,
    scope: PerformanceScope,
    account_id: int | None,
    valuation_date: date | None,
    performance_currency: str,
) -> tuple[CoverageStatus, tuple[str, ...]]:
    """Report flow/scope evidence without changing the valuation total."""

    if valuation_date is None:
        return (
            CoverageStatus.UNKNOWN,
            (ValuationReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value,),
        )
    flows = list(
        session.scalars(
            select(ExternalFlow)
            .where(
                ExternalFlow.reporting_month_id == month_id,
                ExternalFlow.event_date <= valuation_date,
            )
            .order_by(ExternalFlow.event_date, ExternalFlow.id)
        )
    )
    reasons_unknown: set[str] = set()
    reasons_unavailable: set[str] = set()
    relevant_flow_seen = False
    normalized_scope = (
        ExternalFlowScope.ACCOUNT
        if scope is PerformanceScope.ACCOUNT
        else ExternalFlowScope.PORTFOLIO
    )
    for flow in flows:
        classification = classify_external_flow(
            session,
            flow.id,
            scope=normalized_scope,
            account_id=account_id,
        )
        if classification is ExternalFlowClassification.NOT_IN_SCOPE:
            continue
        relevant_flow_seen = True
        if flow.scope_membership == ExternalFlowScopeMembership.UNKNOWN.value:
            reasons_unknown.add(ValuationReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)
        if classification is ExternalFlowClassification.NOT_AUTHORITATIVE:
            reasons_unknown.add(ValuationReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value)
        if classification is ExternalFlowClassification.UNRESOLVED:
            reasons_unavailable.add(ValuationReasonCode.TRANSFER_IDENTITY_UNRESOLVED.value)
        if flow.currency.strip().upper() != performance_currency:
            reasons_unavailable.add(ValuationReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)
        if flow.event_date == valuation_date:
            reasons_unknown.add(ValuationReasonCode.VALUATION_BOUNDARY_ORDER_UNKNOWN.value)

    if reasons_unavailable:
        return CoverageStatus.UNAVAILABLE, tuple(sorted(reasons_unavailable | reasons_unknown))
    if relevant_flow_seen and reasons_unknown:
        return CoverageStatus.UNKNOWN, tuple(sorted(reasons_unknown))
    return CoverageStatus.COMPLETE, ()


def valuation_point_for_month(
    session: Session,
    reporting_month_id: int,
    *,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> ValuationPoint:
    """Return one strict, derived valuation point for a reporting month."""

    normalized_scope = _coerce_scope(scope)
    month = session.get(ReportingMonth, reporting_month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

    settings = session.get(AppSettings, APP_SETTINGS_ID)
    performance_currency = (
        settings.base_currency.strip().upper() if settings is not None else DEFAULT_BASE_CURRENCY
    )
    selected_accounts, unknown_membership_ids, scope_reasons = _selected_accounts(
        session,
        scope=normalized_scope,
        account_id=account_id,
        valuation_date=month.snapshot_date,
    )
    selected_account_ids = {account.id for account in selected_accounts}
    components: list[ValuationComponent] = []
    provenance: list[ValuationProvenance] = []
    extra_reasons = set(scope_reasons)

    if unknown_membership_ids:
        components.append(
            _component(
                "scope_membership_history",
                status=ComponentStatus.UNKNOWN,
                amount=None,
                source_kind="account_performance_scope_membership",
                source_ids=unknown_membership_ids,
                reason_codes=(ValuationReasonCode.SCOPE_MEMBERSHIP_HISTORY_MISSING.value,),
            )
        )

    if month.status != "closed":
        extra_reasons.add(ValuationReasonCode.REPORTING_MONTH_NOT_CLOSED.value)
    if month.snapshot_date is None:
        extra_reasons.add(ValuationReasonCode.SNAPSHOT_DATE_MISSING.value)
    if performance_currency != DEFAULT_BASE_CURRENCY:
        extra_reasons.add(ValuationReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)

    positions = list(
        session.scalars(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.reporting_month_id == reporting_month_id,
                PositionSnapshot.account_id.in_(selected_account_ids),
            )
            .order_by(PositionSnapshot.account_id, PositionSnapshot.id)
        )
    )
    position_ids = [row.id for row in positions]
    invalid_positions = [row.id for row in positions if not _valid_amount(row.market_value_kopecks)]
    if positions:
        components.append(
            _component(
                "positions",
                status=(
                    ComponentStatus.UNAVAILABLE
                    if invalid_positions
                    else ComponentStatus.AUTHORITATIVE
                ),
                amount=(
                    None
                    if invalid_positions
                    else sum(row.market_value_kopecks for row in positions)
                ),
                source_kind="position_snapshot",
                source_ids=position_ids,
                reason_codes=(
                    (ValuationReasonCode.UNSUPPORTED_POSITION_VALUATION.value,)
                    if invalid_positions
                    else ()
                ),
            )
        )
        provenance.append(_provenance("position_snapshot", position_ids, month.snapshot_date))

    deposits = list(
        session.scalars(
            select(DepositSnapshot)
            .where(
                DepositSnapshot.reporting_month_id == reporting_month_id,
                DepositSnapshot.account_id.in_(selected_account_ids),
            )
            .order_by(DepositSnapshot.account_id, DepositSnapshot.id)
        )
    )
    deposit_ids = [row.id for row in deposits]
    invalid_deposits = [row.id for row in deposits if not _valid_amount(row.balance_kopecks)]
    if deposits:
        components.append(
            _component(
                "deposits",
                status=(
                    ComponentStatus.UNAVAILABLE
                    if invalid_deposits
                    else ComponentStatus.AUTHORITATIVE
                ),
                amount=(None if invalid_deposits else sum(row.balance_kopecks for row in deposits)),
                source_kind="deposit_snapshot",
                source_ids=deposit_ids,
                reason_codes=(
                    (ValuationReasonCode.UNSUPPORTED_POSITION_VALUATION.value,)
                    if invalid_deposits
                    else ()
                ),
            )
        )
        provenance.append(_provenance("deposit_snapshot", deposit_ids, month.snapshot_date))

    cash_rows = list(
        session.scalars(
            select(CashBalance)
            .where(CashBalance.reporting_month_id == reporting_month_id)
            .order_by(CashBalance.id)
        )
    )
    relevant_cash = [
        row for row in cash_rows if row.account_id is None or row.account_id in selected_account_ids
    ]
    cash_ids = [row.id for row in relevant_cash]
    unclassified_cash = [row.id for row in relevant_cash if row.account_id is None]
    invalid_cash = [row.id for row in relevant_cash if not _valid_amount(row.amount_kopecks)]
    non_base_cash = [
        row.id
        for row in relevant_cash
        if not isinstance(row.currency, str) or row.currency.strip().upper() != performance_currency
    ]
    if relevant_cash:
        cash_reasons: set[str] = set()
        cash_status = ComponentStatus.AUTHORITATIVE
        if unclassified_cash:
            cash_status = ComponentStatus.UNKNOWN
            cash_reasons.add(ValuationReasonCode.SCOPE_CASH_UNCLASSIFIED.value)
        if invalid_cash or non_base_cash:
            cash_status = ComponentStatus.UNAVAILABLE
        if invalid_cash:
            cash_reasons.add(ValuationReasonCode.UNSUPPORTED_POSITION_VALUATION.value)
        if non_base_cash:
            cash_reasons.add(ValuationReasonCode.CURRENCY_CONVERSION_INCOMPLETE.value)
        components.append(
            _component(
                "performance_cash",
                status=cash_status,
                amount=(
                    None
                    if cash_status is not ComponentStatus.AUTHORITATIVE
                    else sum(row.amount_kopecks for row in relevant_cash)
                ),
                source_kind="cash_balance",
                source_ids=cash_ids,
                reason_codes=tuple(sorted(cash_reasons)),
            )
        )
        if cash_status is ComponentStatus.AUTHORITATIVE:
            provenance.append(_provenance("cash_balance", cash_ids, month.snapshot_date))

    account_evidence: dict[int, set[str]] = defaultdict(set)
    for row in positions:
        account_evidence[row.account_id].add("positions")
    for row in deposits:
        account_evidence[row.account_id].add("deposits")
    for row in relevant_cash:
        if row.account_id is not None:
            account_evidence[row.account_id].add("performance_cash")
    required_components = {"positions", "deposits", "performance_cash"}
    incomplete_accounts = sorted(
        account_id
        for account_id in selected_account_ids
        if account_evidence[account_id] != required_components
    )
    if incomplete_accounts:
        components.append(
            _component(
                "selected_account_coverage",
                status=ComponentStatus.UNKNOWN,
                amount=None,
                source_kind="account",
                source_ids=incomplete_accounts,
                reason_codes=(ValuationReasonCode.SCOPE_COVERAGE_INCOMPLETE.value,),
            )
        )

    membership_status, membership_reasons = _scope_membership_coverage(
        session,
        month_id=reporting_month_id,
        scope=normalized_scope,
        account_id=account_id,
        valuation_date=month.snapshot_date,
        performance_currency=performance_currency,
    )
    return build_valuation_point(
        reporting_month_id=reporting_month_id,
        scope=normalized_scope,
        account_id=account_id if normalized_scope is PerformanceScope.ACCOUNT else None,
        valuation_date=month.snapshot_date,
        performance_currency=performance_currency,
        components=components,
        provenance=provenance,
        extra_reason_codes=extra_reasons,
        scope_membership_status=membership_status,
        scope_membership_reason_codes=membership_reasons,
    )


build_valuation_point_for_month = valuation_point_for_month
