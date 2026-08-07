from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType
from hermes_finance.persistence import Base
from hermes_finance.services.incomes import (
    IncomeEntryNotFoundError,
    create_income_entry,
    delete_income_entry,
    get_income_entry,
    list_income_entries,
    update_income_entry,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "incomes.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> int:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    return month.id


def test_cashback_is_excluded_from_passive_income_by_default(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.CASHBACK,
            name="Synthetic Cashback",
            gross_amount="500.00",
            tax_amount="0.00",
            net_amount="500.00",
        )
        assert entry.include_in_cash_flow is True
        assert entry.include_in_passive_income is False
    finally:
        session.close()
        database.engine.dispose()


def test_cashback_rejects_explicit_passive_income_flag(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        with pytest.raises(ValueError, match="must not be included in passive income"):
            create_income_entry(
                session,
                reporting_month_id=month_id,
                income_type=IncomeType.CASHBACK,
                name="Synthetic Cashback",
                gross_amount="500.00",
                tax_amount="0.00",
                net_amount="500.00",
                include_in_passive_income=True,
            )
    finally:
        session.close()
        database.engine.dispose()


def test_non_cashback_income_can_be_marked_passive(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SIDE_INCOME,
            name="Synthetic Rent",
            gross_amount="10000.00",
            tax_amount="1300.00",
            net_amount="8700.00",
            include_in_passive_income=True,
        )
        assert entry.include_in_passive_income is True
    finally:
        session.close()
        database.engine.dispose()


def test_actual_net_may_differ_from_calculated(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Synthetic Salary",
            gross_amount="100000.00",
            tax_amount="13000.00",
            net_amount="85000.00",
        )
        assert entry.gross_amount_kopecks == 10_000_000
        assert entry.tax_amount_kopecks == 1_300_000
        assert entry.net_amount_kopecks == 8_500_000
    finally:
        session.close()
        database.engine.dispose()


def test_income_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.BONUS,
            name="  Synthetic Bonus  ",
            gross_amount="50000.00",
            tax_amount="6500.00",
            net_amount="43500.00",
            received_at=date(2030, 5, 15),
            is_recurring=False,
            notes="synthetic note",
        )
        assert entry.name == "Synthetic Bonus"
        assert entry.received_at == date(2030, 5, 15)

        updated = update_income_entry(
            session,
            entry.id,
            income_type=IncomeType.OTHER,
            name="Synthetic Bonus Updated",
            is_recurring=True,
            notes="updated",
        )
        assert updated.income_type == IncomeType.OTHER.value
        assert updated.is_recurring is True
        assert len(list_income_entries(session)) == 1

        delete_income_entry(session, entry.id)
        with pytest.raises(IncomeEntryNotFoundError):
            get_income_entry(session, entry.id)
    finally:
        session.close()
        database.engine.dispose()


def test_income_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_income_entry(
                session,
                reporting_month_id=month_id,
                income_type=IncomeType.SALARY,
                name="  ",
                gross_amount="1.00",
                tax_amount="0.00",
                net_amount="1.00",
            )
        with pytest.raises(ValueError, match="unsupported income type"):
            create_income_entry(
                session,
                reporting_month_id=month_id,
                income_type="dividend",
                name="Synthetic",
                gross_amount="1.00",
                tax_amount="0.00",
                net_amount="1.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_income_entry(
                session,
                reporting_month_id=month_id,
                income_type=IncomeType.SALARY,
                name="Synthetic",
                gross_amount="1.00",
                tax_amount="0.00",
                net_amount="-1.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def _build_passive_income_entry(session: Session, month_id: int):
    return create_income_entry(
        session,
        reporting_month_id=month_id,
        income_type=IncomeType.SIDE_INCOME,
        name="Synthetic Passive Rent",
        gross_amount="10000.00",
        tax_amount="1300.00",
        net_amount="8700.00",
        include_in_passive_income=True,
    )


def test_update_switching_type_to_cashback_forces_passive_income_false(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = _build_passive_income_entry(session, month_id)
        assert entry.include_in_passive_income is True

        updated = update_income_entry(session, entry.id, income_type=IncomeType.CASHBACK)

        assert updated.income_type == IncomeType.CASHBACK.value
        assert updated.include_in_passive_income is False
    finally:
        session.close()
        database.engine.dispose()


def test_update_switching_to_cashback_ignores_explicit_passive_true(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = _build_passive_income_entry(session, month_id)

        updated = update_income_entry(
            session, entry.id, income_type=IncomeType.CASHBACK, include_in_passive_income=True
        )

        assert updated.include_in_passive_income is False
    finally:
        session.close()
        database.engine.dispose()


def test_update_cashback_entry_keeps_passive_income_false(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.CASHBACK,
            name="Synthetic Cashback",
            gross_amount="500.00",
            tax_amount="0.00",
            net_amount="500.00",
        )
        assert entry.include_in_passive_income is False

        updated = update_income_entry(
            session, entry.id, name="Updated Cashback", include_in_passive_income=True
        )

        assert updated.include_in_passive_income is False
    finally:
        session.close()
        database.engine.dispose()


def test_update_cashback_entry_without_flag_keeps_passive_income_false(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.CASHBACK,
            name="Synthetic Cashback",
            gross_amount="500.00",
            tax_amount="0.00",
            net_amount="500.00",
        )

        updated = update_income_entry(session, entry.id, name="Updated Cashback")

        assert updated.include_in_passive_income is False
    finally:
        session.close()
        database.engine.dispose()


def test_update_non_cashback_keeps_explicit_passive_income_flag(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_environment(session)
        entry = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SIDE_INCOME,
            name="Synthetic Rent",
            gross_amount="10000.00",
            tax_amount="1300.00",
            net_amount="8700.00",
            include_in_passive_income=False,
        )
        assert entry.include_in_passive_income is False

        updated = update_income_entry(session, entry.id, include_in_passive_income=True)

        assert updated.income_type == IncomeType.SIDE_INCOME.value
        assert updated.include_in_passive_income is True
    finally:
        session.close()
        database.engine.dispose()
