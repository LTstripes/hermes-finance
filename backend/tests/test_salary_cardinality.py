"""M03-03 regression coverage for canonical monthly salary cardinality."""

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import IncomeType
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, IncomeEntry
from hermes_finance.services.incomes import (
    SalaryCardinalityError,
    create_income_entry,
    replace_salary_entry,
    update_income_entry,
)
from hermes_finance.services.month_clone import clone_reporting_month
from hermes_finance.services.reporting_months import create_reporting_month


def _session(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "salary-cardinality.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _month(session: Session, *, year: int = 2030, month: int = 5) -> int:
    return create_reporting_month(
        session,
        year=year,
        month=month,
        snapshot_date=date(year, month, 15),
    ).id


def _legacy_salary(
    session: Session,
    month_id: int,
    *,
    gross: int,
    tax: int,
    net: int,
    name: str,
) -> IncomeEntry:
    row = IncomeEntry(
        reporting_month_id=month_id,
        income_type=IncomeType.SALARY.value,
        name=name,
        gross_amount_kopecks=gross,
        tax_amount_kopecks=tax,
        net_amount_kopecks=net,
        received_at=None,
        is_recurring=True,
        include_in_cash_flow=True,
        include_in_passive_income=False,
        notes=None,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_generic_create_rejects_second_salary(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Salary 1",
            gross_amount="200000.00",
            tax_amount="26000.00",
            net_amount="174000.00",
        )

        with pytest.raises(SalaryCardinalityError, match="already has a salary"):
            create_income_entry(
                session,
                reporting_month_id=month_id,
                income_type=IncomeType.SALARY,
                name="Salary 2",
                gross_amount="50000.00",
                tax_amount="6500.00",
                net_amount="43500.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_generic_update_cannot_turn_another_row_into_second_salary(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SALARY,
            name="Salary",
            gross_amount="200000.00",
            tax_amount="26000.00",
            net_amount="174000.00",
        )
        other = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.OTHER,
            name="Other",
            gross_amount="1000.00",
            tax_amount="0.00",
            net_amount="1000.00",
        )

        with pytest.raises(SalaryCardinalityError, match="already has a salary"):
            update_income_entry(session, other.id, income_type=IncomeType.SALARY)
    finally:
        session.close()
        database.engine.dispose()


def test_atomic_replace_collapses_legacy_duplicate_salaries(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session)
        first = _legacy_salary(
            session,
            month_id,
            gross=20_000_000,
            tax=2_600_000,
            net=17_400_000,
            name="Legacy A",
        )
        _legacy_salary(
            session,
            month_id,
            gross=5_000_000,
            tax=650_000,
            net=4_350_000,
            name="Legacy B",
        )

        replaced = replace_salary_entry(
            session,
            month_id,
            gross_amount="250000.00",
            tax_amount="32500.00",
            net_amount="217500.00",
        )

        assert replaced is not None
        assert replaced.id == first.id
        assert replaced.name == "Зарплата"
        assert replaced.gross_amount_kopecks == 25_000_000
        assert replaced.tax_amount_kopecks == 3_250_000
        assert replaced.net_amount_kopecks == 21_750_000
        rows = list(
            session.scalars(
                select(IncomeEntry).where(
                    IncomeEntry.reporting_month_id == month_id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                )
            )
        )
        assert [row.id for row in rows] == [first.id]
    finally:
        session.close()
        database.engine.dispose()


def test_zero_replace_deletes_all_legacy_salary_rows(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session)
        _legacy_salary(session, month_id, gross=100, tax=0, net=100, name="A")
        _legacy_salary(session, month_id, gross=200, tax=0, net=200, name="B")

        assert (
            replace_salary_entry(
                session,
                month_id,
                gross_amount="0.00",
                tax_amount="0.00",
                net_amount="0.00",
            )
            is None
        )
        assert not list(
            session.scalars(
                select(IncomeEntry).where(
                    IncomeEntry.reporting_month_id == month_id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                )
            )
        )
    finally:
        session.close()
        database.engine.dispose()


def test_clone_aggregates_legacy_recurring_salary_rows(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        source_id = _month(session, year=2030, month=5)
        _legacy_salary(
            session,
            source_id,
            gross=20_000_000,
            tax=2_600_000,
            net=17_400_000,
            name="Legacy A",
        )
        _legacy_salary(
            session,
            source_id,
            gross=5_000_000,
            tax=650_000,
            net=4_350_000,
            name="Legacy B",
        )

        target = clone_reporting_month(
            session,
            source_id,
            target_year=2030,
            target_month=6,
            snapshot_date=date(2030, 6, 15),
        )
        rows = list(
            session.scalars(
                select(IncomeEntry).where(
                    IncomeEntry.reporting_month_id == target.id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                )
            )
        )

        assert len(rows) == 1
        assert rows[0].name == "Legacy A"
        assert rows[0].gross_amount_kopecks == 25_000_000
        assert rows[0].tax_amount_kopecks == 3_250_000
        assert rows[0].net_amount_kopecks == 21_750_000
        assert rows[0].received_at is None
    finally:
        session.close()
        database.engine.dispose()


def test_clone_preserves_single_recurring_salary_name(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        source_id = _month(session, year=2030, month=5)
        _legacy_salary(
            session,
            source_id,
            gross=20_000_000,
            tax=2_600_000,
            net=17_400_000,
            name="Custom Salary Name",
        )

        target = clone_reporting_month(
            session,
            source_id,
            target_year=2030,
            target_month=6,
            snapshot_date=date(2030, 6, 15),
        )
        rows = list(
            session.scalars(
                select(IncomeEntry).where(
                    IncomeEntry.reporting_month_id == target.id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                )
            )
        )

        assert len(rows) == 1
        assert rows[0].name == "Custom Salary Name"
        assert rows[0].gross_amount_kopecks == 20_000_000
        assert rows[0].tax_amount_kopecks == 2_600_000
        assert rows[0].net_amount_kopecks == 17_400_000
    finally:
        session.close()
        database.engine.dispose()


def test_replace_rolls_back_when_commit_fails(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session)
        first = _legacy_salary(session, month_id, gross=100, tax=10, net=90, name="A")
        second = _legacy_salary(session, month_id, gross=200, tax=20, net=180, name="B")

        def fail_commit() -> None:
            raise RuntimeError("synthetic commit failure")

        session.commit = fail_commit  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            replace_salary_entry(
                session,
                month_id,
                gross_amount="250000.00",
                tax_amount="32500.00",
                net_amount="217500.00",
            )

        rows = list(
            session.scalars(
                select(IncomeEntry)
                .where(
                    IncomeEntry.reporting_month_id == month_id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                )
                .order_by(IncomeEntry.id)
            )
        )
        assert [(row.id, row.name, row.gross_amount_kopecks) for row in rows] == [
            (first.id, "A", 100),
            (second.id, "B", 200),
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_salary_replace_api_keeps_one_visible_salary_row(tmp_path: Path) -> None:
    database = create_database(tmp_path / "salary-cardinality-api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            month = client.post(
                "/api/months",
                json={"year": 2030, "month": 5, "snapshot_date": "2030-05-15"},
            )
            assert month.status_code == 201
            month_id = month.json()["id"]

            def rub(amount: str) -> dict[str, str]:
                return {"amount": amount, "currency": "RUB"}

            first = client.post(
                "/api/incomes",
                json={
                    "reporting_month_id": month_id,
                    "income_type": "salary",
                    "name": "Зарплата",
                    "gross_amount": rub("200000.00"),
                    "tax_amount": rub("26000.00"),
                    "net_amount": rub("174000.00"),
                },
            )
            assert first.status_code == 201

            duplicate = client.post(
                "/api/incomes",
                json={
                    "reporting_month_id": month_id,
                    "income_type": "salary",
                    "name": "Duplicate",
                    "gross_amount": rub("50000.00"),
                    "tax_amount": rub("6500.00"),
                    "net_amount": rub("43500.00"),
                },
            )
            assert duplicate.status_code == 422
            error = duplicate.json()["error"]
            assert error["code"] == "unprocessable"
            assert "already has a salary" in error["message"]
            assert error["details"] == []

            replaced = client.put(
                f"/api/incomes/salary/{month_id}",
                json={
                    "gross_amount": rub("250000.00"),
                    "tax_amount": rub("32500.00"),
                    "net_amount": rub("217500.00"),
                },
            )
            assert replaced.status_code == 200
            assert replaced.json()["gross_amount"] == rub("250000.00")

            listing = client.get(f"/api/incomes?month_id={month_id}")
            salary_rows = [row for row in listing.json() if row["income_type"] == "salary"]
            assert len(salary_rows) == 1
    finally:
        database.engine.dispose()


def test_salary_replace_api_rejects_closed_month(tmp_path: Path) -> None:
    database = create_database(tmp_path / "salary-cardinality-closed.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            month = client.post(
                "/api/months",
                json={"year": 2030, "month": 5, "snapshot_date": "2030-05-15"},
            )
            assert month.status_code == 201
            month_id = month.json()["id"]

            def rub(amount: str) -> dict[str, str]:
                return {"amount": amount, "currency": "RUB"}

            created = client.post(
                "/api/incomes",
                json={
                    "reporting_month_id": month_id,
                    "income_type": "salary",
                    "name": "Зарплата",
                    "gross_amount": rub("200000.00"),
                    "tax_amount": rub("26000.00"),
                    "net_amount": rub("174000.00"),
                },
            )
            assert created.status_code == 201
            original = created.json()

            closed = client.post(f"/api/months/{month_id}/close")
            assert closed.status_code == 200

            replaced = client.put(
                f"/api/incomes/salary/{month_id}",
                json={
                    "gross_amount": rub("250000.00"),
                    "tax_amount": rub("32500.00"),
                    "net_amount": rub("217500.00"),
                },
            )
            assert replaced.status_code == 409
            error = replaced.json()["error"]
            assert error["code"] == "conflict"
            assert "reopened" in error["message"]
            assert error["details"] == []

            listing = client.get(f"/api/incomes?month_id={month_id}")
            salary_rows = [row for row in listing.json() if row["income_type"] == "salary"]
            assert len(salary_rows) == 1
            assert salary_rows[0]["id"] == original["id"]
            assert salary_rows[0]["gross_amount"] == original["gross_amount"]
            assert salary_rows[0]["net_amount"] == original["net_amount"]
    finally:
        database.engine.dispose()
