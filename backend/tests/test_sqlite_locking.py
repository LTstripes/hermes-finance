"""SQLite locking regression coverage, originally recorded as R02-10."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from hermes_finance import database as database_module
from hermes_finance.database import (
    ReadSnapshotCleanupError,
    ReadSnapshotMutationError,
    coherent_read_snapshot,
    create_database,
)

SQLITE_DEFAULT_BUSY_TIMEOUT_MS = 5_000


def _run_contended_write(
    database_path: Path,
    started: threading.Event,
    result: dict[str, object],
) -> None:
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            started.set()
            started_at = time.monotonic()
            try:
                connection.exec_driver_sql("INSERT INTO lock_probe (value) VALUES (2)")
                connection.commit()
                result.update(status="success", elapsed=time.monotonic() - started_at)
            except Exception as error:  # noqa: BLE001 - assert the real lock outcome
                result.update(
                    status=type(error).__name__,
                    error=str(error),
                    elapsed=time.monotonic() - started_at,
                )
    finally:
        database.engine.dispose()


def _exercise_lock(
    database_path: Path,
    *,
    lock_sql: str,
    read_before_write: bool,
) -> dict[str, object]:
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            connection.exec_driver_sql("CREATE TABLE lock_probe (value INTEGER NOT NULL)")
            connection.commit()
            connection.exec_driver_sql(lock_sql)
            if read_before_write:
                connection.exec_driver_sql("SELECT count(*) FROM lock_probe").scalar_one()
            else:
                connection.exec_driver_sql("INSERT INTO lock_probe (value) VALUES (1)")

            started = threading.Event()
            result: dict[str, object] = {}
            worker = threading.Thread(
                target=_run_contended_write,
                args=(database_path, started, result),
            )
            worker.start()
            assert started.wait(2)
            time.sleep(0.2)
            connection.commit()
            worker.join(timeout=10)
            assert not worker.is_alive()
            return result
    finally:
        database.engine.dispose()


def test_sqlite_lock_policy_keeps_rollback_journal_and_waits_for_short_contention(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "synthetic-finance.db"
    database = create_database(database_path)
    try:
        with database.engine.connect() as connection:
            pragmas = {
                name: connection.exec_driver_sql(f"PRAGMA {name}").scalar_one()
                for name in ("busy_timeout", "journal_mode")
            }
    finally:
        database.engine.dispose()

    assert pragmas == {
        "busy_timeout": SQLITE_DEFAULT_BUSY_TIMEOUT_MS,
        "journal_mode": "delete",
    }

    write_result = _exercise_lock(
        database_path,
        lock_sql="BEGIN IMMEDIATE",
        read_before_write=False,
    )
    read_result = _exercise_lock(
        tmp_path / "read-write.db",
        lock_sql="BEGIN",
        read_before_write=True,
    )

    for result in (write_result, read_result):
        assert result["status"] == "success"
        assert float(result["elapsed"]) >= 0.15

    assert not Path(f"{database_path}-wal").exists()
    assert not Path(f"{database_path}-shm").exists()
    assert not (tmp_path / "read-write.db-wal").exists()
    assert not (tmp_path / "read-write.db-shm").exists()


def test_coherent_read_snapshot_is_nested_read_only_and_releases_on_error(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "read-snapshot.db")
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE snapshot_probe (value INTEGER NOT NULL)")
            connection.exec_driver_sql("INSERT INTO snapshot_probe (value) VALUES (1)")

        with database.session_factory() as session:
            with pytest.raises(RuntimeError, match="synthetic read failure"):
                with coherent_read_snapshot(session):
                    driver = session.connection().connection.driver_connection
                    assert driver.in_transaction is True
                    assert driver.execute("PRAGMA query_only").fetchone() == (1,)
                    with coherent_read_snapshot(session):
                        assert session.connection().connection.driver_connection is driver
                        assert (
                            session.connection()
                            .exec_driver_sql("SELECT value FROM snapshot_probe")
                            .scalar_one()
                            == 1
                        )
                    raise RuntimeError("synthetic read failure")

            driver = session.connection().connection.driver_connection
            assert driver.in_transaction is False
            assert driver.execute("PRAGMA query_only").fetchone() == (0,)

            with pytest.raises(OperationalError, match="attempt to write a readonly database"):
                with coherent_read_snapshot(session):
                    session.connection().exec_driver_sql(
                        "INSERT INTO snapshot_probe (value) VALUES (2)"
                    )

            assert driver.in_transaction is False
            assert driver.execute("PRAGMA query_only").fetchone() == (0,)

            with pytest.raises(
                RuntimeError,
                match="cannot be committed inside the protected operation",
            ):
                with coherent_read_snapshot(session):
                    session.commit()

            with coherent_read_snapshot(session):
                assert (
                    session.connection()
                    .exec_driver_sql("SELECT value FROM snapshot_probe")
                    .scalar_one()
                    == 1
                )
            assert driver.in_transaction is False
            assert driver.execute("PRAGMA query_only").fetchone() == (0,)

            assert (
                session.connection()
                .exec_driver_sql("SELECT count(*) FROM snapshot_probe")
                .scalar_one()
                == 1
            )
    finally:
        database.engine.dispose()


def test_coherent_read_snapshot_rejects_a_preexisting_flushed_transaction(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "preexisting-transaction.db")
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE snapshot_probe (value INTEGER NOT NULL)")

        with database.session_factory() as session:
            session.connection().exec_driver_sql("INSERT INTO snapshot_probe (value) VALUES (1)")
            driver = session.connection().connection.driver_connection
            assert driver.in_transaction is True
            assert not session.new and not session.dirty and not session.deleted

            with pytest.raises(
                ReadSnapshotMutationError,
                match="requires no pre-existing SQLite transaction",
            ):
                with coherent_read_snapshot(session):
                    pass

            assert driver.in_transaction is True
            session.rollback()

        with database.engine.connect() as connection:
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM snapshot_probe").scalar_one() == 0
            )
    finally:
        database.engine.dispose()


def test_coherent_read_snapshot_restores_query_only_when_begin_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = create_database(tmp_path / "begin-failure.db")
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE snapshot_probe (value INTEGER NOT NULL)")

        def fail_begin(_connection) -> None:
            raise RuntimeError("synthetic begin failure")

        monkeypatch.setattr(database_module, "_begin_sqlite_read_snapshot", fail_begin)
        with database.session_factory() as session:
            driver = session.connection().connection.driver_connection
            with pytest.raises(RuntimeError, match="synthetic begin failure"):
                with coherent_read_snapshot(session):
                    pass
            assert driver.in_transaction is False
            assert driver.execute("PRAGMA query_only").fetchone() == (0,)

        with database.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO snapshot_probe (value) VALUES (1)")
    finally:
        database.engine.dispose()


def test_coherent_read_snapshot_invalidates_connection_when_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = create_database(tmp_path / "cleanup-failure.db")
    try:
        with database.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE snapshot_probe (value INTEGER NOT NULL)")

        real_set_query_only = database_module._set_sqlite_query_only

        def fail_disable(connection, *, enabled: bool) -> None:
            if not enabled:
                raise RuntimeError("synthetic query-only cleanup failure")
            real_set_query_only(connection, enabled=enabled)

        monkeypatch.setattr(database_module, "_set_sqlite_query_only", fail_disable)
        with database.session_factory() as session:
            with pytest.raises(
                ReadSnapshotCleanupError,
                match="could not restore its SQLite connection",
            ):
                with coherent_read_snapshot(session):
                    raise RuntimeError("synthetic read failure")

        with database.engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA query_only").scalar_one() == 0
            connection.exec_driver_sql("INSERT INTO snapshot_probe (value) VALUES (1)")
    finally:
        database.engine.dispose()
