"""API tests for R03-12 capital composition history."""

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
    database = create_database(tmp_path / "capital_composition.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _create_month(client: TestClient, *, year: int, month: int, snapshot_date: str) -> int:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": snapshot_date},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_position(
    client: TestClient,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    amount: str,
    price_date: str,
) -> None:
    response = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "1",
            "average_cost_per_unit": _rub("1.00"),
            "market_price_per_unit": _rub(amount),
            "price_source": "manual",
            "price_date": price_date,
        },
    )
    assert response.status_code == 201, response.text


def _create_cash(client: TestClient, month_id: int, amount: str) -> None:
    response = client.post(
        "/api/cash-balances",
        json={
            "reporting_month_id": month_id,
            "name": f"Cash {month_id}",
            "amount": _rub(amount),
        },
    )
    assert response.status_code == 201, response.text


def _create_deposit(client: TestClient, month_id: int, account_id: int, amount: str) -> None:
    response = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "name": f"Deposit {month_id}",
            "deposit_type": "deposit",
            "balance": _rub(amount),
            "annual_rate": "0.00",
            "actual_interest_received": _rub("0.00"),
        },
    )
    assert response.status_code == 201, response.text


def _create_debt(client: TestClient, month_id: int, amount: str) -> None:
    response = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": f"Debt {month_id}",
            "current_balance": _rub(amount),
            "include_in_liquid_capital": True,
        },
    )
    assert response.status_code == 201, response.text


def test_capital_composition_closed_history_gap_and_known_zero(client: TestClient) -> None:
    account = client.post(
        "/api/accounts",
        json={"name": "Synthetic brokerage", "account_type": "brokerage"},
    ).json()
    bond = client.post(
        "/api/instruments",
        json={"name": "Synthetic bond", "instrument_type": "bond"},
    ).json()
    stock = client.post(
        "/api/instruments",
        json={"name": "Synthetic stock", "instrument_type": "stock"},
    ).json()
    gold = client.post(
        "/api/instruments",
        json={"name": "Synthetic gold", "instrument_type": "gold"},
    ).json()

    may_id = _create_month(client, year=2031, month=5, snapshot_date="2031-05-31")
    _create_cash(client, may_id, "100000.00")
    _create_deposit(client, may_id, account["id"], "400000.00")
    _create_position(
        client,
        month_id=may_id,
        account_id=account["id"],
        instrument_id=stock["id"],
        amount="300000.00",
        price_date="2031-05-31",
    )
    _create_position(
        client,
        month_id=may_id,
        account_id=account["id"],
        instrument_id=bond["id"],
        amount="700000.00",
        price_date="2031-05-31",
    )
    _create_position(
        client,
        month_id=may_id,
        account_id=account["id"],
        instrument_id=gold["id"],
        amount="200000.00",
        price_date="2031-05-31",
    )
    _create_debt(client, may_id, "100000.00")
    close_may = client.post(f"/api/months/{may_id}/close")
    assert close_may.status_code == 200, close_may.text

    june_id = _create_month(client, year=2031, month=6, snapshot_date="2031-06-30")
    _create_cash(client, june_id, "999999.00")
    # June intentionally remains DRAFT and must not become a historical zero or point.

    july_id = _create_month(client, year=2031, month=7, snapshot_date="2031-07-31")
    _create_cash(client, july_id, "120000.00")
    _create_deposit(client, july_id, account["id"], "450000.00")
    _create_position(
        client,
        month_id=july_id,
        account_id=account["id"],
        instrument_id=bond["id"],
        amount="800000.00",
        price_date="2031-07-31",
    )
    _create_position(
        client,
        month_id=july_id,
        account_id=account["id"],
        instrument_id=gold["id"],
        amount="230000.00",
        price_date="2031-07-31",
    )
    _create_debt(client, july_id, "50000.00")
    close_july = client.post(f"/api/months/{july_id}/close")
    assert close_july.status_code == 200, close_july.text

    response = client.get("/api/analytics/capital-composition")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["asset_classes"] == [
        "cash",
        "deposits",
        "stocks",
        "bonds",
        "gold_other",
    ]
    assert [(point["year"], point["month"]) for point in body["points"]] == [
        (2031, 5),
        (2031, 7),
    ]
    assert {point["reporting_month_id"] for point in body["points"]} == {may_id, july_id}
    assert june_id not in {point["reporting_month_id"] for point in body["points"]}

    may = body["points"][0]
    may_allocation = {item["asset_class"]: item["amount"] for item in may["allocation"]}
    assert list(may_allocation) == body["asset_classes"]
    assert may_allocation["cash"] == _rub("100000.00")
    assert may_allocation["deposits"] == _rub("400000.00")
    assert may_allocation["stocks"] == _rub("300000.00")
    assert may_allocation["bonds"] == _rub("700000.00")
    assert may_allocation["gold_other"] == _rub("200000.00")
    assert may["liquid_assets_total"] == _rub("1700000.00")
    assert may["included_debts"] == _rub("100000.00")
    assert may["liquid_capital_net"] == _rub("1600000.00")

    july = body["points"][1]
    july_allocation = {item["asset_class"]: item["amount"] for item in july["allocation"]}
    assert july_allocation["stocks"] == _rub("0.00")
    assert july_allocation["cash"] == _rub("120000.00")
    assert july_allocation["deposits"] == _rub("450000.00")
    assert july_allocation["bonds"] == _rub("800000.00")
    assert july_allocation["gold_other"] == _rub("230000.00")
    assert july["liquid_assets_total"] == _rub("1600000.00")
    assert july["included_debts"] == _rub("50000.00")
    assert july["liquid_capital_net"] == _rub("1550000.00")

    dashboard = client.get(f"/api/months/{july_id}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["asset_allocation"] == july["allocation"]


def test_reopened_month_disappears_from_capital_composition_history(client: TestClient) -> None:
    month_id = _create_month(client, year=2032, month=1, snapshot_date="2032-01-31")
    _create_cash(client, month_id, "1000.00")
    close = client.post(f"/api/months/{month_id}/close")
    assert close.status_code == 200, close.text

    before = client.get("/api/analytics/capital-composition")
    assert [point["reporting_month_id"] for point in before.json()["points"]] == [month_id]

    reopen = client.post(f"/api/months/{month_id}/reopen")
    assert reopen.status_code == 200, reopen.text

    after = client.get("/api/analytics/capital-composition")
    assert after.status_code == 200, after.text
    assert after.json()["points"] == []
    assert after.json()["asset_classes"] == [
        "cash",
        "deposits",
        "stocks",
        "bonds",
        "gold_other",
    ]
