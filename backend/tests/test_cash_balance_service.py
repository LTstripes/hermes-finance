"""Integration tests for the ORM cash-balance service (C06)."""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DepositType,
    ExpenseType,
    IncomeType,
    RubleAmount,
)
from hermes_finance.domain.cash_balance import CashBalanceBreakdown, CashBalanceResult
from hermes_finance.persistence import Base, IncomeEntry
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash_balance import cash_balance_for_month
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expenses import (
    create_expense_entry,
    create_saving_allocation,
)
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "cash_balance.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session) -> int:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    return month.id


# --- full month scenario ---


def test_full_month_scenario(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="100000.00",
            tax_amount="0.00",
            net_amount="100000.00",
        )
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.BONUS,
            name="Synthetic Bonus",
            gross_amount="20000.00",
            tax_amount="0.00",
            net_amount="20000.00",
        )
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SIDE_INCOME,
            name="Synthetic Side Gig",
            gross_amount="5000.00",
            tax_amount="0.00",
            net_amount="5000.00",
        )
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.CASHBACK,
            name="Synthetic Cashback",
            gross_amount="1000.00",
            tax_amount="0.00",
            net_amount="1000.00",
            include_in_passive_income=False,
        )
        deposit_account = create_account(
            session, name="Synthetic Deposit Account", account_type=AccountType.DEPOSIT
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit_account.id,
            name="Depo 1",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="3000.00",
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Rent",
            amount="40000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Fun",
            amount="5000.00",
            expense_type=ExpenseType.COMFORTABLE,
        )
        create_saving_allocation(
            session,
            reporting_month_id=month_id,
            destination="Synthetic Emergency Fund",
            amount="20000.00",
        )

        result = cash_balance_for_month(session, month_id)
        assert isinstance(result, CashBalanceResult)
        # 100000.00 + 20000.00 + 5000.00 + 1000.00 + 3000.00
        # - 40000.00 - 5000.00 - 20000.00 = 64000.00 RUB = 6_400_000 kopecks
        assert result.total == RubleAmount(6_400_000)
        assert result.breakdown.salary_net == RubleAmount(10_000_000)
        assert result.breakdown.bonus_net == RubleAmount(2_000_000)
        assert result.breakdown.side_income_net == RubleAmount(500_000)
        assert result.breakdown.cashback == RubleAmount(100_000)
        assert result.breakdown.passive_income == RubleAmount(300_000)
        assert result.breakdown.mandatory_expenses == RubleAmount(4_000_000)
        assert result.breakdown.other_expenses == RubleAmount(500_000)
        assert result.breakdown.saving_allocations == RubleAmount(2_000_000)
    finally:
        session.close()
        database.engine.dispose()


# --- cashback is never passive income ---


def test_cashback_not_counted_as_passive_income(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.CASHBACK,
            name="Synthetic Cashback",
            gross_amount="1000.00",
            tax_amount="0.00",
            net_amount="1000.00",
            include_in_passive_income=False,
        )
        result = cash_balance_for_month(session, month_id)
        assert result.breakdown.passive_income == RubleAmount(0)
        assert result.breakdown.cashback == RubleAmount(100_000)
        assert result.total == RubleAmount(100_000)
    finally:
        session.close()
        database.engine.dispose()


# --- income with include_in_passive_income=False still counts in the balance ---


def test_income_excluded_from_passive_still_counts_in_balance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="10000.00",
            tax_amount="0.00",
            net_amount="10000.00",
            include_in_passive_income=False,
        )
        result = cash_balance_for_month(session, month_id)
        assert result.breakdown.salary_net == RubleAmount(1_000_000)
        assert result.breakdown.passive_income == RubleAmount(0)
        assert result.total == RubleAmount(1_000_000)
    finally:
        session.close()
        database.engine.dispose()


def test_legacy_invalid_passive_income_flags_count_cash_once(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        legacy_rows = (
            (IncomeType.SALARY, 100_000),
            (IncomeType.BONUS, 200_000),
            (IncomeType.SIDE_INCOME, 300_000),
        )
        for income_type, net_amount_kopecks in legacy_rows:
            session.add(
                IncomeEntry(
                    reporting_month_id=month_id,
                    income_type=income_type.value,
                    name=f"Legacy {income_type.value}",
                    gross_amount_kopecks=net_amount_kopecks,
                    tax_amount_kopecks=0,
                    net_amount_kopecks=net_amount_kopecks,
                    include_in_cash_flow=True,
                    include_in_passive_income=True,
                )
            )
        session.commit()

        result = cash_balance_for_month(session, month_id)

        assert result.breakdown.salary_net == RubleAmount(100_000)
        assert result.breakdown.bonus_net == RubleAmount(200_000)
        assert result.breakdown.side_income_net == RubleAmount(300_000)
        assert result.breakdown.passive_income == RubleAmount(0)
        assert result.total == RubleAmount(600_000)
    finally:
        session.close()
        database.engine.dispose()


# --- negative balance ---


def test_negative_balance_when_expenses_exceed_income(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="10000.00",
            tax_amount="0.00",
            net_amount="10000.00",
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Rent",
            amount="40000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        result = cash_balance_for_month(session, month_id)
        # 10000.00 - 40000.00 = -30000.00 RUB = -3_000_000 kopecks
        assert result.total == RubleAmount(-3_000_000)
    finally:
        session.close()
        database.engine.dispose()


# --- zero month ---


def test_zero_month_returns_all_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        result = cash_balance_for_month(session, month_id)
        assert result.total == RubleAmount(0)
        assert result.breakdown == CashBalanceBreakdown(
            salary_net=RubleAmount(0),
            bonus_net=RubleAmount(0),
            side_income_net=RubleAmount(0),
            cashback=RubleAmount(0),
            passive_income=RubleAmount(0),
            mandatory_expenses=RubleAmount(0),
            other_expenses=RubleAmount(0),
            saving_allocations=RubleAmount(0),
        )
    finally:
        session.close()
        database.engine.dispose()


# --- other expenses: comfortable + other, mandatory stays separate ---


def test_other_expenses_sum_comfortable_and_other_types(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Rent",
            amount="3000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Fun",
            amount="5000.00",
            expense_type=ExpenseType.COMFORTABLE,
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Misc",
            amount="2000.00",
            expense_type=ExpenseType.OTHER,
        )
        result = cash_balance_for_month(session, month_id)
        # mandatory stays separate: 3000.00
        assert result.breakdown.mandatory_expenses == RubleAmount(300_000)
        # comfortable + other: 5000.00 + 2000.00 = 7000.00
        assert result.breakdown.other_expenses == RubleAmount(700_000)
        assert result.total == RubleAmount(-1_000_000)
    finally:
        session.close()
        database.engine.dispose()
