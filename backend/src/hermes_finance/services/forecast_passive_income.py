"""ORM application service for forecast passive income (C04).

Loads expected cash flows from the 12-month calendar window and actual net
dividends from closed reporting months, maps them into the pure domain
calculator input, and returns the domain result DTO.  No API, no Pydantic,
no React.

Implements MASTER_SPEC §10.6:

    forecast_12m_net_passive_income =
        expected_deposit_interest_next_12m
      + expected_coupon_net_next_12m
      + expected_dividend_component
      + other_expected_capital_income

Key invariants (wiki §7):
- Money is integer kopecks via :class:`RubleAmount`; no binary float.
- Redemption is excluded from forecast passive income even though it
  appears in the expected cash-flow calendar.
- The dividend component comes from ACTUAL net dividends (closed months
  only), never from expected dividend flows — this prevents double-counting
  coupons and interest that are already in the calendar.
- Reads on closed months are allowed (B19-R2 guard is for writes only).
- No session.commit(), no migrations, no frontend, no C05 scope.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.cash_flows import ExpectedCashFlowType
from hermes_finance.domain.forecast_passive_income import (
    ExpectedFlow,
    ForecastPassiveIncomeInput,
    ForecastPassiveIncomeResult,
    calculate_forecast_passive_income,
)
from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.persistence import APP_SETTINGS_ID, AppSettings, ReportingMonth
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.reporting_months import get_reporting_month
from hermes_finance.services.settings import parse_passive_income_history_start_month


def forecast_passive_income(
    session: Session,
    reporting_month_id: int,
    forecast_version: str,
) -> ForecastPassiveIncomeResult:
    """Assemble forecast passive-income input from the database and calculate.

    1. Resolve the reporting month to obtain the snapshot date for the
       12-month calendar window.
    2. Load the canonical merged manual/provider payout calendar via
       ``merged_payout_calendar`` (window ``[snapshot_date, snapshot_date +
       1 year)``). Map each merged item to an :class:`ExpectedFlow`; the
       calendar owns reconciliation and lifecycle filtering. Redemption rows
       are skipped early to keep the list small; dividend rows are kept so
       the pure calculator's ignore-branch remains defense in depth.
    3. Load actual net dividends from all closed reporting months ordered
       by year/month.  For each closed month, call the C02 per-month
       calculator and take ``breakdown.dividends`` (NOT total) to build
       :class:`MonthlyPassiveIncome` entries.
    4. Delegate to the pure domain calculator.
    """
    # 1. Resolve reporting month
    get_reporting_month(session, reporting_month_id)

    # 2. Countable expected flows from the canonical merged calendar
    merged_months = merged_payout_calendar(
        session,
        reporting_month_id=reporting_month_id,
        forecast_version=forecast_version,
    )

    expected_flows: list[ExpectedFlow] = []
    for calendar_month in merged_months:
        for flow in calendar_month.items:
            # Skip redemption early — it must never increase passive income.
            # Keep dividend rows so the calculator's ignore-branch is tested.
            if ExpectedCashFlowType(flow.flow_type) is ExpectedCashFlowType.REDEMPTION:
                continue
            expected_flows.append(
                ExpectedFlow(
                    flow_type=flow.flow_type,
                    net_amount_kopecks=flow.expected_net_amount.kopecks,
                    is_approximate=flow.is_approximate,
                )
            )

    # 3. Actual net dividends from closed reporting months
    closed_months = session.execute(
        select(ReportingMonth.id, ReportingMonth.year, ReportingMonth.month)
        .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
        .order_by(ReportingMonth.year, ReportingMonth.month)
    ).all()

    dividend_months: list[MonthlyPassiveIncome] = []
    for month_id, year, month in closed_months:
        result = passive_income_for_month(session, month_id)
        dividend_months.append(
            MonthlyPassiveIncome(
                year=year,
                month=month,
                amount=result.breakdown.dividends,
            )
        )

    # 4. Delegate to pure calculator
    # Settings are optional for this read path. Do not call
    # ``get_or_create_settings`` here: its first-read seed commits a row and
    # would violate the C04/monthly-summary/dashboard no-writes contract.
    settings = session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))
    history_start_month = parse_passive_income_history_start_month(
        settings.passive_income_history_start_month if settings is not None else None
    )
    return calculate_forecast_passive_income(
        ForecastPassiveIncomeInput(
            expected_flows=tuple(expected_flows),
            dividend_months=tuple(dividend_months),
            history_start_month=history_start_month,
        )
    )
