from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.main import create_app


def _app_without_frontend(tmp_path: Path):
    application = create_app(static_dir=tmp_path / "missing-frontend")

    @application.post("/api/security-probe")
    async def security_probe() -> dict[str, str]:
        return {"status": "ok"}

    return application


def test_foreign_host_is_rejected_for_read_requests(tmp_path: Path) -> None:
    client = TestClient(_app_without_frontend(tmp_path))

    response = client.get("/api/health", headers={"host": "finance.attacker.example"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_local_hosts_remain_available(tmp_path: Path) -> None:
    application = _app_without_frontend(tmp_path)

    with TestClient(application, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/health").status_code == 200

    with TestClient(application, base_url="http://localhost:8000") as client:
        assert client.get("/api/health").status_code == 200


def test_foreign_origin_is_rejected_for_state_changing_requests(tmp_path: Path) -> None:
    client = TestClient(
        _app_without_frontend(tmp_path),
        base_url="http://127.0.0.1:8000",
    )

    response = client.post(
        "/api/security-probe",
        headers={"origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_same_origin_write_is_allowed(tmp_path: Path) -> None:
    client = TestClient(
        _app_without_frontend(tmp_path),
        base_url="http://127.0.0.1:8000",
    )

    response = client.post(
        "/api/security-probe",
        headers={"origin": "http://127.0.0.1:8000"},
    )

    assert response.status_code == 200


def test_vite_proxy_origin_is_allowed(tmp_path: Path) -> None:
    client = TestClient(
        _app_without_frontend(tmp_path),
        base_url="http://127.0.0.1:5173",
    )

    response = client.post(
        "/api/security-probe",
        headers={"origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200


def test_originless_local_api_write_remains_available(tmp_path: Path) -> None:
    client = TestClient(
        _app_without_frontend(tmp_path),
        base_url="http://127.0.0.1:8000",
    )

    response = client.post("/api/security-probe")

    assert response.status_code == 200
