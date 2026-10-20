"""Synthetic monthly Dietz/chaining and independent Decimal XIRR references."""

from datetime import date
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from hermes_finance.domain.monthly_return_chain import calculate_monthly_return_chain

START = date(2026, 1, 31)
MID = date(2026, 2, 14)
END = date(2026, 2, 28)


def test_no_flow_month_and_compounded_chain():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 11_000), (date(2026, 3, 31), 13_200)], []
    )
    first, second = result.months
    assert (first.opening_kopecks, first.closing_kopecks) == (10_000, 11_000)
    assert first.contributions_kopecks == first.withdrawals_kopecks == 0
    assert first.growth_kopecks == 1_000
    assert first.modified_dietz_return == Decimal("0.1")
    assert second.modified_dietz_return == Decimal("0.2")
    assert result.period.chained_return == Decimal("0.32")
    assert result.period.growth_kopecks == 3_200
    assert first.approximate and result.period.approximate
    assert not first.assumptions_used and not first.missing_endpoint
    assert not first.reason_codes and not result.period.chain_reason_codes


def test_intra_month_deposit_uses_remaining_days():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 16_500)], [(MID, 5_000, "confirmed")]
    )
    row = result.months[0]
    assert row.contributions_kopecks == result.period.contributions_kopecks == 5_000
    assert row.withdrawals_kopecks == 0
    assert row.growth_kopecks == result.period.growth_kopecks == 1_500
    assert row.modified_dietz_return == Decimal("0.12")  # 1500 / (10000 + 5000/2)


def test_last_day_deposit_has_zero_weight():
    row = calculate_monthly_return_chain(
        [(START, 10_000), (END, 16_000)], [(END, 5_000, "confirmed")]
    ).months[0]
    assert row.growth_kopecks == 1_000
    assert row.modified_dietz_return == Decimal("0.1")


def test_withdrawal_is_positive_magnitude_and_reduces_weighted_capital():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 6_800)], [(MID, -4_000, "confirmed")]
    )
    row = result.months[0]
    assert row.contributions_kopecks == 0
    assert row.withdrawals_kopecks == result.period.withdrawals_kopecks == 4_000
    assert row.growth_kopecks == result.period.growth_kopecks == 800
    assert row.modified_dietz_return == Decimal("0.1")


def test_missing_middle_boundary_preserves_later_month_and_outer_period():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, None), (date(2026, 3, 31), 12_000), (date(2026, 4, 30), 13_200)], []
    )
    for row in result.months[:2]:
        assert row.missing_endpoint
        assert row.growth_kopecks is row.modified_dietz_return is None
        assert row.reason_codes == ("missing_endpoint",)
        assert row.contributions_kopecks == row.withdrawals_kopecks == 0
    assert result.months[2].modified_dietz_return == Decimal("0.1")
    assert not result.months[2].missing_endpoint
    assert result.period.chained_return is None
    assert result.period.chain_reason_codes == ("missing_endpoint",)
    assert result.period.missing_endpoint
    assert result.period.growth_kopecks == 3_200
    assert result.period.xirr_period_return is not None
    assert abs(result.period.xirr_period_return - Decimal("0.32")) < Decimal("1e-23")


def test_missing_outer_endpoint_blocks_growth_and_xirr_but_keeps_flows():
    result = calculate_monthly_return_chain(
        [(START, None), (END, 1_100)], [(MID, 1_000, "confirmed")]
    )
    assert result.period.contributions_kopecks == 1_000
    assert result.period.growth_kopecks is result.period.xirr_annualized_return is None
    assert result.period.xirr_period_return is None
    assert (
        result.period.growth_reason_codes
        == result.period.xirr_reason_codes
        == ("missing_endpoint",)
    )


@pytest.mark.parametrize("closing", [0, 100])
def test_zero_opening_without_weighted_capital_is_unavailable(closing):
    result = calculate_monthly_return_chain([(START, 0), (END, closing)], [])
    row = result.months[0]
    assert not row.missing_endpoint
    assert row.growth_kopecks == closing
    assert row.modified_dietz_return is result.period.chained_return is None
    assert row.reason_codes == ("non_positive_dietz_denominator",)
    assert result.period.xirr_annualized_return is None
    assert result.period.xirr_reason_codes == ("not_computable_xirr_no_valid_root",)


def test_zero_opening_with_intra_month_deposit_has_valid_weighted_capital():
    row = calculate_monthly_return_chain(
        [(START, 0), (END, 110)], [(MID, 100, "confirmed")]
    ).months[0]
    assert row.growth_kopecks == 10
    assert row.modified_dietz_return == Decimal("0.2")
    assert not row.missing_endpoint


def test_total_loss_has_zero_chain_factor_and_unavailable_xirr():
    result = calculate_monthly_return_chain([(START, 1_000), (END, 0)], [])
    assert result.months[0].modified_dietz_return == -1
    assert result.period.chained_return == -1
    assert result.period.xirr_annualized_return is None


