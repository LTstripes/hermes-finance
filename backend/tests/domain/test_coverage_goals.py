"""Unit tests for the pure coverage/goal calculator (C05, no database)."""

from decimal import Decimal

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.coverage_goals import (
    CoverageGoalsInput,
    calculate_coverage_goals,
)


def run(
    forecast_monthly: int,
    expenses: int,
    goal: int = 10_000_000,
    actual_average: int = 0,
    is_approximate: bool = False,
    forecast_warnings: tuple[str, ...] = (),
):
    return calculate_coverage_goals(
        CoverageGoalsInput(
            forecast_monthly=RubleAmount(forecast_monthly),
            actual_average=RubleAmount(actual_average),
            mandatory_expenses=RubleAmount(expenses),
            goal_target=RubleAmount(goal),
            is_approximate=is_approximate,
            forecast_warnings=forecast_warnings,
        )
    )


# --- normal case ---


def test_coverage_and_progress_normal_case() -> None:
    result = run(forecast_monthly=1_000_000, expenses=500_000)
    # 10000.00 / 5000.00 * 100 = 200.00%
    assert result.coverage_pct == Decimal("200.00")
    # 10000.00 / 100000.00 * 100 = 10.00%
    assert result.goal_progress_pct == Decimal("10.00")
    assert result.passive_income_minus_mandatory_expenses == RubleAmount(500_000)
    assert result.forecast_monthly == RubleAmount(1_000_000)
    assert result.mandatory_expenses == RubleAmount(500_000)
    assert result.goal_target == RubleAmount(10_000_000)
    assert result.is_approximate is False
    assert result.warnings == ()


# --- zero denominators are safe ---


def test_zero_expenses_returns_none_coverage_and_warning() -> None:
    result = run(forecast_monthly=1_000_000, expenses=0)
    assert result.coverage_pct is None
    assert result.passive_income_minus_mandatory_expenses == RubleAmount(1_000_000)
    assert "Обязательные расходы равны нулю — покрытие не рассчитывается" in result.warnings
    # goal progress still works
    assert result.goal_progress_pct == Decimal("10.00")


def test_zero_goal_returns_none_progress_and_warning() -> None:
    result = run(forecast_monthly=1_000_000, expenses=500_000, goal=0)
    assert result.goal_progress_pct is None
    assert "Цель равна нулю — прогресс не рассчитывается" in result.warnings
    assert result.coverage_pct == Decimal("200.00")


def test_both_zero_denominators_warn() -> None:
    result = run(forecast_monthly=1_000_000, expenses=0, goal=0)
    assert result.coverage_pct is None
    assert result.goal_progress_pct is None
    assert len(result.warnings) == 2


# --- coverage below and above 100 ---


def test_coverage_below_hundred_and_negative_remainder() -> None:
    result = run(forecast_monthly=7250, expenses=500_000)
    # 72.50 / 5000.00 * 100 = 1.45%
    assert result.coverage_pct == Decimal("1.45")
    assert result.passive_income_minus_mandatory_expenses == RubleAmount(-492_750)


def test_progress_above_hundred() -> None:
    result = run(forecast_monthly=20_000_000, expenses=500_000)
    # 200000.00 / 100000.00 * 100 = 200.00%
    assert result.goal_progress_pct == Decimal("200.00")


# --- rounding to 0.01 with ROUND_HALF_UP ---


def test_percent_quantized_to_two_decimals() -> None:
    result = run(forecast_monthly=10_000, expenses=30_000)
    # 100.00 / 300.00 * 100 = 33.333... -> 33.33
    assert result.coverage_pct == Decimal("33.33")


def test_percent_rounds_half_up() -> None:
    result = run(forecast_monthly=7250, expenses=100_000)
    # 72.50 / 1000.00 * 100 = 7.25
    assert result.coverage_pct == Decimal("7.25")
    # 72.50 / 100000.00 * 100 = 0.0725 -> 0.07
    assert result.goal_progress_pct == Decimal("0.07")


# --- approximate propagation and warning merge ---


def test_is_approximate_propagates() -> None:
    result = run(forecast_monthly=1_000_000, expenses=500_000, is_approximate=True)
    assert result.is_approximate is True


def test_forecast_warnings_merged_with_own_warnings() -> None:
    result = run(
        forecast_monthly=1_000_000,
        expenses=0,
        forecast_warnings=("Нет ожидаемых выплат в календаре прогноза",),
    )
    assert "Нет ожидаемых выплат в календаре прогноза" in result.warnings
    assert "Обязательные расходы равны нулю — покрытие не рассчитывается" in result.warnings


# --- actual average is passed through ---


def test_actual_average_passthrough() -> None:
    result = run(forecast_monthly=1_000_000, expenses=500_000, actual_average=333_333)
    assert result.actual_average == RubleAmount(333_333)
