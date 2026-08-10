from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


def test_goals_api_crud_main_selection_and_restart_persistence(tmp_path: Path) -> None:
    database = create_database(tmp_path / "goals-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            initial = client.get("/api/goals")
            assert initial.status_code == 200
            assert len(initial.json()) == 1
            initial_goal = initial.json()[0]
            assert initial_goal["goal_type"] == "passive_income"
            assert initial_goal["is_main"] is True
            assert initial_goal["target_value"] == {"amount": "100000.00", "currency": "RUB"}

            created = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic Capital Goal",
                    "goal_type": "capital",
                    "target_value": {"amount": "2000000.00", "currency": "RUB"},
                    "target_date": "2031-01-01",
                    "calculation_mode": "capital_total",
                    "notes": "synthetic",
                },
            )
            assert created.status_code == 201
            created_goal = created.json()
            assert created_goal["is_main"] is False

            selected = client.patch(
                f"/api/goals/{initial_goal['id']}",
                json={"target_value": {"amount": "123456.78", "currency": "RUB"}},
            )
            assert selected.status_code == 200
            assert selected.json()["target_value"] == {
                "amount": "123456.78",
                "currency": "RUB",
            }

            created_passive = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic Passive Alternative",
                    "goal_type": "passive_income",
                    "target_value": {"amount": "150000.00", "currency": "RUB"},
                    "calculation_mode": "monthly_net_passive_income",
                },
            )
            assert created_passive.status_code == 201
            passive_goal_id = created_passive.json()["id"]

            selected = client.patch(f"/api/goals/{passive_goal_id}", json={"is_main": True})
            assert selected.status_code == 200
            assert selected.json()["is_main"] is True

            active_goals = client.get("/api/goals")
            assert active_goals.status_code == 200
            assert sum(goal["is_main"] for goal in active_goals.json()) == 1
            assert (
                next(goal for goal in active_goals.json() if goal["is_main"])["id"]
                == passive_goal_id
            )

            settings = client.get("/api/settings")
            assert settings.status_code == 200
            assert settings.json()["passive_income_goal"] == {
                "amount": "150000.00",
                "currency": "RUB",
            }

            deleted = client.delete(f"/api/goals/{created_goal['id']}")
            assert deleted.status_code == 204

            delete_main = client.delete(f"/api/goals/{passive_goal_id}")
            assert delete_main.status_code == 422
            deactivate_main = client.patch(
                f"/api/goals/{passive_goal_id}", json={"is_active": False}
            )
            assert deactivate_main.status_code == 422

        with TestClient(create_app(database)) as restarted_client:
            persisted = restarted_client.get("/api/goals")
            assert persisted.status_code == 200
            assert [goal["id"] for goal in persisted.json() if goal["is_main"]] == [passive_goal_id]
            assert restarted_client.get("/api/settings").json()["passive_income_goal"][
                "amount"
            ] == ("150000.00")
    finally:
        database.engine.dispose()


def test_goals_api_filters_inactive_and_rejects_invalid_payloads(tmp_path: Path) -> None:
    database = create_database(tmp_path / "goals-validation-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            inactive = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic Inactive",
                    "goal_type": "capital",
                    "target_value": {"amount": "1.00", "currency": "RUB"},
                    "calculation_mode": "capital_total",
                    "is_active": False,
                },
            )
            assert inactive.status_code == 201
            assert all(
                goal["id"] != inactive.json()["id"] for goal in client.get("/api/goals").json()
            )
            assert any(
                goal["id"] == inactive.json()["id"]
                for goal in client.get("/api/goals?include_inactive=true").json()
            )

            negative = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic Negative",
                    "goal_type": "capital",
                    "target_value": {"amount": "-1.00", "currency": "RUB"},
                    "calculation_mode": "capital_total",
                },
            )
            assert negative.status_code == 422

            unsupported_currency = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic USD",
                    "goal_type": "capital",
                    "target_value": {"amount": "1.00", "currency": "USD"},
                    "calculation_mode": "capital_total",
                },
            )
            assert unsupported_currency.status_code == 422

            unknown_field = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic Unknown",
                    "goal_type": "capital",
                    "target_value": {"amount": "1.00", "currency": "RUB"},
                    "calculation_mode": "capital_total",
                    "unsupported": True,
                },
            )
            assert unknown_field.status_code == 422
    finally:
        database.engine.dispose()
