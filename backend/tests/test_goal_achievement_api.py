from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


def test_goals_summary_static_route_returns_backend_decimal_dto_and_filters_inactive(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "goal-summary-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            month = client.post(
                "/api/months",
                json={"year": 2030, "month": 5, "snapshot_date": "2030-05-12"},
            )
            assert month.status_code == 201, month.text
            month_id = month.json()["id"]

            active = client.post(
                "/api/goals",
                json={
                    "name": "Summary Capital",
                    "goal_type": "capital",
                    "target_value": {"amount": "123.45", "currency": "RUB"},
                    "calculation_mode": "liquid_capital_net",
                },
            )
            assert active.status_code == 201, active.text
            inactive = client.post(
                "/api/goals",
                json={
                    "name": "Summary Inactive",
                    "goal_type": "capital",
                    "target_value": {"amount": "1.00", "currency": "RUB"},
                    "calculation_mode": "liquid_capital_net",
                    "is_active": False,
                },
            )
            assert inactive.status_code == 201, inactive.text

            response = client.get(f"/api/goals/summary?reporting_month_id={month_id}")
            assert response.status_code == 200, response.text
            body = response.json()
            assert all(item["id"] != inactive.json()["id"] for item in body)
            assert body
            first = body[0]
            forecast = first["achievement_forecast"]
            assert first["target_value"]["currency"] == "RUB"
            assert isinstance(first["target_value"]["amount"], str)
            assert forecast["reporting_month_id"] == month_id
            assert forecast["as_of_date"] == "2030-05-12"
            assert forecast["method_version"] == "goal_achievement_v1"
            assert forecast["target_value"]["amount"] == first["target_value"]["amount"]
            assert isinstance(forecast["progress_pct"], str)
            assert forecast["progress_pct"] == "0.00"
            assert forecast["remaining_amount"]["amount"] == first["target_value"]["amount"]

            included = client.get(
                f"/api/goals/summary?reporting_month_id={month_id}&include_inactive=true"
            )
            assert included.status_code == 200, included.text
            inactive_result = next(
                item for item in included.json() if item["id"] == inactive.json()["id"]
            )
            assert inactive_result["achievement_forecast"]["status"] == "inactive"
            assert inactive_result["achievement_forecast"]["current_value"] is None
            assert inactive_result["achievement_forecast"]["estimated_achievement_date"] is None
    finally:
        database.engine.dispose()


def test_goals_summary_requires_reporting_month_without_dynamic_goal_id_validation(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "goal-summary-route.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            response = client.get("/api/goals/summary")
            assert response.status_code == 422
            assert "reporting_month_id" in response.text
            assert "goal_id" not in response.text
    finally:
        database.engine.dispose()
