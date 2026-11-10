from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from hermes_finance.domain.clean_instrument_return import (
    calculate_clean_return,
    clean_trade_amount,
    clean_trade_assumptions,
    cost_only_trade,
    trade_amount_with_nkd,
)
from hermes_finance.domain.instrument_return import CashLeg, Coverage, Endpoint, InstrumentEvent
from hermes_finance.services.clean_instrument_return import project_clean_analysis
from hermes_finance.services.clean_purchase_returns import clean_purchase_price_contributions

START, END, DAY = date(2030, 1, 1), date(2030, 1, 31), date(2030, 1, 16)


def trade(kind, amount, nkd, *, basis="includes_paid_nkd"):
    return InstrumentEvent(
        event_key=kind,
        provider="synthetic",
        native_source_account="a",
        isin="ZZ0000000011",
        kind=kind,
        source_references=(kind,),
        event_date=DAY,
        cash_settlement_date=DAY,
        native_trade_amount_kopecks=amount,
        native_total_basis=basis,
        accrued_interest_kopecks=nkd,
        commission_kopecks=900,
    )


@pytest.mark.parametrize(
    "change",
    [
        "none",
        "undated",
        "wrong_date",
        "missing_face",
        "invalid_face",
        "wrong_unit",
        "no_identity",
        "repo",
        "conflicting_total",
        "one_kopeck_tolerance",
        "missing_total",
    ],
)
def test_bond_principal_from_dated_price_uses_exact_half_up_rounding(change):
    event = replace(
        trade("BUY", 102000, None, basis=None),
        provider="alfa_mybroker",
        native_identity="trade-1",
        native_ids=("1", "2"),
        execution_date=DAY,
        unit_price=Decimal("99.9995"),
        price_unit="PERCENT_OF_FACE",
        face_value=Decimal("1000"),
        face_value_date=DAY,
        quantity_delta=Decimal("1"),
    )
    changes = {
        "undated": {"face_value_date": None},
        "wrong_date": {"face_value_date": START},
        "missing_face": {"face_value": None},
        "invalid_face": {"face_value": Decimal("NaN")},
        "wrong_unit": {"price_unit": "UNKNOWN"},
        "no_identity": {"native_identity": None},
        "repo": {"reason_codes": ("repo_trade_unsupported",)},
        "conflicting_total": {"native_trade_amount_kopecks": 99998},
        "one_kopeck_tolerance": {"native_trade_amount_kopecks": 99999},
        "missing_total": {"native_trade_amount_kopecks": None},
    }
    event = replace(event, **changes.get(change, {}))
    assert clean_trade_amount(event) == (
        100000 if change in {"none", "one_kopeck_tolerance"} else None
    )


@pytest.mark.parametrize("field", ["cash_settlement_date", "depository_settlement_date"])
def test_cost_only_recovery_rejects_settlement_before_execution(field):
    event = replace(
        trade("BUY", 102000, None, basis=None),
        provider="alfa_mybroker",
        native_identity="trade-1",
        native_ids=("1", "2"),
        execution_date=DAY,
        depository_settlement_date=DAY,
        unit_price=Decimal("100"),
        price_unit="PERCENT_OF_FACE",
        face_value=Decimal("1000"),
        face_value_date=DAY,
        quantity_delta=Decimal("1"),
        counted=False,
        reason_codes=("trade_components_missing", "trade_nkd_basis_unknown"),
    )
    assert cost_only_trade(event)
    assert not cost_only_trade(replace(event, **{field: DAY - timedelta(days=1)}))


@pytest.mark.parametrize(
    "paid, expected", [(-100000, True), (-102000, True), (-101999, False), (102000, False)]
)
def test_bond_clean_price_requires_linked_cash_to_match_price_or_unknown_basis_total(
    paid, expected
):
    event = replace(
        trade("BUY", 102000, None, basis=None),
        provider="alfa_mybroker",
        native_identity="trade-1",
        native_ids=("1", "2"),
        execution_date=DAY,
        depository_settlement_date=DAY,
        unit_price=Decimal("100"),
        price_unit="PERCENT_OF_FACE",
        face_value=Decimal("1000"),
        face_value_date=DAY,
        quantity_delta=Decimal("1"),
        counted=False,
        reason_codes=("trade_components_missing", "trade_nkd_basis_unknown"),
        cash_legs=(CashLeg("principal", DAY, paid, -paid, ("cash",), "cash"),),
    )
    assert cost_only_trade(event) is expected


def cash(kind, amount):
    return InstrumentEvent(
        event_key=kind,
        provider="synthetic",
        native_source_account="a",
        isin="ZZ0000000011",
        kind=kind,
        source_references=(kind,),
        event_date=DAY,
        cash_legs=(CashLeg(kind, DAY, amount, -amount, (kind,), kind),),
        net_payout_kopecks=amount if kind == "DIVIDEND" else None,
        gross_payout_kopecks=10000 if kind == "DIVIDEND" else None,
        withheld_tax_kopecks=1300 if kind == "DIVIDEND" else None,
    )


def calc(events, **kwargs):
    return calculate_clean_return(
        START,
        END,
        0,
        110000,
        events,
        **(
            {
                "trades_complete": True,
                "payouts_complete": True,
                "redemptions_complete": True,
                "valuation_complete": True,
            }
            | kwargs
        ),
    )


def position_return(*, days=365, closed=False, payouts=(), changes=None, **coverage):
    first = date(2028, 1, 2)
    end = first + timedelta(days=days)
    buy = replace(trade("BUY", 100000, 2000), execution_date=first, cash_settlement_date=first)
    events = (replace(buy, **(changes or {})), *payouts)
    if closed:
        events += (replace(trade("SELL", 110000, 0), execution_date=end, cash_settlement_date=end),)
    return calculate_clean_return(
        first - timedelta(days=1),
        end + timedelta(days=700) if closed else end,
        0,
        0 if closed else 110000,
        events,
        trades_complete=coverage.get("trades_complete", True),
        payouts_complete=coverage.get("payouts_complete", True),
        redemptions_complete=coverage.get("redemptions_complete", True),
        valuation_complete=coverage.get("valuation_complete", True),
        position_closed=closed,
        weighted_holding_days=Decimal(days),  # Synthetic complete single-lot match.
    )


@pytest.mark.parametrize("days", [0, 1, 364, 365, 730])
def test_position_simple_and_annual_return_have_independent_holding_gate(days):
    result = position_return(days=days)
    simple, annual = result.simple_return, result.xirr
    assert simple.value == Decimal("0.1")
    assert simple.invested_kopecks == 100000  # Retains the statement's NKD.
    assert not simple.annualized and simple.for_position_comparison
    assert simple.basis == "statement_purchases_including_nkd"
    assert annual.holding_days == days
    assert annual.weighted_holding_days == days
    assert annual.eligibility_basis == "capital_weighted_holding_days"
    assert annual.start_date == date(2028, 1, 2)
    assert annual.end_date == date(2028, 1, 2) + timedelta(days=days)
    assert annual.annualized
    if days < 365:
        assert annual.value is None
        assert annual.reason_codes == ("short_holding",)
    else:
        assert annual.status == "supported"
        # Analytic single-purchase example, independent of solver invocation.
        with localcontext() as context:
            context.prec = 60
            expected = Decimal("1.1") ** (Decimal(365) / Decimal(days)) - 1
        assert abs(annual.value - expected) < Decimal("1e-25")


@pytest.mark.parametrize("days", [30, 365, 730])
def test_closed_position_uses_disposal_date_and_never_adds_terminal_value(days, monkeypatch):
    from hermes_finance.domain import clean_instrument_return as domain
    from hermes_finance.domain.xirr import calculate_xirr

    observed = []

    def solve(flows):
        observed.extend(flows)
        return calculate_xirr(flows)

    monkeypatch.setattr(domain, "calculate_xirr", solve)
    result = position_return(days=days, closed=True)
    assert result.simple_return.value == Decimal("0.1")
    assert result.xirr.holding_days == days  # The much later report is irrelevant.
    if days < 365:
        assert result.xirr.reason_codes == ("short_holding",)
        assert not observed
    else:
        assert result.xirr.value is not None
        assert [(f.event_date, f.amount_kopecks) for f in observed] == [
            (date(2028, 1, 2), -100000),
            (date(2028, 1, 2) + timedelta(days=days), 110000),
        ]


@pytest.mark.parametrize("kind", ["COUPON", "DIVIDEND"])
def test_position_xirr_counts_actual_payout_cash_dates_once(kind):
    day = date(2028, 1, 2) + timedelta(days=365)
    paid = replace(
        cash(kind, 10000),
        event_date=day - timedelta(days=2),
        cash_legs=(CashLeg(kind, day, 10000, -10000, (kind,), kind),),
    )
    result = position_return(payouts=(paid,))
    assert result.simple_return.value == Decimal("0.2")
    assert abs(result.xirr.value - Decimal("0.2")) < Decimal("1e-25")


@pytest.mark.parametrize(
    "coverage, reason",
    [
        ("trades_complete", "clean_trades_incomplete"),
        ("payouts_complete", "paid_income_incomplete"),
        ("redemptions_complete", "redemption_incomplete"),
        ("valuation_complete", "clean_valuation_incomplete"),
    ],
)
def test_incomplete_position_never_manufactures_total_percent_or_xirr(coverage, reason):
    result = position_return(**{coverage: False})
    assert result.xirr.value is result.simple_return.value is None
    assert result.xirr.status == "unavailable"
    assert reason in result.xirr.reason_codes
    assert reason in result.simple_return.reason_codes


def test_unknown_first_execution_keeps_known_simple_return():
    result = position_return(changes={"execution_date": None})
    assert result.simple_return.value == Decimal("0.1")
    assert result.simple_return.start_date is None
    assert result.xirr.value is result.xirr.holding_days is None
    assert "first_purchase_date_unknown" in result.xirr.reason_codes


def test_zero_invested_is_unknown_rate_instead_of_zero():
    result = position_return(
        changes={"native_trade_amount_kopecks": 0, "accrued_interest_kopecks": 0}
    )
    assert result.pnl.value == 110000
    assert result.simple_return.invested_kopecks == 0
    assert result.simple_return.value is result.xirr.value is None
    assert "zero_invested" in result.simple_return.reason_codes
    assert "zero_invested" in result.xirr.reason_codes


def test_truncated_position_cannot_claim_lifetime_invested_or_holding():
    result = calculate_clean_return(
        START,
        END,
        100000,
        110000,
        (trade("BUY", 1000, 0),),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
    )
    assert result.pnl.value == 9000
    assert result.simple_return.value is result.xirr.value is None
    assert "position_inception_unproven" in result.simple_return.reason_codes
    assert result.xirr.holding_days is None
    assert result.simple_return.invested_kopecks is None


