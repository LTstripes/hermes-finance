"""Non-persistent clean security return operands derived from existing events.

The caller supplies clean endpoint values and coverage for the selected scope.
Account cash balances and the historical cash-economic calculation are separate.
"""

from dataclasses import dataclass
from datetime import date

from hermes_finance.domain.instrument_return import InstrumentEvent, Metric
from hermes_finance.domain.monthly_return_chain import calculate_interval_return


@dataclass(frozen=True)
class CleanInstrumentReturn:
    opening_value: Metric
    closing_value: Metric
    buys: Metric
    sells: Metric
    payouts: Metric
    redemption: Metric
    valuation_and_trades: Metric
    known_result: Metric
    pnl: Metric
    modified_dietz: Metric


def clean_trade_amount(event: InstrumentEvent) -> int | None:
    """Extract the security principal, never guessing a missing NKD basis."""
    amount = event.native_trade_amount_kopecks
    if amount is None or amount < 0:
        return None
    if event.native_total_basis == "excludes_paid_nkd":
        return amount
    if event.native_total_basis == "includes_paid_nkd":
        nkd = event.accrued_interest_kopecks
        if nkd is None or nkd < 0 or nkd > amount:
            return None
        return amount - nkd
    return None


def missing_fee_only(event: InstrumentEvent) -> bool:
    return (
        event.kind in {"BUY", "SELL"}
        and event.current
        and not event.counted
        and event.reason_codes == ("trade_components_missing",)
        and event.commission_kopecks is None
        and event.quantity_delta is not None
        and (
            (event.kind == "BUY" and event.quantity_delta > 0)
            or (event.kind == "SELL" and event.quantity_delta < 0)
        )
        and clean_trade_amount(event) is not None
    )


def clean_trade_date(event: InstrumentEvent) -> date | None:
    """Use the linked principal's posting date when it is unambiguous."""
    principal = [leg for leg in event.cash_legs if leg.role == "principal"]
    if not principal and event.attribution_basis == "native_money_group_bridge":
        principal = [leg for leg in event.cash_legs if leg.role == "native_money"]
    dates = {leg.date for leg in principal}
    if len(dates) > 1:
        return None
    return next(iter(dates)) if dates else event.cash_settlement_date


