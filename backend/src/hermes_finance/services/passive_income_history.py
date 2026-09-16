"""Backend read model for the Home passive-income block.

The read model intentionally contains only CLOSED reporting months. Actual
monthly totals and the selected report's canonical source buckets are built
from the existing passive-income service; forecast and dated future payouts
remain separate read concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.passive_income import PassiveIncomeResult
from hermes_finance.domain.passive_income_average import PassiveIncomeAverageResult
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import ReportingMonth
from hermes_finance.services.passive_income import passive_income_for_months
from hermes_finance.services.passive_income_average import passive_income_average_from_results
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


@dataclass(frozen=True, slots=True)
class PassiveIncomeHistoryPoint:
    """Actual passive income for one CLOSED reporting month."""

    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    passive_income_actual: RubleAmount
    included_in_average_window: bool


@dataclass(frozen=True, slots=True)
class PassiveIncomeSelectedReport:
    """Actual passive income and canonical bucket totals for one CLOSED report."""

    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    result: PassiveIncomeResult


@dataclass(frozen=True, slots=True)
class PassiveIncomeHistoryReadModel:
    """Home passive-income history plus one selected report breakdown."""

    points: tuple[PassiveIncomeHistoryPoint, ...]
    average: PassiveIncomeAverageResult
    latest_closed_report_id: int | None
    selected_report: PassiveIncomeSelectedReport | None


def passive_income_history(
    session: Session,
    *,
    selected_reporting_month_id: int | None = None,
) -> PassiveIncomeHistoryReadModel:
    """Return CLOSED actual history and the selected/latest source breakdown.

    The optional selection is restricted to CLOSED reports. With no selection,
    the latest CLOSED report is selected by reporting period, independently of
    any newer DRAFT report. The three source tables are read once through the
    existing batch helper, and the average is calculated from those same
    results.
    """
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        )
    )
    month_rows = tuple((month.id, month.year, month.month) for month in months)
    result_by_month = passive_income_for_months(
        session,
        [month_id for month_id, _, _ in month_rows],
    )
    average = passive_income_average_from_results(session, month_rows, result_by_month)
    average_months_used = set(average.months_used)

    points = tuple(
        PassiveIncomeHistoryPoint(
            reporting_month_id=month.id,
            year=month.year,
            month=month.month,
            snapshot_date=month.snapshot_date,
            passive_income_actual=result_by_month[month.id].total_net_passive_income,
            included_in_average_window=f"{month.year:04d}-{month.month:02d}" in average_months_used,
        )
        for month in months
    )

    if selected_reporting_month_id is None:
        selected_month = months[-1] if months else None
    else:
        selected_month = next(
            (month for month in months if month.id == selected_reporting_month_id),
            None,
        )
        if selected_month is None:
            existing = session.get(ReportingMonth, selected_reporting_month_id)
            if existing is None:
                raise ReportingMonthNotFoundError(
                    f"reporting month {selected_reporting_month_id} was not found"
                )
            raise LookupError(f"reporting month {selected_reporting_month_id} is not closed")

    selected_report = (
        PassiveIncomeSelectedReport(
            reporting_month_id=selected_month.id,
            year=selected_month.year,
            month=selected_month.month,
            snapshot_date=selected_month.snapshot_date,
            result=result_by_month[selected_month.id],
        )
        if selected_month is not None
        else None
    )
    return PassiveIncomeHistoryReadModel(
        points=points,
        average=average,
        latest_closed_report_id=months[-1].id if months else None,
        selected_report=selected_report,
    )
