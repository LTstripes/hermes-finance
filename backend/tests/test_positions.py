from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import (
    PositionSnapshotNotFoundError,
    create_position_snapshot,
    delete_position_snapshot,
    get_position_snapshot,
    list_position_snapshots,
    update_position_snapshot,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "positions.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(
    session: Session, *, instrument_type: InstrumentType = InstrumentType.BOND
) -> tuple[int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(session, name="Synthetic Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic Instrument", instrument_type=instrument_type
    )
    return month.id, account.id, instrument.id


def test_position_metrics_are_computed_and_recomputed_on_price_change(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=10,
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            price_date=date(2030, 5, 12),
        )
        assert snapshot.quantity == Decimal("10.000000")
        assert snapshot.average_cost_per_unit_kopecks == 10_000
        assert snapshot.market_price_per_unit_kopecks == 15_000
        assert snapshot.market_value_kopecks == 150_000
        assert snapshot.cost_basis_kopecks == 100_000
        assert snapshot.unrealized_result_kopecks == 50_000

        updated = update_position_snapshot(session, snapshot.id, market_price_per_unit="200.00")
        assert updated.market_value_kopecks == 200_000
        assert updated.unrealized_result_kopecks == 100_000
    finally:
        session.close()
        database.engine.dispose()


def test_position_accrued_interest_and_fractional_quantity(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="0.5",
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            accrued_interest="10.00",
            price_date=date(2030, 5, 12),
        )
        assert snapshot.quantity == Decimal("0.500000")
        assert snapshot.market_value_kopecks == 7_500 + 1_000
        assert snapshot.cost_basis_kopecks == 5_000
        assert snapshot.unrealized_result_kopecks == 3_500
    finally:
        session.close()
        database.engine.dispose()


def test_position_uniqueness_per_month_account_instrument(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2030, 5, 12),
        )
        with pytest.raises(ValueError, match="already exists"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=2,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_position_crud_lists_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=3,
            average_cost_per_unit="50.00",
            market_price_per_unit="60.00",
            price_source=PriceSource.MOEX,
            manual_adjustment=True,
            notes="synthetic note",
            price_date=date(2030, 5, 12),
        )
        assert snapshot.price_source == PriceSource.MOEX.value
        assert snapshot.manual_adjustment is True
        assert snapshot.notes == "synthetic note"
        assert len(list_position_snapshots(session)) == 1

        delete_position_snapshot(session, snapshot.id)
        with pytest.raises(PositionSnapshotNotFoundError):
            get_position_snapshot(session, snapshot.id)
    finally:
        session.close()
        database.engine.dispose()


def test_position_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        with pytest.raises(ValueError, match="must be positive"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=-1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
        with pytest.raises(ValueError, match="unsupported price source"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_source="yahoo",
                price_date=date(2030, 5, 12),
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="-1.00",
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_stock_quantity_must_be_positive_whole_number(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(
            session, instrument_type=InstrumentType.STOCK
        )
        with pytest.raises(ValueError, match="positive whole number"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity="0.5",
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
        with pytest.raises(ValueError, match="must be positive"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=0,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()
