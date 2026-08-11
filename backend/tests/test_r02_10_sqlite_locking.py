from __future__ import annotations

import threading
import time
from pathlib import Path

from hermes_finance.database import create_database

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
