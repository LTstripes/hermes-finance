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
      + actual_net_passive_income
      - mandatory_expenses
      - other_recorded_expenses
      - saving_allocations

Key invariants (wiki §7):
- Cashback participates in the cash flow but is never passive income.
- Only ACTUAL recorded bonus entries count (normalized bonus of C08
  is a separate analytical metric and must not appear here).
- Saving allocations reduce the monthly balance.
- All income entries participate in the cash flow regardless of
  ``include_in_passive_income``; the passive flag only matters for
  the passive-income classification.
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
        )
    )
    return RubleAmount(int(total or 0))


def cash_balance_for_month(session: Session, reporting_month_id: int) -> CashBalanceResult:
    """Assemble cash-balance input from the database and calculate."""
    salary_net = _sum_income_by_type(session, reporting_month_id, IncomeType.SALARY)
    bonus_net = _sum_income_by_type(session, reporting_month_id, IncomeType.BONUS)
    side_income_net = _sum_income_by_type(session, reporting_month_id, IncomeType.SIDE_INCOME)
    cashback = _sum_income_by_type(session, reporting_month_id, IncomeType.CASHBACK)

    passive_income = passive_income_for_month(session, reporting_month_id).total_net_passive_income

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
            passive_income=passive_income,
            mandatory_expenses=mandatory_expenses,
            other_expenses=other_expenses,
            saving_allocations=saving_allocations,
        )
    )
