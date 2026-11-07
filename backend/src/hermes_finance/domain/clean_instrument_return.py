"""Non-persistent clean security return operands derived from existing events.

The caller supplies clean endpoint values and coverage for the selected scope.
Account cash balances and the historical cash-economic calculation are separate.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext

from hermes_finance.domain.instrument_return import InstrumentEvent, Metric
from hermes_finance.domain.monthly_return_chain import calculate_interval_return


@dataclass(frozen=True)
class CleanInstrumentReturn:
    opening_value: Metric
    closing_value: Metric
    buys: Metric
    sells: Metric
    coupons: Metric
    dividends: Metric
    payouts: Metric
    redemption: Metric
    valuation_and_trades: Metric
    known_result: Metric
    pnl: Metric
    modified_dietz: Metric


def _priced_bond_principal(event: InstrumentEvent) -> int | None:
    """Calculate only from the dated, explicitly sourced price and face."""
    amount = event.native_trade_amount_kopecks
    if amount is None or amount < 0:
        return None
    # The source's bond price is a percentage of the trade-date face value.
    # Convert directly to kopecks: /100 for percent and *100 for RUB cancel.
    price, face, quantity = event.unit_price, event.face_value, event.quantity_delta
    if (
        event.provider != "alfa_mybroker"
        or event.kind not in {"BUY", "SELL"}
        or not event.native_identity
        or len(event.native_ids) != 2
        or "repo_trade_unsupported" in event.reason_codes
        or event.price_unit != "PERCENT_OF_FACE"
        or event.execution_date is None
        or event.face_value_date != event.execution_date
        or any(
            not isinstance(value, Decimal) or not value.is_finite()
            for value in (price, face, quantity)
        )
        or price < 0
        or face <= 0
        or quantity == 0
        or (quantity > 0) != (event.kind == "BUY")
    ):
        return None
    try:
        with localcontext() as context:
            context.prec = 200
            priced = int(
                (price * face * abs(quantity)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
            )
        # The supported source total includes nonnegative NKD. Preserve its
        # existing one-kopeck per-trade tolerance; a smaller total conflicts
        # with the independently calculated principal.
        return priced if amount + 1 >= priced else None
    except ArithmeticError:
        return None


def clean_trade_amount(event: InstrumentEvent) -> int | None:
    """Extract clean principal from supported source operands."""
    amount = event.native_trade_amount_kopecks
    if amount is None or amount < 0:
        return None
    if event.native_total_basis == "excludes_paid_nkd":
        return amount
    if event.native_total_basis == "includes_paid_nkd":
        nkd = event.accrued_interest_kopecks
        if nkd is not None and 0 <= nkd <= amount:
            return amount - nkd
    return _priced_bond_principal(event)


def trade_amount_with_nkd(event: InstrumentEvent) -> int | None:
    """Return the trade money including NKD, excluding commission.

    Purchases, valuations and coupons are compared on one basis: a coupon
    returns NKD paid at purchase, and a statement position value carries NKD.
    """
    principal = clean_trade_amount(event)
    if principal is None:
        return None
    if event.native_total_basis == "excludes_paid_nkd":
        nkd = event.accrued_interest_kopecks
        # An unknown or invalid NKD never blocks the trade the statement proves.
        return principal + nkd if nkd is not None and nkd >= 0 else principal
    return event.native_trade_amount_kopecks


def _missing_fee_principal_consistent(event: InstrumentEvent) -> bool:
    principal = [leg for leg in event.cash_legs if leg.role == "principal"]
    nkd_legs = [leg for leg in event.cash_legs if leg.role == "nkd"]
    if any(leg.role not in {"principal", "nkd", "commission"} for leg in event.cash_legs):
        return False
    if len({leg.date for leg in principal}) > 1:
        return False
    if not principal and not nkd_legs:
        return True
    nkd = event.accrued_interest_kopecks
    if nkd is None or nkd < 0 or clean_trade_amount(event) is None:
        return False
    sign = -1 if event.kind == "BUY" else 1
    if any(sign * leg.account_cash_kopecks < 0 for leg in (*principal, *nkd_legs)):
        return False
    dirty = event.native_trade_amount_kopecks + (
        nkd if event.native_total_basis == "excludes_paid_nkd" else 0
    )
    split = bool(nkd_legs) or (
        event.kind == "BUY" and event.native_total_basis == "includes_paid_nkd" and nkd > 0
    )
    return (
        not principal
        or sum(leg.account_cash_kopecks for leg in principal)
        == sign * (dirty - nkd if split else dirty)
    ) and (not nkd_legs or sum(leg.account_cash_kopecks for leg in nkd_legs) == sign * nkd)


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
        and _missing_fee_principal_consistent(event)
    )


def fee_only_trade_conflict(event: InstrumentEvent) -> bool:
    """Recognise a cash mismatch only when principal and NKD both reconcile."""
    if (
        event.kind not in {"BUY", "SELL"}
        or not event.current
        or event.counted
        or event.reason_codes != ("trade_money_cash_conflict",)
        or not isinstance(event.quantity_delta, Decimal)
        or not event.quantity_delta.is_finite()
        or (event.kind == "BUY" and event.quantity_delta <= 0)
        or (event.kind == "SELL" and event.quantity_delta >= 0)
        or event.commission_kopecks is None
        or event.commission_kopecks < 0
        or clean_trade_amount(event) is None
        or event.accrued_interest_kopecks is None
        or event.accrued_interest_kopecks < 0
    ):
        return False
    roles = {
        role: [leg for leg in event.cash_legs if leg.role == role]
        for role in ("principal", "nkd", "commission")
    }
    if (
        not roles["principal"]
        or not roles["commission"]
        or len({leg.date for leg in roles["principal"]}) > 1
        or any(leg.role not in roles for leg in event.cash_legs)
    ):
        return False
    sign = -1 if event.kind == "BUY" else 1
    if any(sign * leg.account_cash_kopecks < 0 for leg in (*roles["principal"], *roles["nkd"])):
        return False
    nkd = event.accrued_interest_kopecks
    dirty = event.native_trade_amount_kopecks + (
        nkd if event.native_total_basis == "excludes_paid_nkd" else 0
    )
    expected_principal = sign * (dirty - nkd if roles["nkd"] else dirty)
    return (
        sum(leg.account_cash_kopecks for leg in roles["principal"]) == expected_principal
        and (
            not roles["nkd"] or sum(leg.account_cash_kopecks for leg in roles["nkd"]) == sign * nkd
        )
        and sum(leg.account_cash_kopecks for leg in roles["commission"])
        != -event.commission_kopecks
    )


def _clean_trade_chronology(event: InstrumentEvent) -> bool:
    principal_date = clean_trade_date(event)
    return (
        event.execution_date is not None
        and principal_date is not None
        and event.depository_settlement_date is not None
        and event.execution_date <= principal_date
        and event.execution_date <= event.depository_settlement_date
    )


def _priced_bond_without_costs(event: InstrumentEvent) -> bool:
    """The source price proves principal even when legacy cost fields are absent."""
    if (
        event.provider != "alfa_mybroker"
        or event.price_unit != "PERCENT_OF_FACE"
        or event.kind not in {"BUY", "SELL"}
        or not event.current
        or event.counted
        or not event.native_identity
        or len(event.native_ids) != 2
        or not _clean_trade_chronology(event)
        or not event.reason_codes
        or not set(event.reason_codes)
        <= {
            "trade_components_missing",
            "trade_nkd_basis_unknown",
            "trade_nkd_basis_conflict",
            "trade_money_cash_conflict",
            "overlapping_trade_conflict",
            "overlap_trade_commission_only",
            "overlap_trade_nkd_only",
        }
        or bool("overlapping_trade_conflict" in event.reason_codes)
        != bool(
            {"overlap_trade_commission_only", "overlap_trade_nkd_only"} & set(event.reason_codes)
        )
        or not isinstance(event.quantity_delta, Decimal)
        or not event.quantity_delta.is_finite()
        or (event.kind == "BUY" and event.quantity_delta <= 0)
        or (event.kind == "SELL" and event.quantity_delta >= 0)
    ):
        return False
    priced = _priced_bond_principal(event)
    amount = clean_trade_amount(event)
    if priced is None or amount is None or abs(priced - amount) > 1:
        return False
    if any(leg.role not in {"principal", "nkd", "commission"} for leg in event.cash_legs):
        return False
    principal = [leg for leg in event.cash_legs if leg.role == "principal"]
    if len({leg.date for leg in principal}) > 1:
        return False
    nkd = event.accrued_interest_kopecks
    if (
        not principal
        and nkd is not None
        and nkd >= 0
        and abs(event.native_trade_amount_kopecks - priced - nkd) > 1
        and "overlap_trade_nkd_only" not in event.reason_codes
    ):
        return False
    sign = -1 if event.kind == "BUY" else 1
    if any(sign * leg.account_cash_kopecks < 0 for leg in principal):
        return False
    if not principal:
        return True
    paid = sum(leg.account_cash_kopecks for leg in principal)
    return (
        paid == sign * amount
        or (
            "overlap_trade_nkd_only" in event.reason_codes
            and event.attribution_basis == "native_trade_settlement"
            and event.native_total_basis == "includes_paid_nkd"
            and not any(leg.role == "nkd" for leg in event.cash_legs)
            and paid == sign * event.native_trade_amount_kopecks
        )
        or (
            nkd is None
            and event.native_total_basis is None
            and not any(leg.role == "nkd" for leg in event.cash_legs)
            and paid == sign * event.native_trade_amount_kopecks
        )
    )


def clean_trade_assumptions(event: InstrumentEvent) -> tuple[str, ...]:
    """Disclose contradictory NKD while retaining independently proved principal."""
    # The trade total comes from the statement; only a recalculation needs face.
    assumptions = tuple(a for a in event.assumptions if a != "trade_face_value_missing")
    if not _priced_bond_without_costs(event):
        return assumptions
    price = _priced_bond_principal(event)
    total = event.native_trade_amount_kopecks
    nkd = event.accrued_interest_kopecks
    legs = [leg for leg in event.cash_legs if leg.role == "nkd"]
    sign = -1 if event.kind == "BUY" else 1
    conflict = bool(
        {"trade_nkd_basis_conflict", "overlap_trade_nkd_only"} & set(event.reason_codes)
    )
    if nkd is not None:
        conflict |= nkd < 0 or abs(total - price - nkd) > 1
    if legs:
        conflict |= any(sign * leg.account_cash_kopecks < 0 for leg in legs)
        expected = nkd if nkd is not None and nkd >= 0 else total - price
        conflict |= abs(sum(leg.account_cash_kopecks for leg in legs) - sign * expected) > 1
    if not conflict:
        return assumptions
    return tuple(sorted(set(assumptions) | {"source_nkd_conflict"}))


def _fee_only_overlap(event: InstrumentEvent) -> bool:
    """Keep a legacy conflict visible while using its identical clean principal."""
    return (
        event.provider == "alfa_mybroker"
        and event.kind in {"BUY", "SELL"}
        and event.current
        and not event.counted
        and bool(event.native_identity)
        and len(event.native_ids) == 2
        and _clean_trade_chronology(event)
        and {"overlapping_trade_conflict", "overlap_trade_commission_only"}.issubset(
            event.reason_codes
        )
        and set(event.reason_codes)
        <= {
            "overlapping_trade_conflict",
            "overlap_trade_commission_only",
            "trade_components_missing",
            "trade_money_cash_conflict",
        }
        and (
            "trade_components_missing" not in event.reason_codes or event.commission_kopecks is None
        )
        and isinstance(event.quantity_delta, Decimal)
        and event.quantity_delta.is_finite()
        and (
            (event.kind == "BUY" and event.quantity_delta > 0)
            or (event.kind == "SELL" and event.quantity_delta < 0)
        )
        and clean_trade_amount(event) is not None
        and _missing_fee_principal_consistent(event)
    )


def cost_only_trade(event: InstrumentEvent) -> bool:
    return (
        missing_fee_only(event)
        or fee_only_trade_conflict(event)
        or _priced_bond_without_costs(event)
        or _fee_only_overlap(event)
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
    result_assumptions: tuple[str, ...] = (),
) -> CleanInstrumentReturn:
    """Calculate from attributable current observations, preserving partial facts.

    A known component is partial when its population is incomplete; an empty
    incomplete population is unknown, not zero. Only complete inputs yield a
    total or a rate. Costs never enter the flows or block this calculation.
    """
    if opening_date >= closing_date:
        raise ValueError("opening_date must precede closing_date")
    values = {kind: [] for kind in ("BUY", "SELL", "COUPON", "DIVIDEND", "REDEMPTION")}
    assumptions = {kind: set() for kind in values}
    assumptions["COUPON"].update(result_assumptions)
    assumptions["DIVIDEND"].update(result_assumptions)
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
        fee_only_gap = cost_only_trade(event)
        if not event.current or (not event.counted and not fee_only_gap):
            if event.kind in {"BUY", "SELL"}:
                trade_gap = True
            elif event.kind == "REDEMPTION":
                redemption_gap = True
            else:
                payout_gap = True
            continue
        if event.kind in {"BUY", "SELL"}:
            value = trade_amount_with_nkd(event)
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
            kind = event.kind
            assumptions[kind].update(event.assumptions)
            for leg in legs:
                if leg.ownership in seen_legs:
                    raise ValueError("duplicate event ownership")
                seen_legs.add(leg.ownership)
                values[kind].append(leg.account_cash_kopecks)
                dated_flows.append((leg.date, -leg.account_cash_kopecks, "confirmed"))
            continue
        values[kind].append(value)
        assumptions[kind].update(clean_trade_assumptions(event))
        dated_flows.append((day, flow, "confirmed"))

    def available_status(used):
        if "source_nkd_conflict" in used:
            return "partial"
        return "provisional" if used else "supported"

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
            else available_status(used),
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
    coupons = component("COUPON", payout_gap)
    dividends = component("DIVIDEND", payout_gap)
    payout_values = values["COUPON"] + values["DIVIDEND"]
    payout_assumptions = tuple(sorted(assumptions["COUPON"] | assumptions["DIVIDEND"]))
    payouts = Metric(
        sum(payout_values) if payout_values or not payout_gap else None,
        "partial"
        if payout_values and payout_gap
        else "unavailable"
        if payout_gap
        else "provisional"
        if payout_assumptions
        else "supported",
        ("paid_income_incomplete",) if payout_gap else (),
        payout_assumptions,
    )
    redemption = component("REDEMPTION", redemption_gap)
    v_complete = valuation_complete and opening_clean is not None and closing_clean is not None
    price = None
    if (
        v_complete
        and not trade_gap
        and not redemption_gap
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
        else ("partial" if trade_gap or redemption_gap else available_status(price_assumptions))
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
    # An empty position has no capital before its first trade, so the money of
    # that first day is the capital held for the whole interval.
    interval_start, interval_capital = opening_date, opening_clean
    first_day = min((row[0] for row in dated_flows), default=None)
    if opening_clean == 0 and first_day is not None:
        if opening_date < first_day < closing_date:
            interval_start = first_day
            interval_capital = sum(row[1] for row in dated_flows if row[0] == first_day)
        else:
            interval_start = max(opening_date, first_day - timedelta(days=1))
    row = calculate_interval_return(
        (interval_start, interval_capital), (closing_date, closing_clean), dated_flows
    )
    used = tuple(sorted(set().union(*assumptions.values())))
    result_status = available_status(used)
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
    # A valuation cannot be combined with an incomplete trade/redemption set:
    # doing so presents unaccounted purchase principal as investment gain.
    # Independent observed receipts remain useful when price is unavailable.
    known = (
        price + sum(payout_values)
        if price is not None
        else sum(payout_values)
        if payout_values
        else None
    )
    known_result = Metric(
        known,
        (result_status if complete else "partial") if known is not None else "unavailable",
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
        coupons,
        dividends,
        payouts,
        redemption,
        price_metric,
        known_result,
        pnl,
        rate,
    )
