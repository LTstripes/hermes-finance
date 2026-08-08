"""Unit tests for the pure forecast passive-income calculator (C04, no database)."""

import pytest

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.forecast_passive_income import (
    ExpectedFlow,
    ForecastPassiveIncomeInput,
    calculate_forecast_passive_income,
)
from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome

WARN_NO_DIVIDEND_MONTHS = "Нет закрытых месяцев для оценки дивидендного компонента"
WARN_NO_EXPECTED_FLOWS = "Нет ожидаемых выплат в календаре прогноза"


def mk_flow(flow_type: str, kopecks: int, approximate: bool = False) -> ExpectedFlow:
    return ExpectedFlow(
        flow_type=flow_type,
        net_amount_kopecks=kopecks,
        is_approximate=approximate,
    )


def mk_month(year: int, month: int, kopecks: int) -> MonthlyPassiveIncome:
    return MonthlyPassiveIncome(year=year, month=month, amount=RubleAmount(kopecks))


# --- empty input ---


def test_empty_input_returns_zeros_and_both_warnings() -> None:
    result = calculate_forecast_passive_income(ForecastPassiveIncomeInput())
    assert result.annual_total == RubleAmount(0)
    assert result.monthly_total == RubleAmount(0)
    assert result.breakdown.expected_deposit_interest == RubleAmount(0)
    assert result.breakdown.expected_coupon_net == RubleAmount(0)
    assert result.breakdown.expected_dividend_component == RubleAmount(0)
    assert result.breakdown.other_expected_capital_income == RubleAmount(0)
    assert result.is_approximate is False
    assert result.dividend_average == RubleAmount(0)
    assert result.dividend_months_used == ()
    assert WARN_NO_DIVIDEND_MONTHS in result.warnings
    assert WARN_NO_EXPECTED_FLOWS in result.warnings


# --- expected flows summed by type ---


def test_flows_sum_by_type() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(
            expected_flows=(
                mk_flow("interest", 10_000),
                mk_flow("coupon", 5_000),
                mk_flow("other", 2_500),
            )
        )
    )
    assert result.annual_total == RubleAmount(17_500)
    # 17500 / 12 = 1458.333 -> 1458 kopecks (ROUND_HALF_UP)
    assert result.monthly_total == RubleAmount(1_458)
    assert result.breakdown.expected_deposit_interest == RubleAmount(10_000)
    assert result.breakdown.expected_coupon_net == RubleAmount(5_000)
    assert result.breakdown.expected_dividend_component == RubleAmount(0)
    assert result.breakdown.other_expected_capital_income == RubleAmount(2_500)
    assert result.is_approximate is False
    assert "Дивидендный компонент оценён по" not in result.warnings
    assert WARN_NO_EXPECTED_FLOWS not in result.warnings
    assert WARN_NO_DIVIDEND_MONTHS in result.warnings


# --- dividend expected flows are ignored (actuals only) ---


def test_dividend_expected_flow_is_ignored() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(
            expected_flows=(
                mk_flow("dividend", 500_000),
                mk_flow("interest", 10_000),
            )
        )
    )
    assert result.annual_total == RubleAmount(10_000)
    assert result.breakdown.expected_dividend_component == RubleAmount(0)


def test_approximate_dividend_flow_still_sets_approximate_flag() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(expected_flows=(mk_flow("dividend", 500_000, approximate=True),))
    )
    assert result.annual_total == RubleAmount(0)
    assert result.is_approximate is True


# --- redemption expected flows are ignored (principal is not income) ---


def test_redemption_expected_flow_is_ignored() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(expected_flows=(mk_flow("redemption", 1_000_000),))
    )
    assert result.annual_total == RubleAmount(0)
    assert result.monthly_total == RubleAmount(0)
    assert result.breakdown.expected_coupon_net == RubleAmount(0)
    assert result.is_approximate is False


# --- unknown flow types are ignored (defense in depth) ---


def test_unknown_flow_type_is_ignored() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(expected_flows=(mk_flow("mystery_type", 5_000),))
    )
    assert result.annual_total == RubleAmount(0)
    assert result.is_approximate is False


# --- dividend months annualised ---