@pytest.mark.parametrize("closing, expected", [(100000, "0"), (90000, "-0.1"), (0, None)])
def test_zero_loss_and_no_root_are_distinct_position_returns(closing, expected):
    first = date(2028, 1, 2)
    result = calculate_clean_return(
        first - timedelta(days=1),
        first + timedelta(days=365),
        0,
        closing,
        (replace(trade("BUY", 100000, 0), execution_date=first, cash_settlement_date=first),),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
        weighted_holding_days=Decimal(365),
    )
    if expected is not None:
        assert result.simple_return.value == Decimal(expected)
        assert abs(result.xirr.value - Decimal(expected)) < Decimal("1e-25")
    else:
        assert result.simple_return.value == Decimal(-1)
        assert result.xirr.value is None
        assert result.xirr.reason_codes == ("not_computable_xirr_no_valid_root",)


def test_ambiguous_xirr_keeps_simple_return_on_all_purchases():
    first = date(2028, 1, 2)
    end = first + timedelta(days=2190)
    events = tuple(
        replace(
            trade(kind, amount, 0),
            event_key=str(index),
            execution_date=first + timedelta(days=days),
            cash_settlement_date=first + timedelta(days=days),
        )
        for index, (kind, amount, days) in enumerate(
            [("BUY", 100000, 0), ("SELL", 230000, 1095), ("BUY", 132000, 2190)]
        )
    )
    result = calculate_clean_return(
        first - timedelta(days=1),
        end,
        0,
        0,
        events,
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
        weighted_holding_days=Decimal(100000) * 1095 / Decimal(232000),
    )
    assert result.simple_return.invested_kopecks == 232000
    assert abs(result.simple_return.value - Decimal(-2000) / Decimal(232000)) < Decimal("1e-28")
    assert result.xirr.value is None
    assert result.xirr.reason_codes == ("not_computable_xirr_root_ambiguity",)


def test_full_redemption_and_later_coupon_keep_their_actual_dates(monkeypatch):
    from hermes_finance.domain import clean_instrument_return as domain
    from hermes_finance.domain.xirr import calculate_xirr

    first = date(2028, 1, 2)
    redeemed = first + timedelta(days=365)
    payout = redeemed + timedelta(days=10)
    observed = []

    def solve(flows):
        observed.extend(flows)
        return calculate_xirr(flows)

    monkeypatch.setattr(domain, "calculate_xirr", solve)
    redemption = replace(
        cash("REDEMPTION", 100000),
        event_date=redeemed,
        depository_settlement_date=redeemed,
        cash_legs=(CashLeg("redemption", redeemed, 100000, -100000, ("r",), "r"),),
    )
    coupon = replace(
        cash("COUPON", 10000),
        event_date=payout,
        cash_legs=(CashLeg("coupon", payout, 10000, -10000, ("c",), "c"),),
    )
    result = calculate_clean_return(
        first - timedelta(days=1),
        payout + timedelta(days=365),
        0,
        0,
        (
            replace(trade("BUY", 100000, 0), execution_date=first, cash_settlement_date=first),
            redemption,
            coupon,
        ),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
        position_closed=True,
        weighted_holding_days=Decimal(365),
    )
    assert result.simple_return.value == Decimal("0.1")
    assert result.xirr.holding_days == 365
    assert result.xirr.holding_end_date == redeemed
    assert result.xirr.end_date == payout
    assert result.xirr.value is not None
    assert [(f.event_date, f.amount_kopecks) for f in observed] == [
        (first, -100000),
        (redeemed, 100000),
        (payout, 10000),
    ]


def test_trade_money_with_nkd_net_receipt_and_costs_excluded():
    result = calc(
        (trade("BUY", 102000, 2000), cash("DIVIDEND", 8700), cash("FEE", -900), cash("TAX", -1300))
    )
    assert result.buys.value == 102000
    assert result.payouts.value == 8700
    assert result.valuation_and_trades.value == 8000
    assert result.pnl.value == 16700
    with localcontext() as context:
        context.prec = 60
        assert round(result.modified_dietz.value, 6) == Decimal("0.178992")


def test_price_and_actual_payout_breakdown_uses_same_period_and_excludes_costs():
    result = calculate_clean_return(
        START,
        END,
        100000,
        95000,
        (
            replace(cash("DIVIDEND", 12000), gross_payout_kopecks=None, withheld_tax_kopecks=None),
            cash("FEE", -1000),
            cash("TAX", -500),
        ),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
    )
    assert result.valuation_and_trades.value == -5000
    assert result.payouts.value == result.dividends.value == 12000
    assert result.pnl.value == result.known_result.value == 7000


def test_breakdown_counts_purchase_sale_and_redemption_once():
    result = calculate_clean_return(
        START,
        END,
        100000,
        95000,
        (
            trade("BUY", 10000, 0, basis="excludes_paid_nkd"),
            trade("SELL", 20000, 0, basis="excludes_paid_nkd"),
            cash("REDEMPTION", 30000),
            cash("COUPON", 12000),
        ),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
    )
    assert result.valuation_and_trades.value == 35000
    assert result.redemption.value == 30000
    assert result.payouts.value == 12000
    assert result.pnl.value == 47000


def test_clean_sale_and_missing_basis_stays_unknown():
    assert clean_trade_amount(trade("SELL", 105000, 5000)) == 100000
    assert clean_trade_amount(trade("SELL", 105000, None)) is None
    result = calc((trade("BUY", 102000, None), cash("DIVIDEND", 8700)))
    assert result.buys.value is None and result.pnl.value is None
    assert result.payouts.value == 8700
    assert result.valuation_and_trades.value is None
    assert result.known_result.value == 8700


def test_partial_and_zero_are_distinct_and_duplicate_payout_is_rejected():
    result = calc((cash("DIVIDEND", 8700),), payouts_complete=False)
    assert result.payouts.value == 8700 and result.payouts.status == "partial"
    assert result.redemption.value == 0 and result.pnl.value is None
    assert result.valuation_and_trades.value == 110000
    assert result.known_result.value == 118700 and result.known_result.status == "partial"
    assert calc(()).payouts.value == 0
    dividend = cash("DIVIDEND", 8700)
    with pytest.raises(ValueError, match="duplicate"):
        calc((dividend, dividend))


def test_missing_fee_alone_does_not_hide_a_valid_trade():
    buy = replace(
        trade("BUY", 102000, 2000),
        commission_kopecks=None,
        counted=False,
        reason_codes=("trade_components_missing",),
        quantity_delta=Decimal(1),
    )
    assert calc((buy,)).pnl.value == 8000
    unknown_sign = replace(buy, quantity_delta=None)
    assert calc((unknown_sign,)).pnl.value is None


def test_income_classification_assumptions_are_disclosed():
    payout = replace(cash("DIVIDEND", 8700), assumptions=("income_assumed",))
    result = calc((payout,))
    assert result.payouts.status == result.pnl.status == "provisional"
    assert result.pnl.assumptions == ("income_assumed",)


def test_linked_principal_posting_date_drives_weighting_and_conflicts_stay_unknown():
    earlier = date(2030, 1, 6)
    leg = CashLeg("principal", earlier, -100000, 100000, ("m",), "m")
    buy = replace(trade("BUY", 102000, 2000), cash_legs=(leg,), attribution_basis="matched_money")
    result = calc((buy,))
    with localcontext() as context:
        context.prec = 60
        assert result.modified_dietz.value == Decimal(8000) / Decimal(102000)
    second = replace(leg, date=DAY, ownership="m2")
    assert calc((replace(buy, cash_legs=(leg, second)),)).pnl.value is None


def test_projection_keeps_foreign_redemption_and_account_cost_outside_security():
    other = replace(cash("REDEMPTION", 90000), isin="ZZ0000000029")
    coverage = {name: Coverage(True) for name in ("events", "quantity", "payouts")}
    coverage["events"] = Coverage(False, ("unallocated_instrument_cost",))
    analysis = SimpleNamespace(
        opening_date=START,
        closing_date=END,
        opening=Endpoint(START, Decimal(0), 0, 0, 0, "dirty"),
        closing=Endpoint(END, Decimal(1), 110000, 110000, 0, "dirty"),
        events=(trade("BUY", 102000, 2000), other),
        coverage=coverage,
    )
    result = project_clean_analysis(analysis, "ZZ0000000011")
    assert result.pnl.value == 8000
    assert result.redemption.value == 0
    unknown_nkd = replace(analysis.closing, accrued_interest_kopecks=None)
    assert (
        project_clean_analysis(
            replace_namespace(analysis, closing=unknown_nkd), "ZZ0000000011"
        ).pnl.value
        == 8000
    )


