import json
import os
import shutil
import sqlite3
import subprocess
import sys
import venv
from pathlib import Path

import pytest
import uvicorn
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pytest import MonkeyPatch, raises

from hermes_finance import cli
from hermes_finance.database import create_database
from hermes_finance.services.migrations import ALEMBIC_CONFIG_PATH


@pytest.mark.skipif(sys.platform != "win32", reason="Windows guarded Start boundary")
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("configuration", ["match", "wrong", "invalid"])
def test_pinned_test_runtime_checks_settings_before_backend_launch(
    monkeypatch: MonkeyPatch, tmp_path: Path, encoding: str, configuration: str
) -> None:
    repository = Path(__file__).resolve().parents[2]
    checkout = tmp_path / "synthetic Test Кириллица"
    backend = checkout / "backend"
    scripts = checkout / "scripts"
    module = backend / "src" / "hermes_finance"
    module.mkdir(parents=True)
    scripts.mkdir()
    for name in (
        "start-local.ps1",
        "prepare-preview-lib.ps1",
        "recovery-runtime-safety.ps1",
        "recovery-readiness.ps1",
    ):
        shutil.copyfile(repository / "scripts" / name, scripts / name)
    shutil.copyfile(repository / "backend/src/hermes_finance/settings.py", module / "settings.py")
    (module / "__init__.py").write_text('__version__ = "synthetic"\n', encoding="utf-8")
    # A separate interpreter with only the current code environment's packages.
    # No runtime/Owner checkout, config or DB is read or mounted.
    venv.EnvBuilder().create(backend / ".venv")
    packages = Path(sys.prefix) / "Lib" / "site-packages"
    (backend / ".venv/Lib/site-packages/test-packages.pth").write_text(
        str(packages), encoding="utf-8"
    )
    (backend / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (checkout / "frontend").mkdir()
    (checkout / "frontend/package.json").write_text("{}", encoding="utf-8")
    (scripts / "prepare-runtime.ps1").write_text(
        "param($Checkout, [switch]$Validate)\nexit 0\n", encoding="utf-8"
    )
    boundary = {
        name: str(tmp_path / name)
        for name in (
            "ControlCheckout",
            "StableCheckout",
            "StableDataDirectory",
            "PreviewDataDirectory",
        )
    }
    for directory in boundary.values():
        Path(directory).mkdir()
    intended = Path(boundary["PreviewDataDirectory"]) / "history.db"
    stable = Path(boundary["StableDataDirectory"]) / "stable.db"
    for database in (intended, stable):
        database.write_bytes(b"fabricated DB identity fixture; never opened as SQLite")
    sidecar = intended.parent / ".hermes-data-identity.json"
    sidecar.write_text('{"kind":"preview"}', encoding="utf-8")
    boundary.update(
        PreviewCheckout=str(checkout), PreviewDatabase=str(intended), StableDatabase=str(stable)
    )
    (checkout / ".hermes-preview-boundary.json").write_text(
        json.dumps(boundary, ensure_ascii=False), encoding="utf-8"
    )
    configured = intended if configuration == "match" else checkout / "data/finance.db"
    content = f'HERMES_FINANCE_DATABASE_PATH="{configured.as_posix()}"\n'
    if configuration == "invalid":
        content = "HERMES_FINANCE_PORT=synthetic-private-invalid-value\n"
    (checkout / ".env").write_text(content, encoding=encoding)
    for name in tuple(os.environ):
        if name.startswith("HERMES_FINANCE_"):
            monkeypatch.delenv(name)
    uv = tmp_path / "uv.cmd"
    launch_marker = tmp_path / "backend-started"
    uv.write_text(f'@echo off\n>"{launch_marker}" echo started\nexit /b 99\n', encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    harness = tmp_path / "probe.ps1"
    if configuration == "wrong":
        # Keep the probe independent of any actual Owner listener on port 8000.
        operation = (
            "function Get-NetTCPConnection {}\n& $args[0] -ExitAfterReady\nexit $LASTEXITCODE"
        )
        target = scripts / "start-local.ps1"
    else:
        operation = ". $args[0]\nAssert-HermesPreviewPinnedRuntimeBoundary -Checkout $args[1]"
        target = scripts / "prepare-preview-lib.ps1"
    harness.write_text('$ErrorActionPreference = "Stop"\n' + operation, encoding="utf-8")
    before = {path: path.read_bytes() for path in (intended, stable, sidecar)}
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(harness),
            str(target),
            str(checkout),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    output = result.stdout + result.stderr
    assert (result.returncode == 0) == (configuration == "match"), output
    if configuration == "wrong":
        assert "runtime database does not match the pinned destination" in output
    assert not launch_marker.exists()
    assert not (checkout / "data/finance.db").exists()
    assert "is ready" not in output
    assert "synthetic-private-invalid-value" not in output
    assert {path: path.read_bytes() for path in before} == before


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
        "revision": "0055_mybroker_corrections",
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

    assert observed == {"revision": "0055_mybroker_corrections"}
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