def calculate_clean_return(
    opening_date: date,
    closing_date: date,
    opening_clean: int | None,
    closing_clean: int | None,
    events: tuple[InstrumentEvent, ...],
    *,
    trades_complete: bool,
    payouts_complete: bool,
    redemptions_complete: bool,
    valuation_complete: bool,
) -> CleanInstrumentReturn:
    """Calculate from attributable current observations, preserving partial facts.

    A known component is partial when its population is incomplete; an empty
    incomplete population is unknown, not zero. Only complete inputs yield a
    total or a rate. Costs never enter the flows or block this calculation.
    """
    if opening_date >= closing_date:
        raise ValueError("opening_date must precede closing_date")
    values = {kind: [] for kind in ("BUY", "SELL", "PAYOUT", "REDEMPTION")}
    assumptions = {kind: set() for kind in values}
    dated_flows = []
    seen_events = set()
    seen_legs = set()
    trade_gap = not trades_complete
    payout_gap = not payouts_complete
    redemption_gap = not redemptions_complete
    for event in events:
        if event.kind in {"FEE", "TAX"}:
            continue
        if event.kind not in {"BUY", "SELL", "COUPON", "DIVIDEND", "REDEMPTION"}:
            continue
        day = clean_trade_date(event) if event.kind in {"BUY", "SELL"} else event.event_date
        if event.kind in {"BUY", "SELL"}:
            if day is None:
                trade_gap = True
                continue
            if not opening_date < day <= closing_date:
                continue
        elif not any(opening_date < leg.date <= closing_date for leg in event.cash_legs):
            if day is None or opening_date < day <= closing_date:
                if event.kind == "REDEMPTION":
                    redemption_gap = True
                else:
                    payout_gap = True
            continue
        if event.event_key in seen_events:
            raise ValueError("duplicate event ownership")
        seen_events.add(event.event_key)
        # The legacy event marks a trade uncounted when any native component is
        # missing. A missing commission alone does not prevent clean principal
        # from being known; all identity, settlement and sign checks still apply.
        fee_only_gap = missing_fee_only(event)
        if not event.current or (not event.counted and not fee_only_gap):
            if event.kind in {"BUY", "SELL"}:
                trade_gap = True
            elif event.kind == "REDEMPTION":
                redemption_gap = True
            else:
                payout_gap = True
            continue
        if event.kind in {"BUY", "SELL"}:
            value = clean_trade_amount(event)
            if value is None:
                trade_gap = True
                continue
            kind = event.kind
            flow = value if kind == "BUY" else -value
        else:
            # A paid cash leg is the observed receipt; gross and tax annotations
            # are not extra money. Respect each leg's actual posting date.
            legs = [leg for leg in event.cash_legs if opening_date < leg.date <= closing_date]
            if not legs:
                if event.kind == "REDEMPTION":
                    redemption_gap = True
                else:
                    payout_gap = True
                continue
            kind = "REDEMPTION" if event.kind == "REDEMPTION" else "PAYOUT"
            assumptions[kind].update(event.assumptions)
            for leg in legs:
                if leg.ownership in seen_legs:
                    raise ValueError("duplicate event ownership")
                seen_legs.add(leg.ownership)
                values[kind].append(leg.account_cash_kopecks)
                dated_flows.append((leg.date, -leg.account_cash_kopecks, "confirmed"))
            continue
        values[kind].append(value)
        assumptions[kind].update(event.assumptions)
        dated_flows.append((day, flow, "confirmed"))

    def component(kind, incomplete):
        observed = values[kind]
        value = sum(observed) if observed or not incomplete else None
        used = tuple(sorted(assumptions[kind]))
        return Metric(
            value,
            "partial"
            if observed and incomplete
            else "unavailable"
            if incomplete
            else "provisional"
            if used
            else "supported",
            (
                "clean_trades_incomplete"
                if kind in {"BUY", "SELL"}
                else "redemption_incomplete"
                if kind == "REDEMPTION"
                else "paid_income_incomplete",
            )
            if incomplete
            else (),
            used,
        )

    buys = component("BUY", trade_gap)
    sells = component("SELL", trade_gap)
    payouts = component("PAYOUT", payout_gap)
    redemption = component("REDEMPTION", redemption_gap)
    v_complete = valuation_complete and opening_clean is not None and closing_clean is not None
    price = None
    if (
        v_complete
        and buys.value is not None
        and sells.value is not None
        and redemption.value is not None
    ):
        price = closing_clean - opening_clean - buys.value + sells.value + redemption.value
    price_assumptions = tuple(
        sorted(assumptions["BUY"] | assumptions["SELL"] | assumptions["REDEMPTION"])
    )
    price_status = (
        "unavailable"
        if price is None
        else (
            "partial"
            if trade_gap or redemption_gap
            else "provisional"
            if price_assumptions
            else "supported"
        )
    )
    price_reasons = tuple(
        reason
        for missing, reason in (
            (not v_complete, "clean_valuation_incomplete"),
            (trade_gap, "clean_trades_incomplete"),
            (redemption_gap, "redemption_incomplete"),
        )
        if missing
    )
    price_metric = Metric(price, price_status, price_reasons, price_assumptions)
    complete = v_complete and not trade_gap and not payout_gap and not redemption_gap
    reasons = tuple(
        reason
        for missing, reason in (
            (not v_complete, "clean_valuation_incomplete"),
            (trade_gap, "clean_trades_incomplete"),
            (payout_gap, "paid_income_incomplete"),
            (redemption_gap, "redemption_incomplete"),
        )
        if missing
    )
    row = calculate_interval_return(
        (opening_date, opening_clean), (closing_date, closing_clean), dated_flows
    )
    used = tuple(sorted(set().union(*assumptions.values())))
    result_status = "provisional" if used else "supported"
    pnl = Metric(
        row.growth_kopecks if complete else None,
        result_status if complete and row.growth_kopecks is not None else "unavailable",
        reasons,
        used,
    )
    rate = Metric(
        row.modified_dietz_return if complete else None,
        result_status if complete and row.modified_dietz_return is not None else "unavailable",
        tuple(sorted(set(reasons + row.reason_codes))),
        used,
    )
    known_result = Metric(
        closing_clean - opening_clean - sum(amount for _, amount, _ in dated_flows)
        if v_complete
        else None,
        (result_status if complete else "partial") if v_complete else "unavailable",
        reasons,
        used,
    )

    def endpoint_metric(value):
        return Metric(
            value,
            "supported" if value is not None else "unavailable",
            () if value is not None else ("clean_valuation_incomplete",),
        )

    return CleanInstrumentReturn(
        endpoint_metric(opening_clean),
        endpoint_metric(closing_clean),
        buys,
        sells,
        payouts,
        redemption,
        price_metric,
        known_result,
        pnl,
        rate,
    )
