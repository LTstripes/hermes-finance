"""Synthetic positive-root certificates, independent of financial persistence."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from hermes_finance.domain.xirr import XirrCashFlow, calculate_xirr


def flows(amounts):
    return [
        XirrCashFlow(date(2020, 1, 1) + timedelta(days=365 * i), n) for i, n in enumerate(amounts)
    ]


@pytest.mark.parametrize(
    "amounts,expected",
    [
        ([-100000, 10000, -50000, 176000], "0.1"),
        ([-100000, 10000, -50000, 109800], "-0.1"),
        ([-1000, 100, -100, 1000], "0"),
        ([-100, 220, -121], "0.1"),
    ],
)
def test_reinvestment_or_exact_tangent_has_one_distinct_root(amounts, expected):
    result = calculate_xirr(flows(amounts))
    assert result.is_available, result.reason_codes
    assert abs(result.rate - Decimal(expected)) < Decimal("1e-25")


@pytest.mark.parametrize(
    "amounts",
    [
        [-100, 230, -132],
        [-72000, 530000, -950000, 500000],
        [2, -3, 1],
        [(10**40 + 1) * (10**40 + 2), -(10**40) * (2 * 10**40 + 3), 10**80],
    ],
)
def test_distinct_roots_never_select_first_or_merge_close_rates(amounts):
    result = calculate_xirr(flows(amounts))
    assert result.rate is None
    assert result.reason_codes == ("not_computable_xirr_root_ambiguity",)


def test_multisign_no_root_is_proved_instead_of_assumed_ambiguous():
    result = calculate_xirr(flows([1, -1, 1]))
    assert result.rate is None
    assert result.reason_codes == ("not_computable_xirr_no_valid_root",)


def test_rounded_npv_zero_cannot_override_exact_root_certificate():
    a, m = 10**60, 10**140
    result = calculate_xirr(flows([-(m + 1), a * (m + 1) + 2 * m, -(2 * a + 1) * m, a * m]))
    assert result.rate is None
    assert result.reason_codes == ("not_computable_xirr_convergence_failed",)


def test_unresolved_irrational_tangent_is_numerical_failure_not_claimed_multiple_roots():
    result = calculate_xirr(flows([1, 2, -1, -2, 1]))
    assert result.rate is None
    assert result.reason_codes == ("not_computable_xirr_convergence_failed",)


def test_same_day_cancellation_and_nonannual_spacing_keep_equation():
    start = date(2020, 1, 1)
    cash = [
        XirrCashFlow(start + timedelta(days=30 * i), n)
        for i, n in enumerate([-1000, 100, -100, 1000])
    ]
    cash += [
        XirrCashFlow(start + timedelta(days=7), 17),
        XirrCashFlow(start + timedelta(days=7), -17),
    ]
    assert calculate_xirr(cash).rate == 0
    # Threefold multiplicity at an exact rational root still denotes one rate.
    assert calculate_xirr(flows([-1, 3, -3, 1])).rate == 0


def test_near_zero_unique_rate_and_extreme_scale_are_certified():
    n = 10**12
    result = calculate_xirr(flows([-(n + 1), 2 * n + 1, -(2 * n + 1), n]))
    assert result.is_available
    expected = Decimal(n) / Decimal(n + 1) - 1
    assert abs(result.rate - expected) < Decimal("1e-25")


@pytest.mark.parametrize(
    "limit,value",
    [
        ("_MAX_NODES", 0),
        ("_MAX_WORK", 0),
        ("_MAX_BITS", 2),
        ("_MAX_DEGREE", 1),
        ("_MAX_EVALUATION_BITS", 1),
    ],
)
def test_certification_resource_exhaustion_never_becomes_financial_unknown_or_zero(
    monkeypatch, limit, value
):
    from hermes_finance.domain import xirr_roots

    monkeypatch.setattr(xirr_roots, limit, value)
    result = calculate_xirr(flows([-100000, 10000, -50000, 176000]))
    assert result.rate is None
    assert result.reason_codes == ("not_computable_xirr_convergence_failed",)


def test_small_iteration_budget_does_not_choose_approximate_multisign_root():
    result = calculate_xirr(flows([-100000, 10000, -50000, 176000]), max_iterations=1)
    assert result.rate is None
    assert result.reason_codes == ("not_computable_xirr_convergence_failed",)


def test_exact_tangent_on_fractional_act365_dates_is_annualized():
    from decimal import localcontext

    cash = [
        XirrCashFlow(date(2020, 1, 1) + timedelta(days=180 * i), n)
        for i, n in enumerate([-100, 220, -121])
    ]
    result = calculate_xirr(cash)
    with localcontext() as context:
        context.prec = 60
        expected = Decimal("1.1") ** (Decimal(365) / 180) - 1
        assert abs(result.rate - expected) < Decimal("1e-55")
