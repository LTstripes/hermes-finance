from pytest import MonkeyPatch

from hermes_finance.settings import Settings


def test_server_defaults_to_loopback() -> None:
    settings = Settings()

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000


def test_settings_read_prefixed_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("HERMES_FINANCE_HOST", "0.0.0.0")
    monkeypatch.setenv("HERMES_FINANCE_PORT", "9001")

    settings = Settings()

    assert settings.host == "0.0.0.0"
    assert settings.port == 9001
