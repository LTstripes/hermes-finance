from pathlib import Path

from pydantic_settings import SettingsConfigDict
from pytest import MonkeyPatch

from hermes_finance.settings import ENV_FILE, REPOSITORY_ROOT, Settings


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


def test_t_invest_token_is_secret_and_empty_is_missing(monkeypatch: MonkeyPatch) -> None:
    settings = Settings(_env_file=None)
    assert settings.t_invest_read_only_token is None

    monkeypatch.setenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", "test-token")
    loaded = Settings(_env_file=None)
    assert loaded.t_invest_read_only_token is not None
    assert loaded.t_invest_read_only_token.get_secret_value() == "test-token"
    assert "test-token" not in repr(loaded)
    assert "test-token" not in str(loaded)

    monkeypatch.setenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", "   ")
    assert Settings(_env_file=None).t_invest_read_only_token is None


def test_frontend_dist_reads_prefixed_environment(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    frontend_dist = tmp_path / "synthetic-dist"
    monkeypatch.setenv("HERMES_FINANCE_FRONTEND_DIST", str(frontend_dist))

    settings = Settings(_env_file=None)

    assert settings.frontend_dist == frontend_dist


def test_default_env_file_is_repository_root_and_independent_of_cwd(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    assert ENV_FILE == REPOSITORY_ROOT / ".env"
    assert ENV_FILE.is_absolute()
    configured = Settings.model_config["env_file"]
    assert Path(configured) == ENV_FILE
    assert Path(configured).is_absolute()
    assert not str(configured).startswith(str(tmp_path))


def test_settings_reads_absolute_env_file_not_cwd_file(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    cwd = tmp_path / "backend"
    cwd.mkdir()
    (cwd / ".env").write_text("HERMES_FINANCE_PORT=8001\n", encoding="utf-8")
    root_env = tmp_path / ".env"
    root_env.write_text("HERMES_FINANCE_PORT=9002\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("HERMES_FINANCE_PORT", raising=False)
    monkeypatch.delenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", raising=False)

    class IsolatedSettings(Settings):
        model_config = SettingsConfigDict(
            env_prefix="HERMES_FINANCE_",
            env_file=root_env,
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )

    loaded = IsolatedSettings()
    assert loaded.port == 9002
    assert loaded.t_invest_read_only_token is None
