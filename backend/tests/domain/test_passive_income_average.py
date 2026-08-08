"""Unit tests for the pure rolling 12-month passive-income average calculator (no database)."""

import pytest

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.passive_income_average import (
    MonthlyPassiveIncome,
    PassiveIncomeAverageInput,
    calculate_passive_income_average,
)


def mk_month(year: int, month: int, kopecks: int) -> MonthlyPassiveIncome:
    return MonthlyPassiveIncome(year=year, month=month, amount=RubleAmount(kopecks))


# --- empty input ---


def test_empty_input_returns_zeros() -> None:
    result = calculate_passive_income_average(PassiveIncomeAverageInput())
    assert result.sum_total == RubleAmount(0)
    assert result.average == RubleAmount(0)
    assert result.count_months == 0
    assert result.is_complete_12m is False
    assert result.months == ()


# --- single month ---


def test_one_month_average_equals_amount() -> None:
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(months=(mk_month(2031, 1, 25_000),))
    )
    assert result.sum_total == RubleAmount(25_000)
    assert result.average == RubleAmount(25_000)
    assert result.count_months == 1
    assert result.is_complete_12m is False


# --- three months ---


def test_three_months_average_is_sum_over_count() -> None:
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 1, 10_000),
                mk_month(2031, 2, 20_000),
                mk_month(2031, 3, 30_000),
            )
        )
    )
    assert result.sum_total == RubleAmount(60_000)
    assert result.average == RubleAmount(20_000)
    assert result.count_months == 3
    assert result.is_complete_12m is False


# --- exactly 12 months ---


def test_exactly_twelve_months_is_complete() -> None:
    months = tuple(mk_month(2031, m, 10_000) for m in range(1, 13))
    result = calculate_passive_income_average(PassiveIncomeAverageInput(months=months))
    assert result.is_complete_12m is True
    assert result.count_months == 12
    assert result.sum_total == RubleAmount(120_000)
    assert result.average == RubleAmount(10_000)
    assert result.months == months


# --- 13 months: rolling window ---


def test_thirteen_months_keeps_only_last_twelve() -> None:
    input_months = tuple(mk_month(2031, m, 10_000) for m in range(1, 13)) + (
        mk_month(2032, 1, 10_000),
    )
    result = calculate_passive_income_average(PassiveIncomeAverageInput(months=input_months))
    expected_window = input_months[1:]
    assert result.is_complete_12m is True
    assert result.count_months == 12
    assert result.sum_total == RubleAmount(120_000)
    assert result.average == RubleAmount(10_000)
    # oldest month (2031, 1) must be excluded
    assert result.months == expected_window


# --- 15 months: still last 12 ---


def test_fifteen_months_keeps_only_last_twelve() -> None:
    input_months = tuple(mk_month(2031, m, 1_000 * m) for m in range(1, 13)) + (
        mk_month(2032, 1, 13_000),
        mk_month(2032, 2, 14_000),
        mk_month(2032, 3, 15_000),
    )
    result = calculate_passive_income_average(PassiveIncomeAverageInput(months=input_months))
    expected_window = input_months[3:]
    assert result.count_months == 12
    assert result.is_complete_12m is True
    assert result.sum_total == RubleAmount(114_000)
    assert result.average == RubleAmount(9_500)
    assert result.months == expected_window


# --- unsorted input ---


def test_unsorted_input_is_sorted_and_average_unaffected() -> None:
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 3, 30_000),
                mk_month(2031, 1, 10_000),
                mk_month(2031, 2, 20_000),
            )
        )
    )
    assert result.count_months == 3
    assert result.sum_total == RubleAmount(60_000)
    assert result.average == RubleAmount(20_000)
    assert result.months == (
        mk_month(2031, 1, 10_000),
        mk_month(2031, 2, 20_000),
        mk_month(2031, 3, 30_000),
    )


# --- zero amounts count as months ---


def test_zero_amounts_still_count_as_months() -> None:
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 1, 0),
                mk_month(2031, 2, 0),
                mk_month(2031, 3, 30_000),
            )
        )
    )
    assert result.count_months == 3
    assert result.sum_total == RubleAmount(30_000)
    assert result.average == RubleAmount(10_000)


# --- rounding (ROUND_HALF_UP to whole kopecks) ---


def test_average_rounds_half_up_to_whole_kopecks() -> None:
    # 100.00 RUB over 3 months -> 10000 / 3 = 3333.33... -> 3333 kopecks
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 1, 10_000),
                mk_month(2031, 2, 0),
                mk_month(2031, 3, 0),
            )
        )
    )
    assert result.sum_total == RubleAmount(10_000)
    assert result.average == RubleAmount(3_333)


def test_average_rounds_fractional_kopeck_half_up() -> None:
    # 50 kopecks over 3 months -> 50 / 3 = 16.666... -> 17 kopecks
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 1, 50),
                mk_month(2031, 2, 0),
                mk_month(2031, 3, 0),
            )
        )
    )
    assert result.sum_total == RubleAmount(50)
    assert result.average == RubleAmount(17)


# --- negative amounts ---


def test_negative_amounts_allowed_in_sum_and_average() -> None:
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 1, -10_000),
                mk_month(2031, 2, -20_000),
            )
        )
    )
    assert result.sum_total == RubleAmount(-30_000)
    assert result.average == RubleAmount(-15_000)
    assert result.count_months == 2


def test_mixed_sign_amounts_average_can_be_negative() -> None:
    result = calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=(
                mk_month(2031, 1, -10_000),
                mk_month(2031, 2, 5_000),
            )
        )
    )
    assert result.sum_total == RubleAmount(-5_000)
    assert result.average == RubleAmount(-2_500)


# --- window in result is sorted ---


@pytest.mark.parametrize(
    ("input_months", "expected_months"),
    [
        (
            (
                mk_month(2032, 1, 13_000),
                mk_month(2031, 11, 11_000),
                mk_month(2031, 1, 1_000),
                mk_month(2031, 12, 12_000),
                mk_month(2031, 2, 2_000),
            ),
            (
                mk_month(2031, 1, 1_000),
                mk_month(2031, 2, 2_000),
                mk_month(2031, 11, 11_000),
                mk_month(2031, 12, 12_000),
                mk_month(2032, 1, 13_000),
            ),
        ),
    ],
)
def test_result_months_are_the_used_sorted_window(
    input_months: tuple[MonthlyPassiveIncome, ...],
    expected_months: tuple[MonthlyPassiveIncome, ...],
) -> None:
    result = calculate_passive_income_average(PassiveIncomeAverageInput(months=input_months))
    assert result.count_months == 5
    assert result.months == expected_months