@pytest.mark.parametrize(
    "case",
    [
        "exact",
        "quantity_above",
        "quantity_below",
        "uncounted_trade",
        "coupon_gap",
        "account_custody_gap",
        "own_custody_gap",
        "intermediate_conflict",
        "unproved_redemption",
        "stale_redemption",
        "positive_redemption_quantity",
        "same_day_purchase",
        "present_in_latest",
    ],
)
def test_full_redemption_closes_only_an_exact_proven_inventory(monkeypatch, case):
    from hermes_finance.services import source_instrument_events
    from hermes_finance.services.clean_closed_position import infer_closed_position

    isin = "ZZ0000000011"
    redeemed, end = date(2030, 2, 16), date(2030, 3, 31)
    buy = replace(
        trade("BUY", 200000, 0),
        quantity_delta=Decimal(2),
        execution_date=DAY,
        trade_time=f"{DAY}T10:00:00",
        depository_settlement_date=DAY,
    )
    redemption = replace(
        cash("REDEMPTION", 200000),
        event_date=redeemed,
        depository_settlement_date=redeemed,
        quantity_delta=Decimal("-2.0000000001")
        if case == "quantity_above"
        else Decimal("-1.9999999999")
        if case == "quantity_below"
        else Decimal(2)
        if case == "positive_redemption_quantity"
        else Decimal(-2),
        attribution_basis=None if case == "unproved_redemption" else "analytical_full_redemption",
        current=case != "stale_redemption",
        cash_legs=(CashLeg("redemption", redeemed, 200000, -200000, ("r",), "r"),),
    )
    if case == "same_day_purchase":
        buy = replace(
            buy,
            event_date=redeemed,
            execution_date=redeemed,
            trade_time=f"{redeemed}T10:00:00",
            cash_settlement_date=redeemed,
            depository_settlement_date=redeemed,
        )
    events = [buy, redemption, replace(cash("COUPON", 2500), event_key="paid-coupon")]
    if case == "uncounted_trade":
        events.append(
            replace(
                buy,
                event_key="unaccounted-buy",
                counted=False,
                native_trade_amount_kopecks=None,
                reason_codes=("trade_components_missing",),
            )
        )
    if case == "coupon_gap":
        events.append(
            replace(
                cash("COUPON", 3000),
                counted=False,
                reason_codes=("payout_link_unresolved_no_match",),
            )
        )
    if case == "own_custody_gap":
        events.append(
            replace(
                cash("UNRESOLVED", 3000),
                counted=False,
                reason_codes=("custody_cancellation_unresolved",),
            )
        )
    endpoint_reasons = ("bond_valuation_basis_unknown", "missing_endpoint")
    monkeypatch.setattr(
        source_instrument_events,
        "endpoint",
        lambda views, isin, day, kind, **kw: Endpoint(
            day, None, None, None, None, "reported_unknown", reason_codes=endpoint_reasons
        ),
    )
    views = [
        {
            "id": index,
            "covered_from": first,
            "covered_to": last,
            "document": {
                "endpoint_basis": {
                    "beginning_value": "previous_day_eod",
                    "ending_value": "covered_to_eod",
                },
                "positions": positions,
            },
        }
        for index, (first, last, positions) in enumerate(
            [
                (
                    "2030-01-02",
                    "2030-01-31",
                    [
                        {
                            "isin": isin,
                            "beginning_actual_quantity": "0",
                            "actual_quantity": "3"
                            if case == "intermediate_conflict"
                            else "0"
                            if case == "same_day_purchase"
                            else "2",
                        }
                    ],
                ),
                (
                    "2030-02-01",
                    "2030-02-28",
                    [
                        {
                            "isin": isin,
                            "beginning_actual_quantity": "0"
                            if case == "same_day_purchase"
                            else "2",
                            "actual_quantity": "0",
                        }
                    ],
                ),
                (
                    "2030-03-01",
                    "2030-03-31",
                    [{"isin": isin}] if case == "present_in_latest" else [],
                ),
            ],
            1,
        )
    ]
    original = source_instrument_events.analyse(
        views,
        isin,
        "bond",
        START,
        end,
        tuple(events),
        (),
        (
            SimpleNamespace(
                code="custody_cancellation_unresolved", isin=None, month=redeemed.replace(day=1)
            ),
        )
        if case in {"account_custody_gap", "own_custody_gap"}
        else (),
    )
    analysis = infer_closed_position(original, views, isin, "bond")
    result = project_clean_analysis(analysis, isin, instrument_type="bond")
    if case in {"exact", "coupon_gap", "account_custody_gap"}:
        assert analysis.opening.quantity == analysis.closing.quantity == 0
        assert result.opening_value.value == result.closing_value.value == 0
        assert result.buys.value == result.redemption.value == 200000
        assert result.buys.status == result.redemption.status == "supported"
        assert result.sells.value == 0 and result.sells.status == "supported"
        if case != "coupon_gap":
            assert result.pnl.value == 2500
            assert result.pnl.status == (
                "provisional" if case == "account_custody_gap" else "supported"
            )
            if case == "account_custody_gap":
                assert "account_money_unattributed" in result.pnl.assumptions
        else:
            assert result.pnl.value is None
            assert result.coupons.value == 2500 and result.coupons.status == "partial"
            assert "paid_income_incomplete" in result.pnl.reason_codes
            assert not analysis.coverage["payouts"].complete
    else:
        assert analysis is original
        assert result.closing_value.value is None
        assert result.pnl.value is None


@pytest.mark.parametrize("role", ["commission", "nkd"])
def test_outside_trade_with_cost_leg_inside_does_not_break_clean_quantity(role, monkeypatch):
    from hermes_finance.services import source_instrument_events

    start, end = date(2030, 1, 31), date(2030, 2, 28)
    prior, fee_date = date(2030, 1, 16), date(2030, 2, 3)
    instrument_type = "bond" if role == "nkd" else "stock"
    buy = replace(
        trade("BUY", 102000 if role == "nkd" else 100000, 2000 if role == "nkd" else 0),
        quantity_delta=Decimal(1),
        event_date=prior,
        cash_settlement_date=prior,
        depository_settlement_date=prior,
        cash_legs=(
            CashLeg("principal", prior, -100000, 100000, ("principal",), "principal"),
            CashLeg(
                role,
                fee_date,
                -2000 if role == "nkd" else -100,
                2000 if role == "nkd" else 100,
                ("cost",),
                "cost",
            ),
        ),
    )
    endpoints = {
        start: Endpoint(start, Decimal(1), 110000, 110000, 0, "dirty"),
        end: Endpoint(end, Decimal(1), 120000, 120000, 0, "dirty"),
    }
    monkeypatch.setattr(
        source_instrument_events, "endpoint", lambda views, isin, day, kind, **kw: endpoints[day]
    )
    views = [
        {"covered_from": "2030-02-01", "covered_to": "2030-02-28", "document": {"warnings": []}}
    ]
    analysis = source_instrument_events.analyse(
        views, "ZZ0000000011", instrument_type, start, end, (buy,), (), ()
    )
    assert "cross_boundary_settlement" in analysis.coverage["quantity"].reason_codes
    clean = project_clean_analysis(analysis, "ZZ0000000011", instrument_type=instrument_type)
    assert clean.pnl.value == 10000


def test_real_principal_and_delivery_crossing_still_blocks_clean_result():
    prior = date(2029, 12, 20)
    buy = replace(
        trade("BUY", 102000, 2000),
        quantity_delta=Decimal(1),
        cash_settlement_date=DAY,
        depository_settlement_date=prior,
        cash_legs=(CashLeg("principal", DAY, -100000, 100000, ("principal",), "principal"),),
    )
    coverage = {name: Coverage(True) for name in ("events", "quantity", "payouts")}
    coverage["quantity"] = Coverage(False, ("cross_boundary_settlement",))
    analysis = SimpleNamespace(
        opening_date=START,
        closing_date=END,
        opening=Endpoint(START, Decimal(1), 100000, 100000, 0, "dirty"),
        closing=Endpoint(END, Decimal(1), 110000, 110000, 0, "dirty"),
        events=(buy,),
        coverage=coverage,
    )
    clean = project_clean_analysis(analysis, "ZZ0000000011")
    assert clean.pnl.value is None and clean.known_result.value is None


def test_unattributed_row_does_not_hide_reconciled_instrument_trades():
    prior = date(2029, 12, 20)
    buy = replace(
        trade("BUY", 102000, 2000),
        quantity_delta=Decimal(1),
        event_date=prior,
        cash_settlement_date=prior,
        depository_settlement_date=prior,
        cash_legs=(
            CashLeg("principal", prior, -100000, 100000, ("principal",), "principal"),
            CashLeg("commission", DAY, -100, 100, ("fee",), "fee"),
        ),
    )
    unresolved = replace(
        trade("BUY", 102000, 2000),
        event_key="unresolved",
        kind="UNRESOLVED",
        isin=None,
        counted=False,
        reason_codes=("trade_components_missing",),
    )
    coverage = {name: Coverage(True) for name in ("events", "quantity", "payouts")}
    coverage["events"] = Coverage(False, ("trade_components_missing",))
    coverage["quantity"] = Coverage(False, ("cross_boundary_settlement",))
    analysis = SimpleNamespace(
        opening_date=START,
        closing_date=END,
        opening=Endpoint(START, Decimal(1), 100000, 100000, 0, "dirty"),
        closing=Endpoint(END, Decimal(1), 110000, 110000, 0, "dirty"),
        events=(buy, unresolved),
        coverage=coverage,
    )
    clean = project_clean_analysis(analysis, "ZZ0000000011")
    assert clean.pnl.value == clean.known_result.value == 10000


def test_positive_tax_does_not_block_clean_trade_result(monkeypatch):
    from hermes_finance.services import source_instrument_events

    tax = replace(cash("TAX", 100), counted=False, reason_codes=("cost_sign_conflict",))
    buy = replace(
        trade("BUY", 102000, 2000),
        quantity_delta=Decimal(1),
        depository_settlement_date=DAY,
        cash_legs=(CashLeg("principal", DAY, -100000, 100000, ("principal",), "principal"),),
    )
    endpoints = {
        START: Endpoint(START, Decimal(0), 0, 0, 0, "dirty"),
        END: Endpoint(END, Decimal(1), 110000, 110000, 0, "dirty"),
    }
    monkeypatch.setattr(
        source_instrument_events,
        "endpoint",
        lambda views, isin, day, kind, **kw: endpoints[day],
    )
    views = [
        {"covered_from": "2030-01-02", "covered_to": "2030-01-31", "document": {"warnings": []}}
    ]
    analysis = source_instrument_events.analyse(
        views, "ZZ0000000011", "stock", START, END, (buy, tax), (), ()
    )
    assert "cost_sign_conflict" in analysis.coverage["events"].reason_codes
    clean = project_clean_analysis(analysis, "ZZ0000000011")
    assert clean.pnl.value == 8000


def replace_namespace(value, **changes):
    return SimpleNamespace(**(vars(value) | changes))


ISIN = "RU000A000000"


def buy(key, amount, quantity, day):
    return InstrumentEvent(
        event_key=key,
        provider="synthetic",
        native_source_account="synthetic",
        isin=ISIN,
        kind="BUY",
        source_references=(key,),
        event_date=day,
        execution_date=day,
        cash_settlement_date=day,
        depository_settlement_date=day,
        quantity_delta=Decimal(quantity),
        native_trade_amount_kopecks=amount,
        native_total_basis="excludes_paid_nkd",
        accrued_interest_kopecks=None,
        commission_kopecks=None,
    )


def case(events, *, quantity="2", closing=30000, complete=True, coverage=None):
    clean = calculate_clean_return(
        START,
        END,
        0,
        closing,
        tuple(events),
        trades_complete=complete,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=closing is not None,
    )
    analysis = SimpleNamespace(
        opening_date=START,
        closing_date=END,
        events=tuple(events),
        coverage=coverage or {"events": Coverage(complete), "quantity": Coverage(complete)},
        opening=Endpoint(START, Decimal(0), 0, 0, 0, "dirty"),
        closing=Endpoint(END, Decimal(quantity), closing, closing, 0, "dirty"),
    )
    return clean_purchase_price_contributions(analysis, clean, ISIN, instrument_type="stock")


def test_two_purchases_show_different_price_results_without_costs_or_payouts():
    rows = case([buy("a", 10000, "1", date(2030, 1, 10)), buy("b", 20000, "1", date(2030, 1, 11))])
    assert [r["price_result_kopecks"] for r in rows] == ["5000", "-5000"]
    assert [r["cost_kopecks"] for r in rows] == ["10000", "20000"]


def holding_analysis(events, *, days=600, quantity="1", closing=120000):
    first = date(2028, 1, 2)
    start, end = first - timedelta(days=1), first + timedelta(days=days)
    return SimpleNamespace(
        opening_date=start,
        closing_date=end,
        opening=Endpoint(start, Decimal(0), 0, 0, 0, "dirty"),
        closing=Endpoint(end, Decimal(quantity), closing, closing, 0, "dirty"),
        events=tuple(events),
        coverage={name: Coverage(True) for name in ("events", "quantity", "payouts")},
    )


