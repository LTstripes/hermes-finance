from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


@pytest.mark.parametrize(
    "branch", ["complete", "partial", "base_unavailable", "unsupported", "income_estimate"]
)
def test_plan_parameter_validation_precedes_source_and_goal_branches(tmp_path, branch):
    from decimal import Decimal
    from itertools import product
    from unittest.mock import patch

    from hermes_finance.domain.portfolio_source_coverage import PortfolioSourceCoverage
    from hermes_finance.services.goal_plan import build_goal_plan

    database = create_database(tmp_path / "plan-validation.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            month = client.post(
                "/api/months", json={"year": 2032, "month": 1, "snapshot_date": "2032-01-15"}
            ).json()
            passive = branch == "income_estimate"
            goal = client.post(
                "/api/goals",
                json={
                    "name": "Synthetic validation goal",
                    "goal_type": "passive_income" if passive else "capital",
                    "calculation_mode": "monthly_net_passive_income"
                    if passive
                    else "liquid_capital_net",
                    "target_value": {"amount": "1000.01", "currency": "RUB"},
                    "target_date": "2032-04-01",
                    "is_active": branch != "unsupported",
                },
            ).json()
            url = f"/api/goals/{goal['id']}/plan"
            rates = [
                None,
                "0",
                "15",
                "100",
                "-1",
                "101",
                "NaN",
                "sNaN",
                "Infinity",
                "-Infinity",
                "invalid",
            ]
            payments = [
                None,
                "0",
                "12.34",
                "1000000000000000",
                "-1",
                "NaN",
                "Infinity",
                "0.001",
                "1000000000000000.01",
                "invalid",
            ]
            invalid_rates = set(rates[4:])
            invalid_payments = set(payments[4:])
            coverage = (
                "unavailable"
                if branch == "base_unavailable"
                else "partial"
                if branch == "partial"
                else "complete"
            )
            with patch(
                "hermes_finance.services.goal_plan.portfolio_source_coverage_for_month",
                return_value=PortfolioSourceCoverage(coverage),
            ):
                for rate, payment in product(rates, payments):
                    params = {"reporting_month_id": month["id"]}
                    if rate is not None:
                        params["annual_rate_pct"] = rate
                    if payment is not None:
                        params["monthly_contribution"] = payment
                    response = client.get(url, params=params)
                    invalid = rate in invalid_rates or payment in invalid_payments
                    assert response.status_code == (422 if invalid else 200), (
                        params,
                        response.text,
                    )
                    if not invalid:
                        expected = (
                            branch
                            if branch in {"base_unavailable", "unsupported", "income_estimate"}
                            else "contribution_missing"
                            if payment is None
                            else "not_reached"
                            if payment == "0"
                            else "projected"
                        )
                        assert response.json()["status"] == expected, params
                        if branch == "unsupported":
                            assert response.json() == {
                                "method_version": "goal_plan_v1",
                                "status": "unsupported",
                            }
                # Direct service consumers must get the same validation as HTTP callers.
                with database.session_factory() as session:
                    for rate in ("-1", "101", "NaN", "Infinity", "-Infinity"):
                        with pytest.raises(ValueError, match="Годовая доходность"):
                            build_goal_plan(
                                session,
                                goal["id"],
                                month["id"],
                                contribution=None,
                                annual_rate=Decimal(rate),
                            )
                    for payment in (-1, 10**17 + 1):
                        with pytest.raises(ValueError, match="Взнос"):
                            build_goal_plan(session, goal["id"], month["id"], contribution=payment)
    finally:
        database.engine.dispose()


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


def test_plan_read_only_states_and_estimate(tmp_path):
    from decimal import Decimal
    from types import SimpleNamespace
    from unittest.mock import patch

    from sqlalchemy import event

    database = create_database(tmp_path / "plan.db")
    Base.metadata.create_all(database.engine)
    with TestClient(create_app(database)) as client:
        month = client.post(
            "/api/months", json={"year": 2032, "month": 1, "snapshot_date": "2032-01-15"}
        ).json()
        goal = client.post(
            "/api/goals",
            json={
                "name": "Synthetic capital",
                "goal_type": "capital",
                "calculation_mode": "liquid_capital_net",
                "target_value": {"amount": "1000.01", "currency": "RUB"},
                "target_date": "2032-04-01",
            },
        ).json()
        statements = []

        @event.listens_for(database.engine, "before_cursor_execute")
        def record(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        url = f"/api/goals/{goal['id']}/plan?reporting_month_id={month['id']}"
        assert client.get(url).json()["status"] == "base_unavailable"
        from hermes_finance.domain import RubleAmount
        from hermes_finance.domain.portfolio_source_coverage import PortfolioSourceCoverage

        with patch(
            "hermes_finance.services.goal_plan.portfolio_source_coverage_for_month",
            return_value=PortfolioSourceCoverage("partial"),
        ):
            result = client.get(url + "&monthly_contribution=100&annual_rate_pct=15")
            assert result.status_code == 200, result.text
            assert result.json()["coverage"] == "partial"
            assert result.json()["required_contribution"] is not None
            assert client.get(url).json()["status"] == "contribution_missing"
            for value in ("-1", "NaN", "Infinity", "0.001"):
                assert client.get(url + "&monthly_contribution=" + value).status_code == 422
            for value in ("-1", "NaN", "101"):
                assert client.get(url + "&annual_rate_pct=" + value).status_code == 422
        assert not any(
            s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
            for s in statements
        )
        event.remove(database.engine, "before_cursor_execute", record)
        passive = client.post(
            "/api/goals",
            json={
                "name": "Synthetic income",
                "goal_type": "passive_income",
                "calculation_mode": "monthly_net_passive_income",
                "target_value": {"amount": "200", "currency": "RUB"},
            },
        ).json()
        with (
            patch(
                "hermes_finance.services.goal_plan.portfolio_source_coverage_for_month",
                return_value=PortfolioSourceCoverage("complete"),
            ),
            patch(
                "hermes_finance.services.goal_plan.liquid_capital_for_month",
                return_value=SimpleNamespace(
                    liquid_capital_net=RubleAmount(100000),
                    total_assets=RubleAmount(100000),
                    total_debts_included=RubleAmount(0),
                ),
            ),
            patch(
                "hermes_finance.services.goal_plan.passive_income_average",
                return_value=SimpleNamespace(
                    average=RubleAmount(1000),
                    count_months=3,
                    months_used=("2031-10", "2031-11", "2031-12"),
                    is_complete_12m=False,
                ),
            ),
        ):
            result = client.get(
                f"/api/goals/{passive['id']}/plan?reporting_month_id={month['id']}"
            ).json()
            assert Decimal(result["required_capital"]) == Decimal("20000")
            assert result["income_months_count"] == 3
            assert result["income_months_complete"] is False
    database.engine.dispose()
