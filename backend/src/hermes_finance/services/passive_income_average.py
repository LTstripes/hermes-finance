"""ORM application service for passive-income average (C03).

Loads closed reporting months, assembles actual net passive income per month
via the existing C02 service, maps results into the pure domain calculator
input, and returns the domain result DTO.  No API, no Pydantic, no React.

Implements MASTER_SPEC §10.5:

    Before 12 months accumulate:

        actual_passive_income_avg =
            sum(actual_net_passive_income for available months)
            / count(available months)

    After 12 months: rolling window of the last 12 reporting months.

Key invariants (wiki §7):
- Money is integer kopecks via :class:`RubleAmount`; no binary float.
- Closed months only; draft months are excluded.
- At most the last 12 months are used.
- Reads on closed months are allowed (B19-R2 guard is for writes only).
- No division by absent months.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.passive_income import PassiveIncomeResult
from hermes_finance.domain.passive_income_average import (
    MonthlyPassiveIncome,
    PassiveIncomeAverageInput,
    PassiveIncomeAverageResult,
    calculate_passive_income_average,
)
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.persistence import APP_SETTINGS_ID, AppSettings, ReportingMonth
from hermes_finance.services.passive_income import passive_income_for_months
from hermes_finance.services.settings import parse_passive_income_history_start_month


def passive_income_average_from_results(
    session: Session,
    month_rows: Sequence[tuple[int, int, int]],
    result_by_month: Mapping[int, PassiveIncomeResult],
) -> PassiveIncomeAverageResult:
    """Calculate the canonical average from one already-batched history read.

    ``month_rows`` contains ``(reporting_month_id, year, month)`` for CLOSED
    reports in calendar order.  Keeping this small adapter beside the public
    average service lets read models reuse the same eligibility setting and
    pure rolling-window calculator without issuing a second batch query.
    """
    month_items = [
        MonthlyPassiveIncome(
            year=year,
            month=month,
            amount=result_by_month[month_id].total_net_passive_income,
        )
        for month_id, year, month in month_rows
    ]

    # This is a read-model service. Missing optional settings use the same
    # default as the seeded row without creating or committing that row.
    settings = session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))
    return calculate_passive_income_average(
        PassiveIncomeAverageInput(
            months=tuple(month_items),
            history_start_month=parse_passive_income_history_start_month(
                settings.passive_income_history_start_month if settings is not None else None
            ),
        )
    )


def passive_income_average(session: Session) -> PassiveIncomeAverageResult:
    """Calculate the rolling 12-month average of actual net passive income.

    Queries all closed reporting months ordered by year/month ascending,
    calls the C02 per-month calculator for each, and delegates to the pure
    domain calculator which keeps at most the last 12 months.
    """
    rows = session.execute(
        select(ReportingMonth.id, ReportingMonth.year, ReportingMonth.month)
        .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
        .order_by(ReportingMonth.year, ReportingMonth.month)
    ).all()

    result_by_month = passive_income_for_months(session, [month_id for month_id, _, _ in rows])
    return passive_income_average_from_results(
        session,
        rows,
        result_by_month,
    )
