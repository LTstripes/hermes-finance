"""Compose a monthly capital bridge from existing scoped read models.

No persistence, new return kernel, inferred transfer pairing or source acceptance.
Explained components are known subtotals; missing facts stay in unexplained.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.liquid_capital import LiquidCapitalResult
from hermes_finance.domain.monthly_summary import MonthlyCapitalChange, explain_capital_change
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    CashBalance,
    ExternalFlow,
    HistoricalOwnerFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.external_flows import classify_external_flow
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.portfolio_source_coverage import portfolio_source_coverage_for_months
from hermes_finance.services.returns_account_link import account_link
from hermes_finance.services.returns_view import _source_scopes
from hermes_finance.services.source_monthly_returns import (
    read_monthly_returns,
    source_read_snapshot,
)


def _same_capital_roster(session, accounts, day):
    """Performance portfolio authority applies only to the identical capital set."""
    memberships = list(
        session.scalars(
            select(AccountPerformanceScopeMembership).where(
                AccountPerformanceScopeMembership.effective_from <= day,
                (AccountPerformanceScopeMembership.effective_to.is_(None))
                | (AccountPerformanceScopeMembership.effective_to >= day),
            )
        )
    )
    included = {account.id for account in accounts if account.include_in_capital}
    by_account = {}
    for row in memberships:
        by_account.setdefault(row.account_id, []).append(row)
    return (
        all(len(rows) == 1 for rows in by_account.values())
        and all(account_id in by_account for account_id in included)
        and {row.account_id for row in memberships if row.include_in_returns} == included
    )


def _external_net(session, accounts, start, end, reasons, month_ids):
    total = 0
    capital_ids = {account.id for account in accounts if account.include_in_capital}
    cash_accounts = session.scalars(
        select(CashBalance.account_id).where(
            CashBalance.reporting_month_id.in_(month_ids),
            CashBalance.include_in_capital.is_(True),
        )
    )
    roster_unproven = any(account_id not in capital_ids for account_id in cash_accounts)
    for flow in session.scalars(
        select(ExternalFlow).where(
            ExternalFlow.event_date >= start,
            ExternalFlow.event_date <= end,
        )
    ):
        if flow.account_id not in capital_ids:
            continue
        if (
            roster_unproven
            or flow.currency != "RUB"
            or not _same_capital_roster(session, accounts, flow.event_date)
        ):
            reasons.add("capital_external_scope_unproven")
            continue
        classification = classify_external_flow(session, flow.id, scope="portfolio")
        if classification.value == "external_contribution":
            total += flow.boundary_amount_kopecks
        elif classification.value == "external_withdrawal":
            total -= flow.boundary_amount_kopecks
        elif classification.value not in {"internal_transfer", "not_in_scope"}:
            reasons.add("capital_external_flow_unresolved")
    # Account-only broker-money facts cannot establish whole-capital funding.
    if (
        session.scalar(
            select(HistoricalOwnerFlow.id)
            .where(
                HistoricalOwnerFlow.event_date >= start,
                HistoricalOwnerFlow.event_date <= end,
            )
            .limit(1)
        )
        is not None
    ):
        reasons.add("capital_account_funding_not_portfolio_evidence")
    reasons.add("capital_external_history_completeness_unproven")
    return total


def _account_values(session, month_id, liquid):
    values = {item.account_id: item.amount.kopecks for item in liquid.accounts}
    for row in session.scalars(
        select(CashBalance).where(
            CashBalance.reporting_month_id == month_id,
            CashBalance.include_in_capital.is_(True),
        )
    ):
        if row.account_id is not None:
            values[row.account_id] = values.get(row.account_id, 0) + row.amount_kopecks
    return values


def _investment_result(session, accounts, current, previous, liquid, previous_liquid, reasons):
    included = {account.id for account in accounts if account.include_in_capital}
    # Reuse canonical deposit-interest facts, never accepted coupons in addition
    # to a source account P&L (which already contains its payouts and costs).
    income = passive_income_for_month(session, current.id)
    total = sum(
        item.amount.kopecks
        for item in income.sources
        if item.source_type == "deposit_snapshot" and item.account_id in included
    )
    before = _account_values(session, previous.id, previous_liquid)
    after = _account_values(session, current.id, liquid)
    linked = {}
    with source_read_snapshot(session):
        canonical = _source_scopes(session)
        for native in sorted(set(canonical.values())):
            link = account_link(session, native, canonical)
            if link["status"] == "linked" and link["financial_account_id"] in included:
                linked[link["financial_account_id"]] = native
        for account in accounts:
            if account.id not in included or account.account_type not in {"brokerage", "iis"}:
                continue
            native = linked.get(account.id)
            if native is None:
                reasons.add("capital_investment_account_result_unavailable")
                continue
            observed = read_monthly_returns(session, source_account=native)
            row = next(
                (
                    row.result
                    for row in observed.months
                    if (
                        row.result.opening_date == previous.snapshot_date
                        and row.result.closing_date == current.snapshot_date
                    )
                ),
                None,
            )
            if (
                row is None
                or row.growth_kopecks is None
                or row.opening_kopecks != before.get(account.id)
                or row.closing_kopecks != after.get(account.id)
            ):
                reasons.add("capital_investment_endpoints_unproven")
                continue
            total += row.growth_kopecks
            reasons.add("capital_investment_source_estimate")
    if (
        session.scalar(
            select(PositionSnapshot.id)
            .where(
                PositionSnapshot.reporting_month_id == current.id,
                PositionSnapshot.account_id.in_(
                    [
                        account.id
                        for account in accounts
                        if account.id in included
                        and account.account_type not in {"brokerage", "iis"}
                    ]
                ),
            )
            .limit(1)
        )
        is not None
    ):
        reasons.add("capital_other_investment_result_unavailable")
    return total


@coherent_read_operation
def monthly_capital_change(
    session: Session,
    *,
    current: ReportingMonth,
    previous: ReportingMonth | None,
    liquid: LiquidCapitalResult,
    previous_liquid: LiquidCapitalResult | None,
) -> MonthlyCapitalChange:
    start, end = current.period_start, current.period_end
    reasons = set()
    breakdown = None
    if previous is None or previous_liquid is None:
        reasons.add("capital_previous_month_unavailable")
    elif previous.period_end != start - timedelta(days=1):
        reasons.add("capital_calendar_gap")
    elif previous.snapshot_date != previous.period_end or current.snapshot_date != end:
        reasons.add("capital_month_end_snapshots_required")
    else:
        coverage = portfolio_source_coverage_for_months(session, [previous.id, current.id])
        if any(item.status == "unavailable" for item in coverage.values()):
            reasons.add("capital_endpoint_snapshot_unavailable")
        else:
            if any(item.status != "complete" for item in coverage.values()):
                reasons.add("capital_endpoint_coverage_partial")
            accounts = list(session.scalars(select(Account).order_by(Account.id)))
            breakdown = explain_capital_change(
                start=previous_liquid.liquid_capital_net,
                end=liquid.liquid_capital_net,
                external_net=RubleAmount(
                    _external_net(
                        session,
                        accounts,
                        start,
                        end,
                        reasons,
                        [previous.id, current.id],
                    )
                ),
                investment_result=RubleAmount(
                    _investment_result(
                        session,
                        accounts,
                        current,
                        previous,
                        liquid,
                        previous_liquid,
                        reasons,
                    )
                ),
                # Identified liability movement only. Asset changes are not
                # relabelled as 'other' to force a zero unexplained residual.
                other_changes=RubleAmount(
                    previous_liquid.total_debts_included.kopecks
                    - liquid.total_debts_included.kopecks
                ),
            )
    return MonthlyCapitalChange(
        reporting_month_id=current.id,
        previous_reporting_month_id=previous.id if previous else None,
        period_start=start,
        period_end=end,
        breakdown=breakdown,
        reason_codes=tuple(sorted(reasons)),
    )
