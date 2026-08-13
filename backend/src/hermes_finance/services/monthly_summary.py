"""ORM application service for the unified Monthly Summary (C10).

Wires every Phase-C calculator (C01-C09) into one domain DTO so the
frontend and export never sum financial figures themselves.  No API,
no Pydantic, no React, no migrations — C10 only calls existing services.

The service computes KPIs and breakdowns for the current reporting month,
computes deltas against the previous reporting month (liquid capital and
passive income actual only), and assembles the pure
:class:`~hermes_finance.domain.monthly_summary.MonthlySummaryResult`.

Key invariants (AGENTS.md / wiki §7):
- Money is integer kopecks via :class:`RubleAmount`; no binary ``float``.
- No formula duplication — each KPI is delegated to its existing service.
- Deltas are ``None`` when no previous reporting month exists.
- IIS results are computed for every account that has an
  :class:`~hermes_finance.persistence.IisProfile`.
- Reads on closed months are allowed (B19-R2 guard is for writes only).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.monthly_summary import (
    MonthlySummaryResult,
    assemble_warnings,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import IisProfile, ReportingMonth
from hermes_finance.services.cash_balance import cash_balance_for_month
from hermes_finance.services.coverage_goals import coverage_and_goals
from hermes_finance.services.forecast_passive_income import (
    forecast_passive_income,
)
from hermes_finance.services.iis_result import iis_result
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.normalized_bonus import normalized_bonus
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.passive_income_average import (
    passive_income_average,
)
from hermes_finance.services.reporting_months import get_reporting_month
from hermes_finance.services.salary import (
    actual_net_for_month,
    calculate_salary_tax,
)

DEFAULT_FORECAST_VERSION = "v1"


def _previous_reporting_month(session: Session, *, year: int, month: int) -> ReportingMonth | None:
    """Return the reporting month with the largest ``(year, month)`` strictly less than ``(year, month)``.

    Any status is accepted; ``None`` when no earlier month exists.
    """
    return session.scalar(
        select(ReportingMonth)
        .where(
            (ReportingMonth.year < year)
            | ((ReportingMonth.year == year) & (ReportingMonth.month < month))
        )
        .order_by(ReportingMonth.year.desc(), ReportingMonth.month.desc())
        .limit(1)
    )


def monthly_summary(
    session: Session,
    reporting_month_id: int,
    *,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> MonthlySummaryResult:
    """Assemble the unified monthly summary for a reporting month.

    Calls every existing Phase-C calculator, derives deltas against the
    previous reporting month, and returns the pure domain DTO.
    """
    reporting_month = get_reporting_month(session, reporting_month_id)
    year = reporting_month.year
    month = reporting_month.month

    # --- Current-month KPIs (always computed) ---
    liquid_capital = liquid_capital_for_month(session, reporting_month_id)
    passive_income_result = passive_income_for_month(session, reporting_month_id)
    passive_income_actual = passive_income_result.total_net_passive_income

    # --- Previous month (for deltas only) ---
    prev = _previous_reporting_month(session, year=year, month=month)

    liquid_capital_delta: RubleAmount | None = None
    passive_income_delta: RubleAmount | None = None

    if prev is not None:
        prev_liquid = liquid_capital_for_month(session, prev.id)
        prev_passive = passive_income_for_month(session, prev.id)

        liquid_capital_delta = RubleAmount(
            liquid_capital.liquid_capital_net.kopecks - prev_liquid.liquid_capital_net.kopecks
        )
        passive_income_delta = RubleAmount(
            passive_income_actual.kopecks - prev_passive.total_net_passive_income.kopecks
        )

    avg_result = passive_income_average(session)
    passive_income_avg = avg_result.average

    forecast = forecast_passive_income(session, reporting_month_id, forecast_version)
    coverage = coverage_and_goals(session, reporting_month_id, forecast_version)
    cash_bal = cash_balance_for_month(session, reporting_month_id)
    salary_tax = calculate_salary_tax(session, reporting_month_id)
    salary_actual_net = actual_net_for_month(session, reporting_month_id)
    norm_bonus = normalized_bonus(session)

    # --- IIS results: one per account having an IisProfile ---
    iis_account_ids = (
        session.execute(select(IisProfile.account_id).order_by(IisProfile.account_id))
        .scalars()
        .all()
    )

    iis_results = tuple(
        iis_result(session, account_id=aid, reporting_month_id=reporting_month_id)
        for aid in iis_account_ids
    )

    # --- Warnings ---
    # PassiveIncomeAverageResult has no warnings field (the UI warning
    # text lives in the docstring, not in the DTO), so its slot is empty.
    warnings = assemble_warnings(
        passive_income_average_warnings=(),
        forecast_warnings=forecast.warnings,
        coverage_warnings=coverage.warnings,
        normalized_bonus_warnings=norm_bonus.warnings,
        iis_warnings=(),  # IisResult carries no warnings
        liquid_capital_delta=liquid_capital_delta,
    )

    return MonthlySummaryResult(
        year=year,
        month=month,
        liquid_capital=liquid_capital,
        liquid_capital_delta=liquid_capital_delta,
        passive_income_actual=passive_income_actual,
        passive_income_delta=passive_income_delta,
        passive_income_average=passive_income_avg,
        passive_income_average_months=avg_result.count_months,
        passive_income_average_complete=avg_result.is_complete_12m,
        passive_income_history_start_month=avg_result.configured_start_month,
        passive_income_average_months_used=avg_result.months_used,
        forecast=forecast,
        coverage=coverage,
        cash_balance=cash_bal,
        salary_tax=salary_tax,
        salary_actual_net=salary_actual_net,
        normalized_bonus=norm_bonus,
        iis=iis_results,
        warnings=warnings,
    )
