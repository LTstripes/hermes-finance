"""Pure domain cash-balance calculator (framework-independent).

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

Cashback participates in the cash flow but is never classified as passive
income (wiki §7 invariant).  Only actual recorded entries count — normalized
bonus (C08) is a separate analytical metric and must not appear here.

All money values use :class:`~hermes_finance.domain.values.RubleAmount`
(integer kopecks); binary ``float`` is never used.  The calculator performs
pure addition/subtraction of integer kopecks — no division, no rounding.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermes_finance.domain.values import RubleAmount


@dataclass(frozen=True, slots=True)
class CashBalanceInput:
    """Pure-domain input for the cash-balance calculator.

    All amounts are integer kopecks via :class:`RubleAmount`.
    The ORM assembler is responsible for sourcing each field from the
    correct persisted rows; the calculator simply sums what it is given.
    """

    salary_net: RubleAmount
    bonus_net: RubleAmount
    side_income_net: RubleAmount
    cashback: RubleAmount
    passive_income: RubleAmount
    mandatory_expenses: RubleAmount
    other_expenses: RubleAmount
    saving_allocations: RubleAmount


@dataclass(frozen=True, slots=True)
class CashBalanceBreakdown:
    """Transparent breakdown of the monthly cash balance.

    Mirrors :class:`CashBalanceInput` so the caller can inspect each
    component that fed into the total.
    """

    salary_net: RubleAmount
    bonus_net: RubleAmount
    side_income_net: RubleAmount
    cashback: RubleAmount
    passive_income: RubleAmount
    mandatory_expenses: RubleAmount
    other_expenses: RubleAmount
    saving_allocations: RubleAmount


@dataclass(frozen=True, slots=True)
class CashBalanceResult:
    """Pure-domain output of the cash-balance calculator."""

    total: RubleAmount
    breakdown: CashBalanceBreakdown


def calculate_cash_balance(input_data: CashBalanceInput) -> CashBalanceResult:
    """Calculate the monthly cash balance from pure-domain input.

    Pure addition/subtraction of integer kopecks — no division, no float,
    no rounding.  Zero input produces total ``RubleAmount(0)``.
    The result may be negative.
    """
    breakdown = CashBalanceBreakdown(
        salary_net=input_data.salary_net,
        bonus_net=input_data.bonus_net,
        side_income_net=input_data.side_income_net,
        cashback=input_data.cashback,
        passive_income=input_data.passive_income,
        mandatory_expenses=input_data.mandatory_expenses,
        other_expenses=input_data.other_expenses,
        saving_allocations=input_data.saving_allocations,
    )

    total = RubleAmount(
        input_data.salary_net.kopecks
        + input_data.bonus_net.kopecks
        + input_data.side_income_net.kopecks
        + input_data.cashback.kopecks
        + input_data.passive_income.kopecks
        - input_data.mandatory_expenses.kopecks
        - input_data.other_expenses.kopecks
        - input_data.saving_allocations.kopecks
    )

    return CashBalanceResult(total=total, breakdown=breakdown)
