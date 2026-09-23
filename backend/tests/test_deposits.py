from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import Database, create_database
from hermes_finance.domain import AccountType, DepositType, PercentageRate
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.concurrency import ConcurrencyError
from hermes_finance.services.deposits import (
    DepositSnapshotNotFoundError,
    create_deposit_snapshot,
    delete_deposit_snapshot,
    get_deposit_snapshot,
    list_deposit_snapshots,
    update_deposit_snapshot,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, Database]:
    database = create_database(tmp_path / "deposits.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT)
    return month.id, account.id


def test_expected_monthly_interest_matches_contract(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        snapshot = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Synthetic Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="12.00",
        )
        assert snapshot.balance_kopecks == 10_000_000
        assert snapshot.annual_rate_basis_points == 1_200
        assert snapshot.expected_monthly_interest_kopecks == 100_000
        assert snapshot.actual_interest_received_kopecks == 0
    finally:
        session.close()
        database.engine.dispose()


def test_expected_monthly_interest_rounds_half_up(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        snapshot = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Synthetic Half",
            deposit_type=DepositType.DEPOSIT,
            balance="1.00",
            annual_rate="6.00",
        )
        assert snapshot.expected_monthly_interest_kopecks == 1
    finally:
        session.close()
        database.engine.dispose()


def test_deposit_update_recomputes_expected_interest(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        snapshot = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Synthetic Deposit",
            deposit_type=DepositType.SAVINGS,
            balance="100000.00",
            annual_rate="12.00",
        )
        updated = update_deposit_snapshot(
            session, snapshot.id, balance="200000.00", annual_rate="6.00"
        )
        assert updated.balance_kopecks == 20_000_000
        assert updated.annual_rate_basis_points == 600
        assert updated.expected_monthly_interest_kopecks == 100_000
    finally:
        session.close()
        database.engine.dispose()


def test_concurrent_balance_and_rate_updates_have_one_atomic_winner(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        snapshot = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Synthetic Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="12.00",
        )
        snapshot_id = snapshot.id
        expected_updated_at = snapshot.updated_at
        session.close()
        ready = Barrier(3)

        def run(update: dict[str, object]) -> str:
            worker_session = database.session_factory()
            try:
                observed = get_deposit_snapshot(worker_session, snapshot_id)
                assert observed.updated_at == expected_updated_at
                ready.wait(timeout=5)
                try:
                    update_deposit_snapshot(
                        worker_session,
                        snapshot_id,
                        expected_updated_at=expected_updated_at,
                        **update,
                    )
                except ConcurrencyError:
                    worker_session.rollback()
                    return "conflict"
                return "success"
            finally:
                worker_session.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(run, {"balance": "240000.00"}),
                executor.submit(run, {"annual_rate": "6.00"}),
            ]
            ready.wait(timeout=5)
            outcomes = [future.result(timeout=10) for future in futures]

        assert sorted(outcomes) == ["conflict", "success"]
        verification_session = database.session_factory()
        try:
            stored = get_deposit_snapshot(verification_session, snapshot_id)
            assert (
                stored.balance_kopecks,
                stored.annual_rate_basis_points,
                stored.expected_monthly_interest_kopecks,
            ) in {
                (24_000_000, 1_200, 240_000),
                (10_000_000, 600, 50_000),
            }
        finally:
            verification_session.close()
    finally:
        session.close()
        database.engine.dispose()


def test_deposit_actual_interest_is_stored_not_replaced(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        snapshot = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Synthetic Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="12.00",
            actual_interest_received="900.00",
        )
        assert snapshot.actual_interest_received_kopecks == 90_000
        updated = update_deposit_snapshot(session, snapshot.id, balance="100000.00")
        assert updated.actual_interest_received_kopecks == 90_000
    finally:
        session.close()
        database.engine.dispose()


def test_deposit_crud_lists_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        snapshot = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="  Synthetic Savings  ",
            deposit_type=DepositType.SAVINGS,
            balance="50000.00",
            annual_rate="8.00",
            notes="synthetic note",
        )
        assert snapshot.name == "Synthetic Savings"
        assert len(list_deposit_snapshots(session)) == 1

        delete_deposit_snapshot(session, snapshot.id)
        with pytest.raises(DepositSnapshotNotFoundError):
            get_deposit_snapshot(session, snapshot.id)
    finally:
        session.close()
        database.engine.dispose()


def test_deposit_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id = build_environment(session)
        with pytest.raises(ValueError, match="must not be empty"):
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                name="  ",
                deposit_type=DepositType.DEPOSIT,
                balance="100.00",
                annual_rate="12.00",
            )
        with pytest.raises(ValueError, match="unsupported deposit type"):
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                name="Synthetic",
                deposit_type="metal",
                balance="100.00",
                annual_rate="12.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                name="Synthetic",
                deposit_type=DepositType.DEPOSIT,
                balance="-1.00",
                annual_rate="12.00",
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                name="Synthetic",
                deposit_type=DepositType.DEPOSIT,
                balance="100.00",
                annual_rate=PercentageRate.from_api("-1.00"),
            )
    finally:
        session.close()
        database.engine.dispose()
