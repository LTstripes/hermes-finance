"""Compose a monthly capital bridge from existing scoped read models.

No persistence, new return kernel, inferred transfer pairing or source acceptance.
Explained components are known subtotals; missing facts stay in unexplained.
"""

import logging
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from hermes_finance.database import (
    DatabaseMaintenanceError,
    ReadSnapshotCleanupError,
    ReadSnapshotMutationError,
    coherent_read_operation,
    snapshot_read_result,
)
from hermes_finance.domain.liquid_capital import LiquidCapitalResult
from hermes_finance.domain.monthly_summary import (
    CapitalChangeHint,
    CapitalChangeItem,
    MonthlyCapitalChange,
    capital_change_component,
    explain_capital_change,
    explain_capital_flow,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    CashBalance,
    Debt,
    ExternalFlow,
    HistoricalOwnerFlow,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.cash_balance import cash_balance_for_month
from hermes_finance.services.external_flows import classify_external_flow
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.portfolio_source_coverage import portfolio_source_coverage_for_months
from hermes_finance.services.returns_account_link import account_link
from hermes_finance.services.returns_view import _source_scopes
from hermes_finance.services.source_monthly_returns import (
    read_monthly_result,
    source_read_snapshot,
)

_LOG = logging.getLogger(__name__)


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
            row = read_monthly_result(
                session,
                source_account=native,
                opening_date=previous.snapshot_date,
                closing_date=current.snapshot_date,
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


def _investment_unavailable_hint(row, before, after):
    """Explain independent blockers together without relaxing the eligibility gates."""
    if row is None:
        return "Нужна выписка с оценками счёта на обе границы месяца."
    hints = []
    if row.opening_kopecks is None or row.closing_kopecks is None:
        hints.append("В выписках не подтверждены оценки счёта на обе границы месяца")
    if before is None or after is None:
        hints.append("В капитале нет оценки счёта на обе границы месяца")
    if {
        "4_Transfers_unsupported",
        "5_UFSR_unsupported",
        "unparsed_source_rows",
    }.intersection(row.reason_codes):
        hints.append(
            "проверьте неподдержанные разделы выписок, одной классификации денег недостаточно"
        )
    elif (
        row.contributions_kopecks is None
        or row.withdrawals_kopecks is None
        or (
            row.growth_kopecks is None
            and row.opening_kopecks is not None
            and row.closing_kopecks is not None
        )
    ):
        hints.append("проверьте денежные движения и полноту выписок в «Доходности»")
    if row.assumptions_used:
        hints.append("есть предположения о потоках или расчёт только по источнику")
    return "; ".join(hints) + "." if hints else None


def _investment_market_change(session, accounts, current, previous, liquid, previous_liquid):
    """Account value change after known funding, less payouts already in Month flow.

    A missing account never poisons a separately proven account contribution.
    Assumed funding is insufficient for this explanation even if Returns exposes
    a provisional estimate. Deposits are entirely represented by monthly flow.
    """
    before = _account_values(session, previous.id, previous_liquid)
    after = _account_values(session, current.id, liquid)
    income = passive_income_for_month(session, current.id)
    items = []
    valuation_items = []
    with source_read_snapshot(session):
        canonical = _source_scopes(session)
        linked = {}
        for native in sorted(set(canonical.values())):
            link = account_link(session, native, canonical)
            if link["status"] == "linked":
                linked.setdefault(link["financial_account_id"], []).append(native)
        for account in accounts:
            if not account.include_in_capital or account.account_type not in {"brokerage", "iis"}:
                continue
            amount = None
            valuation_difference = None
            reasons = ()
            hint = None
            source_reasons = ()
            natives = linked.get(account.id, [])
            if len(natives) != 1:
                reasons = ("capital_investment_account_result_unavailable",)
                hint = "Проверьте однозначную связь счёта с его выписками в настройках источников."
            else:
                row = read_monthly_result(
                    session,
                    source_account=natives[0],
                    opening_date=previous.snapshot_date,
                    closing_date=current.snapshot_date,
                )
                source_reasons = row.reason_codes if row is not None else ()
                if (
                    row is None
                    or row.opening_kopecks is None
                    or row.closing_kopecks is None
                    or before.get(account.id) is None
                    or after.get(account.id) is None
                ):
                    reasons = ("capital_investment_endpoints_unproven",)
                elif (
                    row.growth_kopecks is None
                    or row.contributions_kopecks is None
                    or row.withdrawals_kopecks is None
                    or row.assumptions_used
                ):
                    reasons = ("capital_investment_flows_unproven",)
                else:
                    payouts_in_flow = sum(
                        source.amount.kopecks
                        for source in income.sources
                        if source.source_type == "investment_cash_flow"
                        and source.account_id == account.id
                    )
                    amount = RubleAmount(row.growth_kopecks - payouts_in_flow)
                    valuation_difference = RubleAmount(
                        (row.opening_kopecks - before[account.id])
                        - (row.closing_kopecks - after[account.id])
                    )
                    if row.approximate:
                        reasons = ("capital_investment_source_estimate",)
                if amount is None:
                    hint = _investment_unavailable_hint(
                        row, before.get(account.id), after.get(account.id)
                    )
            items.append(CapitalChangeItem(account.id, None, amount, reasons, hint, source_reasons))
            valuation_items.append(
                CapitalChangeItem(
                    account.id, None, valuation_difference, reasons, hint, source_reasons
                )
            )
    return capital_change_component(tuple(items)), capital_change_component(tuple(valuation_items))


def _gold_revaluation(session, accounts, current, previous):
    """Match physical gold by account/instrument, never by name or total weight.

    Gold held inside brokerage/IIS is already within that account's result.
    Quantity changes have no accepted transaction-history adapter here.
    """
    account_ids = [
        account.id
        for account in accounts
        if account.include_in_capital and account.account_type not in {"brokerage", "iis"}
    ]
    endpoints = {previous.id: {}, current.id: {}}
    gold_keys = set()
    for position, instrument in session.execute(
        select(PositionSnapshot, Instrument)
        .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
        .where(
            PositionSnapshot.reporting_month_id.in_(endpoints),
            PositionSnapshot.account_id.in_(account_ids),
        )
    ):
        kind = position.historical_instrument_type or instrument.instrument_type
        key = (position.account_id, position.instrument_id)
        endpoints[position.reporting_month_id][key] = (position, kind, instrument.currency)
        if kind == "gold":
            gold_keys.add(key)
    items = []
    for account_id, instrument_id in sorted(gold_keys):
        key = (account_id, instrument_id)
        before = endpoints[previous.id].get(key)
        after = endpoints[current.id].get(key)
        amount = None
        reasons = ()
        if before is None or after is None:
            reasons = ("capital_gold_endpoints_unproven",)
        elif before[1:] != ("gold", "RUB") or after[1:] != ("gold", "RUB"):
            reasons = ("capital_gold_scope_unproven",)
        elif (
            before[0].market_value_kopecks is None
            or after[0].market_value_kopecks is None
            or before[0].price_date > previous.snapshot_date
            or after[0].price_date > current.snapshot_date
        ):
            reasons = ("capital_gold_endpoints_unproven",)
        elif before[0].quantity != after[0].quantity:
            reasons = ("capital_gold_quantity_changed_history_unproven",)
        else:
            amount = RubleAmount(after[0].market_value_kopecks - before[0].market_value_kopecks)
        items.append(CapitalChangeItem(account_id, instrument_id, amount, reasons))
    return capital_change_component(tuple(items))


def _context_hints(session, current, previous, expenses):
    def card_debt(month_id):
        return session.scalar(
            select(func.coalesce(func.sum(Debt.current_balance_kopecks), 0)).where(
                Debt.reporting_month_id == month_id,
                Debt.debt_type == "credit_card",
                Debt.include_in_liquid_capital.is_(True),
            )
        )

    growth = card_debt(current.id) - card_debt(previous.id)
    # Exact kopeck comparison: no hidden materiality threshold or spending inference.
    return (CapitalChangeHint(RubleAmount(growth), expenses),) if growth > expenses.kopecks else ()


@coherent_read_operation
def monthly_capital_change(
    session: Session,
    *,
    current: ReportingMonth,
    previous: ReportingMonth | None,
    liquid: LiquidCapitalResult,
    previous_liquid: LiquidCapitalResult | None,
) -> MonthlyCapitalChange | None:
    """Keep this optional explanation from breaking established financial reads."""
    try:
        return snapshot_read_result(
            session,
            "monthly_capital_change",
            (current.id, previous.id if previous else None, repr(liquid), repr(previous_liquid)),
            lambda: _monthly_capital_change(
                session,
                current=current,
                previous=previous,
                liquid=liquid,
                previous_liquid=previous_liquid,
            ),
        )
    except (
        DatabaseMaintenanceError,
        ReadSnapshotCleanupError,
        ReadSnapshotMutationError,
        SQLAlchemyError,
    ):
        # A failed database/read-only boundary must never look like a valid read.
        raise
    except Exception as error:
        # Do not expose source payloads or exception text in logs/API responses.
        # NULL means unavailable; zero/partial operands would invent an explanation.
        _LOG.warning("Capital-change explanation unavailable (%s)", type(error).__name__)
        return None


def _monthly_capital_change(
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
    flow_breakdown = None
    context_hints = ()
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
            cash = cash_balance_for_month(session, current.id)
            market, valuation_difference = _investment_market_change(
                session, accounts, current, previous, liquid, previous_liquid
            )
            flow_breakdown = explain_capital_flow(
                start=previous_liquid.liquid_capital_net,
                end=liquid.liquid_capital_net,
                monthly_flow=RubleAmount(
                    cash.total.kopecks + cash.breakdown.saving_allocations.kopecks
                ),
                investment_market_change=market,
                investment_valuation_difference=valuation_difference,
                physical_gold_revaluation=_gold_revaluation(session, accounts, current, previous),
            )
            context_hints = _context_hints(
                session,
                current,
                previous,
                RubleAmount(
                    cash.breakdown.mandatory_expenses.kopecks
                    + cash.breakdown.other_expenses.kopecks
                ),
            )
    return MonthlyCapitalChange(
        reporting_month_id=current.id,
        previous_reporting_month_id=previous.id if previous else None,
        period_start=start,
        period_end=end,
        breakdown=breakdown,
        reason_codes=tuple(sorted(reasons)),
        flow_breakdown=flow_breakdown,
        context_hints=context_hints,
    )
