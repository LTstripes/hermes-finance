"""Coherent, zero-write ORM adapter for total-income analytics."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.incomes import IncomeType
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.total_income import (
    TotalIncomePoint,
    TotalIncomeResult,
    calculate_total_income,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import APP_SETTINGS_ID, AppSettings, IncomeEntry, ReportingMonth
from hermes_finance.services.passive_income import passive_income_for_months
from hermes_finance.services.settings import parse_passive_income_history_start_month


@dataclass(frozen=True, slots=True)
class TotalIncomeReadModel:
    latest_closed_report_id: int | None
    result: TotalIncomeResult


@coherent_read_operation
def total_income(session: Session, *, month_id: int | None = None) -> TotalIncomeReadModel:
    """Read CLOSED records only; explicit month must still be the latest CLOSED.

    No settings seeding, salary writes, tax recalculation or external I/O.
    Income amounts are saved net facts, independently of cash-flow inclusion.
    """
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        )
    )
    latest_id = months[-1].id if months else None
    if month_id is not None and month_id != latest_id:
        raise LookupError("Для общего дохода выберите последний закрытый месяц")
    ids = [m.id for m in months]
    totals = (
        {
            (report_id, income_type): int(amount)
            for report_id, income_type, amount in session.execute(
                select(
                    IncomeEntry.reporting_month_id,
                    IncomeEntry.income_type,
                    func.sum(IncomeEntry.net_amount_kopecks),
                )
                .where(IncomeEntry.reporting_month_id.in_(ids))
                .group_by(IncomeEntry.reporting_month_id, IncomeEntry.income_type)
            )
        }
        if ids
        else {}
    )
    passive = passive_income_for_months(session, ids)
    settings = session.get(AppSettings, APP_SETTINGS_ID)
    start = parse_passive_income_history_start_month(
        settings.passive_income_history_start_month if settings is not None else None
    )
    points = tuple(
        TotalIncomePoint(
            reporting_month_id=m.id,
            year=m.year,
            month=m.month,
            salary_net=RubleAmount(totals.get((m.id, IncomeType.SALARY.value), 0)),
            bonus_net=RubleAmount(totals.get((m.id, IncomeType.BONUS.value), 0)),
            passive_actual=passive[m.id].total_net_passive_income,
            other_net=RubleAmount(
                sum(
                    totals.get((m.id, kind.value), 0)
                    for kind in (IncomeType.SIDE_INCOME, IncomeType.CASHBACK, IncomeType.OTHER)
                )
            ),
        )
        for m in months
    )
    return TotalIncomeReadModel(
        latest_closed_report_id=latest_id,
        result=calculate_total_income(points, history_start_month=start),
    )
