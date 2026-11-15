"""Exact total-income rules, coverage and analytical salary estimates."""

from dataclasses import replace

import pytest

from hermes_finance.domain.total_income import TotalIncomePoint, calculate_total_income
from hermes_finance.domain.values import RubleAmount


def point(
    year: int,
    month: int,
    *,
    salary: int = 100,
    bonus: int = 0,
    passive: int | None = 0,
    other: int = 0,
) -> TotalIncomePoint:
    return TotalIncomePoint(
        reporting_month_id=year * 12 + month,
        year=year,
        month=month,
        salary_net=RubleAmount(salary),
        bonus_net=RubleAmount(bonus),
        passive_actual=RubleAmount(passive) if passive is not None else None,
        other_net=RubleAmount(other),
    )


def test_estimate_only_leading_zero_and_leave_input_unchanged() -> None:
    months = (
        point(2031, 1, salary=0),
        point(2031, 3, salary=0),
        point(2031, 4, salary=800),
        point(2031, 5, salary=0),
        point(2031, 6, salary=900),
    )
    result = calculate_total_income(tuple(reversed(months)))
    assert [p.salary_net.kopecks for p in result.points] == [800, 800, 800, 0, 900]
    assert [p.salary_is_estimate for p in result.points] == [True, True, False, False, False]
    assert result.calendar_year.estimate_months == 2
    assert result.calendar_year.salary_sum == RubleAmount(3300)
    assert result.calendar_year.months_observed == 5
    assert result.calendar_year.warnings[0] == "Зарплата за 2 мес оценена по апрельской (04.2031)"
    assert months[0].salary_net == RubleAmount(0)
    assert not months[0].salary_is_estimate


def test_all_zero_salary_has_no_estimate_or_invented_bonus() -> None:
    result = calculate_total_income((point(2031, 2, salary=0),))
    assert not result.points[0].salary_is_estimate
    assert result.all.salary_months == result.all.bonus_months == 1
    assert result.all.bonus_sum == result.all.bonus_smoothed_monthly == RubleAmount(0)
    assert result.all.monthly_average == RubleAmount(0)


def test_passive_boundary_null_zero_and_negative_have_distinct_coverage() -> None:
    result = calculate_total_income(
        (
            point(2031, 1, passive=999),
            point(2031, 3, passive=0),
            point(2031, 4, passive=None),
            point(2031, 5, passive=-30),
        ),
        history_start_month=(2031, 3),
    )
    assert [p.passive_actual for p in result.points] == [
        None,
        RubleAmount(0),
        None,
        RubleAmount(-30),
    ]
    assert result.all.passive_months == 2
    assert result.all.passive_sum == RubleAmount(-30)
    assert result.all.monthly_average == RubleAmount(85)
    assert "Пассивка учитывается с 03.2031" in result.all.warnings
    assert result.configured_start_month == "2031-03"


def test_no_passive_months_keeps_headline_unknown() -> None:
    window = calculate_total_income((point(2031, 1),), history_start_month=(2031, 2)).all
    assert window.salary_monthly_average == RubleAmount(100)
    assert window.passive_sum is window.passive_monthly_average is None
    assert window.monthly_average is window.current_level is None
    assert window.passive_months == window.current_passive_months == 0


def test_calendar_windows_leave_missing_calendar_slots_absent() -> None:
    result = calculate_total_income(
        (
            point(2029, 12, bonus=1200),
            point(2030, 12),
            point(2031, 1),
            point(2031, 10),
        )
    )
    assert (result.calendar_year.from_month, result.calendar_year.to_month) == (
        "2031-01",
        "2031-10",
    )
    assert result.calendar_year.months_used == ("2031-01", "2031-10")
    assert (result.rolling_12.from_month, result.rolling_12.to_month) == (
        "2030-11",
        "2031-10",
    )
    assert result.rolling_12.months_observed == 3
    assert result.rolling_12.bonus_sum == RubleAmount(0)
    assert result.all.from_month == "2029-12"
    assert result.all.months_observed == 4
    # 2029-12..2031-10 spans 23 calendar months: 1200 / 23 = 52.17 -> 52.
    assert result.all.bonus_target_months == 23
    assert result.all.bonus_smoothed_monthly == RubleAmount(52)


def test_december_bonus_is_actual_once_and_smoothed_over_twelve() -> None:
    months = tuple(point(2031, m, bonus=1200 if m == 12 else 0) for m in range(1, 13))
    result = calculate_total_income(months)
    assert [p.bonus_net.kopecks for p in result.points] == [0] * 11 + [1200]
    assert result.calendar_year.bonus_sum == RubleAmount(1200)
    assert result.calendar_year.bonus_smoothed_monthly == RubleAmount(100)
    assert result.calendar_year.monthly_average == RubleAmount(200)
    assert result.calendar_year.bonus_months == result.calendar_year.bonus_target_months == 12
    partial = calculate_total_income((months[-1],)).rolling_12
    assert partial.months_observed == 1
    assert partial.bonus_smoothed_monthly == RubleAmount(100)
    assert partial.monthly_average == RubleAmount(200)


