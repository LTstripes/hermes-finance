"""G08 acceptance: exercise the complete synthetic MVP control scenario over HTTP."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "g08_control.db")
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


def test_g08_mvp_control_scenario(client: TestClient) -> None:
    """Create, close, clone, update, close, compare, export and backup one MVP cycle."""
    health = client.get("/api/health")
    assert health.status_code == 200, health.text

    source = _created(
        client.post(
            "/api/months",
            json={"year": 2049, "month": 12, "snapshot_date": "2049-12-31"},
        )
    )
    source_id = source["id"]

    account = _created(
        client.post("/api/accounts", json={"name": "G08 Broker", "account_type": "brokerage"})
    )
    instrument = _created(
        client.post("/api/instruments", json={"name": "G08 Bond", "instrument_type": "bond"})
    )

    _created(
        client.post(
            "/api/positions",
            json={
                "reporting_month_id": source_id,
                "account_id": account["id"],
                "instrument_id": instrument["id"],
                "quantity": "10",
                "average_cost_per_unit": _rub("1000.00"),
                "market_price_per_unit": _rub("1100.00"),
                "price_source": "manual",
                "price_date": "2049-12-31",
            },
        )
    )
    deposit = _created(
        client.post(
            "/api/deposits",
            json={
                "reporting_month_id": source_id,
                "account_id": account["id"],
                "name": "G08 Deposit",
                "deposit_type": "deposit",
                "balance": _rub("100000.00"),
                "annual_rate": "12.00",
                "actual_interest_received": _rub("500.00"),
            },
        )
    )
    assert deposit["expected_monthly_interest"] == _rub("1000.00")

    salary = _created(
        client.post(
            "/api/incomes",
            json={
                "reporting_month_id": source_id,
                "income_type": "salary",
                "name": "G08 Salary",
                "gross_amount": _rub("100000.00"),
                "tax_amount": _rub("13000.00"),
                "net_amount": _rub("87000.00"),
                "is_recurring": True,
            },
        )
    )
    _created(
        client.post(
            "/api/incomes",
            json={
                "reporting_month_id": source_id,
                "income_type": "cashback",
                "name": "G08 Cashback",
                "gross_amount": _rub("1500.00"),
                "tax_amount": _rub("0.00"),
                "net_amount": _rub("1500.00"),
                "include_in_passive_income": False,
            },
        )
    )

    for flow_type, gross, net in (
        ("coupon", "1000.00", "870.00"),
        ("dividend", "800.00", "670.00"),
        ("interest", "500.00", "500.00"),
    ):
        _created(
            client.post(
                "/api/investment-flows",
                json={
                    "reporting_month_id": source_id,
                    "account_id": account["id"],
                    "instrument_id": instrument["id"],
                    "flow_type": flow_type,
                    "event_date": "2049-12-15",
                    "gross_amount": _rub(gross),
                    "tax_amount": _rub("130.00" if flow_type != "interest" else "0.00"),
                    "commission_amount": _rub("0.00"),
                    "net_amount": _rub(net),
                    "source": "manual",
                },
            )
        )

    _created(
        client.post(
            "/api/expenses",
            json={
                "reporting_month_id": source_id,
                "category": "G08 Mandatory expenses",
                "amount": _rub("20000.00"),
                "expense_type": "mandatory",
            },
        )
    )
    _created(
        client.post(
            "/api/debts",
            json={
                "reporting_month_id": source_id,
                "debt_type": "credit_card",
                "name": "G08 Credit card",
                "current_balance": _rub("45000.00"),
                "include_in_liquid_capital": True,
            },
        )
    )
    _created(
        client.post(
            "/api/properties",
            json={
                "reporting_month_id": source_id,
                "name": "G08 Apartment",
                "estimated_value": _rub("15000000.00"),
                "mortgage_balance": _rub("5000000.00"),
                "monthly_payment": _rub("75000.00"),
            },
        )
    )
    _created(
        client.post(
            "/api/comments",
            json={"reporting_month_id": source_id, "text": "G08 source month note"},
        )
    )

    source_dashboard = client.get(f"/api/months/{source_id}/dashboard")
    assert source_dashboard.status_code == 200, source_dashboard.text
    assert source_dashboard.json()["kpis"]["liquid_capital_net"]["amount"]

    closed_source = client.post(f"/api/months/{source_id}/close")
    assert closed_source.status_code == 200, closed_source.text
    assert closed_source.json()["status"] == "closed"

    target = _created(
        client.post(
            f"/api/months/{source_id}/clone",
            json={"year": 2050, "month": 1, "snapshot_date": "2050-01-31"},
        )
    )
    target_id = target["id"]
    assert target["status"] == "draft"

    target_salaries = _created(client.get(f"/api/incomes?month_id={target_id}"))
    assert len(target_salaries) == 1
    target_salary = target_salaries[0]
    assert target_salary["name"] == salary["name"]
    updated_salary = client.patch(
        f"/api/incomes/{target_salary['id']}",
        json={
            "gross_amount": _rub("120000.00"),
            "tax_amount": _rub("15600.00"),
            "net_amount": _rub("104400.00"),
        },
    )
    assert updated_salary.status_code == 200, updated_salary.text

    target_deposit = _created(client.get(f"/api/deposits?month_id={target_id}"))[0]
    updated_deposit = client.patch(
        f"/api/deposits/{target_deposit['id']}",
        headers={"If-Match": target_deposit["updated_at"]},
        json={"balance": _rub("120000.00"), "annual_rate": "13.00"},
    )
    assert updated_deposit.status_code == 200, updated_deposit.text

    target_position = _created(client.get(f"/api/positions?month_id={target_id}"))[0]
    updated_position = client.patch(
        f"/api/positions/{target_position['id']}",
        headers={"If-Match": target_position["updated_at"]},
        json={"quantity": "12", "market_price_per_unit": _rub("1250.00")},
    )
    assert updated_position.status_code == 200, updated_position.text

    target_comment = client.post(
        "/api/comments",
        json={"reporting_month_id": target_id, "text": "G08 target month review"},
    )
    assert target_comment.status_code == 201, target_comment.text

    target_preview = client.get(f"/api/months/{target_id}/dashboard")
    assert target_preview.status_code == 200, target_preview.text
    assert target_preview.json()["month"]["status"] == "draft"

    closed_target = client.post(f"/api/months/{target_id}/close")
    assert closed_target.status_code == 200, closed_target.text
    assert closed_target.json()["status"] == "closed"

    comparison = client.get(f"/api/months/{target_id}/dashboard")
    assert comparison.status_code == 200, comparison.text
    assert comparison.json()["month"]["status"] == "closed"

    markdown = client.post(f"/api/months/{target_id}/export/markdown")
    assert markdown.status_code == 200, markdown.text
    assert markdown.headers["content-type"] == "text/markdown; charset=utf-8"
    assert "G08 target month review" in markdown.text

    exported_json = client.post(f"/api/months/{target_id}/export/json")
    assert exported_json.status_code == 200, exported_json.text
    assert exported_json.headers["content-type"] == "application/json; charset=utf-8"
    json_body = exported_json.json()
    assert json_body["schema_version"] == "1.0"
    assert json_body["raw"]["reporting_month"]["id"] == target_id

    backup = client.post("/api/backups")
    assert backup.status_code == 201, backup.text
    backup_body = backup.json()
    assert backup_body["id"]
    assert backup_body["size_bytes"] > 0

    backups = client.get("/api/backups")
    assert backups.status_code == 200, backups.text
    assert any(item["id"] == backup_body["id"] for item in backups.json())
