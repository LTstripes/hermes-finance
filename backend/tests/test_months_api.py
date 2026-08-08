"""Integration tests for the reporting months API (D01 + D02 + D08).

Covers the CRUD lifecycle, validation, close/reopen semantics, closed-month
guards, the unified error response contract and list ordering through the
HTTP boundary. Each test builds a fresh in-memory-backed SQLite database via
``create_database`` + ``create_app`` so tests are isolated from each other and
from the production database.
"""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "months_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _assert_month_body(
    body: dict,
    *,
    year: int,
    month: int,
    snapshot_date: str,
    source: str = "manual",
    status: str = "draft",
) -> None:
    assert set(body) == {"id", "year", "month", "status", "snapshot_date", "source"}
    assert isinstance(body["id"], int)
    assert body["year"] == year
    assert body["month"] == month
    assert body["status"] == status
    assert body["snapshot_date"] == snapshot_date
    assert body["source"] == source


def _assert_error_body(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], list)


def _create(client: TestClient, year: int, month: int, snapshot_date: str) -> dict:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": snapshot_date},
    )
    assert response.status_code == 201
    return response.json()


def test_crud_happy_path(client: TestClient) -> None:
    created = _create(client, 2031, 1, "2031-01-15")
    _assert_month_body(created, year=2031, month=1, snapshot_date="2031-01-15")

    listing = client.get("/api/months")
    assert listing.status_code == 200
    assert listing.json() == [created]

    fetched = client.get(f"/api/months/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    updated = client.patch(f"/api/months/{created['id']}", json={"snapshot_date": "2031-01-20"})
    assert updated.status_code == 200
    assert updated.json()["id"] == created["id"]
    assert updated.json()["snapshot_date"] == "2031-01-20"

    deleted = client.delete(f"/api/months/{created['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    after_delete = client.get(f"/api/months/{created['id']}")
    assert after_delete.status_code == 404
    _assert_error_body(after_delete.json(), "not_found")


def test_create_validation_and_duplicate(client: TestClient) -> None:
    invalid_month = client.post(
        "/api/months", json={"year": 2031, "month": 13, "snapshot_date": "2031-01-15"}
    )
    assert invalid_month.status_code == 422
    invalid_month_body = invalid_month.json()
    _assert_error_body(invalid_month_body, "unprocessable")
    assert any(detail["field"] == "month" for detail in invalid_month_body["error"]["details"])

    extra_field = client.post(
        "/api/months",
        json={"year": 2031, "month": 1, "snapshot_date": "2031-01-15", "bogus": True},
    )
    assert extra_field.status_code == 422
    extra_field_body = extra_field.json()
    _assert_error_body(extra_field_body, "unprocessable")
    assert any(detail["field"] == "bogus" for detail in extra_field_body["error"]["details"])

    missing_snapshot = client.post("/api/months", json={"year": 2031, "month": 1})
    assert missing_snapshot.status_code == 422
    missing_snapshot_body = missing_snapshot.json()
    _assert_error_body(missing_snapshot_body, "unprocessable")
    assert any(
        detail["field"] == "snapshot_date" for detail in missing_snapshot_body["error"]["details"]
    )

    _create(client, 2031, 1, "2031-01-15")
    duplicate = client.post(
        "/api/months", json={"year": 2031, "month": 1, "snapshot_date": "2031-01-15"}
    )
    assert duplicate.status_code == 409
    _assert_error_body(duplicate.json(), "conflict")


def test_close_and_reopen_cycle(client: TestClient) -> None:
    created = _create(client, 2031, 3, "2031-03-15")

    closed = client.post(f"/api/months/{created['id']}/close")
    assert closed.status_code == 200
    _assert_month_body(
        closed.json(), year=2031, month=3, snapshot_date="2031-03-15", status="closed"
    )

    closed_again = client.post(f"/api/months/{created['id']}/close")
    assert closed_again.status_code == 200
    assert closed_again.json()["status"] == "closed"

    fetched_closed = client.get(f"/api/months/{created['id']}")
    assert fetched_closed.status_code == 200
    assert fetched_closed.json()["status"] == "closed"

    reopened = client.post(f"/api/months/{created['id']}/reopen")
    assert reopened.status_code == 200
    _assert_month_body(
        reopened.json(), year=2031, month=3, snapshot_date="2031-03-15", status="draft"
    )


def test_closed_month_guards_patch_and_delete(client: TestClient) -> None:
    created = _create(client, 2031, 4, "2031-04-15")
    closed = client.post(f"/api/months/{created['id']}/close")
    assert closed.status_code == 200

    patched = client.patch(f"/api/months/{created['id']}", json={"snapshot_date": "2031-04-20"})
    assert patched.status_code == 409
    _assert_error_body(patched.json(), "conflict")

    deleted = client.delete(f"/api/months/{created['id']}")
    assert deleted.status_code == 409
    _assert_error_body(deleted.json(), "conflict")


def test_error_contract_codes(client: TestClient) -> None:
    not_found = client.get("/api/months/999999")
    assert not_found.status_code == 404
    _assert_error_body(not_found.json(), "not_found")

    created = _create(client, 2031, 5, "2031-05-15")
    client.post(f"/api/months/{created['id']}/close")
    conflict = client.patch(f"/api/months/{created['id']}", json={"snapshot_date": "2031-05-20"})
    assert conflict.status_code == 409
    _assert_error_body(conflict.json(), "conflict")

    unprocessable = client.post(
        "/api/months", json={"year": 2031, "month": 13, "snapshot_date": "2031-01-15"}
    )
    assert unprocessable.status_code == 422
    _assert_error_body(unprocessable.json(), "unprocessable")

    method_not_allowed = client.put(f"/api/months/{created['id']}", json={})
    assert method_not_allowed.status_code == 405
    _assert_error_body(method_not_allowed.json(), "method_not_allowed")


def test_health_with_error_handlers_registered(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str)


def test_listing_orders_by_year_then_month(client: TestClient) -> None:
    _create(client, 2031, 2, "2031-02-15")
    _create(client, 2031, 1, "2031-01-15")

    listing = client.get("/api/months")
    assert listing.status_code == 200
    months = listing.json()
    assert [(month["year"], month["month"]) for month in months] == [(2031, 1), (2031, 2)]
