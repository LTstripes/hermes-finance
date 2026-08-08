"""API tests for position and deposit snapshots with concurrency (D05).

Covers server-side recalculation of position metrics and expected monthly
interest, month/account list filtering, duplicate conflicts, the
If-Match optimistic-concurrency matrix (428/409/200) and unknown-id
handling through the HTTP boundary. All amounts are synthetic (2031).
"""

from collections.abc import Generator
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base

POSITION_KEYS = {
    "id",
    "reporting_month_id",
    "account_id",
    "instrument_id",
    "quantity",
    "average_cost_per_unit",
    "market_price_per_unit",
    "market_value",
    "cost_basis",
    "unrealized_result",
    "accrued_interest",
    "price_source",
    "price_date",
    "notes",
    "updated_at",
}
DEPOSIT_KEYS = {
    "id",
    "reporting_month_id",
    "account_id",
    "name",
    "deposit_type",
    "balance",
    "annual_rate",
    "expected_monthly_interest",
    "actual_interest_received",
    "notes",
    "updated_at",
}
STALE_IF_MATCH = "2000-01-01T00:00:00"


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "positions_deposits_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _assert_error_body(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], list)


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _create_month(client: TestClient, year: int = 2031, month: int = 1) -> int:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": f"{year:04d}-{month:02d}-15"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_account(client: TestClient, name: str = "Брокерский") -> dict:
    response = client.post("/api/accounts", json={"name": name, "account_type": "brokerage"})
    assert response.status_code == 201
    return response.json()


def _create_instrument(client: TestClient, name: str = "Сбер") -> dict:
    response = client.post("/api/instruments", json={"name": name, "instrument_type": "stock"})
    assert response.status_code == 201
    return response.json()


def _create_position(
    client: TestClient,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    quantity: str = "10",
    average_cost_per_unit: str = "1000.00",
    market_price_per_unit: str = "1250.00",
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {
        "reporting_month_id": month_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "quantity": quantity,
        "average_cost_per_unit": _rub(average_cost_per_unit),
        "market_price_per_unit": _rub(market_price_per_unit),
        "price_source": "manual",
        "price_date": "2031-01-15",
    }
    payload.update(overrides)
    response = client.post("/api/positions", json=payload)
    assert response.status_code == 201
    return response.json()


def _create_deposit(
    client: TestClient,
    *,
    month_id: int,
    account_id: int,
    name: str = "Вклад",
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {
        "reporting_month_id": month_id,
        "account_id": account_id,
        "name": name,
        "deposit_type": "deposit",
        "balance": _rub("100000.00"),
        "annual_rate": "12.00",
    }
    payload.update(overrides)
    response = client.post("/api/deposits", json=payload)
    assert response.status_code == 201
    return response.json()


# --- positions ---


def test_position_create_recalculates_metrics(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)

    created = _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
        quantity="10",
        average_cost_per_unit="1000.00",
        market_price_per_unit="1250.00",
    )
    assert set(created) == POSITION_KEYS
    assert created["reporting_month_id"] == month_id
    assert created["account_id"] == account["id"]
    assert created["instrument_id"] == instrument["id"]
    assert Decimal(created["quantity"]) == Decimal("10")
    assert created["average_cost_per_unit"] == _rub("1000.00")
    assert created["market_price_per_unit"] == _rub("1250.00")
    # 10 * 125000 kopecks = 1250000 kopecks
    assert created["market_value"] == _rub("12500.00")
    # 10 * 100000 kopecks = 1000000 kopecks
    assert created["cost_basis"] == _rub("10000.00")
    assert created["unrealized_result"] == _rub("2500.00")
    assert created["accrued_interest"] is None
    assert created["price_source"] == "manual"
    assert created["price_date"] == "2031-01-15"
    assert created["notes"] is None
    assert isinstance(datetime.fromisoformat(created["updated_at"]), datetime)


def test_position_create_includes_accrued_interest_in_market_value(
    client: TestClient,
) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)

    created = _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
        quantity="1",
        average_cost_per_unit="900.00",
        market_price_per_unit="1000.00",
        accrued_interest=_rub("50.00"),
    )
    # market_value = 1 * 100000 kopecks + 5000 kopecks accrued interest
    assert created["market_value"] == _rub("1050.00")
    assert created["accrued_interest"] == _rub("50.00")


