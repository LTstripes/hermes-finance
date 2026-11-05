from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from hermes_finance.domain.clean_instrument_return import calculate_clean_return, clean_trade_amount
from hermes_finance.domain.instrument_return import CashLeg, Coverage, Endpoint, InstrumentEvent
from hermes_finance.services.clean_instrument_return import project_clean_analysis

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


def replace_namespace(value, **changes):
    return SimpleNamespace(**(vars(value) | changes))
