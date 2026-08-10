"""API tests for D06 financial-event endpoints.

Covers incomes, investment flows, expected flows, expenses, savings, debts,
properties and comments through the HTTP boundary. Each test builds a fresh
SQLite database via ``create_database`` + ``create_app``.
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
    database = create_database(tmp_path / "d06_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _assert_error(body: dict, code: str) -> None:
    assert set(body) == {"error"}
    error = body["error"]
    assert set(error) == {"code", "message", "details"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], list)


def _month(client: TestClient, year: int = 2031, month: int = 1) -> int:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": f"{year}-{month:02d}-15"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _account(client: TestClient, name: str = "Брокер", account_type: str = "brokerage") -> int:
    response = client.post(
        "/api/accounts",
        json={"name": name, "account_type": account_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _instrument(client: TestClient, name: str = "ОФЗ", instrument_type: str = "bond") -> int:
    response = client.post(
        "/api/instruments",
        json={"name": name, "instrument_type": instrument_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --- incomes ---


def test_income_crud_and_cashback_flag(client: TestClient) -> None:
    month_id = _month(client)
    created = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "salary",
            "name": "Зарплата",
            "gross_amount": _rub("200000.00"),
            "tax_amount": _rub("26000.00"),
            "net_amount": _rub("174000.00"),
            "is_recurring": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["income_type"] == "salary"
    assert body["gross_amount"] == _rub("200000.00")
    assert body["net_amount"] == _rub("174000.00")
    assert body["include_in_passive_income"] is False
    entry_id = body["id"]

    listing = client.get(f"/api/incomes?month_id={month_id}")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    patched = client.patch(
        f"/api/incomes/{entry_id}",
        json={"name": "Зарплата net"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Зарплата net"

    cashback = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "cashback",
            "name": "Кэшбэк",
            "gross_amount": _rub("500.00"),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub("500.00"),
        },
    )
    assert cashback.status_code == 201
    assert cashback.json()["include_in_passive_income"] is False

    cashback_passive = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "cashback",
            "name": "Кэшбэк bad",
            "gross_amount": _rub("500.00"),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub("500.00"),
            "include_in_passive_income": True,
        },
    )
    assert cashback_passive.status_code == 422
    _assert_error(cashback_passive.json(), "unprocessable")

    bad_type = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "bogus",
            "name": "x",
            "gross_amount": _rub("1.00"),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub("1.00"),
        },
    )
    assert bad_type.status_code == 422
    _assert_error(bad_type.json(), "unprocessable")

    deleted = client.delete(f"/api/incomes/{entry_id}")
    assert deleted.status_code == 204
    missing = client.get(f"/api/incomes/{entry_id}")
    assert missing.status_code == 404
    _assert_error(missing.json(), "not_found")


@pytest.mark.parametrize("income_type", ["salary", "bonus", "side_income", "cashback"])
def test_income_api_rejects_forbidden_passive_types(client: TestClient, income_type: str) -> None:
    month_id = _month(client, year=2031, month=2)
    response = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": income_type,
            "name": "Forbidden passive",
            "gross_amount": _rub("100.00"),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub("100.00"),
            "include_in_passive_income": True,
        },
    )

    assert response.status_code == 422
    _assert_error(response.json(), "unprocessable")


# --- investment flows ---


def test_investment_flow_crud_and_net_validation(client: TestClient) -> None:
    month_id = _month(client)
    account_id = _account(client)
    instrument_id = _instrument(client)

    created = client.post(
        "/api/investment-flows",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "flow_type": "dividend",
            "event_date": "2031-01-10",
            "gross_amount": _rub("1000.00"),
            "tax_amount": _rub("130.00"),
            "commission_amount": _rub("0.00"),
            "net_amount": _rub("870.00"),
            "source": "manual",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["flow_type"] == "dividend"
    assert body["net_amount"] == _rub("870.00")
    flow_id = body["id"]

    listing = client.get(f"/api/investment-flows?month_id={month_id}")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    bad_net = client.post(
        "/api/investment-flows",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "flow_type": "coupon",
            "event_date": "2031-01-11",
            "gross_amount": _rub("100.00"),
            "tax_amount": _rub("0.00"),
            "commission_amount": _rub("0.00"),
            "net_amount": _rub("50.00"),
            "source": "manual",
        },
    )
    assert bad_net.status_code == 422
    _assert_error(bad_net.json(), "unprocessable")

    patched = client.patch(
        f"/api/investment-flows/{flow_id}",
        json={"notes": "дивиденд ОФЗ"},
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "дивиденд ОФЗ"

    deleted = client.delete(f"/api/investment-flows/{flow_id}")
    assert deleted.status_code == 204


# --- expected flows ---


def test_expected_flow_crud_and_filters(client: TestClient) -> None:
    month_id = _month(client)
    account_id = _account(client)
    instrument_id = _instrument(client)

    created = client.post(
        "/api/expected-flows",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "flow_type": "coupon",
            "expected_date": "2031-03-01",
            "gross_amount": _rub("5000.00"),
            "expected_tax_amount": _rub("650.00"),
            "expected_net_amount": _rub("4350.00"),
            "source": "manual",
            "source_as_of_date": "2031-01-15",
            "forecast_version": "v1",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["expected_net_amount"] == _rub("4350.00")
    assert body["forecast_version"] == "v1"
    assert body["is_approximate"] is False
    flow_id = body["id"]

    listing = client.get(f"/api/expected-flows?month_id={month_id}&forecast_version=v1")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    empty = client.get(f"/api/expected-flows?month_id={month_id}&forecast_version=v2")
    assert empty.status_code == 200
    assert empty.json() == []

    deleted = client.delete(f"/api/expected-flows/{flow_id}")
    assert deleted.status_code == 204
    missing = client.get(f"/api/expected-flows/{flow_id}")
    assert missing.status_code == 404


# --- expenses + savings ---


def test_expense_and_saving_crud(client: TestClient) -> None:
    month_id = _month(client)

    expense = client.post(
        "/api/expenses",
        json={
            "reporting_month_id": month_id,
            "category": "ЖКХ",
            "amount": _rub("12000.00"),
            "expense_type": "mandatory",
            "is_recurring": True,
        },
    )
    assert expense.status_code == 201, expense.text
    expense_id = expense.json()["id"]
    assert expense.json()["amount"] == _rub("12000.00")

    filtered = client.get(f"/api/expenses?month_id={month_id}&expense_type=mandatory")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    comfort = client.get(f"/api/expenses?month_id={month_id}&expense_type=comfortable")
    assert comfort.status_code == 200
    assert comfort.json() == []

    saving = client.post(
        "/api/savings",
        json={
            "reporting_month_id": month_id,
            "destination": "Подушка",
            "amount": _rub("30000.00"),
        },
    )
    assert saving.status_code == 201, saving.text
    saving_id = saving.json()["id"]
    assert saving.json()["destination"] == "Подушка"

    savings_list = client.get(f"/api/savings?month_id={month_id}")
    assert savings_list.status_code == 200
    assert len(savings_list.json()) == 1

    assert client.delete(f"/api/expenses/{expense_id}").status_code == 204
    assert client.delete(f"/api/savings/{saving_id}").status_code == 204


# --- debts + properties ---


def test_debt_and_property_crud(client: TestClient) -> None:
    month_id = _month(client)

    debt = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Карта",
            "current_balance": _rub("45000.00"),
            "include_in_liquid_capital": True,
        },
    )
    assert debt.status_code == 201, debt.text
    debt_id = debt.json()["id"]
    assert debt.json()["current_balance"] == _rub("45000.00")

    patched_debt = client.patch(
        f"/api/debts/{debt_id}",
        json={"current_balance": _rub("40000.00")},
    )
    assert patched_debt.status_code == 200
    assert patched_debt.json()["current_balance"] == _rub("40000.00")

    prop = client.post(
        "/api/properties",
        json={
            "reporting_month_id": month_id,
            "name": "Квартира",
            "estimated_value": _rub("15000000.00"),
            "mortgage_balance": _rub("5000000.00"),
            "monthly_payment": _rub("75000.00"),
        },
    )
    assert prop.status_code == 201, prop.text
    prop_id = prop.json()["id"]
    assert prop.json()["estimated_value"] == _rub("15000000.00")
    assert prop.json()["mortgage_balance"] == _rub("5000000.00")

    props = client.get(f"/api/properties?month_id={month_id}")
    assert props.status_code == 200
    assert len(props.json()) == 1

    assert client.delete(f"/api/debts/{debt_id}").status_code == 204
    assert client.delete(f"/api/properties/{prop_id}").status_code == 204
    assert client.get(f"/api/debts/{debt_id}").status_code == 404


# --- comments ---


def test_comments_crud_and_move(client: TestClient) -> None:
    month_id = _month(client)

    first = client.post(
        "/api/comments",
        json={"reporting_month_id": month_id, "text": "Первый"},
    )
    second = client.post(
        "/api/comments",
        json={"reporting_month_id": month_id, "text": "Второй"},
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_id = first.json()["id"]
    second_id = second.json()["id"]
    assert first.json()["position"] == 1
    assert second.json()["position"] == 2

    listing = client.get(f"/api/comments?month_id={month_id}")
    assert listing.status_code == 200
    assert [item["text"] for item in listing.json()] == ["Первый", "Второй"]

    moved = client.post(
        f"/api/comments/{second_id}/move",
        json={"new_position": 1},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["position"] == 1

    after_move = client.get(f"/api/comments?month_id={month_id}")
    texts = [item["text"] for item in after_move.json()]
    assert texts == ["Второй", "Первый"]

    patched = client.patch(
        f"/api/comments/{first_id}",
        json={"text": "Первый обновлён"},
    )
    assert patched.status_code == 200
    assert patched.json()["text"] == "Первый обновлён"

    assert client.delete(f"/api/comments/{first_id}").status_code == 204
    remaining = client.get(f"/api/comments?month_id={month_id}")
    assert len(remaining.json()) == 1
    assert remaining.json()[0]["text"] == "Второй"
    assert remaining.json()[0]["position"] == 1


def test_closed_month_blocks_writes(client: TestClient) -> None:
    month_id = _month(client)
    client.post(f"/api/months/{month_id}/close")

    blocked = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": month_id,
            "income_type": "salary",
            "name": "поздно",
            "gross_amount": _rub("100.00"),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub("100.00"),
        },
    )
    assert blocked.status_code == 409
    _assert_error(blocked.json(), "conflict")


def test_extra_field_rejected(client: TestClient) -> None:
    month_id = _month(client)
    response = client.post(
        "/api/expenses",
        json={
            "reporting_month_id": month_id,
            "category": "x",
            "amount": _rub("1.00"),
            "expense_type": "other",
            "surprise": True,
        },
    )
    assert response.status_code == 422
    _assert_error(response.json(), "unprocessable")