def test_rolling_twelve_includes_exact_start_and_excludes_older_bonus() -> None:
    result = calculate_total_income(
        (
            point(2030, 10, bonus=2400),
            point(2030, 11, bonus=1200),
            point(2031, 10),
        )
    )
    assert result.rolling_12.months_used == ("2030-11", "2031-10")
    assert result.rolling_12.bonus_smoothed_monthly == RubleAmount(100)
    assert result.calendar_year.bonus_smoothed_monthly == RubleAmount(0)
    # 2030-10..2031-10 spans 13 months: 3600 / 13 = 276.92 -> 277.
    assert result.all.bonus_smoothed_monthly == RubleAmount(277)


def test_all_window_longer_than_a_year_does_not_double_yearly_bonuses() -> None:
    months = tuple(
        point(year, m, bonus=1200 if m == 12 else 0) for year in (2030, 2031) for m in range(1, 13)
    )
    result = calculate_total_income(months)
    assert result.all.bonus_target_months == 24
    assert result.all.bonus_smoothed_monthly == RubleAmount(100)
    assert result.rolling_12.bonus_smoothed_monthly == RubleAmount(100)
    assert result.all.monthly_average == result.rolling_12.monthly_average == RubleAmount(200)


def test_passive_start_warning_only_when_window_reaches_before_start() -> None:
    result = calculate_total_income(
        (point(2030, 1, passive=5), point(2031, 6, passive=5)), history_start_month=(2031, 1)
    )
    assert "Пассивка учитывается с 01.2031" in result.all.warnings
    assert not any(w.startswith("Пассивка") for w in result.calendar_year.warnings)


def test_estimate_basis_can_be_outside_window() -> None:
    result = calculate_total_income((point(2030, 1, salary=0), point(2031, 12, salary=600)))
    assert result.all.estimate_months == 1
    assert result.calendar_year.estimate_months == result.rolling_12.estimate_months == 0
    assert result.all.salary_sum == RubleAmount(1200)


def test_current_level_uses_last_three_closed_observations_and_window_bonus() -> None:
    result = calculate_total_income(
        (
            point(2029, 12, passive=900, bonus=1200),
            point(2030, 12, passive=30),
            point(2031, 2, passive=None),
            point(2031, 5, salary=400, passive=90, other=99999),
        )
    )
    assert result.all.current_passive_months == 2
    # all spans 2029-12..2031-05 = 18 months: 400 + 60 + 1200 / 18 = 526.67 -> 527.
    assert result.all.current_level == RubleAmount(527)
    assert result.calendar_year.current_level == result.rolling_12.current_level == RubleAmount(460)
    assert result.calendar_year.other_sum == RubleAmount(99999)
    assert result.calendar_year.monthly_average == RubleAmount(340)


def test_round_once_after_adding_unrounded_ratios_half_up() -> None:
    result = calculate_total_income((point(2031, 1, salary=0, passive=0, bonus=6),))
    assert result.all.bonus_smoothed_monthly == RubleAmount(1)
    assert result.all.monthly_average == RubleAmount(1)
    # Salary = 0.5 kop, passive = 0.5 kop: total rounds to 1, not 2.
    result = calculate_total_income((point(2031, 1, salary=1, passive=1), point(2031, 2, salary=0)))
    assert result.all.salary_monthly_average == RubleAmount(1)
    assert result.all.passive_monthly_average == RubleAmount(1)
    assert result.all.monthly_average == RubleAmount(1)
    negative = calculate_total_income(
        (point(2031, 1, salary=0, passive=-1), point(2031, 2, salary=0))
    )
    assert negative.all.monthly_average == RubleAmount(-1)


def test_empty_history_is_unavailable_not_zero() -> None:
    result = calculate_total_income(())
    assert result.points == ()
    for window in (result.calendar_year, result.rolling_12, result.all):
        assert window.from_month is window.to_month is None
        assert window.salary_sum is window.passive_sum is window.bonus_sum is None
        assert (
            window.bonus_smoothed_monthly is window.monthly_average is window.current_level is None
        )
        assert window.months_observed == 0


def test_duplicate_or_invalid_month_fails() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        calculate_total_income((point(2031, 1), point(2031, 1)))
    with pytest.raises(ValueError, match="invalid"):
        calculate_total_income((replace(point(2031, 1), month=13),))
