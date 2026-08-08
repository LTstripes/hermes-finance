"""API tests for the instruments reference dictionary (D04).

Covers the CRUD lifecycle, the optional ``?active=`` list filter,
``nominal_value`` MoneyValue round-trip, duplicate ``isin`` conflicts,
enum validation and the unified error envelope through the HTTP boundary.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base

INSTRUMENT_KEYS = {
    "id",
    "name",
    "instrument_type",
    "isin",
    "ticker",
    "moex_secid",
    "currency",
    "nominal_value",
    "is_active",
    "manual_price_allowed",
    "notes",
}


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "instruments_api.db")
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


def _create(
    client: TestClient,
    name: str,
    instrument_type: str = "stock",
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {"name": name, "instrument_type": instrument_type}
    payload.update(overrides)
    response = client.post("/api/instruments", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_instrument_returns_full_body(client: TestClient) -> None:
    created = _create(
        client,
        "ОФЗ 26233",
        instrument_type="bond",
        isin="ru000a1002j6",
        ticker="OFZ26233",
        moex_secid="OFZ26233",
        currency="RUB",
        nominal_value={"amount": "1000.00", "currency": "RUB"},
        is_active=True,
        manual_price_allowed=True,
        notes="облигация",
    )
    assert set(created) == INSTRUMENT_KEYS
    assert isinstance(created["id"], int)
    assert created["name"] == "ОФЗ 26233"
    assert created["instrument_type"] == "bond"
    assert created["isin"] == "RU000A1002J6"  # service normalizes to uppercase
    assert created["ticker"] == "OFZ26233"
    assert created["moex_secid"] == "OFZ26233"
    assert created["currency"] == "RUB"
    assert created["nominal_value"] == {"amount": "1000.00", "currency": "RUB"}
    assert created["is_active"] is True
    assert created["manual_price_allowed"] is True
    assert created["notes"] == "облигация"


def test_create_instrument_defaults(client: TestClient) -> None:
    created = _create(client, "Сбер", instrument_type="stock")
    assert created["isin"] is None
    assert created["ticker"] is None
    assert created["moex_secid"] is None
    assert created["currency"] == "RUB"
    assert created["nominal_value"] is None
    assert created["is_active"] is True
    assert created["manual_price_allowed"] is True
    assert created["notes"] is None


def test_list_instruments_empty(client: TestClient) -> None:
    response = client.get("/api/instruments")
    assert response.status_code == 200
    assert response.json() == []


def test_list_instruments_filters_by_active(client: TestClient) -> None:
    _create(client, "Сбер", instrument_type="stock", is_active=True)
    _create(
        client,
        "ОФЗ",
        instrument_type="bond",
        isin="RU000A0JX0J2",
        is_active=False,
    )

    inactive = client.get("/api/instruments?active=false")
    assert inactive.status_code == 200
    assert [instrument["name"] for instrument in inactive.json()] == ["ОФЗ"]

    active = client.get("/api/instruments?active=true")
    assert active.status_code == 200
    assert [instrument["name"] for instrument in active.json()] == ["Сбер"]


def test_get_instrument(client: TestClient) -> None:
    created = _create(client, "Сбер", instrument_type="stock")
    response = client.get(f"/api/instruments/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_patch_instrument_changes_isin_and_type(client: TestClient) -> None:
    created = _create(client, "Бумага", instrument_type="stock", isin="RU0000000001")
    response = client.patch(
        f"/api/instruments/{created['id']}",
        json={"isin": "RU0000000002", "instrument_type": "bond"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == INSTRUMENT_KEYS
    assert body["id"] == created["id"]
    assert body["isin"] == "RU0000000002"
    assert body["instrument_type"] == "bond"


def test_delete_instrument(client: TestClient) -> None:
    created = _create(client, "Удаляемый", instrument_type="currency")
    deleted = client.delete(f"/api/instruments/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    listing = client.get("/api/instruments")
    assert listing.status_code == 200
    assert listing.json() == []


def test_duplicate_isin_is_conflict(client: TestClient) -> None:
    _create(client, "Первый", instrument_type="stock", isin="RU000A1002J6")
    duplicate = client.post(
        "/api/instruments",
        json={"name": "Второй", "instrument_type": "bond", "isin": "RU000A1002J6"},
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")

    other = _create(client, "Третий", instrument_type="fund")
    patched = client.patch(f"/api/instruments/{other['id']}", json={"isin": "RU000A1002J6"})
    assert patched.status_code == 409
    _assert_error_body(patched.json(), "conflict")


def test_invalid_instrument_type_is_422(client: TestClient) -> None:
    response = client.post("/api/instruments", json={"name": "Плохой", "instrument_type": "crypto"})
    assert response.status_code == 422
    _assert_error_body(response.json(), "unprocessable")
    assert "unsupported instrument type" in response.json()["error"]["message"]


def test_extra_field_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/instruments",
        json={"name": "Сбер", "instrument_type": "stock", "bogus": True},
    )
    assert response.status_code == 422
    body = response.json()
    _assert_error_body(body, "unprocessable")
    assert any(detail["field"] == "bogus" for detail in body["error"]["details"])


def test_unknown_instrument_is_404(client: TestClient) -> None:
    missing = client.get("/api/instruments/999999")
    assert missing.status_code == 404
    _assert_error_body(missing.json(), "not_found")

    missing_patch = client.patch("/api/instruments/999999", json={"name": "X"})
    assert missing_patch.status_code == 404
    _assert_error_body(missing_patch.json(), "not_found")

    missing_delete = client.delete("/api/instruments/999999")
    assert missing_delete.status_code == 404
    _assert_error_body(missing_delete.json(), "not_found")
