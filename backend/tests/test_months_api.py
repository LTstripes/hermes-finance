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
from sqlalchemy import event, update

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, IncomeEntry


@pytest.fixture
def database(tmp_path: Path) -> Generator[Database, None, None]:
    database = create_database(tmp_path / "months_api.db")
    Base.metadata.create_all(database.engine)
    try:
        yield database
    finally:
        database.engine.dispose()


@pytest.fixture
def client(database: Database) -> Generator[TestClient, None, None]:
    with TestClient(create_app(database)) as test_client:
        yield test_client


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
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": created["id"],
                "name": "Recorded cash",
                "amount": {"amount": "0.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )

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
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": created["id"],
                "name": "Recorded cash",
                "amount": {"amount": "0.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )
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
    assert (
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": created["id"],
                "name": "Recorded cash",
                "amount": {"amount": "0.00", "currency": "RUB"},
            },
        ).status_code
        == 201
    )
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


def _working_status(client: TestClient) -> dict:
    response = client.get("/api/months/working-status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"month", "completed_steps", "total_steps"}
    assert body["total_steps"] == 10
    return body


def _close(client: TestClient, month_id: int) -> None:
    assert client.post(f"/api/months/{month_id}/close").status_code == 200


def _add_income(client: TestClient, month_id: int) -> None:
    zero = {"amount": "0.00", "currency": "RUB"}
    response = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "other",
            "name": "Synthetic income",
            "gross_amount": zero,
            "tax_amount": zero,
            "net_amount": zero,
        },
    )
    assert response.status_code == 201


def test_working_status_without_months(client: TestClient) -> None:
    assert _working_status(client) == {"month": None, "completed_steps": 0, "total_steps": 10}


def test_working_status_follows_the_close_page_month(client: TestClient) -> None:
    older_draft = _create(client, 2031, 1, "2031-01-31")
    assert _working_status(client)["month"]["id"] == older_draft["id"]

    closed = _create(client, 2031, 2, "2031-02-28")
    _close(client, closed["id"])
    body = _working_status(client)
    assert body["month"]["id"] == closed["id"]
    assert body["month"]["status"] == "closed"

    newer_draft = _create(client, 2031, 3, "2031-03-31")
    body = _working_status(client)
    assert body["month"]["id"] == newer_draft["id"]
    assert body["month"]["status"] == "draft"
    _assert_month_body(body["month"], year=2031, month=3, snapshot_date="2031-03-31")


def test_working_status_counts_saved_sections(client: TestClient, database: Database) -> None:
    month_id = _create(client, 2031, 1, "2031-01-31")["id"]
    assert _working_status(client)["completed_steps"] == 1

    comment = {"reporting_month_id": month_id, "text": "Synthetic note"}
    assert client.post("/api/comments", json=comment).status_code == 201
    assert _working_status(client)["completed_steps"] == 2

    _add_income(client, month_id)
    assert _working_status(client)["completed_steps"] == 3

    # A row without saved-actual provenance, as after a clone, proves nothing.
    with database.session_factory() as session:
        session.execute(update(IncomeEntry).values(actual_fact_origin=None))
        session.commit()
    assert _working_status(client)["completed_steps"] == 2

    _close(client, month_id)
    assert _working_status(client)["completed_steps"] == 3


def test_working_status_stays_one_month_query_and_one_facts_query(
    client: TestClient, database: Database
) -> None:
    month_id = _create(client, 2031, 1, "2031-01-31")["id"]
    _add_income(client, month_id)
    statements: list[str] = []

    def record(_conn, _cursor, statement, *_args) -> None:
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        assert _working_status(client)["completed_steps"] == 2
    finally:
        event.remove(database.engine, "before_cursor_execute", record)

    selects = [item for item in statements if item.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 2
    assert "FROM reporting_months" in selects[0]
    assert "EXISTS" in selects[1]