def test_positions_list_by_month_and_account(client: TestClient) -> None:
    month_1 = _create_month(client, 2031, 1)
    month_2 = _create_month(client, 2031, 2)
    account_1 = _create_account(client, "Брокер 1")
    account_2 = _create_account(client, "Брокер 2")
    instrument_1 = _create_instrument(client, "Сбер")
    instrument_2 = _create_instrument(client, "Газпром")

    _create_position(
        client,
        month_id=month_1,
        account_id=account_1["id"],
        instrument_id=instrument_1["id"],
    )
    _create_position(
        client,
        month_id=month_1,
        account_id=account_1["id"],
        instrument_id=instrument_2["id"],
    )
    _create_position(
        client,
        month_id=month_1,
        account_id=account_2["id"],
        instrument_id=instrument_1["id"],
    )
    _create_position(
        client,
        month_id=month_2,
        account_id=account_1["id"],
        instrument_id=instrument_1["id"],
    )

    by_month = client.get(f"/api/positions?month_id={month_1}")
    assert by_month.status_code == 200
    assert len(by_month.json()) == 3

    by_month_and_account = client.get(
        f"/api/positions?month_id={month_1}&account_id={account_1['id']}"
    )
    assert by_month_and_account.status_code == 200
    assert len(by_month_and_account.json()) == 2

    other_month = client.get(f"/api/positions?month_id={month_2}")
    assert other_month.status_code == 200
    assert len(other_month.json()) == 1


def test_duplicate_position_is_conflict(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)
    _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
    )

    duplicate = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "5",
            "average_cost_per_unit": _rub("100.00"),
            "market_price_per_unit": _rub("110.00"),
            "price_source": "manual",
            "price_date": "2031-01-15",
        },
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")


def test_position_patch_requires_if_match(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)
    created = _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
    )

    response = client.patch(f"/api/positions/{created['id']}", json={"quantity": "11"})
    assert response.status_code == 428
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert "If-Match" in body["error"]["message"]


def test_position_patch_stale_if_match_is_conflict(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)
    created = _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
    )

    response = client.patch(
        f"/api/positions/{created['id']}",
        json={"quantity": "11"},
        headers={"If-Match": STALE_IF_MATCH},
    )
    assert response.status_code == 409
    _assert_error_body(response.json(), "conflict")


