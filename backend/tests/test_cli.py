from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from pydantic import ValidationError
from pytest import MonkeyPatch

from hermes_finance import cli


class StubEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


def test_cli_uses_environment_for_server(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    call: dict[str, object] = {}

    def capture_run(app: str, *, host: str, port: int, reload: bool) -> None:
        call.update(app=app, host=host, port=port, reload=reload)

    monkeypatch.setenv("HERMES_FINANCE_HOST", "127.0.0.1")
    monkeypatch.setenv("HERMES_FINANCE_PORT", "9001")
    monkeypatch.setenv("HERMES_FINANCE_RELOAD", "true")
    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(tmp_path / "server.db"))
    monkeypatch.setattr(uvicorn, "run", capture_run)
    monkeypatch.setattr(
        cli,
        "create_database",
        lambda _database_path: SimpleNamespace(engine=StubEngine()),
    )

    cli.main()

    assert call == {
        "app": "hermes_finance.main:app",
        "host": "127.0.0.1",
        "port": 9001,
        "reload": True,
    }


def test_cli_rejects_non_loopback_host(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_FINANCE_HOST", "0.0.0.0")

    with pytest.raises(ValidationError, match="loopback IP address"):
        cli.main()


def test_cli_initializes_configured_database(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    database_path = tmp_path / "local-data" / "configured.db"
    database_call: dict[str, Path] = {}
    engine = StubEngine()

    def capture_database(path: Path) -> SimpleNamespace:
        database_call["path"] = path
        return SimpleNamespace(engine=engine)

    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(database_path))
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "create_database", capture_database)

    cli.main()

    assert database_call == {"path": database_path}
    assert engine.dispose_calls == 1
