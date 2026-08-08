"""ORM application service for the normalized bonus (C08).

Loads BONUS income entries from closed reporting months, aggregates them per
month, and delegates to the pure normalized-bonus calculator.  The result is
analytical only — it is never mixed into the actual cash flow (MASTER_SPEC
§10.15).

Implements:

    normalized_bonus_monthly = sum(bonuses for selected 12m period) / 12

Key facts:
- Only CLOSED reporting months participate (the available actual history),
  ordered by year/month — same window contract as C03/C04.
- Per month the bonus figure is the sum of ``net_amount_kopecks`` of BONUS
  income entries (actual payment), consistent with the cash-balance service.
- Reads on closed months are allowed (B19-R2 guard is for writes only).
"""

from __future__ import annotations

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.incomes import IncomeType
from hermes_finance.domain.normalized_bonus import (
    NormalizedBonusResult,
    calculate_normalized_bonus,
)
from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import IncomeEntry, ReportingMonth


def normalized_bonus(session: Session) -> NormalizedBonusResult:
    """Calculate the normalized monthly bonus over the available window."""
    rows = session.execute(
        select(
            ReportingMonth.year,
            ReportingMonth.month,
            func.coalesce(func.sum(IncomeEntry.net_amount_kopecks), 0),
        )
        .join(
            IncomeEntry,
            and_(
                IncomeEntry.reporting_month_id == ReportingMonth.id,
                IncomeEntry.income_type == IncomeType.BONUS.value,
            ),
            isouter=True,
        )
        .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
        .group_by(ReportingMonth.year, ReportingMonth.month)
        .order_by(ReportingMonth.year, ReportingMonth.month)
    ).all()

    months = tuple(
        MonthlyPassiveIncome(year=year, month=month, amount=RubleAmount(int(total or 0)))
        for year, month, total in rows
    )

    return calculate_normalized_bonus(months)
