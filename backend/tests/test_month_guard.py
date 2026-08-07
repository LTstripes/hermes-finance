"""B19-R2 regression: closed-month immutability for all month-scoped child entities.

Every month-scoped child table (income_entries, expense_entries,
saving_allocations, debts, property_snapshots, deposit_snapshots,
position_snapshots, cash_balances, investment_cash_flows,
expected_cash_flows, monthly_comments) must refuse create/update/delete
while the parent reporting month is CLOSED (PROJECT_WIKI section 7, item 7).

Global entities (accounts, instruments, goals, app_settings, iis profiles)
are not month-scoped and must remain editable regardless of month status.
"""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DebtType,
    DepositType,
    ExpectedCashFlowType,
    ExpenseType,
    GoalType,
    IncomeType,
    InstrumentType,
    InvestmentCashFlowType,
    PriceSource,
    RubleAmount,
)
from hermes_finance.persistence import (
    Base,
    CashBalance,
    Debt,
    DepositSnapshot,
    ExpectedCashFlow,
    ExpenseEntry,
    IncomeEntry,
    InvestmentCashFlow,
    MonthlyComment,
    PositionSnapshot,
    PropertySnapshot,
    SavingAllocation,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import (
    create_cash_balance,
    delete_cash_balance,
    update_cash_balance,
)
from hermes_finance.services.comments import (
    create_monthly_comment,
    delete_monthly_comment,
    list_monthly_comments,
    move_monthly_comment,
    update_monthly_comment,
)
from hermes_finance.services.debts import create_debt, delete_debt, update_debt
from hermes_finance.services.deposits import (
    create_deposit_snapshot,
    delete_deposit_snapshot,
    update_deposit_snapshot,
)
from hermes_finance.services.expected_cash_flows import (
    create_expected_cash_flow,
    delete_expected_cash_flow,
    update_expected_cash_flow,
)
from hermes_finance.services.expenses import (
    create_expense_entry,
    create_saving_allocation,
    delete_expense_entry,
    delete_saving_allocation,
    update_expense_entry,
    update_saving_allocation,
)
from hermes_finance.services.goals import create_goal
from hermes_finance.services.iis import create_iis_profile
from hermes_finance.services.incomes import (
    create_income_entry,
    delete_income_entry,
    update_income_entry,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import (
    create_investment_cash_flow,
    delete_investment_cash_flow,
    update_investment_cash_flow,
)
from hermes_finance.services.positions import (
    create_position_snapshot,
    delete_position_snapshot,
    update_position_snapshot,
)
from hermes_finance.services.properties import (
    create_property_snapshot,
    delete_property_snapshot,
    update_property_snapshot,
)
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)
from hermes_finance.services.settings import update_settings


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "month-guard.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _create_account(session: Session, name: str, account_type: AccountType) -> object:
    return create_account(session, name=name, account_type=account_type)


def _create_instrument(session: Session) -> object:
    return create_instrument(session, name="Synthetic Bond", instrument_type=InstrumentType.BOND)


MONTH_SCOPED_CASES = [
    {
        "id": "income_entries",
        "model": IncomeEntry,
        "create": lambda session, month_id: create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="100000.00",
            tax_amount="13000.00",
            net_amount="87000.00",
        ),
        "update": lambda session, row: update_income_entry(session, row.id, name="Updated"),
        "delete": lambda session, row: delete_income_entry(session, row.id),
    },
    {
        "id": "expense_entries",
        "model": ExpenseEntry,
        "create": lambda session, month_id: create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Synthetic Food",
            amount="5000.00",
            expense_type=ExpenseType.MANDATORY,
        ),
        "update": lambda session, row: update_expense_entry(session, row.id, amount="6000.00"),
        "delete": lambda session, row: delete_expense_entry(session, row.id),
    },
    {
        "id": "saving_allocations",
        "model": SavingAllocation,
        "create": lambda session, month_id: create_saving_allocation(
            session,
            reporting_month_id=month_id,
            destination="Synthetic Emergency",
            amount="10000.00",
        ),
        "update": lambda session, row: update_saving_allocation(session, row.id, amount="11000.00"),
        "delete": lambda session, row: delete_saving_allocation(session, row.id),
    },
    {
        "id": "debts",
        "model": Debt,
        "create": lambda session, month_id: create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="50000.00",
        ),
        "update": lambda session, row: update_debt(session, row.id, current_balance="45000.00"),
        "delete": lambda session, row: delete_debt(session, row.id),
    },
    {
        "id": "property_snapshots",
        "model": PropertySnapshot,
        "create": lambda session, month_id: create_property_snapshot(
            session,
            reporting_month_id=month_id,
            name="Synthetic Flat",
            estimated_value="8000000.00",
            mortgage_balance="3000000.00",
            monthly_payment="50000.00",
        ),
        "update": lambda session, row: update_property_snapshot(session, row.id, name="Updated"),
        "delete": lambda session, row: delete_property_snapshot(session, row.id),
    },
    {
        "id": "deposit_snapshots",
        "model": DepositSnapshot,
        "create": lambda session, month_id: create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=_create_account(
                session, "Synthetic Deposit Account", AccountType.DEPOSIT
            ).id,
            name="Synthetic Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="1000000.00",
            annual_rate="13.50",
        ),
        "update": lambda session, row: update_deposit_snapshot(
            session, row.id, balance="1100000.00"
        ),
        "delete": lambda session, row: delete_deposit_snapshot(session, row.id),
    },
    {
        "id": "position_snapshots",
        "model": PositionSnapshot,
        "create": lambda session, month_id: create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=_create_account(session, "Synthetic Brokerage", AccountType.BROKERAGE).id,
            instrument_id=_create_instrument(session).id,
            quantity=10,
            average_cost_per_unit="1000.00",
            market_price_per_unit="1100.00",
            price_date=date(2030, 5, 12),
            price_source=PriceSource.MANUAL,
        ),
        "update": lambda session, row: update_position_snapshot(session, row.id, quantity=11),
        "delete": lambda session, row: delete_position_snapshot(session, row.id),
    },
    {
        "id": "cash_balances",
        "model": CashBalance,
        "create": lambda session, month_id: create_cash_balance(
            session,
            reporting_month_id=month_id,
            name="Synthetic Cash",
            amount="150000.00",
        ),
        "update": lambda session, row: update_cash_balance(session, row.id, amount="160000.00"),
        "delete": lambda session, row: delete_cash_balance(session, row.id),
    },
    {
        "id": "investment_cash_flows",
        "model": InvestmentCashFlow,
        "create": lambda session, month_id: create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=_create_account(session, "Synthetic Brokerage", AccountType.BROKERAGE).id,
            flow_type=InvestmentCashFlowType.DIVIDEND,
            event_date=date(2030, 5, 15),
            gross_amount="1000.00",
            tax_amount="130.00",
            commission_amount="0.00",
            net_amount="870.00",
            source="Synthetic",
        ),
        "update": lambda session, row: update_investment_cash_flow(
            session, row.id, notes="Updated"
        ),
        "delete": lambda session, row: delete_investment_cash_flow(session, row.id),
    },
    {
        "id": "expected_cash_flows",
        "model": ExpectedCashFlow,
        "create": lambda session, month_id: create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=_create_account(session, "Synthetic Brokerage", AccountType.BROKERAGE).id,
            instrument_id=_create_instrument(session).id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2030, 6, 1),
            gross_amount="1000.00",
            expected_tax_amount="130.00",
            expected_net_amount="870.00",
            source="Synthetic",
            source_as_of_date=date(2030, 5, 12),
            forecast_version="v1",
        ),
        "update": lambda session, row: update_expected_cash_flow(
            session, row.id, is_confirmed=True
        ),
        "delete": lambda session, row: delete_expected_cash_flow(session, row.id),
    },
    {
        "id": "monthly_comments",
        "model": MonthlyComment,
        "create": lambda session, month_id: create_monthly_comment(
            session,
            reporting_month_id=month_id,
            text="Synthetic note",
        ),
        "update": lambda session, row: update_monthly_comment(session, row.id, text="Updated note"),
        "delete": lambda session, row: delete_monthly_comment(session, row.id),
    },
]


