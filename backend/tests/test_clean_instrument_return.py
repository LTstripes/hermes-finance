from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from hermes_finance.domain.clean_instrument_return import calculate_clean_return, clean_trade_amount
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


def test_clean_principal_net_receipt_and_costs_excluded():
    result = calc(
        (trade("BUY", 102000, 2000), cash("DIVIDEND", 8700), cash("FEE", -900), cash("TAX", -1300))
    )
    assert result.buys.value == 100000
    assert result.payouts.value == 8700
    assert result.valuation_and_trades.value == 10000
    assert result.pnl.value == 18700
    with localcontext() as context:
        context.prec = 60
        assert result.modified_dietz.value == Decimal(18700) / Decimal(45650)


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
    assert calc((buy,)).pnl.value == 10000
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
        assert result.modified_dietz.value == Decimal(10000) / (Decimal(100000) * 25 / 30)
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
    assert result.pnl.value == 10000
    assert result.redemption.value == 0
    unknown_bond = replace(analysis.closing, accrued_interest_kopecks=None)
    assert (
        project_clean_analysis(
            replace_namespace(analysis, closing=unknown_bond), "ZZ0000000011"
        ).pnl.value
        is None
    )


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


def test_cost_boundary_recheck_does_not_erase_unrelated_missing_trade():
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
    assert clean.pnl.value is None and clean.known_result.value is None


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
    assert clean.pnl.value == 10000


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


def test_fifo_partial_sale_uses_original_cost_and_matches_instrument_price_result():
    first = buy("a", 10000, "1", date(2030, 1, 10))
    second = buy("b", 20000, "1", date(2030, 1, 11))
    sale = replace(buy("sale", 18000, "-1", date(2030, 1, 12)), kind="SELL")
    rows = case([first, second, sale], quantity="1", closing=15000)
    assert [r["price_result_kopecks"] for r in rows] == ["8000", "-5000"]
    assert [r["remaining_quantity"] for r in rows] == ["0", "1"]
    assert [r["return_fraction"] for r in rows] == ["0.8", "-0.25"]
    assert sum(int(row["price_result_kopecks"]) for row in rows) == 3000


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


def test_fifo_excludes_fees_and_paid_nkd_from_buy_and_sale():
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
    assert row["cost_kopecks"] == "10000" and row["sale_proceeds_kopecks"] == "18000"
    assert row["price_result_kopecks"] == "8000" and row["return_fraction"] == "0.8"


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
    rows = case([original], quantity="1", closing=11000, complete=False)
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


def test_purchase_principal_excludes_nkd_and_missing_commission_does_not_block():
    event = replace(
        buy("bond", 10200, "1", date(2030, 1, 10)),
        native_total_basis="includes_paid_nkd",
        accrued_interest_kopecks=200,
        commission_kopecks=None,
        counted=False,
        reason_codes=("trade_components_missing",),
    )
    result = case([event], quantity="1", closing=11000)
    assert result[0]["cost_kopecks"] == "10000"
    assert result[0]["price_result_kopecks"] == "1000"


def test_zero_and_rounding_are_known_and_add_to_total():
    rows = case(
        [buy("a", 100, "1", date(2030, 1, 10)), buy("b", 100, "1", date(2030, 1, 11))], closing=201
    )
    assert sum(int(row["value_kopecks"]) for row in rows) == 201
    assert any(row["price_result_kopecks"] == "0" for row in rows)


@pytest.mark.parametrize("shape", ["sale", "quantity", "incomplete", "missing_date", "wrong_isin"])
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
            complete=shape != "incomplete",
        )
        is None
    )