def test_token_early_purchase_cannot_make_recent_capital_eligible_for_xirr():
    first = date(2028, 1, 2)
    analysis = holding_analysis(
        [buy("early", 10000, "1", first), buy("large", 990000, "99", first + timedelta(days=320))],
        days=400,
        quantity="100",
        closing=1100000,
    )
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert result.simple_return.value == Decimal("0.1")
    assert result.xirr.holding_days == 400
    assert result.xirr.weighted_holding_days == Decimal("83.2")
    assert result.xirr.value is None
    assert result.xirr.reason_codes == ("short_holding",)


def test_fifo_holding_projection_does_not_repeat_interval_solver(monkeypatch):
    from hermes_finance.domain import clean_instrument_return as domain

    calculate = domain.calculate_interval_return
    calls = []

    def observed(*args):
        calls.append(args[:2])
        return calculate(*args)

    monkeypatch.setattr(domain, "calculate_interval_return", observed)
    analysis = holding_analysis([buy("lot", 100000, "1", date(2028, 1, 2))])
    project_clean_analysis(analysis, ISIN, instrument_type="stock", include_position_rates=False)
    baseline = list(calls)
    calls.clear()
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert result.xirr.weighted_holding_days == 600
    assert result.xirr.value is not None
    assert calls == baseline


@pytest.mark.parametrize("days", [364, 365, 730])
def test_complete_long_lot_is_eligible_at_exactly_365_weighted_days(days):
    analysis = holding_analysis([buy("lot", 100000, "1", date(2028, 1, 2))], days=days)
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert result.simple_return.value == Decimal("0.2")
    assert result.xirr.weighted_holding_days == days
    assert (result.xirr.value is not None) == (days >= 365)


def test_partial_fifo_sales_weight_each_disposed_part_and_open_remainder():
    first = date(2028, 1, 2)
    events = [
        buy("lot", 120000, "4", first),
        replace(buy("sale1", 40000, "-1", first + timedelta(days=100)), kind="SELL"),
        replace(buy("sale2", 40000, "-1", first + timedelta(days=200)), kind="SELL"),
    ]
    analysis = holding_analysis(events, quantity="2", closing=80000)
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert result.xirr.holding_days == 600
    assert result.xirr.weighted_holding_days == Decimal(375)  # (100 + 200 + 2*600)/4
    assert result.xirr.value is not None
    purchases = clean_purchase_price_contributions(analysis, result, ISIN, instrument_type="stock")
    assert purchases[0]["remaining_quantity"] == "2"
    assert purchases[0]["cost_kopecks"] == "120000"
    assert purchases[0]["sale_proceeds_kopecks"] == "80000"


def test_holding_weights_include_nkd_and_do_not_round_fractional_days_to_threshold():
    first = date(2028, 1, 2)
    events = [
        replace(buy("early", 100000, "1", first), accrued_interest_kopecks=900000),
        buy("late", 9000000, "9", first + timedelta(days=1)),
    ]
    analysis = holding_analysis(events, days=365, quantity="10", closing=11000000)
    result = project_clean_analysis(analysis, ISIN, instrument_type="bond")
    assert result.simple_return.invested_kopecks == 10000000
    assert result.simple_return.value == Decimal("0.1")
    assert result.xirr.weighted_holding_days == Decimal("364.1")
    assert result.xirr.reason_codes == ("short_holding",)


def test_sale_crossing_lots_uses_each_purchase_cost_and_its_own_remaining_quantity():
    first = date(2028, 1, 2)
    analysis = holding_analysis(
        [
            buy("early", 100000, "2", first),
            buy("late", 300000, "2", first + timedelta(days=100)),
            replace(buy("sale", 330000, "-3", first + timedelta(days=200)), kind="SELL"),
        ],
        quantity="1",
        closing=180000,
    )
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    # Early lot: 200 days. Late lot: half 100 days, half 500 days.
    assert result.xirr.weighted_holding_days == Decimal(275)
    assert result.simple_return.invested_kopecks == 400000
    assert result.simple_return.value == Decimal("0.275")
    assert result.xirr.reason_codes == ("short_holding",)


@pytest.mark.parametrize("days", [100, 365])
def test_fifo_closed_position_does_not_age_until_report_end(days):
    first = date(2028, 1, 2)
    analysis = holding_analysis(
        [
            buy("lot", 100000, "1", first),
            replace(buy("sale", 120000, "-1", first + timedelta(days=days)), kind="SELL"),
        ],
        quantity="0",
        closing=0,
    )
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert result.xirr.holding_days == days
    assert result.xirr.weighted_holding_days == days
    assert result.xirr.holding_end_date == first + timedelta(days=days)
    assert (result.xirr.value is not None) == (days >= 365)


@pytest.mark.parametrize("gap", ["no_delivery", "ambiguous_order", "redemption"])
def test_no_complete_fifo_keeps_simple_return_and_withholds_holding_period(gap):
    first = date(2028, 1, 2)
    events = [buy("lot", 100000, "2", first)]
    quantity = "2"
    if gap == "no_delivery":
        events[0] = replace(events[0], depository_settlement_date=None)
    elif gap == "ambiguous_order":
        events.append(replace(buy("sale", 60000, "-1", first), kind="SELL"))
        quantity = "1"
    else:
        day = first + timedelta(days=400)
        events.append(
            replace(
                cash("REDEMPTION", 100000),
                isin=ISIN,
                event_date=day,
                depository_settlement_date=day,
                quantity_delta=Decimal(-2),
                cash_legs=(CashLeg("redemption", day, 100000, -100000, ("r",), "r"),),
            )
        )
        quantity = "0"
    analysis = holding_analysis(events, quantity=quantity, closing=0 if quantity == "0" else 120000)
    result = project_clean_analysis(analysis, ISIN, instrument_type="stock")
    assert result.simple_return.value is not None
    assert result.xirr.holding_days >= 365
    assert result.xirr.weighted_holding_days is None
    assert result.xirr.value is None
    assert result.xirr.reason_codes == ("holding_period_unknown",)


def test_fifo_partial_sale_uses_original_cost_and_matches_instrument_price_result():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 11))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 12)), kind="SELL")
    rows = case([first, second, sale], quantity="1", closing=15000)
    assert [r["price_result_kopecks"] for r in rows] == ["8000", "-5000"]
    assert [r["remaining_quantity"] for r in rows] == ["0", "1"]
    assert [r["return_fraction"] for r in rows] == ["0.8", "-0.25"]
    assert sum(int(row["price_result_kopecks"]) for row in rows) == 3000


def test_sale_assumption_applies_only_to_lots_consumed_by_that_sale():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 11))
    sale = replace(
        buy("sale", 18000, "-1", date(2030, 1, 12)),
        kind="SELL",
        assumptions=("income_assumed",),
    )
    rows = case([first, second, sale], quantity="1", closing=15000)
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["return_fraction"] == "0.8"
    assert rows[0]["status"] == "partial" and rows[0]["reason_codes"] == ["income_assumed"]
    assert rows[1]["price_result_kopecks"] == "-5000" and rows[1]["status"] == "supported"


def test_fifo_full_sale_and_unattributed_payout_stays_at_instrument():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 12)), kind="SELL")
    payout = cash("DIVIDEND", 12000)
    row = case([first, sale, payout], quantity="0", closing=0)[0]
    assert row["remaining_quantity"] == "0"
    assert row["price_result_kopecks"] == "8000" and row["return_fraction"] == "0.8"


def test_closed_purchase_survives_unknown_closing_value_of_open_purchase():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    second = buy("b", 20000, "1", date(2030, 1, 12))
    rows = case([first, sale, second], quantity="1", closing=None)
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["return_fraction"] == "0.8"
    assert rows[0]["value_kopecks"] == "0" and rows[0]["status"] == "supported"
    assert rows[1]["cost_kopecks"] == "20000" and rows[1]["remaining_quantity"] == "1"
    assert rows[1]["value_kopecks"] is rows[1]["price_result_kopecks"] is None
    assert "closing_value_unknown" in rows[1]["reason_codes"]


def test_closed_purchase_survives_later_unknown_clean_purchase_amount():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    second = replace(
        buy("b", 20000, "1", date(2030, 1, 12)),
        native_total_basis=None,
        counted=False,
        reason_codes=("trade_nkd_basis_unknown",),
    )
    coverage = {
        "events": Coverage(False, ("trade_nkd_basis_unknown",)),
        "quantity": Coverage(
            False, ("quantity_events_incomplete", "quantity_reconciliation_mismatch")
        ),
    }
    rows = case([first, sale, second], quantity="1", closing=15000, coverage=coverage)
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["return_fraction"] == "0.8"
    assert rows[1]["cost_kopecks"] is None and rows[1]["value_kopecks"] == "15000"
    assert rows[1]["price_result_kopecks"] is None


def test_unordered_later_buys_without_later_sales_do_not_hide_closed_purchase():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    second = buy("b", 20000, "1", date(2030, 1, 12))
    third = buy("c", 10000, "1", date(2030, 1, 12))
    rows = case([first, sale, second, third], quantity="2", closing=30000)
    assert [r["price_result_kopecks"] for r in rows] == ["8000", "-5000", "5000"]


def test_later_ambiguous_sale_leaves_already_closed_purchase_known():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    second = buy("b", 20000, "1", date(2030, 1, 12))
    third = buy("c", 10000, "1", date(2030, 1, 12))
    last_sale = replace(buy("last-sale", 15000, "-1", date(2030, 1, 13)), kind="SELL")
    rows = case([first, sale, second, third, last_sale], quantity="1", closing=15000)
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["status"] == "supported"
    assert all(
        row["remaining_quantity"] is None and row["price_result_kopecks"] is None
        for row in rows[1:]
    )


def test_same_day_buys_fully_sold_together_have_order_independent_results():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 30000, "-2", date(2030, 1, 11)), kind="SELL")
    rows = case([first, second, sale], quantity="0", closing=0)
    assert [r["price_result_kopecks"] for r in rows] == ["5000", "-5000"]
    assert [r["return_fraction"] for r in rows] == ["0.5", "-0.25"]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("sale_day", [10, 11])
