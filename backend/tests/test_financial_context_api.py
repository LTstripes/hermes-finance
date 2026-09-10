"""API contract for the #336 financial-context facts.

Covers debt rate/due/end terms, the mortgage annual rate and the month-local
planned budget over the authoritative backend DTOs. Unknown stays ``null``;
``0`` is a real owner-entered value.
"""

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
    database = create_database(tmp_path / "financial-context-api.db")
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
        json={"year": 2032, "month": 1, "snapshot_date": "2032-01-15"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_debt_terms_round_trip_and_zero_differs_from_unknown(client: TestClient) -> None:
    month_id = _month(client)

    unknown = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Карта без ставки",
            "current_balance": _rub("25000.00"),
        },
    )
    assert unknown.status_code == 201, unknown.text
    unknown_body = unknown.json()
    assert unknown_body["annual_rate"] is None
    assert unknown_body["next_due_date"] is None
    assert unknown_body["contract_end_date"] is None

    zero = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "other",
            "name": "Беспроцентный заём",
            "current_balance": _rub("50000.00"),
            "annual_rate": "0.00",
            "next_due_date": "2032-02-20",
            "contract_end_date": "2034-02-20",
        },
    )
    assert zero.status_code == 201, zero.text
    zero_body = zero.json()
    assert zero_body["annual_rate"] == "0.00"
    assert zero_body["next_due_date"] == "2032-02-20"
    assert zero_body["contract_end_date"] == "2034-02-20"
    debt_id = zero_body["id"]

    cleared = client.patch(f"/api/debts/{debt_id}", json={"annual_rate": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["annual_rate"] is None
    # Clearing one term must not touch the other dates.
    assert cleared.json()["next_due_date"] == "2032-02-20"
    assert cleared.json()["contract_end_date"] == "2034-02-20"

    renamed = client.patch(f"/api/debts/{debt_id}", json={"name": "Заём"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["contract_end_date"] == "2034-02-20"

    listed = client.get(f"/api/debts?month_id={month_id}")
    assert listed.status_code == 200, listed.text
    assert [row["annual_rate"] for row in listed.json()] == [None, None]

    negative = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Плохая ставка",
            "current_balance": _rub("1.00"),
            "annual_rate": "-0.01",
        },
    )
    assert negative.status_code == 422, negative.text

    unknown_field = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Лишнее поле",
            "current_balance": _rub("1.00"),
            "apr": "10.00",
        },
    )
    assert unknown_field.status_code == 422, unknown_field.text


def test_property_mortgage_rate_round_trip(client: TestClient) -> None:
    month_id = _month(client)

    created = client.post(
        "/api/properties",
        json={
            "reporting_month_id": month_id,
            "name": "Квартира",
            "estimated_value": _rub("8000000.00"),
            "mortgage_balance": _rub("3000000.00"),
            "monthly_payment": _rub("50000.00"),
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["mortgage_annual_rate"] is None
    property_id = created.json()["id"]

    rated = client.patch(f"/api/properties/{property_id}", json={"mortgage_annual_rate": "11.75"})
    assert rated.status_code == 200, rated.text
    assert rated.json()["mortgage_annual_rate"] == "11.75"

    zeroed = client.patch(f"/api/properties/{property_id}", json={"mortgage_annual_rate": "0.00"})
    assert zeroed.status_code == 200, zeroed.text
    assert zeroed.json()["mortgage_annual_rate"] == "0.00"
    assert zeroed.json()["mortgage_balance"] == _rub("3000000.00")

    cleared = client.patch(f"/api/properties/{property_id}", json={"mortgage_annual_rate": None})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["mortgage_annual_rate"] is None


def test_planned_budget_crud_and_comparison(client: TestClient) -> None:
    month_id = _month(client)

    empty = client.get(f"/api/planned-budget?month_id={month_id}")
    assert empty.status_code == 200, empty.text
    assert empty.json() == []

    created = client.post(
        "/api/planned-budget",
        json={
            "reporting_month_id": month_id,
            "category": "Аренда",
            "planned_amount": _rub("48000.00"),
            "expense_type": "mandatory",
            "notes": "офис",
        },
    )
    assert created.status_code == 201, created.text
    line = created.json()
    assert line["planned_amount"] == _rub("48000.00")
    assert line["expense_type"] == "mandatory"

    # A plan is not an actual expense stream.
    assert client.get(f"/api/expenses?month_id={month_id}").json() == []

    client.post(
        "/api/expenses",
        json={
            "reporting_month_id": month_id,
            "category": "Аренда",
            "amount": _rub("50000.00"),
            "expense_type": "mandatory",
        },
    )
    comparison = client.get(f"/api/planned-budget/comparison?month_id={month_id}")
    assert comparison.status_code == 200, comparison.text
    rows = comparison.json()
    assert len(rows) == 1
    assert rows[0]["category"] == "Аренда"
    assert rows[0]["planned"] == _rub("48000.00")
    assert rows[0]["actual"] == _rub("50000.00")

    zeroed = client.patch(
        f"/api/planned-budget/{line['id']}", json={"planned_amount": _rub("0.00")}
    )
    assert zeroed.status_code == 200, zeroed.text
    assert zeroed.json()["planned_amount"] == _rub("0.00")

    bad_type = client.post(
        "/api/planned-budget",
        json={
            "reporting_month_id": month_id,
            "category": "Лишнее",
            "planned_amount": _rub("1.00"),
            "expense_type": "luxury",
        },
    )
    assert bad_type.status_code == 422, bad_type.text

    deleted = client.delete(f"/api/planned-budget/{line['id']}")
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/planned-budget/{line['id']}").status_code == 404


def test_comparison_keeps_absent_side_null_and_explicit_zero_distinct(
    client: TestClient,
) -> None:
    """#336 blocker: an absent side must serialize as null, never as 0.00."""
    month_id = _month(client)
    # The owner entered a plan line and stated an explicit zero.
    planned = client.post(
        "/api/planned-budget",
        json={
            "reporting_month_id": month_id,
            "category": "Подписки",
            "planned_amount": _rub("0.00"),
            "expense_type": "other",
        },
    )
    assert planned.status_code == 201, planned.text
    # An actual with no plan line at all.
    actual = client.post(
        "/api/expenses",
        json={
            "reporting_month_id": month_id,
            "category": "Еда",
            "amount": _rub("12000.00"),
            "expense_type": "mandatory",
        },
    )
    assert actual.status_code == 201, actual.text

    response = client.get(f"/api/planned-budget/comparison?month_id={month_id}")
    assert response.status_code == 200, response.text
    by_key = {(row["category"], row["expense_type"]): row for row in response.json()}

    # Explicit owner-entered zero survives as 0.00 ...
    assert by_key[("Подписки", "other")]["planned"] == _rub("0.00")
    # ... while the missing counterpart stays absent.
    assert by_key[("Подписки", "other")]["actual"] is None
    assert by_key[("Еда", "mandatory")]["planned"] is None
    assert by_key[("Еда", "mandatory")]["actual"] == _rub("12000.00")
