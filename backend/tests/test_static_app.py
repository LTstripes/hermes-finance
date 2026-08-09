from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.main import create_app


def test_production_app_serves_frontend_assets_and_spa_routes(tmp_path: Path) -> None:
    static_dir = tmp_path / "dist"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        "<!doctype html><title>Hermes Finance</title><div id='root'></div>",
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("console.log('synthetic');", encoding="utf-8")

    with TestClient(create_app(static_dir=static_dir)) as client:
        root = client.get("/")
        asset = client.get("/assets/app.js")
        spa_route = client.get("/months/synthetic")
        health = client.get("/api/health")
        unknown_api = client.get("/api/not-a-route")

    assert root.status_code == 200
    assert "Hermes Finance" in root.text
    assert asset.status_code == 200
    assert asset.text == "console.log('synthetic');"
    assert spa_route.status_code == 200
    assert "Hermes Finance" in spa_route.text
    assert health.status_code == 200
    assert unknown_api.status_code == 404


def test_production_app_without_build_returns_not_found(tmp_path: Path) -> None:
    with TestClient(create_app(static_dir=tmp_path / "missing-dist")) as client:
        response = client.get("/")

    assert response.status_code == 404
