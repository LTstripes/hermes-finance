"""Unit tests for the pure progressive salary-tax (НДФЛ) calculator (no database)."""

import pytest

from hermes_finance.domain.salary_tax import (
    SalaryTaxInput,
    SalaryTaxResult,
    TaxBracketRule,
    calculate_progressive_tax,
)


def mk_bracket(from_kopecks: int, to_kopecks: int | None, rate_bps: int) -> TaxBracketRule:
    return TaxBracketRule(from_kopecks=from_kopecks, to_kopecks=to_kopecks, rate_bps=rate_bps)


# Official five-bracket scale (ФЗ-176-ФЗ of 12.07.2024) used across the matrix.
OFFICIAL_BRACKETS = (
    mk_bracket(0, 240_000_000, 1300),
    mk_bracket(240_000_000, 500_000_000, 1500),
    mk_bracket(500_000_000, 2_000_000_000, 1800),
    mk_bracket(2_000_000_000, 5_000_000_000, 2000),
    mk_bracket(5_000_000_000, None, 2200),
)


def calc(ytd: int, payment: int, brackets=OFFICIAL_BRACKETS) -> SalaryTaxResult:
    return calculate_progressive_tax(
        SalaryTaxInput(
            ytd_gross_kopecks=ytd,
            payment_gross_kopecks=payment,
            brackets=brackets,
        )
    )


# --- threshold crossing ---


def test_payment_crossing_into_second_bracket_splits_into_two_parts() -> None:
    # ytd 2_350_000.00 RUB, payment 100_000.00 RUB: [235M, 245M) kopecks
    result = calc(ytd=235_000_000, payment=10_000_000)
    assert isinstance(result, SalaryTaxResult)
    assert len(result.parts) == 2
    # 5_000_000 kopecks at 13%
    assert result.parts[0].from_kopecks == 0
    assert result.parts[0].to_kopecks == 240_000_000
    assert result.parts[0].rate_bps == 1300
    assert result.parts[0].taxable_kopecks == 5_000_000
    assert result.parts[0].tax_kopecks == 650_000
    # 5_000_000 kopecks at 15%
    assert result.parts[1].from_kopecks == 240_000_000
    assert result.parts[1].to_kopecks == 500_000_000
    assert result.parts[1].rate_bps == 1500
    assert result.parts[1].taxable_kopecks == 5_000_000
    assert result.parts[1].tax_kopecks == 750_000
    assert result.tax_kopecks == 1_400_000
    assert result.calculated_net_kopecks == 8_600_000


# --- full five-bracket run ---


def test_full_five_bracket_run_applies_every_rate() -> None:
    # payment 60_000_000.00 RUB from zero YTD: covers all five brackets
    result = calc(ytd=0, payment=6_000_000_000)
    assert isinstance(result, SalaryTaxResult)
    assert len(result.parts) == 5
    assert [p.rate_bps for p in result.parts] == [1300, 1500, 1800, 2000, 2200]
    assert [p.taxable_kopecks for p in result.parts] == [
        240_000_000,
        260_000_000,
        1_500_000_000,
        3_000_000_000,
        1_000_000_000,
    ]
    # 312_000 + 390_000 + 2_700_000 + 6_000_000 + 2_200_000 = 11_602_000 RUB
    assert [p.tax_kopecks for p in result.parts] == [
        31_200_000,
        39_000_000,
        270_000_000,
        600_000_000,
        220_000_000,
    ]
    assert result.tax_kopecks == 1_160_200_000
    assert result.calculated_net_kopecks == 4_839_800_000


# --- exactly at a threshold ---


def test_payment_starting_exactly_at_threshold_uses_upper_rate() -> None:
    # ytd 2_400_000.00 RUB: the whole payment sits in the 15% bracket
    result = calc(ytd=240_000_000, payment=10_000_000)
    assert len(result.parts) == 1
    assert result.parts[0].rate_bps == 1500
    assert result.parts[0].taxable_kopecks == 10_000_000
    assert result.parts[0].tax_kopecks == 1_500_000
    assert result.tax_kopecks == 1_500_000
    assert result.calculated_net_kopecks == 8_500_000


# --- inside the first bracket ---


def test_payment_inside_first_bracket_taxed_at_13_percent() -> None:
    result = calc(ytd=0, payment=10_000_000)
    assert len(result.parts) == 1
    assert result.parts[0].rate_bps == 1300
    assert result.tax_kopecks == 1_300_000
    assert result.calculated_net_kopecks == 8_700_000


# --- zero payment ---


def test_zero_payment_returns_zeros_and_no_parts() -> None:
    result = calc(ytd=0, payment=0)
    assert result.tax_kopecks == 0
    assert result.calculated_net_kopecks == 0
    assert result.parts == ()


def test_zero_payment_ignores_high_ytd() -> None:
    result = calc(ytd=6_000_000_000, payment=0)
    assert result.tax_kopecks == 0
    assert result.calculated_net_kopecks == 0
    assert result.parts == ()


# --- rounding (ROUND_HALF_UP to whole kopecks) ---


def test_sub_kopeck_tax_rounds_down_to_zero() -> None:
    # 1 kopeck * 13% = 0.13 kopecks -> 0
    result = calc(ytd=0, payment=1)
    assert result.tax_kopecks == 0
    assert result.calculated_net_kopecks == 1


def test_half_kopeck_tax_rounds_half_up() -> None:
    # 5 kopecks * 13% = 0.65 kopecks -> 1
    result = calc(ytd=0, payment=5)
    assert result.tax_kopecks == 1
    assert result.calculated_net_kopecks == 4


# --- validation: empty brackets ---


def test_empty_brackets_raise_value_error() -> None:
    with pytest.raises(ValueError):
        calc(ytd=0, payment=10_000_000, brackets=())


# --- validation: overlapping brackets ---


def test_overlapping_brackets_raise_value_error() -> None:
    brackets = (
        mk_bracket(0, 240_000_000, 1300),
        mk_bracket(200_000_000, 500_000_000, 1500),
    )
    with pytest.raises(ValueError):
        calc(ytd=0, payment=10_000_000, brackets=brackets)


# --- validation: gap in coverage ---


def test_gap_in_bracket_coverage_raises_value_error() -> None:
    # 240M..500M kopecks are uncovered; the payment crosses the hole
    brackets = (
        mk_bracket(0, 240_000_000, 1300),
        mk_bracket(500_000_000, None, 1800),
    )
    with pytest.raises(ValueError):
        calc(ytd=0, payment=300_000_000, brackets=brackets)


# --- validation: open upper bound must be last ---


def test_open_upper_bound_not_last_raises_value_error() -> None:
    brackets = (
        mk_bracket(240_000_000, None, 1500),
        mk_bracket(500_000_000, None, 1800),
    )
    with pytest.raises(ValueError):
        calc(ytd=0, payment=10_000_000, brackets=brackets)


# --- validation: negative amounts ---


def test_negative_payment_raises_value_error() -> None:
    with pytest.raises(ValueError):
        calc(ytd=0, payment=-5)


def test_negative_ytd_raises_value_error() -> None:
    with pytest.raises(ValueError):
        calc(ytd=-1, payment=10_000_000)
