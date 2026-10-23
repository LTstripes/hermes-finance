"""Independent integer/fraction acceptance vectors from the accepted #891 contract."""

from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction
from types import SimpleNamespace

import pytest

from hermes_finance.domain.instrument_return import (
    CashLeg,
    Coverage,
    Endpoint,
    InstrumentEvent,
    calculate_economics,
    chain_monthly,
)
from hermes_finance.domain.monthly_return_chain import calculate_interval_return

START = date(2030, 3, 31)
END = date(2030, 4, 30)
COMPLETE = {
    k: Coverage(True) for k in ("events", "quantity", "endpoints", "payouts", "costs", "valuation")
}


def endpoint(value, closing=False):
    return Endpoint(END if closing else START, Decimal(0), value, value, 0, "dirty")


def event(kind, rubles, day, index=0, **kwargs):
    amount = rubles * 100
    credit = -amount if kind in {"BUY", "FEE", "TAX"} else amount
    key = f"{kind}:{day}:{index}"
    return InstrumentEvent(
        event_key=key,
        provider="synthetic",
        native_source_account="account",
        isin="ZZ0000000011",
        effective_isin="ZZ0000000011",
        kind=kind,
        event_date=START + timedelta(days=day),
        source_references=(key,),
        cash_legs=(CashLeg(kind, START + timedelta(days=day), credit, -credit, (key,), key),),
        **kwargs,
    )


@pytest.mark.parametrize(
    "v0,v1,flows,pnl,capital,rate",
    [
        (0, 1100, (("BUY", 1000, 10),), 100, 20000, Fraction(3, 20)),
        (1000, 1600, (("BUY", 500, 5),), 100, 42500, Fraction(6, 85)),
        (1000, 1600, (("BUY", 500, 25),), 100, 32500, Fraction(6, 65)),
        (1000, 1100, (("DIVIDEND", 100, 15), ("BUY", 100, 15)), 100, 30000, Fraction(1, 10)),
        (1000, 660, (("SELL", 440, 15),), 100, 23400, Fraction(5, 39)),
        (1000, 0, (("SELL", 1100, 20),), 100, 19000, Fraction(3, 19)),
        (0, 1010, (("BUY", 1002, 15), ("COUPON", 30, 30)), 38, 15030, Fraction(38, 501)),
        (1000, 1000, (("DIVIDEND", 87, 15),), 87, 28695, Fraction(174, 1913)),
        (1000, 1000, (("DIVIDEND", 100, 15), ("TAX", 13, 15)), 87, 28695, Fraction(174, 1913)),
        (0, 1100, (("BUY", 1000, 30),), 100, 0, None),
        (0, 0, (("SELL", 1000, 15),), 1000, -15000, None),
        (1000, 0, (("REDEMPTION", 1000, 30), ("COUPON", 20, 30)), 20, 30000, Fraction(1, 50)),
    ],
)
def test_contract_vectors(v0, v1, flows, pnl, capital, rate):
    events = tuple(event(*flow, index=i) for i, flow in enumerate(flows))
    with localcontext() as context:
        context.prec = 6  # caller precision cannot change the financial result
        components, result, _, md, _ = calculate_economics(
            endpoint(v0 * 100), endpoint(v1 * 100, True), events, COMPLETE
        )
    assert result.value == pnl * 100
    assert md.capital_days == capital * 100
    if rate is None:
        assert md.value is None
        assert md.reason_codes == ("non_positive_dietz_denominator",)
    else:
        with localcontext() as context:
            context.prec = 60
            assert md.value == Decimal(rate.numerator) / Decimal(rate.denominator)
    assert md.method == "modified_dietz" and md.approximate and not md.annualized
    if flows[0][0] == "REDEMPTION":
        assert components["redemption"].value == 100000
        assert components["coupons"].value == 2000


def test_missing_versus_zero_and_partial_subtotal():
    events = (event("COUPON", 30, 15),)
    incomplete = COMPLETE | {"costs": Coverage(False, ("fee_missing",))}
    components, pnl, subtotal, md, _ = calculate_economics(
        endpoint(100000), endpoint(110000, True), events, incomplete
    )
    assert pnl.value is md.value is None
    assert subtotal.value == 13000 and subtotal.status == "partial"
    assert components["coupons"].value == 3000
    assert components["fees"].value is None
    _, pnl, _, md, _ = calculate_economics(endpoint(None), endpoint(110000, True), events, COMPLETE)
    assert pnl.value is md.value is None


def test_known_net_does_not_subtract_informational_tax_again():
    net = event(
        "DIVIDEND",
        87,
        15,
        gross_payout_kopecks=10000,
        withheld_tax_kopecks=1300,
        net_payout_kopecks=8700,
    )
    components, pnl, _, _, _ = calculate_economics(
        endpoint(100000), endpoint(100000, True), (net,), COMPLETE
    )
    assert pnl.value == components["dividends"].value == 8700
    assert components["taxes"].value == 0


def test_duplicate_owned_cash_rejected_and_dates_unshifted():
    buy = event("BUY", 1000, 10)
    with pytest.raises(ValueError, match="ownership"):
        calculate_economics(endpoint(0), endpoint(110000, True), (buy, buy), COMPLETE)
    result = calculate_interval_return(
        (START, 100000), (END, 110000), [(START, 999, "confirmed"), (END, 10000, "confirmed")]
    )
    assert result.growth_kopecks == 0 and result.modified_dietz_return == 0
    with pytest.raises(ValueError):
        calculate_interval_return((END, 0), (START, 0), [])
    with pytest.raises(TypeError):
        calculate_interval_return((START, 0.0), (END, 0), [])


def test_monthly_chain_requires_all_months_compatible_seams_and_nonnegative_factors():
    from hermes_finance.domain.instrument_return import Metric

    middle = date(2030, 4, 30)
    last = date(2030, 5, 31)
    a = SimpleNamespace(
        opening_date=START,
        closing_date=middle,
        opening=endpoint(100000),
        closing=endpoint(110000, True),
        modified_dietz=Metric(Decimal("0.1"), "supported"),
        assumptions=(),
    )
    b = SimpleNamespace(
        opening_date=middle,
        closing_date=last,
        opening=endpoint(110000),
        closing=endpoint(121000, True),
        modified_dietz=Metric(Decimal("0.1"), "supported"),
        assumptions=(),
    )
    assert chain_monthly([a, b], START, last).value == Decimal("0.21")
    assert chain_monthly([a], START, last).value is None
    b.modified_dietz = Metric(Decimal(-1), "supported")
    assert chain_monthly([a, b], START, last).value == -1
    b.modified_dietz = Metric(Decimal("-1.01"), "supported")
    assert chain_monthly([a, b], START, last).value is None
    b.modified_dietz = Metric(Decimal("0.1"), "supported")
    b.opening = endpoint(109999)
    assert chain_monthly([a, b], START, last).reason_codes == ("seam_mismatch",)
