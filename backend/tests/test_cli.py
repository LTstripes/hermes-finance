from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from pydantic import ValidationError
from pytest import MonkeyPatch

from hermes_finance import cli


@pytest.fixture(autouse=True)
def standard_cli_arguments(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["hermes-finance-api"])


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


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "::1"])
def test_cli_rejects_noncanonical_host(monkeypatch: MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("HERMES_FINANCE_HOST", host)

    with pytest.raises(ValidationError, match="host must be exactly 127.0.0.1"):
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


@pytest.fixture(scope="module")
def migrated_reg_isin_template(tmp_path_factory):
    from _migration_helpers import run_alembic

    path = tmp_path_factory.mktemp("synthetic-reg-isin-cli") / "template.db"
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    return path


@pytest.fixture
def reg_isin_database(migrated_reg_isin_template, tmp_path, monkeypatch):
    from shutil import copyfile

    path = tmp_path / "selected-synthetic.db"
    copyfile(migrated_reg_isin_template, path)
    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(path))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("mapping CLI must not migrate or start the server")

    monkeypatch.setattr(cli, "upgrade_database", forbidden)
    monkeypatch.setattr(uvicorn, "run", forbidden)
    return path


def test_reg_isin_cli_selected_database_import_list_set_relink_remove(
    reg_isin_database, tmp_path, capsys
):
    import json
    import sqlite3

    path = tmp_path / "invented-crosswalk.csv"
    path.write_text(
        "reg_number,isin,note\n1-01-99999-z,zz0000000011,Synthetic CLI seed\n",
        encoding="utf-8-sig",
    )
    cli.main(["reg-isin", "import", str(path)])
    assert json.loads(capsys.readouterr().out) == {"processed": 1, "changed": 1}
    cli.main(["reg-isin", "import", str(path)])
    assert json.loads(capsys.readouterr().out) == {"processed": 1, "changed": 0}
    cli.main(["reg-isin", "list"])
    row = json.loads(capsys.readouterr().out)[0]
    assert (row["reg_number"], row["isin"], row["note"]) == (
        "1-01-99999-Z",
        "ZZ0000000011",
        "Synthetic CLI seed",
    )
    cli.main(["reg-isin", "set", "1-01-99999-z", "ZZ0000000022", "--note", "Synthetic update"])
    assert json.loads(capsys.readouterr().out)["id"] == row["id"]
    with sqlite3.connect(reg_isin_database) as connection:
        assert connection.execute("SELECT isin FROM security_reg_isin_mappings").fetchone() == (
            "ZZ0000000022",
        )
    cli.main(["reg-isin", "relink"])
    assert json.loads(capsys.readouterr().out) == {
        "processed": 0,
        "changed": 0,
        "skipped_closed": 0,
    }
    cli.main(["reg-isin", "remove", "1-01-99999-z"])
    assert json.loads(capsys.readouterr().out) == {"removed": True}
    cli.main(["reg-isin", "list"])
    assert json.loads(capsys.readouterr().out) == []


def test_reg_isin_cli_invalid_import_is_atomic(reg_isin_database, tmp_path, capsys):
    import sqlite3

    path = tmp_path / "invalid-crosswalk.csv"
    path.write_text(
        "reg_number,isin,note\n1-01-99999-Z,ZZ0000000011,\n4B02-09-99999-Z-001P,invalid,\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as error:
        cli.main(["reg-isin", "import", str(path)])
    assert error.value.code == 2
    assert "isin_invalid: row 3" in capsys.readouterr().err
    with sqlite3.connect(reg_isin_database) as connection:
        assert connection.execute("SELECT * FROM security_reg_isin_mappings").fetchall() == []


def test_reg_isin_cli_requires_explicit_existing_path(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("HERMES_FINANCE_DATABASE_PATH", raising=False)
    with pytest.raises(SystemExit) as error:
        cli.main(["reg-isin", "list"])
    assert error.value.code == 2
    assert "HERMES_FINANCE_DATABASE_PATH is required" in capsys.readouterr().err
    missing = tmp_path / "missing.db"
    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(missing))
    with pytest.raises(SystemExit):
        cli.main(["reg-isin", "set", "1-01-99999-Z", "ZZ0000000011"])
    assert "reg_isin_database_not_found" in capsys.readouterr().err
    assert not missing.exists()


def test_reg_isin_cli_rejects_old_schema_without_migrating(reg_isin_database, capsys):
    from _migration_helpers import revision_rows, run_alembic

    result = run_alembic(reg_isin_database, "downgrade", "0061_money_instrument_links")
    assert result.returncode == 0, result.stderr
    with pytest.raises(SystemExit) as error:
        cli.main(["reg-isin", "list"])
    assert error.value.code == 2
    assert "reg_isin_database_not_current" in capsys.readouterr().err
    assert revision_rows(reg_isin_database) == ["0061_money_instrument_links"]
