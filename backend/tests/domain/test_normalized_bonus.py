"""Unit tests for the pure normalized-bonus calculator (C08, no database)."""

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.normalized_bonus import calculate_normalized_bonus
from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome


def mk_month(year: int, month: int, kopecks: int) -> MonthlyPassiveIncome:
    return MonthlyPassiveIncome(year=year, month=month, amount=RubleAmount(kopecks))


# --- empty input ---


def test_empty_input_returns_unavailable_and_warning() -> None:
    result = calculate_normalized_bonus(())
    assert result.monthly_average is None
    assert result.sum_total is None
    assert result.count_months == 0
    assert result.is_complete_12m is False
    assert result.months == ()
    assert result.warnings == ("Нет закрытых месяцев для оценки нормализованной премии",)


# --- single month ---


def test_single_month_is_normalized_over_selected_twelve_month_period() -> None:
    result = calculate_normalized_bonus((mk_month(2031, 3, 300_000),))
    # One observed 3,000 RUB bonus is 250 RUB/month over the selected 12m
    # normalization period; missing months are not inferred as observed rows.
    assert result.monthly_average == RubleAmount(25_000)
    assert result.sum_total == RubleAmount(300_000)
    assert result.count_months == 1
    assert result.is_complete_12m is False
    assert result.warnings == ("Премия оценена по 1 месяцев из 12",)


# --- three months: sum / 12 ---


def test_three_months_average_is_sum_over_count() -> None:
    result = calculate_normalized_bonus(
        (
            mk_month(2031, 1, 100_000),
            mk_month(2031, 2, 200_000),
            mk_month(2031, 3, 300_000),
        )
    )
    # 600000 / 12 = 50000 kopecks = 500.00 RUB
    assert result.monthly_average == RubleAmount(50_000)
    assert result.sum_total == RubleAmount(600_000)
    assert result.count_months == 3
    assert result.is_complete_12m is False
    assert result.warnings == ("Премия оценена по 3 месяцев из 12",)


# --- exactly 12 months ---


def test_exactly_twelve_months_is_complete() -> None:
    months = tuple(mk_month(2031, m, 100_000) for m in range(1, 13))
    result = calculate_normalized_bonus(months)
    assert result.is_complete_12m is True
    assert result.count_months == 12
    assert result.sum_total == RubleAmount(1_200_000)
    assert result.monthly_average == RubleAmount(100_000)
    assert result.warnings == ()


# --- 13 months: only the last 12 ---


def test_thirteen_months_keeps_last_twelve() -> None:
    months = tuple(mk_month(2031, m, 100_000) for m in range(1, 13)) + (mk_month(2032, 1, 300_000),)
    result = calculate_normalized_bonus(months)
    # window = 11 * 100000 + 300000 = 1400000; avg = 1400000/12 = 116666.66 -> 116667
    assert result.is_complete_12m is True
    assert result.count_months == 12
    assert result.sum_total == RubleAmount(1_400_000)
    assert result.monthly_average == RubleAmount(116_667)
    # oldest month (2031, 1) excluded
    assert result.months[0] == mk_month(2031, 2, 100_000)
    assert result.warnings == ()


def test_partial_calendar_window_does_not_stretch_to_twelve_records() -> None:
    # The latest month is March 2032, so the selected period starts in April
    # 2031.  April 2031 is missing; the older March row is outside the period.
    months = (
        mk_month(2031, 3, 900_000),
        mk_month(2031, 4, 100_000),
        mk_month(2031, 5, 100_000),
        mk_month(2032, 3, 100_000),
    )
    result = calculate_normalized_bonus(months)
    assert result.count_months == 3
    assert result.months == (months[1], months[2], months[3])
    assert result.sum_total == RubleAmount(300_000)
    assert result.monthly_average == RubleAmount(25_000)
    assert result.is_complete_12m is False


# --- rounding ROUND_HALF_UP ---


def test_average_rounds_half_up() -> None:
    result = calculate_normalized_bonus(
        (
            mk_month(2031, 1, 10_000),
            mk_month(2031, 2, 0),
            mk_month(2031, 3, 0),
        )
    )
    # 10000 / 12 = 833.33 -> 833
    assert result.monthly_average == RubleAmount(833)
    assert result.sum_total == RubleAmount(10_000)


# --- unsorted input is sorted ---


def test_unsorted_input_sorted_by_year_month() -> None:
    result = calculate_normalized_bonus(
        (
            mk_month(2031, 3, 300_000),
            mk_month(2031, 1, 100_000),
            mk_month(2031, 2, 200_000),
        )
    )
    assert [(m.year, m.month) for m in result.months] == [
        (2031, 1),
        (2031, 2),
        (2031, 3),
    ]
    assert result.sum_total == RubleAmount(600_000)
