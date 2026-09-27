"""Bounded Income & Plans read model for the S10 planning slice.

This assembler deliberately composes the existing passive-income forecast,
coverage/goals, and cash-balance services.  It does not include the broader
monthly summary because salary-tax, IIS, and unrelated summary components are
not prerequisites for this planning surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.cash_balance import CashBalanceResult
from hermes_finance.domain.coverage_goals import CoverageGoalsResult
from hermes_finance.domain.forecast_passive_income import ForecastPassiveIncomeResult
from hermes_finance.persistence import ReportingMonth
from hermes_finance.services.cash_balance import cash_balance_for_month
from hermes_finance.services.coverage_goals import coverage_and_goals
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.reporting_months import get_reporting_month


@dataclass(frozen=True, slots=True)
class IncomePlanSummaryResult:
    """Canonical inputs needed by the Income & Plans page."""

    month: ReportingMonth
    forecast_version: str
    forecast: ForecastPassiveIncomeResult
    coverage: CoverageGoalsResult
    cash_balance: CashBalanceResult
    warnings: tuple[str, ...]


@coherent_read_operation
def income_plan_summary(
    session: Session,
    reporting_month_id: int,
    *,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> IncomePlanSummaryResult:
    """Assemble the independent, read-only S10 planning summary."""
    reporting_month = get_reporting_month(session, reporting_month_id)
    forecast = forecast_passive_income(session, reporting_month_id, forecast_version)
    coverage = coverage_and_goals(session, reporting_month_id, forecast_version)
    cash_balance = cash_balance_for_month(session, reporting_month_id)

    # Coverage is the canonical planning warning aggregate: it carries the
    # forecast warnings and adds only its own denominator warnings.
    return IncomePlanSummaryResult(
        month=reporting_month,
        forecast_version=forecast_version,
        forecast=forecast,
        coverage=coverage,
        cash_balance=cash_balance,
        warnings=coverage.warnings,
    )
