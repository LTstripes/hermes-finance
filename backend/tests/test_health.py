from fastapi.testclient import TestClient

from hermes_finance.main import app


def test_health_returns_status_and_version() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.7.0"}
