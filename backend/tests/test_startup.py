import sqlite3
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import MonkeyPatch, raises

from hermes_finance import cli
from hermes_finance.database import create_database
from hermes_finance.services.migrations import ALEMBIC_CONFIG_PATH


def _upgrade_to(database_path: Path, revision: str) -> None:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.attributes["database_path"] = str(database_path)
    command.upgrade(config, revision)


def test_create_app_and_health_do_not_touch_market_providers(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    from hermes_finance.main import create_app
    from hermes_finance.market_data import moex_iss, t_invest
    from hermes_finance.persistence import Base

    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("startup must not construct a market-data client")

    monkeypatch.setattr(moex_iss, "MoexIssClient", boom)
    monkeypatch.setattr(t_invest, "TInvestClient", boom)
    database = create_database(tmp_path / "startup_market.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            assert client.get("/api/health").status_code == 200
            assert client.get("/api/months").status_code == 200
    finally:
        database.engine.dispose()


def test_standard_cli_startup_migrates_database_before_serving_db_endpoint(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "clean-install" / "finance.db"
    observed: dict[str, object] = {}

    def capture_run(app: str, *, host: str, port: int, reload: bool) -> None:
        observed.update(app=app, host=host, port=port, reload=reload)
        connection = sqlite3.connect(database_path)
        try:
            observed["revision"] = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        finally:
            connection.close()

        database = create_database(database_path)
        try:
            with TestClient(cli.app) as client:
                response = client.get("/api/months")
        finally:
            database.engine.dispose()
        observed["months_status"] = response.status_code

    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(database_path))
    monkeypatch.setattr(uvicorn, "run", capture_run)

    cli.main()

    assert observed == {
        "app": "hermes_finance.main:app",
        "host": "127.0.0.1",
        "port": 8000,
        "reload": False,
        "revision": "0027_applied_provider_payouts",
        "months_status": 200,
    }


def test_standard_cli_startup_upgrades_database_from_previous_revision(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    database_path = tmp_path / "previous-revision" / "finance.db"
    _upgrade_to(database_path, "0019_position_deposit_updated_at")
    observed: dict[str, object] = {}
    starts = 0

    def capture_run(_app: str, *, host: str, port: int, reload: bool) -> None:
        nonlocal starts
        starts += 1
        connection = sqlite3.connect(database_path)
        try:
            observed["revision"] = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0]
        finally:
            connection.close()

    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(database_path))
    monkeypatch.setattr(uvicorn, "run", capture_run)

    cli.main()
    cli.main()

    assert observed == {"revision": "0027_applied_provider_payouts"}
    assert starts == 2


def test_cli_does_not_start_server_when_migration_fails(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    started = False

    def fail_migration(_database_path: Path) -> None:
        raise RuntimeError("synthetic migration failure")

    def capture_run(*_args: object, **_kwargs: object) -> None:
        nonlocal started
        started = True

    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(tmp_path / "failed.db"))
    monkeypatch.setattr(cli, "upgrade_database", fail_migration)
    monkeypatch.setattr(uvicorn, "run", capture_run)

    with raises(RuntimeError, match="synthetic migration failure"):
        cli.main()

    assert started is False