def test_same_instant_buys_fully_consumed_by_one_sale(reverse, sale_day):
    first = replace(buy("a", 50000, "5", date(2030, 1, 10)), trade_time="2030-01-10T09:00:00")
    second = replace(buy("b", 60000, "5", date(2030, 1, 10)), trade_time=first.trade_time)
    sale = replace(
        buy("sale", 130000, "-10", date(2030, 1, sale_day)),
        kind="SELL",
        trade_time=f"2030-01-{sale_day:02}T10:00:00",
    )
    events = [first, second, sale]
    rows = case(events[::-1] if reverse else events, quantity="0", closing=0)
    assert [r["cost_kopecks"] for r in rows] == ["50000", "60000"]
    assert [r["sale_proceeds_kopecks"] for r in rows] == ["65000", "65000"]
    assert [r["remaining_quantity"] for r in rows] == ["0", "0"]
    assert [r["price_result_kopecks"] for r in rows] == ["15000", "5000"]
    with localcontext() as context:
        context.prec = 200
        assert [r["return_fraction"] for r in rows] == ["0.3", str(Decimal(5000) / 60000)]


@pytest.mark.parametrize("sales", [1, 2])
@pytest.mark.parametrize("sale_time", ["09:00:00", "10:00:00"])
def test_same_instant_order_dependent_purchases_remain_unknown(sales, sale_time):
    first = replace(buy("a", 50000, "5", date(2030, 1, 10)), trade_time="2030-01-10T09:00:00")
    second = replace(buy("b", 60000, "5", date(2030, 1, 10)), trade_time=first.trade_time)
    sale = replace(
        buy("sale", 70000, "-5", date(2030, 1, 10)),
        kind="SELL",
        trade_time=f"2030-01-10T{sale_time}",
    )
    events = [first, second, sale]
    if sales == 2:
        events.append(
            replace(
                sale,
                event_key="sale2",
                trade_time="2030-01-10T11:00:00",
                native_trade_amount_kopecks=60000,
            )
        )
    rows = case(events, quantity="5" if sales == 1 else "0", closing=65000 if sales == 1 else 0)
    assert all(r["price_result_kopecks"] is None and r["return_fraction"] is None for r in rows)
    assert all("fifo_order_ambiguous" in r["reason_codes"] for r in rows)


def test_same_instant_group_untouched_after_sale_of_older_lot():
    older = replace(buy("older", 10000, "1", date(2030, 1, 10)), trade_time="2030-01-10T08:00:00")
    first = replace(buy("a", 50000, "5", date(2030, 1, 10)), trade_time="2030-01-10T09:00:00")
    second = replace(buy("b", 60000, "5", date(2030, 1, 10)), trade_time=first.trade_time)
    sale = replace(
        buy("sale", 12000, "-1", date(2030, 1, 10)), kind="SELL", trade_time="2030-01-10T10:00:00"
    )
    rows = case([older, first, second, sale], quantity="10", closing=130000)
    assert [r["remaining_quantity"] for r in rows] == ["0", "5", "5"]
    assert [r["price_result_kopecks"] for r in rows] == ["2000", "15000", "5000"]


@pytest.mark.parametrize("sales", [1, 2])
def test_unordered_buys_split_between_sales_keep_affected_results_unknown(sales):
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    events = [first, second, sale]
    if sales == 2:
        events.append(replace(buy("sale2", 12000, "-1", date(2030, 1, 12)), kind="SELL"))
    rows = case(events, quantity=str(2 - sales), closing=15000 if sales == 1 else 0)
    assert all(row["price_result_kopecks"] is None for row in rows)
    assert all("fifo_order_ambiguous" in row["reason_codes"] for row in rows)


def test_unordered_buys_behind_older_purchase_do_not_hide_sale_of_that_purchase():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 11))
    third = buy("c", 10000, "1", date(2030, 1, 11))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 12)), kind="SELL")
    rows = case([first, second, third, sale], quantity="2", closing=30000)
    assert [r["price_result_kopecks"] for r in rows] == ["8000", "-5000", "5000"]


def test_purchase_after_ambiguous_partial_sale_keeps_its_exact_value():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    third = buy("c", 10000, "1", date(2030, 1, 12))
    rows = case([first, second, sale, third], quantity="2", closing=30000)
    assert all(row["price_result_kopecks"] is None for row in rows[:2])
    assert rows[2]["remaining_quantity"] == "1" and rows[2]["value_kopecks"] == "15000"
    assert rows[2]["price_result_kopecks"] == "5000" and rows[2]["return_fraction"] == "0.5"
    uncertain_kopeck = case([first, second, sale, third], quantity="2", closing=30001)
    assert uncertain_kopeck[2]["remaining_quantity"] == "1"
    assert uncertain_kopeck[2]["value_kopecks"] is None
    assert uncertain_kopeck[2]["price_result_kopecks"] is None


def test_later_unknown_sale_proceeds_do_not_hide_earlier_closed_purchase():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 11)), kind="SELL")
    second = buy("b", 20000, "1", date(2030, 1, 12))
    unknown_sale = replace(
        buy("sale-b", 15000, "-1", date(2030, 1, 13)),
        kind="SELL",
        native_trade_amount_kopecks=None,
        counted=False,
        reason_codes=("trade_components_missing",),
    )
    coverage = {
        "events": Coverage(False, ("trade_components_missing",)),
        "quantity": Coverage(
            False, ("quantity_events_incomplete", "quantity_reconciliation_mismatch")
        ),
    }
    rows = case([first, sale, second, unknown_sale], quantity="0", closing=0, coverage=coverage)
    assert rows[0]["price_result_kopecks"] == "8000" and rows[0]["return_fraction"] == "0.8"
    assert rows[1]["remaining_quantity"] == "0" and rows[1]["sale_proceeds_kopecks"] is None
    assert rows[1]["price_result_kopecks"] is None


def test_fifo_excludes_fees_and_keeps_nkd_in_buy_and_sale():
    first = replace(
        buy("a", 10200, "1", date(2030, 1, 10)),
        native_total_basis="includes_paid_nkd",
        accrued_interest_kopecks=200,
        commission_kopecks=600,
    )
    sale = replace(
        buy("sale", 18300, "-1", date(2030, 1, 12)),
        kind="SELL",
        native_total_basis="includes_paid_nkd",
        accrued_interest_kopecks=300,
        commission_kopecks=1100,
    )
    row = case([first, sale, cash("FEE", -900), cash("TAX", -1300)], quantity="0", closing=0)[0]
    assert row["cost_kopecks"] == "10200" and row["sale_proceeds_kopecks"] == "18300"
    assert row["price_result_kopecks"] == "8100"
    with localcontext() as context:
        context.prec = 200
        assert Decimal(row["return_fraction"]) == Decimal(8100) / Decimal(10200)


def test_fifo_rejects_ambiguous_same_day_order_and_zero_cost_rate_is_unknown():
    first = buy("a", 0, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 100, "-1", date(2030, 1, 10)), kind="SELL")
    ambiguous = case([first, sale], quantity="0", closing=0)
    assert ambiguous[0]["price_result_kopecks"] is None
    assert "fifo_order_ambiguous" in ambiguous[0]["reason_codes"]
    sold_next_day = replace(
        sale,
        event_date=date(2030, 1, 11),
        execution_date=date(2030, 1, 11),
        cash_settlement_date=date(2030, 1, 11),
        depository_settlement_date=date(2030, 1, 11),
    )
    row = case([first, sold_next_day], quantity="0", closing=0)[0]
    assert row["price_result_kopecks"] == "100" and row["return_fraction"] is None


@pytest.mark.parametrize("kind", ["BUY", "SELL"])
@pytest.mark.parametrize("field", ["cash_settlement_date", "depository_settlement_date"])
def test_fifo_rejects_settlement_or_delivery_before_execution(kind, field):
    first = buy("a", 10000, "1", date(2030, 1, 10))
    sale = replace(buy("sale", 12000, "-1", date(2030, 1, 12)), kind="SELL")
    target = first if kind == "BUY" else sale
    inconsistent = replace(
        target, **{field: target.execution_date.replace(day=target.execution_date.day - 1)}
    )
    events = [inconsistent, sale] if kind == "BUY" else [first, inconsistent]
    assert case(events, quantity="0", closing=0) is None


@pytest.mark.parametrize("field", ["cash_settlement_date", "depository_settlement_date"])
def test_fifo_requires_both_settlement_dates_inside_period_and_accepts_end(field):
    first = buy("a", 10000, "1", date(2030, 1, 10))
    assert case([replace(first, **{field: START})], quantity="1", closing=11000) is None
    end_day = buy("end", 10000, "1", END)
    result = case([end_day], quantity="1", closing=11000)
    assert result[0]["price_result_kopecks"] == "1000"


def test_fifo_rejects_mismatched_execution_date_and_native_timestamp():
    event = replace(buy("a", 10000, "1", date(2030, 1, 10)), trade_time="2030-01-11T09:00:00")
    assert case([event], quantity="1", closing=11000) is None


def test_observed_purchase_fallback_requires_unique_current_identity_and_clean_cost():
    original = replace(buy("a", 10000, "1", date(2030, 1, 10)), native_identity="native-a")
    rows = case([original], quantity="2", closing=11000, complete=False)
    assert rows and rows[0]["cost_kopecks"] == "10000"
    assert rows[0]["status"] == "partial" and rows[0]["price_result_kopecks"] is None
    assert rows[0]["remaining_quantity"] is None and rows[0]["return_fraction"] is None
    duplicate = replace(original, event_key="duplicate")
    assert case([original, duplicate], quantity="2", closing=22000, complete=False) is None
    conflict = replace(duplicate, counted=False, reason_codes=("overlapping_trade_conflict",))
    assert case([original, conflict], quantity="2", closing=22000, complete=False) is None
    assert (
        case([replace(original, current=False)], quantity="1", closing=11000, complete=False)
        is None
    )
    assert (
        case(
            [replace(original, native_total_basis=None)],
            quantity="1",
            closing=11000,
            complete=False,
        )
        is None
    )
    zero = case(
        [replace(original, native_trade_amount_kopecks=0)],
        quantity="1",
        closing=11000,
        complete=False,
    )
    assert zero[0]["cost_kopecks"] == "0" and zero[0]["return_fraction"] is None


@pytest.mark.parametrize("outside", [None, "cash_settlement_date", "depository_settlement_date"])
def test_observed_purchase_fallback_requires_both_settlements_in_period(outside):
    event = replace(
        buy("a", 10000, "1", START),
        native_identity="native-a",
        cash_settlement_date=date(2030, 1, 2),
        depository_settlement_date=date(2030, 1, 2),
    )
    if outside:
        event = replace(event, **{outside: START})
    rows = case([event], quantity="1", closing=11000, complete=False)
    if outside:
        assert rows is None
    else:
        assert rows and rows[0]["date"] == START and rows[0]["cost_kopecks"] == "10000"


@pytest.mark.parametrize("role", ["principal", "native_money"])
def test_fifo_checks_actual_linked_money_date_not_only_native_settlement(role):
    day = date(2030, 1, 9)
    event = replace(
        buy("a", 10000, "1", date(2030, 1, 10)),
        attribution_basis="native_money_group_bridge"
        if role == "native_money"
        else "matched_money",
        cash_legs=(CashLeg(role, day, -10000, 10000, ("synthetic",), "synthetic"),),
    )
    assert case([event], quantity="1", closing=11000) is None


