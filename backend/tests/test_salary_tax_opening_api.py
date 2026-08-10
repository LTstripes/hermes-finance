from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def test_opening_context_put_get_replace_and_delete(client: TestClient) -> None:
    created = client.put(
        "/api/salary-tax/years/2031/opening-context",
        json={
            "effective_from_month": 5,
            "opening_taxable_gross": {"amount": "400000.00", "currency": "RUB"},
        },
    )

    assert created.status_code == 200
    assert created.json() == {
        "tax_year": 2031,
        "effective_from_month": 5,
        "opening_taxable_gross": {"amount": "400000.00", "currency": "RUB"},
    }
    assert client.get("/api/salary-tax/years/2031/opening-context").json() == created.json()

    replaced = client.put(
        "/api/salary-tax/years/2031/opening-context",
        json={
            "effective_from_month": 6,
            "opening_taxable_gross": {"amount": "500000.00", "currency": "RUB"},
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["effective_from_month"] == 6
    assert replaced.json()["opening_taxable_gross"]["amount"] == "500000.00"

    deleted = client.delete("/api/salary-tax/years/2031/opening-context")
    assert deleted.status_code == 204
    missing = client.get("/api/salary-tax/years/2031/opening-context")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


def test_opening_context_rejects_nonzero_january_baseline(client: TestClient) -> None:
    response = client.put(
        "/api/salary-tax/years/2031/opening-context",
        json={
            "effective_from_month": 1,
            "opening_taxable_gross": {"amount": "0.01", "currency": "RUB"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable"
    assert "opening taxable gross must be zero" in response.json()["error"]["message"]


def test_salary_tax_incomplete_error_has_contract_code(client: TestClient) -> None:
    month = client.post(
        "/api/months",
        json={"year": 2031, "month": 5, "snapshot_date": "2031-05-15"},
    ).json()
    created_income = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month["id"],
            "income_type": "salary",
            "name": "Synthetic Salary",
            "gross_amount": {"amount": "100000.00", "currency": "RUB"},
            "tax_amount": {"amount": "0.00", "currency": "RUB"},
            "net_amount": {"amount": "100000.00", "currency": "RUB"},
        },
    )
    assert created_income.status_code == 201

    response = client.get(f"/api/months/{month['id']}/summary")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "salary_tax_history_incomplete"
