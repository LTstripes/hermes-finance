import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.backups import backup_directory, create_backup
from hermes_finance.services.settings import update_settings


@pytest.fixture
def app_context(tmp_path: Path) -> tuple[TestClient, Database]:
    database = create_database(tmp_path / "data" / "synthetic-finance.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _set_locale(database: Database, locale: str) -> None:
    with database.session_factory() as session:
        update_settings(session, locale=locale)


def _make_candidate_backup(
    database: Database,
    tmp_path: Path,
    *,
    locale: str,
    name_timestamp: str = "20330101T010203000000Z",
) -> Path:
    candidate = create_database(tmp_path / "candidate" / "candidate.db")
    Base.metadata.create_all(candidate.engine)
    try:
        _set_locale(candidate, locale)
        metadata = create_backup(
            candidate,
            now=datetime.strptime(name_timestamp, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC),
        )
        destination = backup_directory(database) / metadata.name
        backup_directory(database).mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_directory(candidate) / metadata.name, destination)
        return destination
    finally:
        candidate.engine.dispose()


def _settings_locale(client: TestClient) -> str:
    response = client.get("/api/settings")
    assert response.status_code == 200, response.text
    return response.json()["locale"]


def test_restore_valid_backup_creates_pre_restore_backup_and_refreshes_new_requests(
    app_context: tuple[TestClient, Database], tmp_path: Path
) -> None:
    client, database = app_context
    _set_locale(database, "before-restore")
    candidate_path = _make_candidate_backup(database, tmp_path, locale="after-restore")

    response = client.post(
        f"/api/backups/{candidate_path.stem}/restore",
        json={"confirm": True},
    )

    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    assert payload["restored_backup"]["id"] == candidate_path.stem
    assert payload["pre_restore_backup"]["id"] != candidate_path.stem
    assert payload["pre_restore_backup"]["source_database"]["name"] == database.database_path.name
    assert _settings_locale(client) == "after-restore"
    assert len(list(backup_directory(database).glob("*.sqlite3"))) == 2
    pre_restore_path = backup_directory(database) / payload["pre_restore_backup"]["name"]
    pre_restore_connection = sqlite3.connect(pre_restore_path)
    try:
        assert pre_restore_connection.execute("SELECT locale FROM app_settings").fetchone() == (
            "before-restore",
        )
    finally:
        pre_restore_connection.close()
    assert list(database.database_path.parent.glob("*.restore.*.tmp")) == []


def test_restore_rejects_corrupt_sqlite_and_keeps_live_database_intact(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _set_locale(database, "still-live")
    corrupt = backup_directory(database) / "finance_backup_20330101T010203000001Z.sqlite3"
    backup_directory(database).mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b"not a sqlite database")

    response = client.post(
        f"/api/backups/{corrupt.stem}/restore",
        json={"confirm": True},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "unprocessable",
            "message": "Backup is not a valid SQLite database",
            "details": [],
        }
    }
    assert _settings_locale(client) == "still-live"
    assert len(list(backup_directory(database).glob("*.sqlite3"))) == 1


def test_restore_rejects_incompatible_sqlite_schema_before_pre_restore_backup(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _set_locale(database, "still-live")
    incompatible = backup_directory(database) / "finance_backup_20330101T010204000001Z.sqlite3"
    backup_directory(database).mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(incompatible)
    try:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
    finally:
        connection.close()

    response = client.post(
        f"/api/backups/{incompatible.stem}/restore",
        json={"confirm": True},
    )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "unprocessable",
            "message": "Backup schema is incompatible with the live database",
            "details": [],
        }
    }
    assert _settings_locale(client) == "still-live"
    assert len(list(backup_directory(database).glob("*.sqlite3"))) == 1


def test_restore_requires_explicit_confirmation(
    app_context: tuple[TestClient, Database], tmp_path: Path
) -> None:
    client, database = app_context
    _set_locale(database, "still-live")
    candidate_path = _make_candidate_backup(database, tmp_path, locale="not-restored")

    response = client.post(
        f"/api/backups/{candidate_path.stem}/restore",
        json={"confirm": False},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable"
    assert _settings_locale(client) == "still-live"
    assert len(list(backup_directory(database).glob("*.sqlite3"))) == 1
