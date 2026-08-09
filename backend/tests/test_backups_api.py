import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.services.backups import (
    BackupStorageError,
    create_backup,
    list_backups,
)


@pytest.fixture
def app_context(tmp_path: Path) -> tuple[TestClient, Database]:
    database = create_database(tmp_path / "data" / "synthetic-finance.db")
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _seed_synthetic_database(database: Database) -> None:
    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE synthetic_ledger (id INTEGER PRIMARY KEY, label TEXT NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO synthetic_ledger (label) VALUES ('alpha'), ('beta')"
        )


def test_sqlite_backup_api_copies_consistent_snapshot_without_mutating_source(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "nested" / "synthetic-finance.db"
    database = create_database(database_path)
    try:
        _seed_synthetic_database(database)
        source_before = database_path.read_bytes()

        metadata = create_backup(
            database,
            now=datetime(2032, 7, 31, 12, 34, 56, 789000, tzinfo=UTC),
        )
        backup_path = database_path.parent / "backups" / metadata.name

        assert backup_path.is_file()
        assert backup_path.read_bytes() != b""
        assert database_path.read_bytes() == source_before
        with sqlite3.connect(backup_path) as connection:
            rows = connection.execute(
                "SELECT id, label FROM synthetic_ledger ORDER BY id"
            ).fetchall()
        assert rows == [(1, "alpha"), (2, "beta")]
        assert metadata.id == "finance_backup_20320731T123456789000Z"
        assert metadata.name == "finance_backup_20320731T123456789000Z.sqlite3"
        assert metadata.size_bytes == backup_path.stat().st_size
        assert metadata.source_database.name == database_path.name
        assert metadata.source_database.size_bytes == len(source_before)
    finally:
        database.engine.dispose()


def test_backup_list_is_newest_first_and_missing_directory_is_empty(tmp_path: Path) -> None:
    database = create_database(tmp_path / "finance.db")
    try:
        assert list_backups(database) == []
        older = create_backup(database, now=datetime(2032, 1, 1, tzinfo=UTC))
        newer = create_backup(database, now=datetime(2032, 1, 2, tzinfo=UTC))

        listed = list_backups(database)

        assert [item.id for item in listed] == [newer.id, older.id]
        assert all(item.source_database.name == "finance.db" for item in listed)
    finally:
        database.engine.dispose()


def test_backup_api_creates_and_lists_metadata(app_context: tuple[TestClient, Database]) -> None:
    client, database = app_context
    _seed_synthetic_database(database)

    created = client.post("/api/backups")

    assert created.status_code == 201, created.text
    payload: dict[str, Any] = created.json()
    assert payload["id"].startswith("finance_backup_")
    assert payload["name"].endswith(".sqlite3")
    assert payload["created_at"].endswith("Z")
    assert payload["size_bytes"] > 0
    assert payload["source_database"]["name"] == "synthetic-finance.db"
    assert "path" not in payload["source_database"]
    assert payload["source_database"]["size_bytes"] == database.database_path.stat().st_size

    listed = client.get("/api/backups")

    assert listed.status_code == 200, listed.text
    assert listed.json() == [payload]
    assert (database.database_path.parent / "backups" / payload["name"]).is_file()


def test_invalid_backup_directory_is_reported_without_creating_a_file(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.db"
    database = create_database(database_path)
    backup_directory = database_path.parent / "backups"
    backup_directory.write_text("not a directory", encoding="utf-8")
    try:
        with pytest.raises(BackupStorageError, match="not a directory"):
            create_backup(database)
        with pytest.raises(BackupStorageError, match="not a directory"):
            list_backups(database)
    finally:
        database.engine.dispose()


def test_backup_api_returns_unified_error_for_invalid_directory(tmp_path: Path) -> None:
    database_path = tmp_path / "finance.db"
    database = create_database(database_path)
    (database_path.parent / "backups").write_text("not a directory", encoding="utf-8")
    try:
        with TestClient(create_app(database)) as client:
            response = client.post("/api/backups")
    finally:
        database.engine.dispose()

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "Backup storage is not available",
            "details": [],
        }
    }
