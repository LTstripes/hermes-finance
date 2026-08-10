"""Unit tests for the pure cash-balance calculator (C06, no database)."""

from hermes_finance.domain import RubleAmount
from hermes_finance.domain.cash_balance import (
    CashBalanceBreakdown,
    CashBalanceInput,
    calculate_cash_balance,
)


def run(**amounts: int):
    return calculate_cash_balance(
        CashBalanceInput(
            salary_net=RubleAmount(amounts.get("salary_net", 0)),
            bonus_net=RubleAmount(amounts.get("bonus_net", 0)),
            side_income_net=RubleAmount(amounts.get("side_income_net", 0)),
            cashback=RubleAmount(amounts.get("cashback", 0)),
            other_income=RubleAmount(amounts.get("other_income", 0)),
            passive_income=RubleAmount(amounts.get("passive_income", 0)),
            mandatory_expenses=RubleAmount(amounts.get("mandatory_expenses", 0)),
            other_expenses=RubleAmount(amounts.get("other_expenses", 0)),
            saving_allocations=RubleAmount(amounts.get("saving_allocations", 0)),
        )
    )


# --- zero input ---


def test_zero_input_returns_zero_total_and_zero_breakdown() -> None:
    result = run()
    assert result.total == RubleAmount(0)
    assert result.breakdown == CashBalanceBreakdown(
        salary_net=RubleAmount(0),
        bonus_net=RubleAmount(0),
        side_income_net=RubleAmount(0),
        cashback=RubleAmount(0),
        other_income=RubleAmount(0),
        passive_income=RubleAmount(0),
        mandatory_expenses=RubleAmount(0),
        other_expenses=RubleAmount(0),
        saving_allocations=RubleAmount(0),
    )


# --- full calculation ---


def test_full_calculation_matches_master_spec() -> None:
    result = run(
        salary_net=1_000_000,
        bonus_net=200_000,
        side_income_net=50_000,
        cashback=10_000,
        passive_income=30_000,
        mandatory_expenses=400_000,
        other_expenses=50_000,
        saving_allocations=200_000,
    )
    # 10000.00 + 2000.00 + 500.00 + 100.00 + 300.00 - 4000.00 - 500.00 - 2000.00 = 6400.00
    assert result.total == RubleAmount(640_000)
    assert result.breakdown.salary_net == RubleAmount(1_000_000)
    assert result.breakdown.bonus_net == RubleAmount(200_000)
    assert result.breakdown.side_income_net == RubleAmount(50_000)
    assert result.breakdown.cashback == RubleAmount(10_000)
    assert result.breakdown.passive_income == RubleAmount(30_000)
    assert result.breakdown.mandatory_expenses == RubleAmount(400_000)
    assert result.breakdown.other_expenses == RubleAmount(50_000)
    assert result.breakdown.saving_allocations == RubleAmount(200_000)


# --- negative total ---


def test_negative_total_when_expenses_exceed_income() -> None:
    result = run(salary_net=100_000, mandatory_expenses=400_000)
    # 1000.00 - 4000.00 = -3000.00
    assert result.total == RubleAmount(-300_000)


# --- cashback and passive income are separate lines ---


def test_cashback_and_passive_income_are_separate_and_both_add() -> None:
    result = run(cashback=10_000, passive_income=30_000)
    assert result.breakdown.cashback == RubleAmount(10_000)
    assert result.breakdown.passive_income == RubleAmount(30_000)
    assert result.total == RubleAmount(40_000)


# --- only subtraction components ---


def test_only_subtraction_components_give_negative_total() -> None:
    result = run(mandatory_expenses=400_000, other_expenses=50_000, saving_allocations=200_000)
    # no income: -4000.00 - 500.00 - 2000.00 = -6500.00
    assert result.total == RubleAmount(-650_000)


# --- breakdown mirrors input exactly ---


def test_breakdown_mirrors_input_exactly() -> None:
    result = run(
        salary_net=111_111,
        bonus_net=222_222,
        side_income_net=333_333,
        cashback=444_444,
        other_income=555_555,
        passive_income=555_555,
        mandatory_expenses=666_666,
        other_expenses=777_777,
        saving_allocations=888_888,
    )
    assert result.breakdown == CashBalanceBreakdown(
        salary_net=RubleAmount(111_111),
        bonus_net=RubleAmount(222_222),
        side_income_net=RubleAmount(333_333),
        cashback=RubleAmount(444_444),
        other_income=RubleAmount(555_555),
        passive_income=RubleAmount(555_555),
        mandatory_expenses=RubleAmount(666_666),
        other_expenses=RubleAmount(777_777),
        saving_allocations=RubleAmount(888_888),
    )
