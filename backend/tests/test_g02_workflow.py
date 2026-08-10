"""End-to-end API integration workflow for G02.

The scenario crosses the HTTP boundary for the monthly workflow:
create month -> add data -> summary -> clone/reset -> close/reopen -> export.
All fixtures are synthetic and isolated in a temporary SQLite database.
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
    database = create_database(tmp_path / "g02_workflow.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _created(response) -> dict:
    assert response.status_code in {200, 201}, response.text
    return response.json()


def test_g02_monthly_workflow_through_http(client: TestClient) -> None:
    source = _created(
        client.post(
            "/api/months",
            json={"year": 2031, "month": 1, "snapshot_date": "2031-01-31"},
        )
    )
    source_id = source["id"]
    assert source["status"] == "draft"

    account = _created(
        client.post("/api/accounts", json={"name": "Synthetic Broker", "account_type": "brokerage"})
    )
    instrument = _created(
        client.post("/api/instruments", json={"name": "Synthetic Bond", "instrument_type": "bond"})
    )

    position = client.post(
        "/api/positions",
        json={
            "reporting_month_id": source_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "quantity": "10",
            "average_cost_per_unit": _rub("1000.00"),
            "market_price_per_unit": _rub("1100.00"),
            "price_source": "manual",
            "price_date": "2031-01-31",
        },
    )
    assert position.status_code == 201, position.text

    deposit = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": source_id,
            "account_id": account["id"],
            "name": "Synthetic Deposit",
            "deposit_type": "deposit",
            "balance": _rub("100000.00"),
            "annual_rate": "12.00",
            "actual_interest_received": _rub("500.00"),
        },
    )
    assert deposit.status_code == 201, deposit.text
    assert deposit.json()["expected_monthly_interest"] == _rub("1000.00")

    income = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": source_id,
            "income_type": "salary",
            "name": "Synthetic Salary",
            "gross_amount": _rub("100000.00"),
            "tax_amount": _rub("13000.00"),
            "net_amount": _rub("87000.00"),
            "is_recurring": True,
        },
    )
    assert income.status_code == 201, income.text

    flow = client.post(
        "/api/investment-flows",
        json={
            "reporting_month_id": source_id,
            "account_id": account["id"],
            "instrument_id": instrument["id"],
            "flow_type": "coupon",
            "event_date": "2031-01-15",
            "gross_amount": _rub("1000.00"),
            "tax_amount": _rub("130.00"),
            "commission_amount": _rub("0.00"),
            "net_amount": _rub("870.00"),
            "source": "manual",
        },
    )
    assert flow.status_code == 201, flow.text

    expense = client.post(
        "/api/expenses",
        json={
            "reporting_month_id": source_id,
            "category": "Synthetic Rent",
            "amount": _rub("20000.00"),
            "expense_type": "mandatory",
        },
    )
    assert expense.status_code == 201, expense.text

    comment = client.post(
        "/api/comments",
        json={"reporting_month_id": source_id, "text": "Synthetic month note"},
    )
    assert comment.status_code == 201, comment.text

    summary = client.get(f"/api/months/{source_id}/summary")
    assert summary.status_code == 200, summary.text
    summary_body = summary.json()
    assert summary_body["month"]["id"] == source_id
    assert summary_body["month"]["status"] == "draft"
    assert summary_body["liquid_capital"]["liquid_capital_net"] == _rub("111000.00")
    assert summary_body["passive_income_actual"] == _rub("1370.00")
    assert summary_body["coverage"]["mandatory_expenses"] == _rub("20000.00")
    assert summary_body["cash_balance"]["breakdown"]["salary_net"] == _rub("87000.00")

    source_closed = client.post(f"/api/months/{source_id}/close")
    assert source_closed.status_code == 200, source_closed.text

    cloned = client.post(
        f"/api/months/{source_id}/clone",
        json={"year": 2031, "month": 2, "snapshot_date": "2031-02-28"},
    )
    target = _created(cloned)
    target_id = target["id"]
    assert target["status"] == "draft"

    target_positions = client.get(f"/api/positions?month_id={target_id}")
    assert target_positions.status_code == 200
    assert len(target_positions.json()) == 1

    target_deposits = client.get(f"/api/deposits?month_id={target_id}")
    assert target_deposits.status_code == 200
    assert len(target_deposits.json()) == 1
    assert target_deposits.json()[0]["actual_interest_received"] == _rub("0.00")
    assert target_deposits.json()[0]["expected_monthly_interest"] == _rub("1000.00")

    target_incomes = client.get(f"/api/incomes?month_id={target_id}")
    assert target_incomes.status_code == 200
    assert len(target_incomes.json()) == 1
    assert target_incomes.json()[0]["income_type"] == "salary"
    assert target_incomes.json()[0]["received_at"] is None

    target_flows = client.get(f"/api/investment-flows?month_id={target_id}")
    assert target_flows.status_code == 200
    assert target_flows.json() == []

    target_comments = client.get(f"/api/comments?month_id={target_id}")
    assert target_comments.status_code == 200
    assert target_comments.json() == []

    closed = client.post(f"/api/months/{target_id}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"

    reopened = client.post(f"/api/months/{target_id}/reopen")
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "draft"

    exported = client.post(f"/api/months/{target_id}/export/markdown")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"] == "text/markdown; charset=utf-8"
    assert exported.headers["content-disposition"] == (
        'attachment; filename="finance_report_2031-02.md"'
    )
    report = exported.content.decode("utf-8")
    assert report.startswith("# Финансовый отчёт — Февраль 2031\n")
    assert "## 5. Доходы" in report
    assert "Synthetic Salary" in report