def test_assumed_flow_is_included_and_flagged():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 16_500)], [(MID, 5_000, "assumed")]
    )
    assert result.months[0].modified_dietz_return == Decimal("0.12")
    assert result.months[0].assumptions_used and result.period.assumptions_used
    assert result.period.xirr_annualized_return is not None


def test_unknown_flow_blocks_affected_month_and_period_without_becoming_zero():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 16_500), (date(2026, 3, 31), 18_150)],
        [(MID, 5_000, "unknown")],
    )
    row = result.months[0]
    assert row.opening_kopecks == 10_000 and row.closing_kopecks == 16_500
    assert row.contributions_kopecks is row.withdrawals_kopecks is row.growth_kopecks is None
    assert row.modified_dietz_return is None
    assert row.reason_codes == ("unknown_flow",)
    assert not row.assumptions_used
    assert result.months[1].modified_dietz_return == Decimal("0.1")
    assert result.period.contributions_kopecks is result.period.growth_kopecks is None
    assert result.period.chained_return is result.period.xirr_period_return is None
    assert result.period.chain_reason_codes == result.period.xirr_reason_codes == ("unknown_flow",)


def test_shared_boundary_flow_is_counted_once_and_outside_flows_are_ignored():
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 16_000), (date(2026, 3, 31), 17_600)],
        [
            (END, 5_000, "confirmed"),
            (START, 90_000, "unknown"),
            (date(2027, 1, 1), 90_000, "unknown"),
        ],
    )
    assert result.months[0].contributions_kopecks == 5_000
    assert result.months[1].contributions_kopecks == 0
    assert result.period.contributions_kopecks == 5_000
    assert result.period.chained_return == Decimal("0.21")


def _independent_xirr(flows):
    # Direct rate-space NPV bisection, independent of the production log-space solver.
    with localcontext() as ctx:
        ctx.prec = 60
        start = flows[0][0]
        low, high = Decimal("-0.9"), Decimal(100)
        for _ in range(200):
            rate = (low + high) / 2
            npv = sum(
                Decimal(amount) / (1 + rate) ** (Decimal((day - start).days) / 365)
                for day, amount in flows
            )
            if npv > 0:
                low = rate
            else:
                high = rate
        return (low + high) / 2


def test_xirr_agrees_with_independent_decimal_bisection():
    final = date(2026, 3, 31)
    result = calculate_monthly_return_chain(
        [(START, 10_000), (END, 16_500), (final, 17_000)],
        [(date(2026, 3, 15), -1_000, "confirmed"), (MID, 5_000, "confirmed")],
    )
    expected = _independent_xirr(
        [(START, -10_000), (MID, -5_000), (date(2026, 3, 15), 1_000), (final, 17_000)]
    )
    annual = result.period.xirr_annualized_return
    period = result.period.xirr_period_return
    assert isinstance(annual, Decimal) and isinstance(period, Decimal)
    assert abs(annual - expected) < Decimal("1e-23")
    with localcontext() as ctx:
        ctx.prec = 60
        expected_period = (1 + expected) ** (Decimal((final - START).days) / 365) - 1
    assert abs(period - expected_period) < Decimal("1e-23")


def test_inputs_and_callers_decimal_context_are_unchanged():
    boundaries = [(START, 10_000), (END, 16_501)]
    flows = [(MID, 5_000, "assumed")]
    expected = calculate_monthly_return_chain(boundaries, flows)
    with localcontext() as ctx:
        ctx.prec = 6
        ctx.rounding = ROUND_DOWN
        assert calculate_monthly_return_chain(boundaries, flows) == expected
        assert ctx.prec == 6 and ctx.rounding == ROUND_DOWN
    assert boundaries == [(START, 10_000), (END, 16_501)]
    assert flows == [(MID, 5_000, "assumed")]


@pytest.mark.parametrize("boundaries", [[], [(START, None)], [(START, 0)]])
def test_insufficient_boundaries_return_unavailable_metrics(boundaries):
    result = calculate_monthly_return_chain(boundaries, [])
    assert result.months == ()
    assert result.period.chained_return is result.period.xirr_period_return is None
    assert result.period.chain_reason_codes == ("insufficient_boundaries",)


@pytest.mark.parametrize(
    "boundaries,flows,error",
    [
        ([(END, 1), (START, 1)], [], ValueError),
        ([(START, 1), (START, 1)], [], ValueError),
        ([(START, True), (END, 1)], [], TypeError),
        ([(START, Decimal(1)), (END, 1)], [], TypeError),
        ([(START, 1), (END, 1)], [(MID, True, "confirmed")], TypeError),
        ([(START, 1), (END, 1)], [(MID, 1, "invalid")], ValueError),
    ],
)
def test_malformed_inputs_are_rejected(boundaries, flows, error):
    with pytest.raises(error):
        calculate_monthly_return_chain(boundaries, flows)
