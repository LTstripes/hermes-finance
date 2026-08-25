"""Pure domain tests for the unified Monthly Summary DTO (C10).

Covers the framework-independent contract of
:mod:`hermes_finance.domain.monthly_summary`:
- ``assemble_warnings`` ordering, duplication and delta-warning rules;
- the frozen/slots shape of :class:`MonthlySummaryResult` and its default
  ``calculation_version``.

No database is used; sub-results are constructed directly via their own
dataclasses with synthetic zero amounts.
"""

from dataclasses import FrozenInstanceError, fields

import pytest

from hermes_finance.domain.cash_balance import CashBalanceBreakdown, CashBalanceResult
from hermes_finance.domain.coverage_goals import CoverageGoalsResult
from hermes_finance.domain.forecast_passive_income import (
    ForecastPassiveIncomeBreakdown,
    ForecastPassiveIncomeResult,
)
from hermes_finance.domain.iis_result import IisResult, IisResultBreakdown
from hermes_finance.domain.liquid_capital import (
    LiquidCapitalClassBreakdown,
    LiquidCapitalResult,
)
from hermes_finance.domain.monthly_summary import (
    CALCULATION_VERSION,
    MonthlySummaryResult,
    assemble_warnings,
)
from hermes_finance.domain.normalized_bonus import NormalizedBonusResult
from hermes_finance.domain.salary_tax import SalaryTaxResult
from hermes_finance.domain.values import RubleAmount

ZERO = RubleAmount(0)

DELTA_WARNING = "Нет предыдущего месяца для расчёта дельты"

EXPECTED_FIELDS = (
    "year",
    "month",
    "liquid_capital",
    "liquid_capital_delta",
    "passive_income_actual",
    "passive_income_delta",
    "passive_income_average",
    "passive_income_average_months",
    "passive_income_average_complete",
    "forecast",
    "coverage",
    "cash_balance",
    "salary_tax",
    "salary_actual_net",
    "normalized_bonus",
    "iis",
    "warnings",
    "calculation_version",
    "passive_income_history_start_month",
    "passive_income_average_months_used",
)


def make_result(**overrides: object) -> MonthlySummaryResult:
    """Build a minimal valid ``MonthlySummaryResult`` (all zeros)."""
    liquid_capital = LiquidCapitalResult(
        total_assets=ZERO,
        total_debts_included=ZERO,
        liquid_capital_net=ZERO,
        breakdown=LiquidCapitalClassBreakdown(
            cash=ZERO,
            deposits=ZERO,
            securities=ZERO,
            other_liquid_assets=ZERO,
        ),
    )
    forecast = ForecastPassiveIncomeResult(
        annual_total=ZERO,
        monthly_total=ZERO,
        breakdown=ForecastPassiveIncomeBreakdown(
            expected_deposit_interest=ZERO,
            expected_coupon_net=ZERO,
            expected_dividend_component=ZERO,
            other_expected_capital_income=ZERO,
        ),
        is_approximate=False,
        warnings=(),
        dividend_average=ZERO,
        dividend_months_used=(),
    )
    coverage = CoverageGoalsResult(
        forecast_monthly=ZERO,
        actual_average=ZERO,
        mandatory_expenses=ZERO,
        coverage_pct=None,
        actual_mandatory_expense_coverage_pct=None,
        passive_income_minus_mandatory_expenses=ZERO,
        goal_target=ZERO,
        goal_progress_pct=None,
        is_approximate=False,
        warnings=(),
    )
    cash_balance = CashBalanceResult(
        total=ZERO,
        breakdown=CashBalanceBreakdown(
            salary_net=ZERO,
            bonus_net=ZERO,
            side_income_net=ZERO,
            cashback=ZERO,
            other_income=ZERO,
            passive_income=ZERO,
            mandatory_expenses=ZERO,
            other_expenses=ZERO,
            saving_allocations=ZERO,
        ),
    )
    salary_tax = SalaryTaxResult(tax_kopecks=0, calculated_net_kopecks=0, parts=())
    normalized_bonus = NormalizedBonusResult(
        monthly_average=ZERO,
        sum_total=ZERO,
        count_months=0,
        is_complete_12m=False,
        months=(),
        warnings=(),
    )
    iis = IisResult(
        portfolio_result_without_tax_benefit=ZERO,
        portfolio_result_with_tax_benefit=ZERO,
        breakdown=IisResultBreakdown(
            unrealized=ZERO,
            coupons=ZERO,
            dividends=ZERO,
            realized_pnl=ZERO,
            received_tax_benefits=ZERO,
            planned_tax_benefits=ZERO,
            submitted_tax_benefits=ZERO,
        ),
    )

    values = dict(
        year=2031,
        month=1,
        liquid_capital=liquid_capital,
        liquid_capital_delta=None,
        passive_income_actual=ZERO,
        passive_income_delta=None,
        passive_income_average=ZERO,
        passive_income_average_months=0,
        passive_income_average_complete=False,
        forecast=forecast,
        coverage=coverage,
        cash_balance=cash_balance,
        salary_tax=salary_tax,
        salary_actual_net=ZERO,
        normalized_bonus=normalized_bonus,
        iis=(iis,),
        warnings=(),
    )
    values.update(overrides)
    return MonthlySummaryResult(**values)


