"""API tests for the accounts reference dictionary (D04).

Covers the CRUD lifecycle, the optional ``?status=`` list filter,
duplicate ``external_code`` conflicts, enum validation and the unified
error envelope through the HTTP boundary. Each test builds a fresh
SQLite database via ``create_database`` + ``create_app``.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base

ACCOUNT_KEYS = {
    "id",
    "name",
    "account_type",
    "status",
    "external_code",
    "include_in_capital",
    "include_in_returns",
    "notes",
}


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "accounts_api.db")
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
    account_type: str = "brokerage",
    **overrides: object,
) -> dict:
    payload: dict[str, object] = {"name": name, "account_type": account_type}
    payload.update(overrides)
    response = client.post("/api/accounts", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_account_returns_full_body(client: TestClient) -> None:
    created = _create(
        client,
        "Брокерский счёт",
        account_type="brokerage",
        external_code="BRK-001",
        notes="основной брокер",
    )
    assert set(created) == ACCOUNT_KEYS
    assert isinstance(created["id"], int)
    assert created["name"] == "Брокерский счёт"
    assert created["account_type"] == "brokerage"
    assert created["status"] == "active"
    assert created["external_code"] == "BRK-001"
    assert created["include_in_capital"] is True
    assert created["include_in_returns"] is True
    assert created["notes"] == "основной брокер"


def test_create_account_defaults(client: TestClient) -> None:
    created = _create(client, "Наличные", account_type="cash")
    assert created["status"] == "active"
    assert created["external_code"] is None
    assert created["include_in_capital"] is True
    assert created["include_in_returns"] is True
    assert created["notes"] is None


def test_list_accounts_empty(client: TestClient) -> None:
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert response.json() == []


def test_list_accounts_filters_by_status(client: TestClient) -> None:
    _create(client, "Активный", account_type="brokerage", status="active")
    _create(client, "Замороженный", account_type="deposit", status="frozen")
    _create(client, "Закрытый", account_type="cash", status="closed")

    active = client.get("/api/accounts?status=active")
    assert active.status_code == 200
    assert [account["name"] for account in active.json()] == ["Активный"]

    frozen = client.get("/api/accounts?status=frozen")
    assert frozen.status_code == 200
    assert [account["name"] for account in frozen.json()] == ["Замороженный"]

    hidden = client.get("/api/accounts?status=hidden")
    assert hidden.status_code == 200
    assert hidden.json() == []


def test_get_account(client: TestClient) -> None:
    created = _create(client, "Брокерский счёт", account_type="brokerage")
    response = client.get(f"/api/accounts/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_patch_account_name_and_status(client: TestClient) -> None:
    created = _create(client, "Старый", account_type="brokerage")
    response = client.patch(
        f"/api/accounts/{created['id']}",
        json={"name": "Новый", "status": "closed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == ACCOUNT_KEYS
    assert body["id"] == created["id"]
    assert body["name"] == "Новый"
    assert body["status"] == "closed"
    assert body["account_type"] == "brokerage"


def test_delete_account_then_get_is_404(client: TestClient) -> None:
    created = _create(client, "Удаляемый", account_type="cash")
    deleted = client.delete(f"/api/accounts/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    after_delete = client.get(f"/api/accounts/{created['id']}")
    assert after_delete.status_code == 404
    _assert_error_body(after_delete.json(), "not_found")


def test_duplicate_external_code_is_conflict(client: TestClient) -> None:
    _create(client, "Первый", account_type="brokerage", external_code="EXT-1")
    duplicate = client.post(
        "/api/accounts",
        json={"name": "Второй", "account_type": "iis", "external_code": "EXT-1"},
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")

    other = _create(client, "Третий", account_type="cash")
    patched = client.patch(f"/api/accounts/{other['id']}", json={"external_code": "EXT-1"})
    assert patched.status_code == 409
    _assert_error_body(patched.json(), "conflict")


def test_invalid_account_type_and_status_are_422(client: TestClient) -> None:
    bad_type = client.post("/api/accounts", json={"name": "Плохой", "account_type": "crypto"})
    assert bad_type.status_code == 422
    _assert_error_body(bad_type.json(), "unprocessable")
    assert "unsupported account type" in bad_type.json()["error"]["message"]

    bad_status = client.post(
        "/api/accounts", json={"name": "Плохой", "account_type": "cash", "status": "liquidated"}
    )
    assert bad_status.status_code == 422
    _assert_error_body(bad_status.json(), "unprocessable")
    assert "unsupported account status" in bad_status.json()["error"]["message"]

    bad_filter = client.get("/api/accounts?status=bogus")
    assert bad_filter.status_code == 422
    _assert_error_body(bad_filter.json(), "unprocessable")


def test_extra_field_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/accounts",
        json={"name": "Счёт", "account_type": "cash", "bogus": True},
    )
    assert response.status_code == 422
    body = response.json()
    _assert_error_body(body, "unprocessable")
    assert any(detail["field"] == "bogus" for detail in body["error"]["details"])


def test_unknown_account_is_404(client: TestClient) -> None:
    missing = client.get("/api/accounts/999999")
    assert missing.status_code == 404
    _assert_error_body(missing.json(), "not_found")

    missing_patch = client.patch("/api/accounts/999999", json={"name": "X"})
    assert missing_patch.status_code == 404
    _assert_error_body(missing_patch.json(), "not_found")

    missing_delete = client.delete("/api/accounts/999999")
    assert missing_delete.status_code == 404
    _assert_error_body(missing_delete.json(), "not_found")
