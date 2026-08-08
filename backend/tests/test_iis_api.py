"""API tests for the IIS profile, contributions and tax benefits (D04).

Covers the profile upsert lifecycle (PUT creates, PUT updates in place,
DELETE), contributions CRUD with the ``?tax_year=`` filter, tax benefits
CRUD with the ``?status=`` filter and status transitions, duplicate
conflicts and unknown-account handling through the HTTP boundary.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base

PROFILE_KEYS = {"id", "account_id", "iis_type", "opened_at", "eligible_close_at", "notes"}
CONTRIBUTION_KEYS = {"id", "account_id", "tax_year", "amount", "is_target_reached", "notes"}
BENEFIT_KEYS = {
    "id",
    "account_id",
    "tax_year",
    "benefit_type",
    "status",
    "amount",
    "received_at",
    "notes",
}


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "iis_api.db")
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


def _create_account(client: TestClient, name: str = "ИИС") -> dict:
    response = client.post("/api/accounts", json={"name": name, "account_type": "iis"})
    assert response.status_code == 201
    return response.json()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


# --- profile ---


def test_profile_get_missing_is_404(client: TestClient) -> None:
    account = _create_account(client)
    response = client.get(f"/api/iis/{account['id']}/profile")
    assert response.status_code == 404
    _assert_error_body(response.json(), "not_found")


def test_profile_put_creates(client: TestClient) -> None:
    account = _create_account(client)
    response = client.put(
        f"/api/iis/{account['id']}/profile",
        json={"iis_type": "iis-a", "opened_at": "2030-01-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == PROFILE_KEYS
    assert isinstance(body["id"], int)
    assert body["account_id"] == account["id"]
    assert body["iis_type"] == "iis-a"
    assert body["opened_at"] == "2030-01-15"
    assert body["eligible_close_at"] is None
    assert body["notes"] is None


def test_profile_put_updates_same_row(client: TestClient) -> None:
    account = _create_account(client)
    first = client.put(
        f"/api/iis/{account['id']}/profile",
        json={"iis_type": "iis-a", "opened_at": "2030-01-15"},
    )
    assert first.status_code == 200

    second = client.put(
        f"/api/iis/{account['id']}/profile",
        json={
            "iis_type": "iis-b",
            "opened_at": "2031-01-01",
            "eligible_close_at": "2036-01-01",
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert body["id"] == first.json()["id"]
    assert body["iis_type"] == "iis-b"
    assert body["opened_at"] == "2031-01-01"
    assert body["eligible_close_at"] == "2036-01-01"

    listing = client.get(f"/api/iis/{account['id']}/profile")
    assert listing.status_code == 200
    assert listing.json()["id"] == first.json()["id"]


def test_profile_delete_then_get_is_404(client: TestClient) -> None:
    account = _create_account(client)
    created = client.put(
        f"/api/iis/{account['id']}/profile",
        json={"iis_type": "iis-a", "opened_at": "2030-01-15"},
    )
    assert created.status_code == 200

    deleted = client.delete(f"/api/iis/{account['id']}/profile")
    assert deleted.status_code == 204
    assert deleted.content == b""

    after_delete = client.get(f"/api/iis/{account['id']}/profile")
    assert after_delete.status_code == 404
    _assert_error_body(after_delete.json(), "not_found")


def test_profile_unknown_account_is_404(client: TestClient) -> None:
    missing_get = client.get("/api/iis/999999/profile")
    assert missing_get.status_code == 404
    _assert_error_body(missing_get.json(), "not_found")

    missing_put = client.put(
        "/api/iis/999999/profile",
        json={"iis_type": "iis-a", "opened_at": "2030-01-15"},
    )
    assert missing_put.status_code == 404
    _assert_error_body(missing_put.json(), "not_found")

    missing_delete = client.delete("/api/iis/999999/profile")
    assert missing_delete.status_code == 404
    _assert_error_body(missing_delete.json(), "not_found")


# --- contributions ---


def test_contribution_create(client: TestClient) -> None:
    account = _create_account(client)
    response = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00"), "notes": "взнос"},
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == CONTRIBUTION_KEYS
    assert isinstance(body["id"], int)
    assert body["account_id"] == account["id"]
    assert body["tax_year"] == 2031
    assert body["amount"] == _rub("400000.00")
    assert body["is_target_reached"] is False
    assert body["notes"] == "взнос"


def test_contributions_list_and_tax_year_filter(client: TestClient) -> None:
    account = _create_account(client)
    first = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00")},
    )
    second = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2032, "amount": _rub("100000.00")},
    )
    assert first.status_code == 201
    assert second.status_code == 201

    all_items = client.get(f"/api/iis/{account['id']}/contributions")
    assert all_items.status_code == 200
    assert [item["tax_year"] for item in all_items.json()] == [2031, 2032]

    filtered = client.get(f"/api/iis/{account['id']}/contributions?tax_year=2031")
    assert filtered.status_code == 200
    assert [item["tax_year"] for item in filtered.json()] == [2031]


def test_contribution_patch_amount(client: TestClient) -> None:
    account = _create_account(client)
    created = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00")},
    ).json()
    response = client.patch(
        f"/api/iis/{account['id']}/contributions/{created['id']}",
        json={"amount": _rub("450000.00"), "is_target_reached": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRIBUTION_KEYS
    assert body["id"] == created["id"]
    assert body["amount"] == _rub("450000.00")
    assert body["is_target_reached"] is True


def test_contribution_delete(client: TestClient) -> None:
    account = _create_account(client)
    created = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00")},
    ).json()
    deleted = client.delete(f"/api/iis/{account['id']}/contributions/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    listing = client.get(f"/api/iis/{account['id']}/contributions")
    assert listing.status_code == 200
    assert listing.json() == []


def test_duplicate_contribution_is_conflict(client: TestClient) -> None:
    account = _create_account(client)
    first = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00")},
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/api/iis/{account['id']}/contributions",
        json={"tax_year": 2031, "amount": _rub("100.00")},
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")


def test_contribution_unknown_account_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/iis/999999/contributions",
        json={"tax_year": 2031, "amount": _rub("400000.00")},
    )
    assert response.status_code == 404
    _assert_error_body(response.json(), "not_found")


# --- tax benefits ---


def test_benefit_create(client: TestClient) -> None:
    account = _create_account(client)
    response = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "planned",
            "amount": _rub("52000.00"),
            "received_at": None,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == BENEFIT_KEYS
    assert isinstance(body["id"], int)
    assert body["account_id"] == account["id"]
    assert body["tax_year"] == 2031
    assert body["benefit_type"] == "deduction"
    assert body["status"] == "planned"
    assert body["amount"] == _rub("52000.00")
    assert body["received_at"] is None
    assert body["notes"] is None


def test_benefits_list_and_status_filter(client: TestClient) -> None:
    account = _create_account(client)
    planned = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "planned",
            "amount": _rub("52000.00"),
        },
    )
    received = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2030,
            "benefit_type": "refund",
            "status": "received",
            "amount": _rub("13000.00"),
        },
    )
    assert planned.status_code == 201
    assert received.status_code == 201

    all_items = client.get(f"/api/iis/{account['id']}/benefits")
    assert all_items.status_code == 200
    assert [(item["tax_year"], item["status"]) for item in all_items.json()] == [
        (2030, "received"),
        (2031, "planned"),
    ]

    filtered = client.get(f"/api/iis/{account['id']}/benefits?status=received")
    assert filtered.status_code == 200
    assert [item["benefit_type"] for item in filtered.json()] == ["refund"]


def test_benefit_status_transition(client: TestClient) -> None:
    account = _create_account(client)
    created = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "planned",
            "amount": _rub("52000.00"),
        },
    ).json()

    submitted = client.patch(
        f"/api/iis/{account['id']}/benefits/{created['id']}",
        json={"status": "submitted"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"

    received = client.patch(
        f"/api/iis/{account['id']}/benefits/{created['id']}",
        json={"status": "received", "received_at": "2031-04-01"},
    )
    assert received.status_code == 200
    assert received.json()["status"] == "received"
    assert received.json()["received_at"] == "2031-04-01"


def test_benefit_delete(client: TestClient) -> None:
    account = _create_account(client)
    created = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "planned",
            "amount": _rub("52000.00"),
        },
    ).json()
    deleted = client.delete(f"/api/iis/{account['id']}/benefits/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    listing = client.get(f"/api/iis/{account['id']}/benefits")
    assert listing.status_code == 200
    assert listing.json() == []


def test_duplicate_benefit_is_conflict(client: TestClient) -> None:
    account = _create_account(client)
    first = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "planned",
            "amount": _rub("52000.00"),
        },
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "submitted",
            "amount": _rub("52000.00"),
        },
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")


def test_benefit_invalid_status_is_422(client: TestClient) -> None:
    account = _create_account(client)
    response = client.post(
        f"/api/iis/{account['id']}/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "bogus",
            "amount": _rub("52000.00"),
        },
    )
    assert response.status_code == 422
    _assert_error_body(response.json(), "unprocessable")
    assert "unsupported tax benefit status" in response.json()["error"]["message"]


def test_benefit_unknown_account_is_404(client: TestClient) -> None:
    response = client.post(
        "/api/iis/999999/benefits",
        json={
            "tax_year": 2031,
            "benefit_type": "deduction",
            "status": "planned",
            "amount": _rub("52000.00"),
        },
    )
    assert response.status_code == 404
    _assert_error_body(response.json(), "not_found")
