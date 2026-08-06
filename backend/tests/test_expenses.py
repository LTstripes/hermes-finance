from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import ExpenseType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.expenses import (
    ExpenseEntryNotFoundError,
    SavingAllocationNotFoundError,
    create_expense_entry,
    create_saving_allocation,
    delete_expense_entry,
    delete_saving_allocation,
    get_expense_entry,
    get_saving_allocation,
    list_expense_entries,
    list_saving_allocations,
    total_expenses,
    total_mandatory_expenses,
    total_saving_allocations,
    update_expense_entry,
    update_saving_allocation,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "expenses.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    first = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    second = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 12))
    return first.id, second.id


def test_saving_allocations_do_not_count_as_mandatory_expenses(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_expense_entry(
            session,
            reporting_month_id=first_id,
            category="Rent",
            amount="50000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        create_expense_entry(
            session,
            reporting_month_id=first_id,
            category="Restaurant",
            amount="3000.00",
            expense_type=ExpenseType.COMFORTABLE,
        )
        create_saving_allocation(
            session, reporting_month_id=first_id, destination="Brokerage", amount="10000.00"
        )
        assert total_mandatory_expenses(session, first_id) == RubleAmount(5_000_000)
        assert total_expenses(session, first_id) == RubleAmount(5_300_000)
        assert total_saving_allocations(session, first_id) == RubleAmount(1_000_000)
    finally:
        session.close()
        database.engine.dispose()


def test_expense_totals_are_scoped_to_month_and_type(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, second_id = build_environment(session)
        create_expense_entry(
            session,
            reporting_month_id=first_id,
            category="Rent",
            amount="50000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        create_expense_entry(
            session,
            reporting_month_id=second_id,
            category="Rent",
            amount="60000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        assert total_mandatory_expenses(session, first_id) == RubleAmount(5_000_000)
        assert total_mandatory_expenses(session, second_id) == RubleAmount(6_000_000)
        assert total_expenses(session, first_id, expense_type=ExpenseType.OTHER) == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_expense_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        entry = create_expense_entry(
            session,
            reporting_month_id=first_id,
            category="  Groceries  ",
            amount="8000.00",
            expense_type=ExpenseType.MANDATORY,
            is_recurring=True,
            notes="synthetic note",
        )
        assert entry.category == "Groceries"
        updated = update_expense_entry(
            session, entry.id, amount="8500.00", expense_type=ExpenseType.OTHER
        )
        assert updated.amount_kopecks == 850_000
        assert updated.expense_type == ExpenseType.OTHER.value
        assert len(list_expense_entries(session)) == 1
        delete_expense_entry(session, entry.id)
        with pytest.raises(ExpenseEntryNotFoundError):
            get_expense_entry(session, entry.id)
    finally:
        session.close()
        database.engine.dispose()


def test_saving_allocation_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        allocation = create_saving_allocation(
            session,
            reporting_month_id=first_id,
            destination="  Brokerage  ",
            amount="10000.00",
            notes="synthetic note",
        )
        assert allocation.destination == "Brokerage"
        updated = update_saving_allocation(session, allocation.id, amount="15000.00")
        assert updated.amount_kopecks == 1_500_000
        assert len(list_saving_allocations(session)) == 1
        delete_saving_allocation(session, allocation.id)
        with pytest.raises(SavingAllocationNotFoundError):
            get_saving_allocation(session, allocation.id)
    finally:
        session.close()
        database.engine.dispose()


def test_expense_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_expense_entry(
                session,
                reporting_month_id=first_id,
                category="  ",
                amount="1.00",
                expense_type=ExpenseType.MANDATORY,
            )
        with pytest.raises(ValueError, match="unsupported expense type"):
            create_expense_entry(
                session,
                reporting_month_id=first_id,
                category="Rent",
                amount="1.00",
                expense_type="luxury",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_expense_entry(
                session,
                reporting_month_id=first_id,
                category="Rent",
                amount="-1.00",
                expense_type=ExpenseType.MANDATORY,
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_saving_allocation(
                session,
                reporting_month_id=first_id,
                destination="Brokerage",
                amount="-1.00",
            )
    finally:
        session.close()
        database.engine.dispose()
