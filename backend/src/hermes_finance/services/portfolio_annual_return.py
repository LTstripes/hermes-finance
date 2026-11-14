"""B9 read projection from current, from-zero source-account evidence.

No receipts are re-attested here. An incomplete account blocks the selected
scope; known flows and position subtotals never stand in for complete history.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext

from sqlalchemy import select

from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr
from hermes_finance.persistence import Account
from hermes_finance.services import returns_view
from hermes_finance.services.portfolio_annual_evidence import read_native_history
from hermes_finance.services.source_money_classifications import is_broker_transfer
from hermes_finance.services.source_monthly_returns import (
    _source_read_inputs,
)


@dataclass(frozen=True)
class Flow:
    day: date
    amount: int  # Account perspective: contribution positive, withdrawal negative.
    account_id: int
    transfer_id: str | None = None  # Explicit paired identity, never amount matching.


@dataclass(frozen=True)
class History:
    account_id: int
    scope: str
    first_operation: date | None
    valuation_date: date | None
    closing: int | None
    flows: tuple[Flow, ...] = ()
    reasons: tuple[str, ...] = ()
    estimates: tuple[str, ...] = ()


def _metric(value=None, reasons=(), *, rate=False, estimate=False):
    return returns_view.metric(
        value,
        reasons=reasons,
        method="portfolio_inception_xirr" if rate else "portfolio_net_contributions",
        unit="fraction" if rate else "kopecks",
        estimate=estimate,
    )


def _weighted_days(flows, end):
    """FIFO external capital, including completed withdrawals in the denominator.

    Same-day contributions precede withdrawals for date-only FIFO; their duration
    is zero on that day. Income retained inside the scope is never a new lot.
    """
    dated = defaultdict(lambda: [0, 0])
    for flow in flows:
        dated[flow.day][0 if flow.amount > 0 else 1] += abs(flow.amount)
    lots, capital, weighted = deque(), 0, 0
    for day, (amount, withdrawal) in sorted(dated.items()):
        if amount > 0:
            capital += amount
            lots.append([day, amount])
        if withdrawal:
            remaining = withdrawal
            while remaining and lots:
                opened, balance = lots[0]
                used = min(remaining, balance)
                weighted += used * (day - opened).days
                remaining -= used
                lots[0][1] -= used
                if not lots[0][1]:
                    lots.popleft()
            # A withdrawal beyond remaining principal takes out earned income; it
            # neither consumes nor invents invested capital, so it adds no weight.
    weighted += sum(balance * (end - opened).days for opened, balance in lots)
    return Decimal(weighted) / Decimal(capital) if capital else None


def calculate(histories):
    """One complete scope; a single-account call treats transfers as its boundary."""
    first = min((h.first_operation for h in histories if h.first_operation), default=None)
    dates = {h.valuation_date for h in histories}
    end = next(iter(dates)) if len(dates) == 1 else None
    reasons = {r for h in histories for r in h.reasons}
    if not histories:
        reasons.add("overall_accounts_missing")
    if any(h.first_operation is None for h in histories):
        reasons.add("overall_inception_unproven")
    if end is None or any(type(h.closing) is not int or h.closing < 0 for h in histories):
        reasons.add("overall_valuation_unavailable")
    if len({h.account_id for h in histories}) != len(histories):
        reasons.add("overall_account_mapping_unproven")
    flows = [f for h in histories for f in h.flows]
    if any(
        type(f.amount) is not int
        or f.account_id != h.account_id
        or h.first_operation is None
        or h.valuation_date is None
        or not h.first_operation <= f.day <= h.valuation_date
        for h in histories
        for f in h.flows
    ):
        reasons.add("overall_external_flows_incomplete")
    pairs = defaultdict(list)
    for flow in flows:
        if flow.transfer_id is not None:
            pairs[flow.transfer_id].append(flow)
    if len(histories) > 1:
        for pair in pairs.values():
            if (
                len(pair) != 2
                or pair[0].account_id == pair[1].account_id
                or pair[0].day != pair[1].day
                or not pair[0].amount
                or pair[0].amount != -pair[1].amount
            ):
                reasons.add("overall_internal_transfer_unproven")
        flows = [f for f in flows if f.transfer_id is None]
    pnl = days = rate = None
    pnl_reasons = sorted(reasons)
    if not reasons:
        pnl = sum(h.closing for h in histories) - sum(f.amount for f in flows)
        with localcontext() as context:
            context.prec = 60
            days = _weighted_days(flows, end)
        if days is None:
            reasons.add("overall_holding_period_unknown")
        elif days < 90:
            reasons.add("overall_short_holding")
        else:
            result = calculate_xirr(
                [XirrCashFlow(f.day, -f.amount) for f in flows]
                + [XirrCashFlow(end, sum(h.closing for h in histories))]
            )
            rate = result.annualized_rate
            reasons.update(result.reason_codes)
            if rate is not None and days < 365:
                reasons.add("overall_short_holding_provisional")
    estimates = sorted({r for h in histories for r in h.estimates})
    return {
        "pnl": _metric(pnl, sorted(set(pnl_reasons) | set(estimates)), estimate=bool(estimates)),
        "rate": _metric(
            rate,
            sorted(reasons | set(estimates)),
            rate=True,
            estimate=bool(estimates) or "overall_short_holding_provisional" in reasons,
        ),
        "first_operation_date": first,
        "valuation_date": end,
        "weighted_holding_days": None if days is None else str(days),
        "eligibility_basis": "capital_weighted_holding_days",
    }


def _history(session, account, source):
    reasons = set()
    if source is None:
        return History(
            account.id, "", None, None, None, reasons=("overall_account_mapping_unproven",)
        )
    scope = source["scope"]
    native = scope.removeprefix("source:")
    selected, native_scope = _source_read_inputs(session, native)
    # Pair identity is still required even when a default transfer was resolved
    # as an account boundary by the shared source-money reader.
    if any(
        c["classification"] == "internal_transfer"
        or is_broker_transfer(c["operation"], c["narrative"])
        for _, view, error in selected
        if view and not error
        for c in view["money_classifications"]
    ):
        reasons.add("overall_internal_transfer_unproven")
    first, end, closing, schedule, native_reasons, estimates = read_native_history(
        session, native, selected, native_scope
    )
    reasons.update(native_reasons)
    return History(
        account.id,
        scope,
        first,
        end,
        closing,
        tuple(Flow(day, amount, account.id) for day, amount in schedule),
        tuple(sorted(reasons)),
        tuple(sorted(estimates)),
    )


def read_annual_return(session, sources):
    accounts = list(
        session.scalars(
            select(Account)
            .where(
                Account.account_type.in_(("brokerage", "iis")), Account.include_in_returns.is_(True)
            )
            .order_by(Account.id)
        )
    )
    histories = []
    for account in accounts:
        matching = [
            s
            for s in sources
            if s.get("account_link")
            and s["account_link"]["financial_account_id"] == account.id
            and s["account_link"]["status"] == "linked"
        ]
        histories.append(_history(session, account, matching[0] if len(matching) == 1 else None))
    return {
        "portfolio": calculate(histories),
        "accounts": [{"scope": h.scope, **calculate([h])} for h in histories if h.scope],
    }