@pytest.mark.parametrize(
    "case", MONTH_SCOPED_CASES, ids=[case["id"] for case in MONTH_SCOPED_CASES]
)
def test_closed_month_blocks_child_create_update_delete(tmp_path: Path, case: dict) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
        child = case["create"](session, month.id)
        close_reporting_month(session, month.id)

        with pytest.raises(ClosedReportingMonthError):
            case["create"](session, month.id)
        with pytest.raises(ClosedReportingMonthError):
            case["update"](session, child)
        with pytest.raises(ClosedReportingMonthError):
            case["delete"](session, child)

        assert session.get(case["model"], child.id) is not None
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_blocks_comment_reorder(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
        first = create_monthly_comment(session, reporting_month_id=month.id, text="First")
        create_monthly_comment(session, reporting_month_id=month.id, text="Second")
        close_reporting_month(session, month.id)

        with pytest.raises(ClosedReportingMonthError):
            move_monthly_comment(session, first.id, new_position=2)

        assert [comment.position for comment in list_monthly_comments(session, month.id)] == [1, 2]
    finally:
        session.close()
        database.engine.dispose()


def test_draft_month_child_crud_still_works(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
        entry = create_income_entry(
            session,
            reporting_month_id=month.id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="100000.00",
            tax_amount="13000.00",
            net_amount="87000.00",
        )
        updated = update_income_entry(session, entry.id, name="Updated")
        assert updated.name == "Updated"

        first = create_monthly_comment(session, reporting_month_id=month.id, text="First")
        create_monthly_comment(session, reporting_month_id=month.id, text="Second")
        moved = move_monthly_comment(session, first.id, new_position=2)
        assert moved.position == 2

        delete_income_entry(session, entry.id)
        assert session.get(IncomeEntry, entry.id) is None
    finally:
        session.close()
        database.engine.dispose()


def test_reopen_allows_child_edits_again(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
        entry = create_income_entry(
            session,
            reporting_month_id=month.id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="100000.00",
            tax_amount="13000.00",
            net_amount="87000.00",
        )
        close_reporting_month(session, month.id)
        with pytest.raises(ClosedReportingMonthError):
            update_income_entry(session, entry.id, name="Blocked")

        reopen_reporting_month(session, month.id)
        updated = update_income_entry(session, entry.id, name="Allowed")
        assert updated.name == "Allowed"
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_does_not_block_global_entities(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
        close_reporting_month(session, month.id)

        account = create_account(
            session, name="Synthetic Account", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        goal = create_goal(
            session,
            name="Synthetic Goal",
            goal_type=GoalType.CAPITAL,
            target_value="100000.00",
            calculation_mode="capital_total",
        )
        iis_profile = create_iis_profile(
            session, account_id=account.id, iis_type="type-a", opened_at=date(2030, 1, 1)
        )
        update_settings(session, passive_income_goal=RubleAmount.from_api("150000.00"))

        assert account.id is not None
        assert instrument.id is not None
        assert goal.id is not None
        assert iis_profile.id is not None
    finally:
        session.close()
        database.engine.dispose()
