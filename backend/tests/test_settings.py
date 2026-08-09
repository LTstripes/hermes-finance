from pathlib import Path

from pytest import MonkeyPatch

from hermes_finance.settings import Settings


def test_server_defaults_to_loopback() -> None:
    settings = Settings(_env_file=None)

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_settings_read_prefixed_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_FINANCE_HOST", "0.0.0.0")
    monkeypatch.setenv("HERMES_FINANCE_PORT", "9001")

    settings = Settings(_env_file=None)

    assert settings.host == "0.0.0.0"
    assert settings.port == 9001


def test_database_defaults_to_repository_data_directory() -> None:
    settings = Settings(_env_file=None)

    repository_root = Path(__file__).resolve().parents[2]
    assert settings.database_path == repository_root / "data" / "finance.db"


def test_frontend_dist_defaults_to_repository_build_directory() -> None:
    settings = Settings(_env_file=None)

    repository_root = Path(__file__).resolve().parents[2]
    assert settings.frontend_dist == repository_root / "frontend" / "dist"


def test_database_path_reads_prefixed_environment(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    database_path = tmp_path / "synthetic-finance.db"
    monkeypatch.setenv("HERMES_FINANCE_DATABASE_PATH", str(database_path))

    settings = Settings(_env_file=None)

    assert settings.database_path == database_path


def test_frontend_dist_reads_prefixed_environment(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    frontend_dist = tmp_path / "synthetic-dist"
    monkeypatch.setenv("HERMES_FINANCE_FRONTEND_DIST", str(frontend_dist))

    settings = Settings(_env_file=None)

    assert settings.frontend_dist == frontend_dist
