"""M03-03 regression coverage for canonical monthly salary cardinality."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.database import Database, create_database
from hermes_finance.domain import IncomeType, RubleAmount
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
from hermes_finance.services.salary import actual_net_for_month, calculate_salary_tax


def _session(tmp_path: Path) -> tuple[Session, Database]:
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


def _api_money(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _salary_payload(gross: str, tax: str, net: str) -> dict[str, dict[str, str]]:
    return {
        "gross_amount": _api_money(gross),
        "tax_amount": _api_money(tax),
        "net_amount": _api_money(net),
    }


def _is_month_writer(statement: str) -> bool:
    normalized = " ".join(statement.casefold().split())
    return normalized.startswith("update reporting_months set status = status where id =")


def _run_serialized_api_race(
    database: Database,
    *,
    first: tuple[str, str, dict[str, object]],
    second: tuple[str, str, dict[str, object]],
) -> tuple[object, object]:
    """Force the second request to reach the shared SQLite writer reservation."""
    app = create_app(database)
    first_reservation_reached = Event()
    second_reservation_attempted = Event()

    def tagged_session(request: Request):
        with database.session_factory() as session:
            session.info["salary_cardinality_race_writer"] = request.headers.get(
                "X-Salary-Cardinality-Writer"
            )
            yield session

    app.dependency_overrides[session_for_request] = tagged_session

    def tag_connection(session: Session, transaction: object, connection: object) -> None:
        del transaction
        role = session.info.get("salary_cardinality_race_writer")
        if role is None:
            connection.info.pop("salary_cardinality_race_writer", None)
        else:
            connection.info["salary_cardinality_race_writer"] = role

    def before_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del cursor, parameters, context, executemany
        if connection.info.get("salary_cardinality_race_writer") == "second" and _is_month_writer(
            statement
        ):
            second_reservation_attempted.set()

    def after_cursor_execute(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del cursor, parameters, context, executemany
        if connection.info.get("salary_cardinality_race_writer") == "first" and _is_month_writer(
            statement
        ):
            first_reservation_reached.set()
            assert second_reservation_attempted.wait(10)

    event.listen(Session, "after_begin", tag_connection)
    event.listen(database.engine, "before_cursor_execute", before_cursor_execute)
    event.listen(database.engine, "after_cursor_execute", after_cursor_execute)

    def send(writer: str, request_data: tuple[str, str, dict[str, object]]):
        method, path, payload = request_data
        with TestClient(app) as client:
            return client.request(
                method,
                path,
                json=payload,
                headers={"X-Salary-Cardinality-Writer": writer},
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(send, "first", first)
            assert first_reservation_reached.wait(10)
            second_future = executor.submit(send, "second", second)
            first_response = first_future.result(timeout=10)
            second_response = second_future.result(timeout=10)
        return first_response, second_response
    finally:
        event.remove(database.engine, "after_cursor_execute", after_cursor_execute)
        event.remove(database.engine, "before_cursor_execute", before_cursor_execute)
        event.remove(Session, "after_begin", tag_connection)
        app.dependency_overrides.pop(session_for_request, None)


def _assert_winning_salary(
    database: Database,
    *,
    month_id: int,
    payload: dict[str, dict[str, str]],
    expected_id: int | None = None,
) -> int:
    expected = {
        field: RubleAmount.from_api(payload[field]["amount"]).kopecks
        for field in ("gross_amount", "tax_amount", "net_amount")
    }
    with database.session_factory() as session:
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
        assert len(rows) == 1
        winner = rows[0]
        assert winner.gross_amount_kopecks == expected["gross_amount"]
        assert winner.tax_amount_kopecks == expected["tax_amount"]
        assert winner.net_amount_kopecks == expected["net_amount"]
        if expected_id is not None:
            assert winner.id == expected_id

        tax = calculate_salary_tax(session, month_id)
        assert sum(part.taxable_kopecks for part in tax.parts) == expected["gross_amount"]
        assert tax.tax_kopecks == expected["tax_amount"]
        assert actual_net_for_month(session, month_id) == RubleAmount(expected["net_amount"])
        return winner.id


@pytest.mark.parametrize(
    ("second_payload", "winner_payload"),
    [
        pytest.param(
            _salary_payload("100000.00", "13000.00", "87000.00"),
            _salary_payload("100000.00", "13000.00", "87000.00"),
            id="identical-saves",
        ),
        pytest.param(
            _salary_payload("200000.00", "26000.00", "174000.00"),
            _salary_payload("200000.00", "26000.00", "174000.00"),
            id="different-saves",
        ),
    ],
)
def test_concurrent_salary_saves_into_empty_month_are_serialized(
    tmp_path: Path,
    second_payload: dict[str, dict[str, str]],
    winner_payload: dict[str, dict[str, str]],
) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session, year=2031, month=1)
        session.close()

        path = f"/api/incomes/salary/{month_id}"
        first_response, second_response = _run_serialized_api_race(
            database,
            first=("PUT", path, _salary_payload("100000.00", "13000.00", "87000.00")),
            second=("PUT", path, second_payload),
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json()["id"] == second_response.json()["id"]
        winner_id = _assert_winning_salary(database, month_id=month_id, payload=winner_payload)
        assert winner_id == first_response.json()["id"]
    finally:
        session.close()
        database.engine.dispose()


def test_concurrent_replacements_of_existing_salary_leave_one_winner(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session, year=2031, month=1)
        original = replace_salary_entry(
            session,
            month_id,
            gross_amount="50000.00",
            tax_amount="6500.00",
            net_amount="43500.00",
        )
        assert original is not None
        session.close()

        path = f"/api/incomes/salary/{month_id}"
        first_payload = _salary_payload("100000.00", "13000.00", "87000.00")
        winner_payload = _salary_payload("200000.00", "26000.00", "174000.00")
        first_response, second_response = _run_serialized_api_race(
            database,
            first=("PUT", path, first_payload),
            second=("PUT", path, winner_payload),
        )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json()["id"] == original.id
        assert second_response.json()["id"] == original.id
        _assert_winning_salary(
            database,
            month_id=month_id,
            payload=winner_payload,
            expected_id=original.id,
        )
    finally:
        session.close()
        database.engine.dispose()


def test_generic_salary_create_and_conversion_cannot_race_to_two_rows(tmp_path: Path) -> None:
    session, database = _session(tmp_path)
    try:
        month_id = _month(session, year=2031, month=1)
        bonus = create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.BONUS,
            name="Synthetic bonus",
            gross_amount="1000.00",
            tax_amount="130.00",
            net_amount="870.00",
        )
        session.close()

        salary_payload = {
            "reporting_month_id": month_id,
            "income_type": IncomeType.SALARY.value,
            "name": "Salary",
            **_salary_payload("100000.00", "13000.00", "87000.00"),
        }
        first_response, second_response = _run_serialized_api_race(
            database,
            first=("POST", "/api/incomes", salary_payload),
            second=("PATCH", f"/api/incomes/{bonus.id}", {"income_type": "salary"}),
        )

        assert first_response.status_code == 201
        assert second_response.status_code == 422
        error = second_response.json()["error"]
        assert error["code"] == "unprocessable"
        assert "already has a salary" in error["message"]
        winner_id = _assert_winning_salary(
            database,
            month_id=month_id,
            payload=_salary_payload("100000.00", "13000.00", "87000.00"),
        )
        assert winner_id == first_response.json()["id"]
        with database.session_factory() as check_session:
            unchanged_bonus = check_session.get(IncomeEntry, bonus.id)
            assert unchanged_bonus is not None
            assert unchanged_bonus.income_type == IncomeType.BONUS.value
            assert unchanged_bonus.gross_amount_kopecks == 100_000
    finally:
        session.close()
        database.engine.dispose()


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
