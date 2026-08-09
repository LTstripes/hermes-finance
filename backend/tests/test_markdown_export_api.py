from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


@pytest.fixture
def app_context(tmp_path: Path) -> Generator[tuple[TestClient, Database], None, None]:
    database = create_database(tmp_path / "markdown_export_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _create_month(client: TestClient) -> int:
    response = client.post(
        "/api/months",
        json={"year": 2032, "month": 7, "snapshot_date": "2032-07-31"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _table_counts(database: Database) -> dict[str, int]:
    with database.session_factory() as session:
        return {
            table.name: int(session.scalar(select(func.count()).select_from(table)) or 0)
            for table in Base.metadata.sorted_tables
        }


def test_markdown_export_downloads_stable_utf8_report_with_safe_filename(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    month_id = _create_month(client)
    assert client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "salary",
            "name": "Синтетическая зарплата",
            "gross_amount": {"amount": "100000.00", "currency": "RUB"},
            "tax_amount": {"amount": "13000.00", "currency": "RUB"},
            "net_amount": {"amount": "87000.00", "currency": "RUB"},
        },
    ).status_code == 201
    assert client.post(
        "/api/expenses",
        json={
            "reporting_month_id": month_id,
            "category": "Синтетическая аренда",
            "amount": {"amount": "20000.00", "currency": "RUB"},
            "expense_type": "mandatory",
        },
    ).status_code == 201
    assert client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Синтетическая карта",
            "current_balance": {"amount": "5000.00", "currency": "RUB"},
        },
    ).status_code == 201
    assert client.post(
        "/api/comments",
        json={"reporting_month_id": month_id, "text": "Синтетический комментарий"},
    ).status_code == 201

    response = client.post(f"/api/months/{month_id}/export/markdown")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="finance_report_2032-07.md"'
    )
    body = response.content.decode("utf-8")
    assert body.startswith("# Финансовый отчёт — Июль 2032\n")
    assert "## 5. Доходы" in body
    assert "Синтетическая зарплата" in body
    assert "Синтетический комментарий" in body


def test_markdown_export_missing_month_uses_unified_not_found_error(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context

    response = client.post("/api/months/999999/export/markdown")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["details"] == []


def test_markdown_export_does_not_persist_read_path_defaults(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    month_id = _create_month(client)
    before = _table_counts(database)

    response = client.post(f"/api/months/{month_id}/export/markdown")

    assert response.status_code == 200, response.text
    assert _table_counts(database) == before
