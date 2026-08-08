"""API tests for cash balances (E05)."""

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
    database = create_database(tmp_path / "cash_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _month(client: TestClient) -> int:
    response = client.post(
        "/api/months",
        json={"year": 2031, "month": 1, "snapshot_date": "2031-01-15"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_cash_balance_crud_and_total(client: TestClient) -> None:
    month_id = _month(client)

    created = client.post(
        "/api/cash-balances",
        json={
            "reporting_month_id": month_id,
            "name": "Кошелёк",
            "amount": _rub("1500.50"),
            "include_in_capital": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Кошелёк"
    assert body["amount"] == _rub("1500.50")
    balance_id = body["id"]

    listing = client.get(f"/api/cash-balances?month_id={month_id}")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    total = client.get(f"/api/cash-balances/total?month_id={month_id}")
    assert total.status_code == 200
    assert total.json()["total"] == _rub("1500.50")

    patched = client.patch(
        f"/api/cash-balances/{balance_id}",
        json={"amount": _rub("2000.00"), "name": "Сейф"},
    )
    assert patched.status_code == 200
    assert patched.json()["amount"] == _rub("2000.00")
    assert patched.json()["name"] == "Сейф"

    deleted = client.delete(f"/api/cash-balances/{balance_id}")
    assert deleted.status_code == 204
    after = client.get(f"/api/cash-balances?month_id={month_id}")
    assert after.json() == []
