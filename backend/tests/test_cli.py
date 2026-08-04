import uvicorn
from pytest import MonkeyPatch


def test_cli_uses_environment_for_server(monkeypatch: MonkeyPatch) -> None:
    call: dict[str, object] = {}

    def capture_run(app: str, *, host: str, port: int, reload: bool) -> None:
        call.update(app=app, host=host, port=port, reload=reload)

    monkeypatch.setenv("HERMES_FINANCE_HOST", "0.0.0.0")
    monkeypatch.setenv("HERMES_FINANCE_PORT", "9001")
    monkeypatch.setenv("HERMES_FINANCE_RELOAD", "true")
    monkeypatch.setattr(uvicorn, "run", capture_run)

    from hermes_finance.cli import main

    main()

    assert call == {
        "app": "hermes_finance.main:app",
        "host": "0.0.0.0",
        "port": 9001,
        "reload": True,
    }
