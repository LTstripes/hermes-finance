from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


def test_settings_api_seeds_and_updates_the_singleton(tmp_path: Path) -> None:
    database = create_database(tmp_path / "settings.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            initial = client.get("/api/settings")
            assert initial.status_code == 200
            assert initial.json() == {
                "base_currency": "RUB",
                "locale": "ru-RU",
                "timezone": "Europe/Moscow",
                "passive_income_goal": {"amount": "100000.00", "currency": "RUB"},
                "formula_version": "v1",
                "passive_income_history_start_month": None,
            }

            updated = client.put(
                "/api/settings",
                json={
                    "passive_income_goal": {"amount": "123456.78", "currency": "RUB"},
                    "locale": "ru-RU",
                    "timezone": "Europe/Moscow",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["passive_income_goal"] == {
                "amount": "123456.78",
                "currency": "RUB",
            }

            persisted = client.get("/api/settings")
            assert persisted.json()["passive_income_goal"]["amount"] == "123456.78"

            configured = client.put(
                "/api/settings",
                json={"passive_income_history_start_month": "2031-05"},
            )
            assert configured.status_code == 200, configured.text
            assert configured.json()["passive_income_history_start_month"] == "2031-05"

            cleared = client.put(
                "/api/settings",
                json={"passive_income_history_start_month": None},
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["passive_income_history_start_month"] is None
    finally:
        database.engine.dispose()


def test_settings_api_rejects_invalid_money_and_currency(tmp_path: Path) -> None:
    database = create_database(tmp_path / "settings-validation.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            invalid_amount = client.put(
                "/api/settings",
                json={"passive_income_goal": {"amount": 100000.0, "currency": "RUB"}},
            )
            invalid_currency = client.put(
                "/api/settings",
                json={"passive_income_goal": {"amount": "100000.00", "currency": "USD"}},
            )
            negative_goal = client.put(
                "/api/settings",
                json={"passive_income_goal": {"amount": "-1.00", "currency": "RUB"}},
            )

        assert invalid_amount.status_code == 422
        assert invalid_currency.status_code == 422
        assert negative_goal.status_code == 422
    finally:
        database.engine.dispose()


def test_settings_api_rejects_unknown_fields(tmp_path: Path) -> None:
    database = create_database(tmp_path / "settings-extra.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            response = client.put("/api/settings", json={"unsupported": True})

        assert response.status_code == 422
    finally:
        database.engine.dispose()


def test_settings_api_rejects_invalid_passive_income_history_month(tmp_path: Path) -> None:
    database = create_database(tmp_path / "settings-history-validation.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            invalid_shape = client.put(
                "/api/settings",
                json={"passive_income_history_start_month": "2031-5"},
            )
            invalid_month = client.put(
                "/api/settings",
                json={"passive_income_history_start_month": "2031-13"},
            )

        assert invalid_shape.status_code == 422
        assert invalid_month.status_code == 422
    finally:
        database.engine.dispose()
