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
from hermes_finance.services import returns_view, source_investment_proofs
from hermes_finance.services.source_account_history import extend_history
from hermes_finance.services.source_money_classifications import is_broker_transfer
from hermes_finance.services.source_monthly_returns import (
    _source_read_inputs,
    read_monthly_for_card_history,
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


def _metric(value=None, reasons=(), *, rate=False):
    return returns_view.metric(
        value,
        reasons=reasons,
        method="portfolio_inception_xirr" if rate else "portfolio_net_contributions",
        unit="fraction" if rate else "kopecks",
        estimate=False,
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
            if remaining:
                return None  # Withdrawn income cannot invent additional invested capital.
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
        elif days < 365:
            reasons.add("overall_short_holding")
        else:
            result = calculate_xirr(
                [XirrCashFlow(f.day, -f.amount) for f in flows]
                + [XirrCashFlow(end, sum(h.closing for h in histories))]
            )
            rate = result.annualized_rate
            reasons.update(result.reason_codes)
    return {
        "pnl": _metric(pnl, pnl_reasons),
        "rate": _metric(rate, sorted(reasons), rate=True),
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
    reports = source_investment_proofs.read_account_summaries(session, source_account=native)
    inception = [p for p in reports if p["history_from_zero"]]
    proof = max(inception, key=lambda p: (p["covered_to"], p["proof_id"]), default=None)
    selected, _ = _source_read_inputs(session, native)
    activity = []
    for _, view, error in selected:
        if error:
            reasons.add("overall_external_flows_incomplete")
            continue
        document = view["document"]
        activity.extend(date.fromisoformat(r["date"]) for r in document.get("money", []))
        activity.extend(
            date.fromisoformat(t["core"]["trade_time"][:10])
            for t in document.get("trades", [])
            if t["core"].get("trade_time")
        )
        if any(
            r["classification"] == "internal_transfer"
            or is_broker_transfer(r["operation"], r["narrative"])
            for r in view["money_classifications"]
        ):
            # Source schedules have no explicit cross-account pair identity.
            # Never remove a leg by matching only date and amount.
            reasons.add("overall_internal_transfer_unproven")
    first = min(activity, default=None)
    end = source["valuation_date"]
    end = date.fromisoformat(end) if isinstance(end, str) else end
    if proof is None:
        reasons.add("overall_inception_unproven")
    elif proof["status"] != "current":
        reasons.add("overall_source_proof_stale")
    if first is None or (proof and first < date.fromisoformat(proof["covered_from"])):
        reasons.add("overall_inception_unproven")
    if reasons:
        return History(account.id, scope, first, end, None, reasons=tuple(sorted(reasons)))

    # The compact index deliberately omits dated flows; use its exact full proof.
    complete = source_investment_proofs.read_reports(
        session, source_account=native, include_xirr=False
    )
    proof = next(p for p in complete if p["proof_id"] == proof["proof_id"])
    monthly = read_monthly_for_card_history(session, source_account=native)
    extended = extend_history(proof, monthly)
    interval = extended["interval"] if extended["status"] == "current" else None
    closing = None
    flows = ()
    if interval is None or interval.get("pnl", {}).get("value") is None:
        reasons.add("overall_external_flows_incomplete")
    else:
        closing = interval["closing_kopecks"]
        if interval["opening_kopecks"] not in (0, "0"):
            reasons.add("overall_inception_unproven")
        if end is None or extended["covered_to"] != str(end):
            reasons.add("overall_valuation_unavailable")
        schedule = interval.get("external_flows")
        if schedule is None or any(f["status"] not in {"confirmed", "assumed"} for f in schedule):
            reasons.add("overall_external_flows_incomplete")
        else:
            flows = tuple(
                Flow(date.fromisoformat(f["date"]), int(f["amount_kopecks"]), account.id)
                for f in schedule
            )
            incoming = sum(f.amount for f in flows if f.amount > 0)
            outgoing = -sum(f.amount for f in flows if f.amount < 0)
            if (incoming, outgoing) != (
                interval["contributions_kopecks"],
                interval["withdrawals_kopecks"],
            ) and (str(incoming), str(outgoing)) != (
                interval["contributions_kopecks"],
                interval["withdrawals_kopecks"],
            ):
                reasons.add("overall_external_flows_incomplete")
    return History(
        account.id,
        scope,
        first,
        end,
        None if closing is None else int(closing),
        flows,
        tuple(sorted(reasons)),
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