def test_purchase_cost_keeps_nkd_and_missing_commission_does_not_block():
    event = replace(
        buy("bond", 10200, "1", date(2030, 1, 10)),
        native_total_basis="includes_paid_nkd",
        accrued_interest_kopecks=200,
        commission_kopecks=None,
        counted=False,
        reason_codes=("trade_components_missing",),
    )
    result = case([event], quantity="1", closing=11000)
    assert result[0]["cost_kopecks"] == "10200"
    assert result[0]["price_result_kopecks"] == "800"


def test_zero_and_rounding_are_known_and_add_to_total():
    rows = case(
        [buy("a", 100, "1", date(2030, 1, 10)), buy("b", 100, "1", date(2030, 1, 11))], closing=201
    )
    assert sum(int(row["value_kopecks"]) for row in rows) == 201
    assert any(row["price_result_kopecks"] == "0" for row in rows)


@pytest.mark.parametrize("shape", ["sale", "quantity", "missing_date", "wrong_isin"])
def test_unknown_or_disposed_inventory_does_not_invent_results(shape):
    one = buy("a", 10000, "1", date(2030, 1, 10))
    two = buy("b", 20000, "1", date(2030, 1, 11))
    if shape == "sale":
        two = replace(two, kind="SELL", quantity_delta=Decimal(-1))
    if shape == "missing_date":
        two = replace(two, depository_settlement_date=None)
    if shape == "wrong_isin":
        two = replace(two, isin="RU000A000001")
    assert (
        case(
            [one, two],
            quantity="3" if shape == "quantity" else "2",
            closing=None if shape == "missing_value" else 30000,
        )
        is None
    )


def scoped_case(*, payout_reasons=("unattributed_income",), other=()):
    buy = replace(
        trade("BUY", 102000, 2000),
        quantity_delta=Decimal(1),
        execution_date=DAY,
        trade_time="2030-01-16T10:00:00",
        depository_settlement_date=DAY,
        cash_legs=(CashLeg("principal", DAY, -100000, 100000, ("principal",), "principal"),),
    )
    coverage = {name: Coverage(True) for name in ("events", "quantity")}
    coverage["events"] = Coverage(False, ("unrecognized_money", "unparsed_source_rows"))
    coverage["quantity"] = Coverage(False, ("4_Transfers_unsupported",))
    coverage["payouts"] = Coverage(False, payout_reasons)
    unknown = replace(
        cash("FEE", -100),
        kind="UNRESOLVED",
        isin=None,
        counted=False,
        current=False,
        reason_codes=("unrecognized_money",),
    )
    return SimpleNamespace(
        opening_date=START,
        closing_date=END,
        opening=Endpoint(START, Decimal(0), 0, None, None, "reported_unknown"),
        closing=Endpoint(
            END,
            Decimal(1),
            99000,
            None,
            None,
            "reported_unknown",
            (),
            ("bond_valuation_basis_unknown",),
        ),
        events=(buy, unknown, *other),
        coverage=coverage,
    )


def test_account_rows_of_other_issues_do_not_hide_a_reconciled_bond():
    result = project_clean_analysis(scoped_case(), "ZZ0000000011", instrument_type="bond")
    assert result.closing_value.value == 99000
    assert result.buys.value == 102000
    assert result.pnl.value == -3000
    assert result.pnl.status == "provisional"
    assert result.pnl.assumptions == ("account_money_unattributed",)


@pytest.mark.parametrize(
    "instrument_type, amortization_isin, incomplete",
    [
        ("bond", None, True),
        ("bond", "ZZ0000000011", True),
        ("bond", "ZZ0000000029", False),
        ("stock", None, False),
        ("fund", None, False),
    ],
)
def test_amortization_gap_is_scoped_to_potentially_affected_bonds(
    instrument_type, amortization_isin, incomplete
):
    amortization = replace(
        cash("COUPON", 25000),
        event_key="amortization",
        kind="UNRESOLVED",
        isin=amortization_isin,
        classification="unknown",
        counted=False,
        current=False,
        reason_codes=("redemption_amortization_unsupported", "unrecognized_money"),
    )
    analysis = scoped_case(payout_reasons=(), other=(amortization,))
    analysis.events = (
        replace(analysis.events[0], native_identity="synthetic-buy"),
        *analysis.events[1:],
    )
    analysis.coverage["events"] = Coverage(False, amortization.reason_codes)
    analysis.coverage["quantity"] = Coverage(False, ("redemption_amortization_unsupported",))
    analysis.closing = Endpoint(END, Decimal(1), 77000, 77000, 0, "dirty")
    clean = project_clean_analysis(analysis, "ZZ0000000011", instrument_type=instrument_type)
    purchases = clean_purchase_price_contributions(
        analysis, clean, "ZZ0000000011", instrument_type=instrument_type
    )
    assert purchases and len(purchases) == 1
    if incomplete:
        assert clean.redemption.value is None
        assert "redemption_incomplete" in clean.redemption.reason_codes
        assert clean.pnl.value is clean.simple_return.value is None
        assert clean.valuation_and_trades.value is None
        assert "redemption_incomplete" in clean.pnl.reason_codes
        assert purchases[0]["status"] == "partial"
        assert purchases[0]["price_result_kopecks"] is None
        assert purchases[0]["return_fraction"] is None
    else:
        assert clean.redemption.value == 0
        assert clean.pnl.value == -25000
        assert clean.simple_return.value is not None
        assert purchases[0]["price_result_kopecks"] == "-25000"


def test_owned_full_redemption_does_not_create_another_bonds_amortization_gap():
    redemption = replace(
        cash("REDEMPTION", 100000),
        isin="ZZ0000000029",
        quantity_delta=Decimal(-1),
        depository_settlement_date=DAY,
        attribution_basis="analytical_full_redemption",
    )
    analysis = scoped_case(payout_reasons=(), other=(redemption,))
    clean = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert clean.redemption.value == 0
    assert clean.redemption.status == "supported"
    assert clean.pnl.value == -3000
    assert "redemption_incomplete" not in clean.pnl.reason_codes


@pytest.mark.parametrize(
    "amortization_date, incomplete",
    [(START, False), (DAY, True), (END, True), (END + timedelta(days=1), False)],
)
def test_carried_bond_without_trades_keeps_period_amortization_unknown(
    amortization_date, incomplete
):
    amortization = replace(
        cash("COUPON", 25000),
        kind="UNRESOLVED",
        isin=None,
        event_date=amortization_date,
        cash_legs=(CashLeg("unknown", amortization_date, 25000, -25000, ("m",), "m"),),
        counted=False,
        current=False,
        reason_codes=("redemption_amortization_unsupported", "unrecognized_money"),
    )
    analysis = scoped_case(payout_reasons=())
    analysis.events = (amortization,)
    analysis.opening = Endpoint(START, Decimal(1), 102000, 102000, 0, "dirty")
    analysis.closing = Endpoint(END, Decimal(1), 77000, 77000, 0, "dirty")
    analysis.coverage["events"] = Coverage(False, amortization.reason_codes)
    analysis.coverage["quantity"] = Coverage(True)
    clean = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    if incomplete:
        assert clean.redemption.value is None
        assert "redemption_incomplete" in clean.pnl.reason_codes
    else:
        assert clean.redemption.value == 0
        assert "redemption_incomplete" not in clean.pnl.reason_codes


