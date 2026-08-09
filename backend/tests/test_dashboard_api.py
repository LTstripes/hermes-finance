"""API tests for month summary and dashboard (D07)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "d07_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _seed_two_months(client: TestClient) -> tuple[int, int]:
    m1 = client.post(
        "/api/months",
        json={"year": 2031, "month": 1, "snapshot_date": "2031-01-31"},
    )
    assert m1.status_code == 201, m1.text
    m1_id = m1.json()["id"]

    account = client.post(
        "/api/accounts", json={"name": "Брокер", "account_type": "brokerage"}
    ).json()
    instrument = client.post(
        "/api/instruments", json={"name": "ОФЗ", "instrument_type": "bond"}
    ).json()

    client.post(
        "/api/positions",
        json={
            "reporting_month_id": m1_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "10",
            "average_cost_per_unit": _rub("1000.00"),
            "market_price_per_unit": _rub("1100.00"),
            "price_source": "manual",
            "price_date": "2031-01-31",
        },
    )
    client.post(
        "/api/deposits",
        json={
            "reporting_month_id": m1_id,
            "account_id": account["id"],
            "name": "Вклад",
            "deposit_type": "deposit",
            "balance": _rub("100000.00"),
            "annual_rate": "12.00",
            "actual_interest_received": _rub("1000.00"),
        },
    )
    client.post(
        "/api/expenses",
        json={
            "reporting_month_id": m1_id,
            "category": "ЖКХ",
            "amount": _rub("20000.00"),
            "expense_type": "mandatory",
        },
    )
    client.post(
        "/api/properties",
        json={
            "reporting_month_id": m1_id,
            "name": "Квартира",
            "estimated_value": _rub("10000000.00"),
            "mortgage_balance": _rub("4000000.00"),
            "monthly_payment": _rub("50000.00"),
        },
    )
    client.post(
        "/api/investment-flows",
        json={
            "reporting_month_id": m1_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "flow_type": "coupon",
            "event_date": "2031-01-15",
            "gross_amount": _rub("1000.00"),
            "tax_amount": _rub("130.00"),
            "commission_amount": _rub("0.00"),
            "net_amount": _rub("870.00"),
            "source": "manual",
        },
    )
    client.post(f"/api/months/{m1_id}/close")

    # clone into February so historical series has 2 points
    m2 = client.post(
        f"/api/months/{m1_id}/clone",
        json={"year": 2031, "month": 2, "snapshot_date": "2031-02-28"},
    )
    assert m2.status_code == 201, m2.text
    m2_id = m2.json()["id"]

    client.post(
        "/api/expected-flows",
        json={
            "reporting_month_id": m2_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "flow_type": "coupon",
            "expected_date": "2031-03-15",
            "gross_amount": _rub("1000.00"),
            "expected_tax_amount": _rub("130.00"),
            "expected_net_amount": _rub("870.00"),
            "source": "manual",
            "source_as_of_date": "2031-02-28",
            "forecast_version": "v1",
        },
    )
    return m1_id, m2_id


def test_summary_and_dashboard_happy_path(client: TestClient) -> None:
    _m1_id, m2_id = _seed_two_months(client)

    summary = client.get(f"/api/months/{m2_id}/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["month"]["id"] == m2_id
    assert body["month"]["year"] == 2031
    assert body["month"]["month"] == 2
    assert body["calculation_version"] == "v1"
    assert "liquid_capital_net" in body["liquid_capital"]
    assert body["liquid_capital"]["breakdown"]["securities"]["currency"] == "RUB"
    assert body["liquid_capital_delta"] is not None
    assert body["passive_income_delta"] is not None
    assert isinstance(body["warnings"], list)
    assert isinstance(body["iis"], list)

    dashboard = client.get(f"/api/months/{m2_id}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    dash = dashboard.json()
    assert dash["month"]["id"] == m2_id
    assert set(dash["kpis"]) >= {
        "liquid_capital_net",
        "liquid_capital_delta",
        "forecast_monthly_passive_income",
        "passive_income_average",
        "goal_progress_pct",
        "mandatory_expenses",
        "mandatory_expense_coverage_pct",
        "mortgage_balance",
        "mortgage_coverage_pct",
    }
    assert dash["kpis"]["mandatory_expenses"] == _rub("20000.00")
    assert dash["kpis"]["mortgage_balance"] == _rub("4000000.00")
    # historical series covers closed months only; the February clone is a draft
    assert len(dash["historical_series"]) == 1
    assert dash["historical_series"][0]["month"] == 1
    assert dash["historical_series"][0]["year"] == 2031
    assert dash["historical_series"][0]["reporting_month_id"] == _m1_id
    assert dash["historical_series"][0]["liquid_capital_net"] == _rub("111000.00")
    classes = {item["asset_class"] for item in dash["asset_allocation"]}
    assert classes == {"cash", "deposits", "securities", "other_liquid_assets"}
    assert any(item["instrument_type"] == "bond" for item in dash["result_by_instrument_class"])
    assert len(dash["expected_payments"]) == 1
    assert dash["expected_payments"][0]["expected_net_amount"] == _rub("870.00")
    assert dash["mortgage"]["mortgage_balance"] == _rub("4000000.00")
    assert dash["calculation_version"] == "v1"


def test_historical_series_grows_when_draft_closes(client: TestClient) -> None:
    _m1_id, m2_id = _seed_two_months(client)

    draft_dash = client.get(f"/api/months/{m2_id}/dashboard")
    assert draft_dash.status_code == 200, draft_dash.text
    # February clone is still a draft: only the closed January point qualifies
    assert [p["month"] for p in draft_dash.json()["historical_series"]] == [1]

    close = client.post(f"/api/months/{m2_id}/close")
    assert close.status_code == 200, close.text

    closed_dash = client.get(f"/api/months/{m2_id}/dashboard")
    assert closed_dash.status_code == 200, closed_dash.text
    series = closed_dash.json()["historical_series"]
    assert [(p["year"], p["month"]) for p in series] == [(2031, 1), (2031, 2)]


def test_summary_missing_month_is_404(client: TestClient) -> None:
    response = client.get("/api/months/99999/summary")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_dashboard_first_month_has_null_deltas(client: TestClient) -> None:
    month = client.post(
        "/api/months",
        json={"year": 2031, "month": 5, "snapshot_date": "2031-05-31"},
    )
    month_id = month.json()["id"]
    dash = client.get(f"/api/months/{month_id}/dashboard")
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["kpis"]["liquid_capital_delta"] is None
    assert body["summary"]["passive_income_delta"] is None
    assert any("предыдущего месяца" in w for w in body["warnings"])
