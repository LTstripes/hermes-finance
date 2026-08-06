from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.cash import (
    CashBalanceNotFoundError,
    create_cash_balance,
    delete_cash_balance,
    get_cash_balance,
    list_cash_balances,
    total_cash,
    update_cash_balance,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "cash.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    first = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    second = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 12))
    return first.id, second.id


def test_total_cash_is_zero_when_no_rows_exist(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        assert total_cash(session, first_id) == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_total_cash_sums_only_the_requested_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, second_id = build_environment(session)
        create_cash_balance(session, reporting_month_id=first_id, name="Wallet", amount="1000.00")
        create_cash_balance(session, reporting_month_id=first_id, name="Safe", amount="2500.50")
        create_cash_balance(session, reporting_month_id=second_id, name="Wallet", amount="99.00")
        assert total_cash(session, first_id) == RubleAmount(350_050)
        assert total_cash(session, second_id) == RubleAmount(9_900)
    finally:
        session.close()
        database.engine.dispose()


def test_total_cash_can_filter_include_in_capital(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_cash_balance(
            session,
            reporting_month_id=first_id,
            name="Wallet",
            amount="1000.00",
            include_in_capital=True,
        )
        create_cash_balance(
            session,
            reporting_month_id=first_id,
            name="Petty cash",
            amount="50.00",
            include_in_capital=False,
        )
        assert total_cash(session, first_id) == RubleAmount(105_000)
        assert total_cash(session, first_id, include_in_capital_only=True) == RubleAmount(100_000)
    finally:
        session.close()
        database.engine.dispose()


def test_cash_crud_updates_flags_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        balance = create_cash_balance(
            session,
            reporting_month_id=first_id,
            name="  Synthetic Wallet  ",
            amount="500.00",
            currency="usd",
            include_in_capital=False,
            notes="synthetic note",
        )
        assert balance.name == "Synthetic Wallet"
        assert balance.currency == "USD"
        assert balance.include_in_capital is False

        updated = update_cash_balance(
            session,
            balance.id,
            amount="600.00",
            include_in_capital=True,
            notes="updated",
        )
        assert updated.amount_kopecks == 60_000
        assert updated.include_in_capital is True
        assert updated.notes == "updated"
        assert len(list_cash_balances(session)) == 1

        delete_cash_balance(session, balance.id)
        with pytest.raises(CashBalanceNotFoundError):
            get_cash_balance(session, balance.id)
    finally:
        session.close()
        database.engine.dispose()


def test_cash_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_cash_balance(session, reporting_month_id=first_id, name="  ", amount="1.00")
        with pytest.raises(ValueError, match="must not be negative"):
            create_cash_balance(session, reporting_month_id=first_id, name="Wallet", amount="-1.00")
    finally:
        session.close()
        database.engine.dispose()