def test_position_patch_with_current_if_match_updates(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)
    created = _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
        quantity="10",
        average_cost_per_unit="1000.00",
        market_price_per_unit="1250.00",
    )

    response = client.patch(
        f"/api/positions/{created['id']}",
        json={"quantity": "11"},
        headers={"If-Match": created["updated_at"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == POSITION_KEYS
    assert body["id"] == created["id"]
    assert Decimal(body["quantity"]) == Decimal("11")
    # 11 * 125000 kopecks = 1375000 kopecks
    assert body["market_value"] == _rub("13750.00")
    assert body["cost_basis"] == _rub("11000.00")
    assert body["unrealized_result"] == _rub("2750.00")
    assert body["updated_at"] != created["updated_at"]


def test_position_delete(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)
    created = _create_position(
        client,
        month_id=month_id,
        account_id=account["id"],
        instrument_id=instrument["id"],
    )

    deleted = client.delete(f"/api/positions/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    listing = client.get(f"/api/positions?month_id={month_id}")
    assert listing.status_code == 200
    assert listing.json() == []


def test_position_unknown_ids_are_404(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    instrument = _create_instrument(client)

    unknown_month = client.post(
        "/api/positions",
        json={
            "reporting_month_id": 999999,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "1",
            "average_cost_per_unit": _rub("1.00"),
            "market_price_per_unit": _rub("1.00"),
            "price_source": "manual",
            "price_date": "2031-01-15",
        },
    )
    assert unknown_month.status_code == 404
    _assert_error_body(unknown_month.json(), "not_found")

    unknown_account = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": 999999,
            "instrument_id": instrument["id"],
            "quantity": "1",
            "average_cost_per_unit": _rub("1.00"),
            "market_price_per_unit": _rub("1.00"),
            "price_source": "manual",
            "price_date": "2031-01-15",
        },
    )
    assert unknown_account.status_code == 404
    _assert_error_body(unknown_account.json(), "not_found")

    unknown_instrument = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": account["id"],
            "instrument_id": 999999,
            "quantity": "1",
            "average_cost_per_unit": _rub("1.00"),
            "market_price_per_unit": _rub("1.00"),
            "price_source": "manual",
            "price_date": "2031-01-15",
        },
    )
    assert unknown_instrument.status_code == 404
    _assert_error_body(unknown_instrument.json(), "not_found")

    unknown_snapshot = client.patch(
        "/api/positions/999999",
        json={"quantity": "1"},
        headers={"If-Match": STALE_IF_MATCH},
    )
    assert unknown_snapshot.status_code == 404
    _assert_error_body(unknown_snapshot.json(), "not_found")


# --- deposits ---


def test_deposit_create_recalculates_interest(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)

    created = _create_deposit(
        client,
        month_id=month_id,
        account_id=account["id"],
        name="Накопительный",
        deposit_type="deposit",
        balance=_rub("100000.00"),
        annual_rate="12.00",
    )
    assert set(created) == DEPOSIT_KEYS
    assert created["reporting_month_id"] == month_id
    assert created["account_id"] == account["id"]
    assert created["name"] == "Накопительный"
    assert created["deposit_type"] == "deposit"
    assert created["balance"] == _rub("100000.00")
    assert created["annual_rate"] == "12.00"
    # 100000.00 * 0.12 / 12 = 1000.00 (ROUND_HALF_UP)
    assert created["expected_monthly_interest"] == _rub("1000.00")
    assert created["actual_interest_received"] == _rub("0.00")
    assert created["notes"] is None
    assert isinstance(datetime.fromisoformat(created["updated_at"]), datetime)


def test_deposit_create_with_actual_interest_round_trip(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)

    created = _create_deposit(
        client,
        month_id=month_id,
        account_id=account["id"],
        name="Вклад с процентами",
        actual_interest_received=_rub("1500.25"),
    )
    assert created["actual_interest_received"] == _rub("1500.25")


def test_deposits_list_by_month_and_account(client: TestClient) -> None:
    month_1 = _create_month(client, 2031, 1)
    month_2 = _create_month(client, 2031, 2)
    account_1 = _create_account(client, "Брокер 1")
    account_2 = _create_account(client, "Брокер 2")

    _create_deposit(client, month_id=month_1, account_id=account_1["id"], name="Вклад А")
    _create_deposit(client, month_id=month_1, account_id=account_2["id"], name="Вклад Б")
    _create_deposit(client, month_id=month_2, account_id=account_1["id"], name="Вклад В")

    by_month = client.get(f"/api/deposits?month_id={month_1}")
    assert by_month.status_code == 200
    assert {item["name"] for item in by_month.json()} == {"Вклад А", "Вклад Б"}

    by_month_and_account = client.get(
        f"/api/deposits?month_id={month_1}&account_id={account_1['id']}"
    )
    assert by_month_and_account.status_code == 200
    assert [item["name"] for item in by_month_and_account.json()] == ["Вклад А"]

    other_month = client.get(f"/api/deposits?month_id={month_2}")
    assert other_month.status_code == 200
    assert [item["name"] for item in other_month.json()] == ["Вклад В"]


def test_deposit_patch_requires_if_match(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    created = _create_deposit(client, month_id=month_id, account_id=account["id"])

    response = client.patch(f"/api/deposits/{created['id']}", json={"balance": _rub("120000.00")})
    assert response.status_code == 428
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert "If-Match" in body["error"]["message"]


def test_deposit_patch_stale_if_match_is_conflict(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    created = _create_deposit(client, month_id=month_id, account_id=account["id"])

    response = client.patch(
        f"/api/deposits/{created['id']}",
        json={"balance": _rub("120000.00")},
        headers={"If-Match": STALE_IF_MATCH},
    )
    assert response.status_code == 409
    _assert_error_body(response.json(), "conflict")


def test_deposit_patch_with_current_if_match_recalculates(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    created = _create_deposit(client, month_id=month_id, account_id=account["id"])

    response = client.patch(
        f"/api/deposits/{created['id']}",
        json={"balance": _rub("120000.00"), "annual_rate": "15.00"},
        headers={"If-Match": created["updated_at"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == DEPOSIT_KEYS
    assert body["id"] == created["id"]
    assert body["balance"] == _rub("120000.00")
    assert body["annual_rate"] == "15.00"
    # 120000.00 * 0.15 / 12 = 1500.00
    assert body["expected_monthly_interest"] == _rub("1500.00")
    assert body["updated_at"] != created["updated_at"]


def test_deposit_delete(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    created = _create_deposit(client, month_id=month_id, account_id=account["id"])

    deleted = client.delete(f"/api/deposits/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    listing = client.get(f"/api/deposits?month_id={month_id}")
    assert listing.status_code == 200
    assert listing.json() == []


def test_invalid_deposit_type_is_422(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)
    response = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": month_id,
            "account_id": account["id"],
            "name": "Крипто",
            "deposit_type": "crypto",
            "balance": _rub("1000.00"),
            "annual_rate": "5.00",
        },
    )
    assert response.status_code == 422
    _assert_error_body(response.json(), "unprocessable")
    assert "unsupported deposit type" in response.json()["error"]["message"]


def test_deposit_unknown_ids_are_404(client: TestClient) -> None:
    month_id = _create_month(client)
    account = _create_account(client)

    unknown_month = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": 999999,
            "account_id": account["id"],
            "name": "Вклад",
            "deposit_type": "deposit",
            "balance": _rub("1000.00"),
            "annual_rate": "5.00",
        },
    )
    assert unknown_month.status_code == 404
    _assert_error_body(unknown_month.json(), "not_found")

    unknown_account = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": month_id,
            "account_id": 999999,
            "name": "Вклад",
            "deposit_type": "deposit",
            "balance": _rub("1000.00"),
            "annual_rate": "5.00",
        },
    )
    assert unknown_account.status_code == 404
    _assert_error_body(unknown_account.json(), "not_found")

    unknown_snapshot = client.patch(
        "/api/deposits/999999",
        json={"name": "X"},
        headers={"If-Match": STALE_IF_MATCH},
    )
    assert unknown_snapshot.status_code == 404
    _assert_error_body(unknown_snapshot.json(), "not_found")
