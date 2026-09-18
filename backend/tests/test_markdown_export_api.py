import json
from collections.abc import Generator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.database import Database, create_database
from hermes_finance.domain.cash_flows import ExpectedCashFlowType
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow


@pytest.fixture
def app_context(tmp_path: Path) -> Generator[tuple[TestClient, Database], None, None]:
    database = create_database(tmp_path / "markdown_export_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _create_month(client: TestClient) -> int:
    response = client.post(
        "/api/months",
        json={"year": 2032, "month": 7, "snapshot_date": "2032-07-31"},
    )
    assert response.status_code == 201, response.text
    month_id = response.json()["id"]
    opening_context = client.put(
        "/api/salary-tax/years/2032/opening-context",
        json={
            "effective_from_month": 7,
            "opening_taxable_gross": {"amount": "0.00", "currency": "RUB"},
        },
    )
    assert opening_context.status_code == 200, opening_context.text
    return month_id


def _table_counts(database: Database) -> dict[str, int]:
    with database.session_factory() as session:
        return {
            table.name: int(session.scalar(select(func.count()).select_from(table)) or 0)
            for table in Base.metadata.sorted_tables
        }


def test_markdown_export_downloads_stable_utf8_report_with_safe_filename(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    month_id = _create_month(client)
    assert (
        client.post(
            "/api/incomes",
            json={
                "reporting_month_id": month_id,
                "income_type": "salary",
                "name": "Синтетическая зарплата",
                "gross_amount": {"amount": "100000.00", "currency": "RUB"},
                "tax_amount": {"amount": "13000.00", "currency": "RUB"},
                "net_amount": {"amount": "87000.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/expenses",
            json={
                "reporting_month_id": month_id,
                "category": "Синтетическая аренда",
                "amount": {"amount": "20000.00", "currency": "RUB"},
                "expense_type": "mandatory",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/debts",
            json={
                "reporting_month_id": month_id,
                "debt_type": "credit_card",
                "name": "Синтетическая карта",
                "current_balance": {"amount": "5000.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/comments",
            json={"reporting_month_id": month_id, "text": "Синтетический комментарий"},
        ).status_code
        == 201
    )

    response = client.post(f"/api/months/{month_id}/export/markdown")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="finance_report_2032-07.md"'
    )
    body = response.content.decode("utf-8")
    assert body.startswith("# Финансовый отчёт — Июль 2032\n")
    assert "## 5. Доходы" in body
    assert "Синтетическая зарплата" in body
    assert "Синтетический комментарий" in body


def test_markdown_export_missing_month_uses_unified_not_found_error(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context

    response = client.post("/api/months/999999/export/markdown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == []


def test_markdown_export_does_not_persist_read_path_defaults(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    month_id = _create_month(client)
    before = _table_counts(database)

    response = client.post(f"/api/months/{month_id}/export/markdown")

    assert response.status_code == 200, response.text
    assert _table_counts(database) == before


def test_json_export_downloads_money_safe_raw_and_derived_data(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    month_id = _create_month(client)
    assert (
        client.post(
            "/api/incomes",
            json={
                "reporting_month_id": month_id,
                "income_type": "salary",
                "name": "Синтетическая зарплата",
                "gross_amount": {"amount": "100000.00", "currency": "RUB"},
                "tax_amount": {"amount": "13000.00", "currency": "RUB"},
                "net_amount": {"amount": "87000.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )

    response = client.post(f"/api/months/{month_id}/export/json")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="finance_data_2032-07.json"'
    )
    payload = json.loads(response.content.decode("utf-8"))
    assert payload["schema_version"] == "1.1"
    assert payload["calculation_version"] == "v2"
    assert payload["raw"]["reporting_month"]["id"] == month_id
    assert payload["raw"]["income_entries"][0]["gross_amount"] == {
        "amount": "100000.00",
        "currency": "RUB",
    }
    assert payload["raw"]["app_settings"]["passive_income_goal"] == {
        "amount": "100000.00",
        "currency": "RUB",
    }
    assert payload["raw"]["tax_brackets"][0]["threshold_from"] == {
        "amount": "0.00",
        "currency": "RUB",
    }
    assert payload["raw"]["tax_brackets"][0]["rate"] == "13.00"
    assert payload["derived"]["dashboard"]["summary"]["salary_tax"]["parts"][0]["from_kopecks"] == {
        "amount": "0.00",
        "currency": "RUB",
    }
    assert payload["derived"]["dashboard"]["summary"]["salary_actual_net"]["currency"] == "RUB"

    def assert_no_binary_float(value: object) -> None:
        if isinstance(value, float):
            raise AssertionError("JSON export must not contain binary float values")
        if isinstance(value, dict):
            for item in value.values():
                assert_no_binary_float(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_binary_float(item)

    assert_no_binary_float(payload)


def test_json_export_missing_month_uses_unified_not_found_error(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context

    response = client.post("/api/months/999999/export/json")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == []


def test_json_export_does_not_mutate_persistence(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    month_id = _create_month(client)
    before = _table_counts(database)

    response = client.post(f"/api/months/{month_id}/export/json")

    assert response.status_code == 200, response.text
    assert _table_counts(database) == before


def test_exports_preserve_selected_main_goal_and_mark_progress_only_on_main(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    month_id = _create_month(client)

    initial = client.get("/api/goals")
    assert initial.status_code == 200, initial.text
    initial_goal = initial.json()[0]
    alternative = client.post(
        "/api/goals",
        json={
            "name": "Synthetic Passive Alternative",
            "goal_type": "passive_income",
            "target_value": {"amount": "200000.00", "currency": "RUB"},
            "calculation_mode": "monthly_net_passive_income",
        },
    )
    assert alternative.status_code == 201, alternative.text
    selected = client.patch(f"/api/goals/{alternative.json()['id']}", json={"is_main": True})
    assert selected.status_code == 200, selected.text

    json_response = client.post(f"/api/months/{month_id}/export/json")
    assert json_response.status_code == 200, json_response.text
    json_payload = json.loads(json_response.content.decode("utf-8"))
    raw_goals = {goal["id"]: goal for goal in json_payload["raw"]["goals"]}
    assert raw_goals[initial_goal["id"]]["is_main"] is False
    assert raw_goals[alternative.json()["id"]]["is_main"] is True
    assert json_payload["raw"]["app_settings"]["passive_income_goal"] == {
        "amount": "200000.00",
        "currency": "RUB",
    }

    markdown_response = client.post(f"/api/months/{month_id}/export/markdown")
    assert markdown_response.status_code == 200, markdown_response.text
    markdown_lines = markdown_response.content.decode("utf-8").splitlines()
    main_line = next(line for line in markdown_lines if "Synthetic Passive Alternative" in line)
    non_main_line = next(line for line in markdown_lines if initial_goal["name"] in line)
    assert "0,00%" in main_line
    assert "—" in non_main_line


def test_legacy_exports_use_actual_passive_goal_progress_not_forecast_coverage(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    historical = client.post(
        "/api/months",
        json={"year": 2032, "month": 1, "snapshot_date": "2032-01-31"},
    )
    assert historical.status_code == 201, historical.text
    historical_id = historical.json()["id"]
    account = client.post(
        "/api/accounts", json={"name": "Synthetic broker", "account_type": "brokerage"}
    )
    assert account.status_code == 201, account.text
    instrument = client.post(
        "/api/instruments", json={"name": "Synthetic stock", "instrument_type": "stock"}
    )
    assert instrument.status_code == 201, instrument.text
    flow = client.post(
        "/api/investment-flows",
        json={
            "reporting_month_id": historical_id,
            "account_id": account.json()["id"],
            "instrument_id": instrument.json()["id"],
            "flow_type": "dividend",
            "event_date": "2032-01-15",
            "gross_amount": {"amount": "1000.00", "currency": "RUB"},
            "tax_amount": {"amount": "0.00", "currency": "RUB"},
            "commission_amount": {"amount": "0.00", "currency": "RUB"},
            "net_amount": {"amount": "1000.00", "currency": "RUB"},
            "source": "synthetic",
        },
    )
    assert flow.status_code == 201, flow.text
    close = client.post(f"/api/months/{historical_id}/close")
    assert close.status_code == 200, close.text

    month_id = _create_month(client)
    with database.session_factory() as session:
        create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account.json()["id"],
            instrument_id=instrument.json()["id"],
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2032, 8, 1),
            gross_amount="1200.00",
            expected_tax_amount="0.00",
            expected_net_amount="1200.00",
            source="synthetic",
            source_as_of_date=date(2032, 7, 31),
            forecast_version="v1",
        )
    dashboard = client.get(f"/api/months/{month_id}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    dashboard_payload = dashboard.json()
    assert dashboard_payload["kpis"]["goal_progress_pct"] == "1.00"
    assert dashboard_payload["kpis"]["forecast_goal_progress_pct"] == "1.10"
    assert dashboard_payload["summary"]["coverage"]["goal_progress_pct"] == "1.00"
    assert dashboard_payload["summary"]["coverage"]["forecast_goal_progress_pct"] == "1.10"

    markdown = client.post(f"/api/months/{month_id}/export/markdown")
    assert markdown.status_code == 200, markdown.text
    main_line = next(
        line
        for line in markdown.content.decode("utf-8").splitlines()
        if "Пассивный доход в месяц" in line
    )
    # One actual 1,000 RUB closed-month average against the 100,000 RUB goal
    # is 1.00%; forecast coverage is a separate metric and has no rows here.
    assert "1,00%" in main_line

    exported = client.post(f"/api/months/{month_id}/export/json")
    assert exported.status_code == 200, exported.text
    payload = exported.json()
    goal_rows = payload["derived"]["report"]["goal_rows"]
    main_row = next(row for row in goal_rows if row["name"] == "Пассивный доход в месяц")
    assert main_row["progress_pct"] == "1.00"
