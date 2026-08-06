from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import DebtType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.debts import (
    DebtNotFoundError,
    create_debt,
    delete_debt,
    get_debt,
    list_debts,
    total_debts,
    total_included_debts,
    update_debt,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "debts.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    first = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    second = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 12))
    return first.id, second.id


def test_credit_card_is_included_in_liquid_capital_deduction(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="25000.00",
        )
        create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.OTHER,
            name="Synthetic Loan",
            current_balance="50000.00",
            include_in_liquid_capital=False,
        )
        assert total_debts(session, first_id) == RubleAmount(7_500_000)
        assert total_included_debts(session, first_id) == RubleAmount(2_500_000)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_totals_are_scoped_to_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, second_id = build_environment(session)
        create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="25000.00",
        )
        create_debt(
            session,
            reporting_month_id=second_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Synthetic Card",
            current_balance="1000.00",
        )
        assert total_included_debts(session, first_id) == RubleAmount(2_500_000)
        assert total_included_debts(session, second_id) == RubleAmount(100_000)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        debt = create_debt(
            session,
            reporting_month_id=first_id,
            debt_type=DebtType.OTHER,
            name="  Synthetic Loan  ",
            current_balance="100000.00",
            notes="synthetic note",
        )
        assert debt.name == "Synthetic Loan"
        updated = update_debt(
            session,
            debt.id,
            current_balance="90000.00",
            include_in_liquid_capital=False,
        )
        assert updated.current_balance_kopecks == 9_000_000
        assert updated.include_in_liquid_capital is False
        assert len(list_debts(session)) == 1
        delete_debt(session, debt.id)
        with pytest.raises(DebtNotFoundError):
            get_debt(session, debt.id)
    finally:
        session.close()
        database.engine.dispose()


def test_debt_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type=DebtType.CREDIT_CARD,
                name="  ",
                current_balance="1.00",
            )
        with pytest.raises(ValueError, match="unsupported debt type"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type="mortgage",
                name="Synthetic",
                current_balance="1.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_debt(
                session,
                reporting_month_id=first_id,
                debt_type=DebtType.CREDIT_CARD,
                name="Synthetic",
                current_balance="-1.00",
            )
    finally:
        session.close()
        database.engine.dispose()