# --- assemble_warnings: empty inputs ---


def test_assemble_warnings_empty_inputs_return_empty_tuple() -> None:
    warnings = assemble_warnings(
        passive_income_average_warnings=(),
        forecast_warnings=(),
        coverage_warnings=(),
        normalized_bonus_warnings=(),
        iis_warnings=(),
        liquid_capital_delta=RubleAmount(0),
    )
    assert warnings == ()


# --- assemble_warnings: fixed concatenation order ---


def test_assemble_warnings_all_sources_in_fixed_order() -> None:
    warnings = assemble_warnings(
        passive_income_average_warnings=("avg-a", "avg-b"),
        forecast_warnings=("forecast-a",),
        coverage_warnings=("coverage-a", "coverage-b", "coverage-c"),
        normalized_bonus_warnings=("bonus-a",),
        iis_warnings=("iis-a", "iis-b"),
        liquid_capital_delta=RubleAmount(1_000),
    )
    assert warnings == (
        "avg-a",
        "avg-b",
        "forecast-a",
        "coverage-a",
        "coverage-b",
        "coverage-c",
        "bonus-a",
        "iis-a",
        "iis-b",
    )
    assert DELTA_WARNING not in warnings


# --- assemble_warnings: duplicates kept ---


def test_assemble_warnings_duplicates_are_kept() -> None:
    warnings = assemble_warnings(
        passive_income_average_warnings=("dup", "dup"),
        forecast_warnings=(),
        coverage_warnings=(),
        normalized_bonus_warnings=("dup",),
        iis_warnings=("dup", "dup"),
        liquid_capital_delta=None,
    )
    assert warnings == ("dup", "dup", "dup", "dup", "dup", DELTA_WARNING)


# --- assemble_warnings: delta warning appended last when delta is None ---


def test_assemble_warnings_delta_warning_appended_last_when_no_previous_month() -> None:
    warnings = assemble_warnings(
        passive_income_average_warnings=("avg-a",),
        forecast_warnings=("forecast-a",),
        coverage_warnings=(),
        normalized_bonus_warnings=(),
        iis_warnings=(),
        liquid_capital_delta=None,
    )
    assert warnings[-1] == DELTA_WARNING
    assert warnings == ("avg-a", "forecast-a", DELTA_WARNING)


def test_assemble_warnings_no_delta_warning_when_delta_is_present() -> None:
    # Even a zero delta is a real value: the warning must not appear.
    warnings = assemble_warnings(
        passive_income_average_warnings=(),
        forecast_warnings=(),
        coverage_warnings=(),
        normalized_bonus_warnings=(),
        iis_warnings=(),
        liquid_capital_delta=RubleAmount(0),
    )
    assert DELTA_WARNING not in warnings


# --- MonthlySummaryResult shape ---


def test_result_field_names_and_count() -> None:
    actual = tuple(f.name for f in fields(MonthlySummaryResult))
    assert actual == EXPECTED_FIELDS
    assert len(actual) == 20


def test_calculation_version_constant_and_default() -> None:
    assert CALCULATION_VERSION == "v2"
    result = make_result()
    assert result.calculation_version == "v2"


def test_result_is_frozen() -> None:
    result = make_result()
    with pytest.raises(FrozenInstanceError):
        result.year = 2032
    with pytest.raises(FrozenInstanceError):
        result.warnings = ("changed",)


def test_result_custom_calculation_version_is_accepted() -> None:
    result = make_result(calculation_version="v2")
    assert result.calculation_version == "v2"
