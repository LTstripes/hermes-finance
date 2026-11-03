from datetime import date
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import null, select

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, IncomeEntry
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.salary import (
    prior_taxable_gross_ytd,
    salary_tax_snapshot_for_month,
)
from hermes_finance.services.salary_tax_context import upsert_salary_tax_year_context


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


@pytest.mark.parametrize(
    "origins",
    [(None, None, None), (None, "saved_actual_v1", "saved_actual_v1")],
    ids=["legacy", "mixed_legacy_and_saved"],
)
@pytest.mark.parametrize("with_opening", [False, True], ids=["full_history", "opening_context"])
def test_closed_legacy_salary_history_supports_dashboard_summary_and_snapshot(
    client: TestClient, origins: tuple[str | None, ...], with_opening: bool
) -> None:
    database = client.app.state.database
    with database.session_factory() as session:
        january = create_reporting_month(
            session, year=2031, month=1, snapshot_date=date(2031, 1, 31)
        )
        february = create_reporting_month(
            session, year=2031, month=2, snapshot_date=date(2031, 2, 28)
        )
        march = create_reporting_month(session, year=2031, month=3, snapshot_date=date(2031, 3, 31))
        # Retained CLOSED history may contain duplicate legacy salary rows.
        for month_id, gross, origin in zip(
            [january.id, january.id, february.id],
            [100_000_000, 100_000_000, 30_000_000],
            origins,
            strict=True,
        ):
            session.add(
                IncomeEntry(
                    reporting_month_id=month_id,
                    income_type="salary",
                    name="Synthetic historical salary",
                    gross_amount_kopecks=gross,
                    tax_amount_kopecks=0,
                    net_amount_kopecks=gross,
                    actual_fact_origin=null() if origin is None else origin,
                )
            )
        # Templates and non-salary income do not enter the prior salary gross.
        for income_type, origin in [("salary", "clone_template_v1"), ("bonus", None)]:
            session.add(
                IncomeEntry(
                    reporting_month_id=january.id,
                    income_type=income_type,
                    name="Synthetic excluded income",
                    gross_amount_kopecks=900_000_000,
                    tax_amount_kopecks=0,
                    net_amount_kopecks=900_000_000,
                    actual_fact_origin=null() if origin is None else origin,
                )
            )
        january.status = february.status = "closed"
        session.commit()
        assert session.scalars(
            select(IncomeEntry.actual_fact_origin)
            .where(IncomeEntry.name == "Synthetic historical salary")
            .order_by(IncomeEntry.id)
        ).all() == list(origins)
        create_income_entry(
            session,
            reporting_month_id=march.id,
            income_type=IncomeType.SALARY,
            name="Synthetic March salary",
            gross_amount="300000.00",
            tax_amount="43000.00",
            net_amount="257000.00",
        )
        march_id = march.id
        if with_opening:
            upsert_salary_tax_year_context(
                session,
                tax_year=2031,
                effective_from_month=2,
                opening_taxable_gross="2000000.00",
            )
        assert prior_taxable_gross_ytd(session, march) == (230_000_000, with_opening)
        snapshot = salary_tax_snapshot_for_month(session, march_id)
        assert snapshot.history_complete is True
        assert snapshot.taxable_gross_ytd_kopecks == 260_000_000
        assert snapshot.calculated_tax_kopecks == 4_300_000
        assert snapshot.warning_codes == ()

    for endpoint in ("dashboard", "summary"):
        response = client.get(f"/api/months/{march_id}/{endpoint}")
        assert response.status_code == 200, response.text
        summary = response.json()["summary"] if endpoint == "dashboard" else response.json()
        salary_tax = summary["salary_tax"]
        assert salary_tax["tax"] == {"amount": "43000.00", "currency": "RUB"}
        assert salary_tax["calculated_net"] == {"amount": "257000.00", "currency": "RUB"}
        assert [(part["rate_bps"], part["taxable"]["amount"]) for part in salary_tax["parts"]] == [
            (1300, "100000.00"),
            (1500, "200000.00"),
        ]


@pytest.mark.parametrize(
    ("income_type", "origin"),
    [(None, None), ("bonus", None), ("salary", "clone_template_v1"), ("salary", "unknown_v1")],
    ids=["no_income", "no_salary", "template_only", "unknown_origin"],
)
def test_closed_month_without_known_salary_still_returns_422(
    client: TestClient, income_type: str | None, origin: str | None
) -> None:
    database = client.app.state.database
    with database.session_factory() as session:
        january = create_reporting_month(
            session, year=2031, month=1, snapshot_date=date(2031, 1, 31)
        )
        february = create_reporting_month(
            session, year=2031, month=2, snapshot_date=date(2031, 2, 28)
        )
        if income_type is not None:
            session.add(
                IncomeEntry(
                    reporting_month_id=january.id,
                    income_type=income_type,
                    name="Synthetic non-qualifying income",
                    gross_amount_kopecks=10_000_000,
                    tax_amount_kopecks=0,
                    net_amount_kopecks=10_000_000,
                    actual_fact_origin=null() if origin is None else origin,
                )
            )
        january.status = "closed"
        session.commit()
        create_income_entry(
            session,
            reporting_month_id=february.id,
            income_type=IncomeType.SALARY,
            name="Synthetic February salary",
            gross_amount="100000.00",
            tax_amount="13000.00",
            net_amount="87000.00",
        )
        february_id = february.id
        snapshot = salary_tax_snapshot_for_month(session, february_id)
        assert snapshot.history_complete is False
        assert snapshot.taxable_gross_ytd_kopecks is None
        assert snapshot.warning_codes == ("salary_tax_history_incomplete",)

    for endpoint in ("dashboard", "summary"):
        response = client.get(f"/api/months/{february_id}/{endpoint}")
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "salary_tax_history_incomplete"