def test_dividend_months_annualise_average() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(
            dividend_months=(
                mk_month(2031, 1, 100_000),
                mk_month(2031, 2, 100_000),
                mk_month(2031, 3, 100_000),
            )
        )
    )
    assert result.dividend_average == RubleAmount(100_000)
    assert result.breakdown.expected_dividend_component == RubleAmount(1_200_000)
    assert result.annual_total == RubleAmount(1_200_000)
    assert result.monthly_total == RubleAmount(100_000)
    assert "Дивидендный компонент оценён по 3 месяцев из 12" in result.warnings
    assert WARN_NO_EXPECTED_FLOWS in result.warnings


def test_thirteen_dividend_months_use_last_twelve() -> None:
    months = tuple(mk_month(2031, m, 100_000) for m in range(1, 13)) + (mk_month(2032, 1, 200_000),)
    result = calculate_forecast_passive_income(ForecastPassiveIncomeInput(dividend_months=months))
    # window = 11 * 100000 + 200000 = 1300000; avg = 1300000/12 = 108333.33 -> 108333
    assert result.dividend_average == RubleAmount(108_333)
    # component = 108333 * 12 = 1299996
    assert result.breakdown.expected_dividend_component == RubleAmount(1_299_996)
    assert result.annual_total == RubleAmount(1_299_996)
    assert result.monthly_total == RubleAmount(108_333)
    assert len(result.dividend_months_used) == 12
    # oldest month (2031, 1) must be excluded from the window
    assert result.dividend_months_used[0] == mk_month(2031, 2, 100_000)


def test_zero_dividend_months_yields_zero_component_and_warning() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(expected_flows=(mk_flow("interest", 10_000),))
    )
    assert result.breakdown.expected_dividend_component == RubleAmount(0)
    assert result.annual_total == RubleAmount(10_000)
    assert WARN_NO_DIVIDEND_MONTHS in result.warnings


# --- is_approximate propagation ---


@pytest.mark.parametrize(
    ("flows", "expected_approximate"),
    [
        ((mk_flow("interest", 10_000), mk_flow("coupon", 5_000)), False),
        ((mk_flow("interest", 10_000), mk_flow("coupon", 5_000, approximate=True)), True),
        ((mk_flow("interest", 10_000, approximate=True), mk_flow("coupon", 5_000)), True),
        ((mk_flow("redemption", 1_000_000, approximate=True),), True),
    ],
)
def test_is_approximate_propagation(
    flows: tuple[ExpectedFlow, ...], expected_approximate: bool
) -> None:
    result = calculate_forecast_passive_income(ForecastPassiveIncomeInput(expected_flows=flows))
    assert result.is_approximate is expected_approximate


# --- monthly rounding (ROUND_HALF_UP to whole kopecks) ---


@pytest.mark.parametrize(
    ("annual_kopecks", "expected_monthly_kopecks"),
    [
        (1, 0),  # 1/12 = 0.0833 -> 0
        (6, 1),  # 6/12 = 0.5 -> 1 (HALF_UP)
        (10_001, 833),  # 10001/12 = 833.4167 -> 833
    ],
)
def test_monthly_total_rounds_half_up(annual_kopecks: int, expected_monthly_kopecks: int) -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(expected_flows=(mk_flow("interest", annual_kopecks),))
    )
    assert result.annual_total == RubleAmount(annual_kopecks)
    assert result.monthly_total == RubleAmount(expected_monthly_kopecks)


# --- dividend average rounding flows into the component ---


def test_dividend_average_rounding_flows_into_component() -> None:
    # 100.00 RUB over 3 months -> 10000/3 = 3333.33 -> 3333; component = 3333 * 12 = 39996
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(
            dividend_months=(
                mk_month(2031, 1, 10_000),
                mk_month(2031, 2, 0),
                mk_month(2031, 3, 0),
            )
        )
    )
    assert result.dividend_average == RubleAmount(3_333)
    assert result.breakdown.expected_dividend_component == RubleAmount(39_996)
    assert result.annual_total == RubleAmount(39_996)


# --- combined flows and dividend months ---


def test_combined_flows_and_dividend_months() -> None:
    result = calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(
            expected_flows=(
                mk_flow("interest", 10_000),
                mk_flow("coupon", 5_000),
            ),
            dividend_months=(
                mk_month(2031, 1, 100_000),
                mk_month(2031, 2, 100_000),
                mk_month(2031, 3, 100_000),
            ),
        )
    )
    # 10000 + 5000 + 1200000 = 1215000; monthly = 1215000/12 = 101250
    assert result.annual_total == RubleAmount(1_215_000)
    assert result.monthly_total == RubleAmount(101_250)
    assert result.warnings == ("Дивидендный компонент оценён по 3 месяцев из 12",)
