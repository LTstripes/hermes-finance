"""ORM application service for the monthly cash balance (C06).

Loads persisted rows for a reporting month, maps them into the pure
domain calculator input, and returns the domain result DTO.  No API,
no Pydantic, no React.

Implements MASTER_SPEC §10.9:

    monthly_cash_balance =
        actual_net_salary
      + actual_net_bonus
      + side_income_net
      + cashback
      + other_income
      + actual_net_passive_income
      - mandatory_expenses
      - other_recorded_expenses
      - saving_allocations

Key invariants (wiki §7):
- Cashback participates in the cash flow but is never passive income.
- Only ACTUAL recorded bonus entries count (normalized bonus of C08
  is a separate analytical metric and must not appear here).
- Saving allocations reduce the monthly balance.
- Income entries participate only when ``include_in_cash_flow`` is true.
- Non-passive ``OTHER`` income has its own ``other_income`` bucket.
- Passive ``OTHER`` rows with ``include_in_cash_flow=False`` remain in
  actual passive-income analytics but are excluded from this balance.
- Reads are allowed on closed months (B19-R2 guard is for writes only).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.cash_balance import (
    CashBalanceInput,
    CashBalanceResult,
    calculate_cash_balance,
)
from hermes_finance.domain.incomes import IncomeType
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import IncomeEntry
from hermes_finance.services.expenses import (
    total_expenses,
    total_mandatory_expenses,
    total_saving_allocations,
)
from hermes_finance.services.passive_income import passive_income_for_month


def _sum_income_by_type(
    session: Session, reporting_month_id: int, income_type: IncomeType
) -> RubleAmount:
    """Sum ``net_amount_kopecks`` for a single income type in a month."""
    total = session.scalar(
        select(func.coalesce(func.sum(IncomeEntry.net_amount_kopecks), 0)).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == income_type.value,
            IncomeEntry.include_in_cash_flow.is_(True),
        )
    )
    return RubleAmount(int(total or 0))


def _sum_other_income(session: Session, reporting_month_id: int) -> RubleAmount:
    """Sum cash-flow-enabled, non-passive ``OTHER`` income entries."""
    total = session.scalar(
        select(func.coalesce(func.sum(IncomeEntry.net_amount_kopecks), 0)).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == IncomeType.OTHER.value,
            IncomeEntry.include_in_cash_flow.is_(True),
            IncomeEntry.include_in_passive_income.is_(False),
        )
    )
    return RubleAmount(int(total or 0))


def _sum_passive_other_excluded_from_cash_flow(
    session: Session, reporting_month_id: int
) -> RubleAmount:
    """Sum passive ``OTHER`` rows kept for analytics but excluded from cash flow."""
    total = session.scalar(
        select(func.coalesce(func.sum(IncomeEntry.net_amount_kopecks), 0)).where(
            IncomeEntry.reporting_month_id == reporting_month_id,
            IncomeEntry.income_type == IncomeType.OTHER.value,
            IncomeEntry.include_in_cash_flow.is_(False),
            IncomeEntry.include_in_passive_income.is_(True),
        )
    )
    return RubleAmount(int(total or 0))


def cash_balance_for_month(session: Session, reporting_month_id: int) -> CashBalanceResult:
    """Assemble cash-balance input from the database and calculate."""
    salary_net = _sum_income_by_type(session, reporting_month_id, IncomeType.SALARY)
    bonus_net = _sum_income_by_type(session, reporting_month_id, IncomeType.BONUS)
    side_income_net = _sum_income_by_type(session, reporting_month_id, IncomeType.SIDE_INCOME)
    cashback = _sum_income_by_type(session, reporting_month_id, IncomeType.CASHBACK)
    other_income = _sum_other_income(session, reporting_month_id)

    passive_income_actual = passive_income_for_month(
        session, reporting_month_id
    ).total_net_passive_income
    passive_income_excluded = _sum_passive_other_excluded_from_cash_flow(
        session, reporting_month_id
    )
    passive_income = RubleAmount(passive_income_actual.kopecks - passive_income_excluded.kopecks)

    mandatory_expenses = total_mandatory_expenses(session, reporting_month_id)
    all_expenses = total_expenses(session, reporting_month_id)
    other_expenses = RubleAmount(all_expenses.kopecks - mandatory_expenses.kopecks)
    saving_allocations = total_saving_allocations(session, reporting_month_id)

    return calculate_cash_balance(
        CashBalanceInput(
            salary_net=salary_net,
            bonus_net=bonus_net,
            side_income_net=side_income_net,
            cashback=cashback,
            other_income=other_income,
            passive_income=passive_income,
            mandatory_expenses=mandatory_expenses,
            other_expenses=other_expenses,
            saving_allocations=saving_allocations,
        )
    )
