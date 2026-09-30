"""API tests for cash balances (E05)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.api import cash as cash_api
from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.cash import update_cash_balance


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


def test_cash_totals_share_one_snapshot_across_writer_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    month_id = _month(client)
    created = client.post(
        "/api/cash-balances",
        json={
            "reporting_month_id": month_id,
            "name": "Snapshot cash",
            "amount": _rub("100.00"),
            "include_in_capital": True,
        },
    )
    assert created.status_code == 201, created.text
    balance_id = created.json()["id"]
    database = client.app.state.database
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"

    real_total_cash = cash_api.total_cash
    writer_committed = False

    def interleaved_total_cash(*args, **kwargs):
        nonlocal writer_committed
        result = real_total_cash(*args, **kwargs)
        if not writer_committed:
            writer_committed = True
            with database.session_factory() as writer:
                update_cash_balance(writer, balance_id, amount="200.00")
        return result

    monkeypatch.setattr(cash_api, "total_cash", interleaved_total_cash)
    response = client.get(f"/api/cash-balances/total?month_id={month_id}")
    assert response.status_code == 200, response.text
    assert writer_committed
    assert response.json()["total"] == _rub("100.00")
    assert response.json()["total_in_capital"] == _rub("100.00")

    fresh = client.get(f"/api/cash-balances/total?month_id={month_id}")
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["total"] == _rub("200.00")
    assert fresh.json()["total_in_capital"] == _rub("200.00")
