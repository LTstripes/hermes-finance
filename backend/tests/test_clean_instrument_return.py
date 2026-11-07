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
