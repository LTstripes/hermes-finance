from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.properties import (
    PropertySnapshotNotFoundError,
    create_property_snapshot,
    delete_property_snapshot,
    get_property_snapshot,
    list_property_snapshots,
    mortgage_coverage,
    property_equity,
    total_mortgage_balance,
    total_property_value,
    update_property_snapshot,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "properties.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    first = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    second = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 12))
    return first.id, second.id


def test_property_equity_is_value_minus_mortgage(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_property_snapshot(
            session,
            reporting_month_id=first_id,
            name="Synthetic Flat",
            estimated_value="10000000.00",
            mortgage_balance="4000000.00",
            monthly_payment="60000.00",
        )
        assert total_property_value(session, first_id) == RubleAmount(1_000_000_000)
        assert total_mortgage_balance(session, first_id) == RubleAmount(400_000_000)
        assert property_equity(session, first_id) == RubleAmount(600_000_000)
    finally:
        session.close()
        database.engine.dispose()


def test_mortgage_coverage_returns_none_when_mortgage_is_zero(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_property_snapshot(
            session,
            reporting_month_id=first_id,
            name="Synthetic Paid Off Flat",
            estimated_value="10000000.00",
            mortgage_balance="0.00",
            monthly_payment="0.00",
        )
        liquid_capital = RubleAmount(5_000_000)
        percentage, gap = mortgage_coverage(session, first_id, liquid_capital)
        assert percentage is None
        assert gap == RubleAmount(5_000_000)
    finally:
        session.close()
        database.engine.dispose()


def test_mortgage_coverage_percentage_and_gap(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        create_property_snapshot(
            session,
            reporting_month_id=first_id,
            name="Synthetic Flat",
            estimated_value="10000000.00",
            mortgage_balance="4000000.00",
            monthly_payment="60000.00",
        )
        liquid_capital = RubleAmount(200_000_000)
        percentage, gap = mortgage_coverage(session, first_id, liquid_capital)
        assert percentage == Decimal("50.00")
        assert gap == RubleAmount(-200_000_000)
    finally:
        session.close()
        database.engine.dispose()


def test_property_crud_updates_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        snapshot = create_property_snapshot(
            session,
            reporting_month_id=first_id,
            name="  Synthetic Flat  ",
            estimated_value="10000000.00",
            mortgage_balance="4000000.00",
            monthly_payment="60000.00",
            notes="synthetic note",
        )
        assert snapshot.name == "Synthetic Flat"
        updated = update_property_snapshot(
            session, snapshot.id, mortgage_balance="3000000.00", notes="updated"
        )
        assert updated.mortgage_balance_kopecks == 300_000_000
        assert updated.notes == "updated"
        assert len(list_property_snapshots(session)) == 1
        delete_property_snapshot(session, snapshot.id)
        with pytest.raises(PropertySnapshotNotFoundError):
            get_property_snapshot(session, snapshot.id)
    finally:
        session.close()
        database.engine.dispose()


def test_property_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first_id, _ = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_property_snapshot(
                session,
                reporting_month_id=first_id,
                name="  ",
                estimated_value="1.00",
                mortgage_balance="0.00",
                monthly_payment="0.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_property_snapshot(
                session,
                reporting_month_id=first_id,
                name="Synthetic",
                estimated_value="-1.00",
                mortgage_balance="0.00",
                monthly_payment="0.00",
            )
    finally:
        session.close()
        database.engine.dispose()
