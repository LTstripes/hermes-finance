"""Unit tests for the pure IIS account-result calculator (C09, no database).

Matrix covers MASTER_SPEC §10.16:
- portfolio_result_without_tax_benefit = unrealized + coupons + dividends
  + realized_pnl;
- portfolio_result_with_tax_benefit = without + received_tax_benefits;
- planned/submitted benefits are breakdown-only and never added to either
  result; rejected benefits are not part of the calculator input at all;
- all money is integer kopecks via RubleAmount, no binary float.
"""

from hermes_finance.domain.iis_result import (
    IisResult,
    IisResultBreakdown,
    IisResultInput,
    calculate_iis_result,
)
from hermes_finance.domain.values import RubleAmount


def _input(
    *,
    unrealized: int = 0,
    coupons: int = 0,
    dividends: int = 0,
    realized_pnl: int = 0,
    received: int = 0,
    planned: int = 0,
    submitted: int = 0,
) -> IisResultInput:
    return IisResultInput(
        unrealized=RubleAmount(unrealized),
        coupons=RubleAmount(coupons),
        dividends=RubleAmount(dividends),
        realized_pnl=RubleAmount(realized_pnl),
        received_tax_benefits=RubleAmount(received),
        planned_tax_benefits=RubleAmount(planned),
        submitted_tax_benefits=RubleAmount(submitted),
    )


def _zero_breakdown() -> IisResultBreakdown:
    return IisResultBreakdown(
        unrealized=RubleAmount(0),
        coupons=RubleAmount(0),
        dividends=RubleAmount(0),
        realized_pnl=RubleAmount(0),
        received_tax_benefits=RubleAmount(0),
        planned_tax_benefits=RubleAmount(0),
        submitted_tax_benefits=RubleAmount(0),
    )


# --- zero input ---


def test_zero_input_produces_zero_results_and_zero_breakdown() -> None:
    result = calculate_iis_result(_input())
    assert isinstance(result, IisResult)
    assert result.portfolio_result_without_tax_benefit == RubleAmount(0)
    assert result.portfolio_result_with_tax_benefit == RubleAmount(0)
    assert result.breakdown == _zero_breakdown()


# --- full scenario ---


def test_full_scenario_matches_hand_computed_kopecks() -> None:
    result = calculate_iis_result(
        _input(
            unrealized=250_000,
            coupons=30_000,
            dividends=20_000,
            realized_pnl=-5_000,
            received=40_000,
            planned=60_000,
            submitted=10_000,
        )
    )
    # without = 250000 + 30000 + 20000 - 5000 = 295000 kopecks
    assert result.portfolio_result_without_tax_benefit == RubleAmount(295_000)
    # with = 295000 + 40000 = 335000 kopecks
    assert result.portfolio_result_with_tax_benefit == RubleAmount(335_000)
    # breakdown mirrors every input field exactly
    assert result.breakdown == IisResultBreakdown(
        unrealized=RubleAmount(250_000),
        coupons=RubleAmount(30_000),
        dividends=RubleAmount(20_000),
        realized_pnl=RubleAmount(-5_000),
        received_tax_benefits=RubleAmount(40_000),
        planned_tax_benefits=RubleAmount(60_000),
        submitted_tax_benefits=RubleAmount(10_000),
    )


# --- planned/submitted never affect either result ---


def test_planned_and_submitted_benefits_never_affect_results() -> None:
    result = calculate_iis_result(_input(realized_pnl=10_000, planned=60_000, submitted=10_000))
    # received == 0 -> with == without even with planned/submitted > 0
    assert result.portfolio_result_without_tax_benefit == RubleAmount(10_000)
    assert result.portfolio_result_with_tax_benefit == RubleAmount(10_000)
    assert result.portfolio_result_with_tax_benefit == result.portfolio_result_without_tax_benefit
    # ...but both still surface in the breakdown
    assert result.breakdown.planned_tax_benefits == RubleAmount(60_000)
    assert result.breakdown.submitted_tax_benefits == RubleAmount(10_000)


# --- negative realized pulls the result down ---


def test_negative_realized_pnl_pulls_result_below_unrealized() -> None:
    result = calculate_iis_result(_input(unrealized=250_000, realized_pnl=-5_000))
    assert result.portfolio_result_without_tax_benefit == RubleAmount(245_000)
    assert result.portfolio_result_without_tax_benefit.kopecks < 250_000
    assert result.portfolio_result_with_tax_benefit == RubleAmount(245_000)
    assert result.breakdown.realized_pnl == RubleAmount(-5_000)


# --- received-only ---


def test_received_only_with_zero_portfolio() -> None:
    result = calculate_iis_result(_input(received=40_000))
    assert result.portfolio_result_without_tax_benefit == RubleAmount(0)
    assert result.portfolio_result_with_tax_benefit == RubleAmount(40_000)
    assert result.breakdown.received_tax_benefits == RubleAmount(40_000)