def test_own_payout_conflict_still_withholds_the_full_result():
    analysis = scoped_case(payout_reasons=("pdf_xml_payout_mismatch",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value is None
    assert result.valuation_and_trades.value == -3000


def test_unreconciled_quantity_keeps_account_gaps():
    analysis = scoped_case()
    analysis.closing = replace(analysis.closing, quantity=Decimal(2))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value is None and result.valuation_and_trades.value is None


def test_trade_money_keeps_statement_total_and_tolerates_unknown_nkd():
    assert trade_amount_with_nkd(trade("BUY", 102000, 2000)) == 102000
    excluded = trade("BUY", 100000, 2000, basis="excludes_paid_nkd")
    assert trade_amount_with_nkd(excluded) == 102000
    assert trade_amount_with_nkd(replace(excluded, accrued_interest_kopecks=None)) == 100000
    assert trade_amount_with_nkd(trade("BUY", None, 2000)) is None


def test_face_value_note_is_not_a_trade_amount_assumption():
    event = replace(trade("BUY", 102000, 2000), assumptions=("trade_face_value_missing",))
    assert clean_trade_assumptions(event) == ()


def test_return_rate_starts_at_the_first_trade_of_an_empty_position():
    result = calc((trade("BUY", 102000, 2000),))
    with localcontext() as context:
        context.prec = 60
        assert result.modified_dietz.value == Decimal(8000) / Decimal(102000)


class FakeResolver:
    def __init__(self, *rows):
        self.instruments = {
            index: SimpleNamespace(name=name, isin=isin, instrument_type="bond")
            for index, (name, isin) in enumerate(rows, 1)
        }


def issuer_view(
    *isins, settled="2030-01-05", quantity="1", positions=(), covered_from="2030-01-01"
):
    trades = [
        {
            "state": "settled",
            "settlement_date": settled,
            "core": {"isin": isin, "source_account": "a", "quantity": quantity},
        }
        for isin in isins
    ]
    view = {
        "covered_from": covered_from,
        "covered_to": "2031-12-31",
        "document": {"trades": trades, "positions": list(positions)},
    }
    return (None, view, None)


@pytest.mark.parametrize(
    "rows, isins, day, found",
    [
        ((("Agro 001P-01", "ZZ0000000011"),), ("ZZ0000000011",), "2030-02-01", True),
        (
            (("Agro 001P-01", "ZZ0000000011"), ("Agro 001P-02", "ZZ0000000029")),
            ("ZZ0000000011", "ZZ0000000029"),
            "2030-02-01",
            False,
        ),
        ((("Other 001P-01", "ZZ0000000011"),), ("ZZ0000000011",), "2030-02-01", False),
        ((("Agro 001P-01", "ZZ0000000011"),), ("ZZ0000000029",), "2030-02-01", False),
        ((("Agro 001P-01", "ZZ0000000011"),), ("ZZ0000000011",), "2030-01-01", False),
        # A second issue absent from the catalogue may be the coupon's real bond.
        (
            (("Agro 001P-01", "ZZ0000000011"),),
            ("ZZ0000000011", "ZZ0000000029"),
            "2030-02-01",
            False,
        ),
    ],
)
def test_issuer_identifies_a_coupon_only_for_one_bond_held_in_the_account(rows, isins, day, found):
    from hermes_finance.services.source_return_evidence import _issuer_bond_in_account

    security = SimpleNamespace(issuer_name='ООО "Agro"')
    selected = [issuer_view(*isins)]
    match = _issuer_bond_in_account(
        FakeResolver(*rows), security, "unresolved_no_match", selected, "a", day
    )
    assert (match is not None) == found


@pytest.mark.parametrize("status", ["unresolved_ambiguous", "linked"])
def test_issuer_never_overrides_a_conflicting_coupon_identity(status):
    from hermes_finance.services.source_return_evidence import _issuer_bond_in_account

    security = SimpleNamespace(issuer_name='ООО "Agro"')
    resolver = FakeResolver(("Agro 001P-01", "ZZ0000000011"))
    selected = [issuer_view("ZZ0000000011")]
    assert not _issuer_bond_in_account(resolver, security, status, selected, "a", "2030-02-01")


def test_incoming_position_of_another_issue_keeps_the_coupon_unattributed():
    from hermes_finance.services.source_return_evidence import _issuer_bond_in_account

    security = SimpleNamespace(issuer_name='ООО "Agro"')
    resolver = FakeResolver(("Agro 001P-01", "ZZ0000000011"), ("Agro 001P-02", "ZZ0000000029"))
    incoming = {
        "isin": "ZZ0000000029",
        "source_account": "a",
        "beginning_actual_quantity": "5",
        "actual_quantity": "5",
    }
    selected = [issuer_view("ZZ0000000011", positions=(incoming,))]
    assert not _issuer_bond_in_account(
        resolver, security, "unresolved_no_match", selected, "a", "2030-02-01"
    )


def test_opening_position_counts_from_the_day_before_its_statement():
    from hermes_finance.services.source_return_evidence import _issuer_bond_in_account

    security = SimpleNamespace(issuer_name='ООО "Agro"')
    resolver = FakeResolver(("Agro 001P-01", "ZZ0000000011"), ("Agro 001P-02", "ZZ0000000029"))
    incoming = {
        "isin": "ZZ0000000029",
        "source_account": "a",
        "beginning_actual_quantity": "5",
    }
    selected = [
        issuer_view("ZZ0000000011"),
        issuer_view(positions=(incoming,), covered_from="2031-01-01"),
    ]
    assert not _issuer_bond_in_account(
        resolver, security, "unresolved_no_match", selected, "a", "2030-12-31"
    )


def test_a_sale_alone_does_not_make_the_issuer_bond_held():
    from hermes_finance.services.source_return_evidence import _issuer_bond_in_account

    security = SimpleNamespace(issuer_name='ООО "Agro"')
    resolver = FakeResolver(("Agro 001P-01", "ZZ0000000011"))
    selected = [issuer_view("ZZ0000000011", quantity="-1")]
    assert not _issuer_bond_in_account(
        resolver, security, "unresolved_no_match", selected, "a", "2030-02-01"
    )


def own_money(index, amount, *, nkd_money=True):
    return replace(
        cash("FEE", amount),
        kind="UNRESOLVED",
        event_key=f"money-{index}",
        counted=False,
        current=False,
        cash_legs=(
            CashLeg("trade_settlement", DAY, amount, -amount, ("money",), "trade_settlement"),
        ),
        reason_codes=("unmatched_trade_money",),
        nkd_money=nkd_money,
    )


def test_money_without_nkd_wording_is_not_trade_nkd():
    analysis = scoped_case(other=(own_money(0, -2000, nkd_money=False),))
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value is None


def test_nkd_already_linked_to_the_trade_cannot_prove_a_second_row():
    analysis = scoped_case(other=(own_money(0, -2000),))
    buy = analysis.events[0]
    leg = CashLeg("nkd", DAY, -2000, 2000, ("linked",), "money:linked")
    analysis.events = (replace(buy, cash_legs=(*buy.cash_legs, leg)), *analysis.events[1:])
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value is None


def test_derived_nkd_leg_does_not_stop_the_nkd_row_proof():
    analysis = scoped_case(other=(own_money(0, -2000),))
    buy = analysis.events[0]
    leg = CashLeg("nkd", DAY, -2000, 2000, ("trade",), "trade:BUY:nkd")
    analysis.events = (replace(buy, cash_legs=(*buy.cash_legs, leg)), *analysis.events[1:])
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value == -3000


def account_money(reason="unmatched_trade_money"):
    return replace(own_money(9, -2500), isin=None, reason_codes=(reason,), nkd_money=False)


def test_unidentified_trade_money_stays_visible_with_a_note():
    analysis = scoped_case(payout_reasons=(), other=(account_money(),))
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value == -3000
    assert result.pnl.assumptions == ("account_money_unattributed",)
    rows = clean_purchase_price_contributions(
        analysis, result, "ZZ0000000011", instrument_type="bond"
    )
    assert rows[0]["price_result_kopecks"] == "-3000"
    assert rows[0]["status"] == "partial"
    assert rows[0]["reason_codes"] == ["account_money_unattributed"]


@pytest.mark.parametrize(
    "amounts, proven",
    [((-2000,), True), ((-12000,), False), ((-2000, -2000), False), ((2000,), False)],
)
def test_own_money_row_is_ignored_only_as_nkd_of_an_own_trade(amounts, proven):
    rows = tuple(own_money(index, amount) for index, amount in enumerate(amounts))
    analysis = scoped_case(other=rows)
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value == (-3000 if proven else None)
    purchases = clean_purchase_price_contributions(
        analysis, result, "ZZ0000000011", instrument_type="bond"
    )
    assert (purchases is not None and purchases[0]["price_result_kopecks"] == "-3000") == proven


def collision(*isins):
    return replace(
        trade("BUY", 500, 0),
        event_key="collision",
        isin=None,
        counted=False,
        reason_codes=("overlapping_trade_conflict",),
        collision_isins=isins,
    )


@pytest.mark.parametrize(
    "isins, visible",
    [
        (("ZZ0000000029", "ZZ0000000037"), True),
        (("ZZ0000000011", "ZZ0000000029"), False),
        ((), False),
    ],
)
def test_trade_collision_blocks_only_the_issues_it_concerns(isins, visible):
    analysis = scoped_case(other=(collision(*isins),))
    analysis.coverage["events"] = Coverage(False, ("overlapping_trade_conflict",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert (result.pnl.value == -3000) == visible
    purchases = clean_purchase_price_contributions(
        analysis, result, "ZZ0000000011", instrument_type="bond"
    )
    assert (purchases is not None and purchases[0]["remaining_quantity"] == "1") == visible


def test_alternate_date_of_a_collision_still_blocks_its_issue():
    alternate = replace(collision("ZZ0000000011", "ZZ0000000029"), kind="UNRESOLVED")
    analysis = scoped_case(other=(alternate,))
    analysis.coverage["events"] = Coverage(False, ("overlapping_trade_conflict",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value is None


@pytest.mark.parametrize(
    "reason",
    [
        "classification_missing_legacy_intake",
        "currency_unsupported",
        "invalid_assumption_choice",
        "invalid_external_flow",
        "invalid_money_row",
        "overlap_flow_choice_conflict",
    ],
)
def test_every_unidentified_money_gap_marks_purchases(reason):
    analysis = scoped_case()
    analysis.events = analysis.events[:1]
    analysis.coverage["payouts"] = Coverage(False, (reason,))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    rows = clean_purchase_price_contributions(
        analysis, result, "ZZ0000000011", instrument_type="bond"
    )
    assert rows[0]["reason_codes"] == ["account_money_unattributed"]


def test_proved_own_nkd_row_is_not_reported_as_unattributed_money():
    analysis = scoped_case()
    analysis.events = (analysis.events[0], own_money(0, -2000))
    analysis.coverage["payouts"] = Coverage(False, ("unmatched_trade_money",))
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    analysis.coverage["quantity"] = Coverage(True)
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value == -3000
    assert result.pnl.assumptions == ()


def test_money_row_of_another_issue_is_not_reported_as_unattributed_money():
    analysis = scoped_case()
    other = replace(own_money(0, -700), isin="ZZ0000000029", nkd_money=False)
    analysis.events = (analysis.events[0], other)
    analysis.coverage["payouts"] = Coverage(False, ("unmatched_trade_money",))
    analysis.coverage["events"] = Coverage(False, ("unmatched_trade_money",))
    analysis.coverage["quantity"] = Coverage(True)
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.value == -3000
    assert result.pnl.assumptions == ()


def test_account_gap_without_a_row_keeps_the_note():
    analysis = scoped_case(payout_reasons=("unparsed_source_rows",))
    analysis.events = analysis.events[:1]
    analysis.coverage["events"] = Coverage(True)
    analysis.coverage["quantity"] = Coverage(True)
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.pnl.assumptions == ("account_money_unattributed",)


def test_own_payout_conflict_is_not_reported_as_unattributed_money():
    analysis = scoped_case(payout_reasons=("pdf_xml_payout_mismatch",))
    analysis.events = analysis.events[:1]
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert "account_money_unattributed" not in result.known_result.assumptions
    assert "account_money_unattributed" not in result.pnl.assumptions


def test_foreign_collision_does_not_undo_a_commission_only_conflict():
    analysis = scoped_case(other=(collision("ZZ0000000029", "ZZ0000000037"),))
    buy = analysis.events[0]
    analysis.events = (
        replace(buy, reason_codes=("overlapping_trade_conflict", "overlap_trade_commission_only")),
        *analysis.events[1:],
    )
    analysis.coverage["events"] = Coverage(False, ("overlapping_trade_conflict",))
    import hermes_finance.services.clean_instrument_return as service

    original = service.cost_only_trade
    service.cost_only_trade = lambda event: event.isin == "ZZ0000000011" or original(event)
    try:
        result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    finally:
        service.cost_only_trade = original
    assert result.valuation_and_trades.value == -3000


def rate_case(day):
    buy = replace(trade("BUY", 10000, 0), event_date=day, cash_settlement_date=day)
    return calculate_clean_return(
        START,
        END,
        0,
        11000,
        (buy,),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
    )


def test_rate_counts_the_first_trade_as_capital_for_the_whole_holding():
    result = rate_case(END - timedelta(days=1))
    assert result.pnl.value == 1000
    assert result.modified_dietz.value == Decimal("0.1")


def test_payout_before_the_first_trade_stays_in_the_result_but_not_the_rate():
    buy = replace(trade("BUY", 10000, 0), event_date=date(2030, 1, 10))
    buy = replace(buy, cash_settlement_date=date(2030, 1, 10))
    coupon = replace(
        cash("COUPON", 500),
        event_date=date(2030, 1, 3),
        cash_legs=(CashLeg("COUPON", date(2030, 1, 3), 500, -500, ("c",), "c"),),
    )
    result = calculate_clean_return(
        START,
        END,
        0,
        12000,
        (buy, coupon),
        trades_complete=True,
        payouts_complete=True,
        redemptions_complete=True,
        valuation_complete=True,
    )
    assert result.pnl.value == 2500
    assert result.modified_dietz.value == Decimal("0.2")


def test_rate_stays_unknown_for_a_trade_on_the_closing_day():
    result = rate_case(END)
    assert result.pnl.value == 1000
    assert result.modified_dietz.value is None


def clean_account(status, assumptions=()):
    return {
        "scope": "s",
        "clean": {"pnl": {"value": "100", "status": status, "assumptions": list(assumptions)}},
    }


@pytest.mark.parametrize(
    "status, whole",
    [("supported", True), ("provisional", True), ("partial", False), ("unavailable", False)],
)
def test_card_is_whole_only_for_results_without_a_partial_status(status, whole):
    from hermes_finance.services.returns_overall import _accounts_have_full_result

    assert _accounts_have_full_result([clean_account(status)], set()) is whole


def test_card_keeps_the_note_of_every_account():
    from hermes_finance.services.returns_overall import _account_result_notes

    accounts = [
        clean_account("provisional", ("account_money_unattributed",)),
        clean_account("supported"),
    ]
    assert _account_result_notes(accounts) == ["account_money_unattributed"]
    assert _account_result_notes([*accounts, {"scope": "x", "clean": None}]) == [
        "account_money_unattributed"
    ]


def test_empty_position_needs_no_reported_value():
    from hermes_finance.services.clean_instrument_return import _clean_endpoint

    empty = Endpoint(
        START, Decimal(0), None, None, None, "reported_unknown", (), ("missing_endpoint",)
    )
    assert _clean_endpoint(empty, "stock") == 0
    held = replace(empty, quantity=Decimal(1))
    assert _clean_endpoint(held, "stock") is None
    unknown = replace(empty, reason_codes=("missing_endpoint", "instrument_type_unknown"))
    assert _clean_endpoint(unknown, None) is None


def scoped_dividend(reasons=("payout_link_unresolved_no_match",), **changes):
    event = replace(
        cash("DIVIDEND", 700),
        counted=False,
        current=False,
        attribution_basis="registration_scope",
        reason_codes=reasons,
    )
    return replace(event, **changes)


def test_dividend_identified_by_registration_number_counts():
    analysis = scoped_case(payout_reasons=("payout_link_unresolved_no_match",))
    analysis.events = (analysis.events[0], scoped_dividend())
    analysis.coverage["events"] = Coverage(True)
    analysis.coverage["quantity"] = Coverage(True)
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert result.dividends.value == 700
    assert result.pnl.value == -2300
    assert "account_money_unattributed" not in result.pnl.assumptions


@pytest.mark.parametrize(
    "changes",
    [
        {"attribution_basis": "persisted_link"},
        {"reason_codes": ("payout_link_unresolved_no_match", "pdf_xml_payout_mismatch")},
        {"kind": "COUPON"},
    ],
)
def test_other_unlinked_payouts_do_not_count(changes):
    analysis = scoped_case(payout_reasons=("payout_link_unresolved_no_match",))
    analysis.events = (analysis.events[0], scoped_dividend(**changes))
    analysis.coverage["events"] = Coverage(True)
    analysis.coverage["quantity"] = Coverage(True)
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="stock")
    assert (result.dividends.value or 0) + (result.coupons.value or 0) == 0


def blank_nkd_trade(**changes):
    event = replace(
        trade("BUY", 102050, None, basis=None),
        provider="alfa_mybroker",
        native_identity="trade-1",
        native_ids=("1", "2"),
        execution_date=DAY,
        depository_settlement_date=DAY,
        unit_price=Decimal("102.05"),
        price_unit="PERCENT_OF_FACE",
        quantity_delta=Decimal("1"),
        counted=False,
        reason_codes=("trade_components_missing", "trade_nkd_basis_unknown"),
    )
    return replace(event, **changes)


def test_blank_nkd_keeps_the_statement_total():
    event = blank_nkd_trade()
    assert trade_amount_with_nkd(event) == 102050
    assert cost_only_trade(event)
    assert calc((event,)).buys.value == 102050


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "synthetic"},
        {"price_unit": "RUB_PER_UNIT"},
        {"native_identity": None},
        {"native_ids": ("1",)},
        {"accrued_interest_kopecks": 100},
        {
            "reason_codes": (
                "trade_components_missing",
                "trade_nkd_basis_unknown",
                "repo_trade_unsupported",
            )
        },
        {"quantity_delta": Decimal("-1")},
        {"native_trade_amount_kopecks": None},
        {"cash_legs": (CashLeg("principal", DAY, -90000, 90000, ("m",), "m"),)},
        {
            "cash_legs": (
                CashLeg("principal", DAY, -102050, 102050, ("m",), "m"),
                CashLeg("nkd", DAY, -500, 500, ("n",), "n"),
            )
        },
    ],
)
def test_blank_nkd_rule_is_narrow(changes):
    event = blank_nkd_trade(**changes)
    assert not cost_only_trade(event) or trade_amount_with_nkd(event) is None


def test_classification_conflict_of_a_linked_row_is_not_unattributed_money():
    analysis = scoped_case()
    linked = replace(
        cash("FEE", -100), kind="UNRESOLVED", reason_codes=("overlap_flow_choice_conflict",)
    )
    analysis.events = (analysis.events[0], linked)
    analysis.coverage["payouts"] = Coverage(False, ("overlap_flow_choice_conflict",))
    result = project_clean_analysis(analysis, "ZZ0000000011", instrument_type="bond")
    assert "account_money_unattributed" not in result.known_result.assumptions


def linked(principal=None, nkd=None):
    legs = []
    if principal is not None:
        legs.append(CashLeg("principal", DAY, -principal, principal, ("p",), "money:p"))
    if nkd is not None:
        legs.append(CashLeg("nkd", DAY, -nkd, nkd, ("n",), "money:n"))
    return tuple(legs)


def priced_trade(**changes):
    event = replace(
        trade("BUY", 102050, None, basis=None),
        provider="alfa_mybroker",
        native_identity="trade-1",
        native_ids=("1", "2"),
        execution_date=DAY,
        depository_settlement_date=DAY,
        unit_price=Decimal("100"),
        price_unit="PERCENT_OF_FACE",
        face_value=Decimal("1000"),
        face_value_date=DAY,
        quantity_delta=Decimal("1"),
        counted=False,
        reason_codes=("trade_components_missing", "trade_nkd_basis_unknown"),
    )
    return replace(event, **changes)


@pytest.mark.parametrize(
    "event, amount",
    [
        # Linked principal and NKD exceed the statement total.
        (priced_trade(cash_legs=linked(100000, 10000)), None),
        # Linked principal contradicts the priced principal.
        (priced_trade(cash_legs=linked(95000, 7050)), None),
        # A linked NKD row alone cannot prove the missing principal row.
        (blank_nkd_trade(cash_legs=linked(None, 500)), 102050),
        (priced_trade(cash_legs=linked(100000, 2050)), 102050),
        (blank_nkd_trade(cash_legs=linked(100000, 10000)), None),
    ],
)
def test_linked_trade_money_must_agree_with_total_and_price(event, amount):
    assert trade_amount_with_nkd(event) == amount
    result = calc((event,))
    assert (result.buys.value == amount) if amount else result.pnl.value is None


@pytest.mark.parametrize(
    "case",
    [
        "current",
        "reaffirmed",
        "mixed_owner",
        "foreign_owner",
        "partial_occurrences",
        "partial_trades",
        "stale",
        "fingerprint",
        "retired",
        "wrong_account",
    ],
)
def test_sale_nkd_reuses_only_complete_current_identical_owned_group(monkeypatch, case):
    from hermes_finance.services import broker_money, source_return_evidence
    from hermes_finance.services.clean_sale_nkd import _current_owned_cohort
    from hermes_finance.statement_import.mybroker import digest

    sales = [
        replace(
            trade("SELL", 103000, 2000), native_identity=f"native-{i}", native_source_account="a"
        )
        for i in range(2)
    ]
    natives = [
        {
            "ordinal": i,
            "amount": "20",
            "date": DAY.isoformat(),
            "currency": "RUB",
            "source_account": "a",
        }
        for i in range(2)
    ]
    view = {"id": 1}
    refs = [f"money:1:money:{i}:synthetic" for i in range(2)]
    rows = [SimpleNamespace(source_references=(ref,)) for ref in refs]
    raw = {ref: (view, native) for ref, native in zip(refs, natives, strict=True)}
    occurrences = [
        {"import_id": 7, "section": "money", "ordinal": n["ordinal"], "row_fingerprint": digest(n)}
        for n in natives
    ]
    gid = digest([7, "c" * 64])
    identities = [sale.native_identity for sale in sales]
    group = {
        "group_id": gid,
        "cohort_digest": "c" * 64,
        "import_id": 7,
        "trade_identities": identities + (["extra"] if case == "partial_trades" else []),
        "occurrences": occurrences[:1] if case == "partial_occurrences" else occurrences,
        "source_account": "other" if case == "wrong_account" else "a",
        "date": DAY.isoformat(),
        "currency": "RUB",
        "native_total_basis": "includes_paid_nkd",
        "signed_nkd_minor": 2000,
    }
    targets = [
        {
            "role": "trade",
            "target_id": i,
            "cash_proof": {"source_identity": identity, "cohort": {"group_id": gid}},
        }
        for i, identity in enumerate(identities)
    ]
    proof = {
        "contract_version": broker_money.CONTRACT_V3,
        "operation": "retire" if case == "retired" else "accept",
        "statement_groups": [group],
        "targets": targets,
    }
    receipt = SimpleNamespace(request_id="synthetic-current")
    owned = {
        ref: [
            {
                "role": "trade_group",
                "target_id": "different" if case == "foreign_owner" else gid,
                "row_fingerprint": "0" * 64 if case == "fingerprint" else digest(native),
            }
        ]
        for ref, native in zip(refs, natives, strict=True)
    }
    if case == "reaffirmed":
        owned = {ref: claim * 3 for ref, claim in owned.items()}
    if case == "mixed_owner":
        owned[refs[0]].append(
            {
                "role": "trade_group",
                "target_id": "other-group",
                "row_fingerprint": digest(natives[0]),
            }
        )
    monkeypatch.setattr(source_return_evidence, "bound_import", lambda *args: SimpleNamespace(id=7))
    monkeypatch.setattr(broker_money, "receipts", lambda session: [(receipt, proof)])
    monkeypatch.setattr(
        broker_money,
        "latest_proofs",
        lambda session: {("trade", t["target_id"]): (receipt, proof, t) for t in targets},
    )
    monkeypatch.setattr(
        broker_money, "proof_blockers", lambda *args: ["stale"] if case == "stale" else []
    )
    assert _current_owned_cohort(object(), sales, rows, raw, owned) is (
        case in {"current", "reaffirmed"}
    )
