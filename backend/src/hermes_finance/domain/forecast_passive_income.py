"""Pure domain forecast passive-income calculator (framework-independent).

Implements MASTER_SPEC §10.6:

    forecast_12m_net_passive_income =
        expected_deposit_interest_next_12m
      + expected_coupon_net_next_12m
      + expected_dividend_component
      + other_expected_capital_income

    forecast_monthly_net_passive_income = forecast_12m_net_passive_income / 12

Component sources (C04 checkpoint clarification):
- **expected_deposit_interest** — sum of expected ``interest`` flows from the
  12-month calendar window (deposit/savings interest events, same calendar
  as coupons).  The ``balance × rate`` deposit-interest option from
  MASTER_SPEC §10.6 is a FUTURE enhancement and is NOT part of this task.
- **expected_coupon_net** — sum of expected ``coupon`` flows (net of tax when
  known, marked approximate when tax is unknown).
- **expected_dividend_component** — annualised projection from the **actual**
  average net dividend over closed months, NOT from expected dividend flows.
  Using the actual average avoids double-counting coupons and interest that
  are already captured in the calendar.  The average reuses the C03 pure
  calculator (``calculate_passive_income_average``) which sorts by year/month,
  keeps at most the last 12, and divides with ``ROUND_HALF_UP``.
- **other_expected_capital_income** — sum of expected ``other`` flows.

Exclusions (defense in depth):
- ``redemption`` flows are NEVER counted — bond principal repayment is not
  income (wiki invariant).  They may appear in the calendar but must not
  increase forecast passive income.
- ``dividend`` flows in the expected calendar are IGNORED here — the dividend
  component comes solely from actual closed-month history.  Accepting them
  would double-count if actuals already reflect dividend seasonality.

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.  Division uses
:class:`decimal.Decimal` with ``ROUND_HALF_UP`` to round to whole kopecks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from hermes_finance.domain.cash_flows import ExpectedCashFlowType
from hermes_finance.domain.passive_income_average import (
    MonthlyPassiveIncome,
    PassiveIncomeAverageInput,
    calculate_passive_income_average,
)
from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount


@dataclass(frozen=True, slots=True)
class ExpectedFlow:
    """A single expected cash-flow row mapped from the ORM layer.

    ``flow_type`` is the string value of an :class:`ExpectedCashFlowType`
    member.  ``net_amount_kopecks`` is the already-computed expected net
    (gross minus tax when known, or gross when tax is unknown).
    """

    flow_type: str
    net_amount_kopecks: int
    is_approximate: bool


@dataclass(frozen=True, slots=True)
class ForecastPassiveIncomeInput:
    """Pure-domain input for the forecast passive-income calculator.

    ``expected_flows`` — expected cash-flow rows from the 12-month calendar
    window.  The calculator sums them by type and ignores ``dividend`` and
    ``redemption`` rows.

    ``dividend_months`` — actual net dividend per closed reporting month.
    The calculator runs these through the C03 averaging logic to produce
    the annualised dividend component.
    """

    expected_flows: tuple[ExpectedFlow, ...] = ()
    dividend_months: tuple[MonthlyPassiveIncome, ...] = ()


@dataclass(frozen=True, slots=True)
class ForecastPassiveIncomeBreakdown:
    """Breakdown of the 12-month forecast by component."""

    expected_deposit_interest: RubleAmount
    expected_coupon_net: RubleAmount
    expected_dividend_component: RubleAmount
    other_expected_capital_income: RubleAmount


@dataclass(frozen=True, slots=True)
class ForecastPassiveIncomeResult:
    """Pure-domain output of the forecast passive-income calculator."""

    annual_total: RubleAmount
    monthly_total: RubleAmount
    breakdown: ForecastPassiveIncomeBreakdown
    is_approximate: bool
    warnings: tuple[str, ...]
    dividend_average: RubleAmount
    dividend_months_used: tuple[MonthlyPassiveIncome, ...]


def _coerce_flow_type(flow_type: str) -> ExpectedCashFlowType | None:
    """Convert a flow-type string to the enum, or ``None`` if unknown."""
    try:
        return ExpectedCashFlowType(flow_type)
    except ValueError:
        return None


def calculate_forecast_passive_income(
    input_data: ForecastPassiveIncomeInput,
) -> ForecastPassiveIncomeResult:
    """Calculate the 12-month forecast passive income from pure-domain input.

    No binary ``float``, no division by zero, no double-counting.

    Empty input produces zero totals, ``is_approximate=False``, and the two
    relevant Russian warnings.
    """
    # --- Expected flows: sum by type, ignore dividend and redemption ---
    deposit_interest_kop = 0
    coupon_net_kop = 0
    other_kop = 0
    is_approximate = False

    for flow in input_data.expected_flows:
        ft = _coerce_flow_type(flow.flow_type)

        # Mark approximate if ANY expected flow is approximate
        if flow.is_approximate:
            is_approximate = True

        if ft is ExpectedCashFlowType.INTEREST:
            deposit_interest_kop += flow.net_amount_kopecks
        elif ft is ExpectedCashFlowType.COUPON:
            coupon_net_kop += flow.net_amount_kopecks
        elif ft is ExpectedCashFlowType.OTHER:
            other_kop += flow.net_amount_kopecks
        # DIVIDEND: ignored — dividend component comes from actuals only.
        # REDEMPTION: ignored — principal repayment is never income.
        # Unknown types: ignored (defense in depth).

    # --- Dividend component: annualise actual average net dividends ---
    avg_result = calculate_passive_income_average(
        PassiveIncomeAverageInput(months=input_data.dividend_months)
    )
    dividend_average = avg_result.average
    dividend_months_used = avg_result.months

    # annual dividend = average monthly dividend × 12 (exact integer kopecks)
    dividend_component_kop = dividend_average.kopecks * 12

    # --- Annual total (integer kopecks, no division) ---
    annual_total_kop = deposit_interest_kop + coupon_net_kop + dividend_component_kop + other_kop

    # --- Monthly total: annual / 12 with ROUND_HALF_UP ---
    monthly_total_kop = (Decimal(annual_total_kop) / Decimal(12)).to_integral_value(
        rounding=FINANCIAL_ROUNDING
    )

    # --- Warnings (Russian, UI-ready) ---
    warnings: list[str] = []

    dividend_count = len(dividend_months_used)
    if dividend_count == 0:
        warnings.append("Нет закрытых месяцев для оценки дивидендного компонента")
    elif dividend_count < 12:
        warnings.append(f"Дивидендный компонент оценён по {dividend_count} месяцев из 12")

    if not input_data.expected_flows:
        warnings.append("Нет ожидаемых выплат в календаре прогноза")

    return ForecastPassiveIncomeResult(
        annual_total=RubleAmount(annual_total_kop),
        monthly_total=RubleAmount(int(monthly_total_kop)),
        breakdown=ForecastPassiveIncomeBreakdown(
            expected_deposit_interest=RubleAmount(deposit_interest_kop),
            expected_coupon_net=RubleAmount(coupon_net_kop),
            expected_dividend_component=RubleAmount(dividend_component_kop),
            other_expected_capital_income=RubleAmount(other_kop),
        ),
        is_approximate=is_approximate,
        warnings=tuple(warnings),
        dividend_average=dividend_average,
        dividend_months_used=dividend_months_used,
    )
