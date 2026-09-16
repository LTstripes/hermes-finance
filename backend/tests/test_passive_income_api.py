"""API tests for the Home passive-income history read model."""

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
    database = create_database(tmp_path / "passive_income_api.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _month(client: TestClient, *, year: int, month: int) -> int:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": f"{year}-{month:02d}-28"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _account(client: TestClient, *, name: str, account_type: str) -> int:
    response = client.post(
        "/api/accounts",
        json={"name": name, "account_type": account_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _instrument(client: TestClient, *, name: str, instrument_type: str) -> int:
    response = client.post(
        "/api/instruments",
        json={"name": name, "instrument_type": instrument_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _deposit_interest(client: TestClient, *, month_id: int, account_id: int, amount: str) -> None:
    response = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "name": "Synthetic deposit",
            "deposit_type": "deposit",
            "balance": _rub("100000.00"),
            "annual_rate": "10.00",
            "actual_interest_received": _rub(amount),
        },
    )
    assert response.status_code == 201, response.text


def _investment_flow(
    client: TestClient,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: str,
    net_amount: str,
) -> None:
    response = client.post(
        "/api/investment-flows",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "flow_type": flow_type,
            "event_date": "2031-05-15",
            "gross_amount": _rub(net_amount),
            "tax_amount": _rub("0.00"),
            "commission_amount": _rub("0.00"),
            "net_amount": _rub(net_amount),
            "source": "synthetic",
        },
    )
    assert response.status_code == 201, response.text


def test_passive_income_history_is_closed_only_and_exposes_selected_buckets(
    client: TestClient,
) -> None:
    deposit = _account(client, name="Synthetic deposit", account_type="deposit")
    brokerage = _account(client, name="Synthetic brokerage", account_type="brokerage")
    bond = _instrument(client, name="Synthetic bond", instrument_type="bond")
    stock = _instrument(client, name="Synthetic stock", instrument_type="stock")

    closed_id = _month(client, year=2031, month=5)
    _deposit_interest(client, month_id=closed_id, account_id=deposit, amount="500.00")
    _investment_flow(
        client,
        month_id=closed_id,
        account_id=brokerage,
        instrument_id=bond,
        flow_type="coupon",
        net_amount="860.00",
    )
    _investment_flow(
        client,
        month_id=closed_id,
        account_id=brokerage,
        instrument_id=stock,
        flow_type="dividend",
        net_amount="435.00",
    )
    other = client.post(
        "/api/incomes",
        json={
            "reporting_month_id": closed_id,
            "income_type": "other",
            "name": "Synthetic other capital income",
            "gross_amount": _rub("200.00"),
            "tax_amount": _rub("0.00"),
            "net_amount": _rub("200.00"),
            "include_in_passive_income": True,
        },
    )
    assert other.status_code == 201, other.text
    # These recorded cash entries must not leak into passive-income buckets.
    for income_type in ("salary", "bonus", "cashback"):
        excluded = client.post(
            "/api/incomes",
            json={
                "reporting_month_id": closed_id,
                "income_type": income_type,
                "name": f"Synthetic {income_type}",
                "gross_amount": _rub("900.00"),
                "tax_amount": _rub("0.00"),
                "net_amount": _rub("900.00"),
            },
        )
        assert excluded.status_code == 201, excluded.text
    _investment_flow(
        client,
        month_id=closed_id,
        account_id=brokerage,
        instrument_id=bond,
        flow_type="redemption",
        net_amount="10000.00",
    )
    close = client.post(f"/api/months/{closed_id}/close")
    assert close.status_code == 200, close.text

    draft_id = _month(client, year=2031, month=7)
    _deposit_interest(client, month_id=draft_id, account_id=deposit, amount="999.00")

    response = client.get("/api/analytics/passive-income")
    assert response.status_code == 200, response.text
    body = response.json()

    assert [point["reporting_month_id"] for point in body["points"]] == [closed_id]
    assert body["latest_closed_report_id"] == closed_id
    assert body["average"] == {
        "average": _rub("1995.00"),
        "count_months": 1,
        "target_window_months": 12,
        "is_complete_12m": False,
        "configured_start_month": None,
        "months_used": ["2031-05"],
    }
    assert body["points"][0]["passive_income_actual"] == _rub("1995.00")
    assert body["points"][0]["included_in_average_window"] is True

    selected = body["selected_report"]
    assert selected["reporting_month_id"] == closed_id
    assert selected["passive_income_actual"] == _rub("1995.00")
    assert selected["breakdown"] == {
        "deposit_interest": _rub("500.00"),
        "bond_coupons": _rub("860.00"),
        "dividends": _rub("435.00"),
        "other_capital_income": _rub("200.00"),
        "total_net_passive_income": _rub("1995.00"),
    }

    explicitly_selected = client.get(
        f"/api/analytics/passive-income?reporting_month_id={closed_id}"
    )
    assert explicitly_selected.status_code == 200, explicitly_selected.text
    assert explicitly_selected.json()["selected_report"] == selected

    draft_response = client.get(f"/api/analytics/passive-income?reporting_month_id={draft_id}")
    assert draft_response.status_code == 404, draft_response.text
    assert draft_response.json()["error"]["code"] == "not_found"


def test_passive_income_history_distinguishes_empty_from_closed_zero(client: TestClient) -> None:
    empty = client.get("/api/analytics/passive-income")
    assert empty.status_code == 200, empty.text
    assert empty.json()["points"] == []
    assert empty.json()["selected_report"] is None
    assert empty.json()["latest_closed_report_id"] is None
    assert empty.json()["average"]["average"] == _rub("0.00")
    assert empty.json()["average"]["count_months"] == 0

    zero_id = _month(client, year=2031, month=5)
    close = client.post(f"/api/months/{zero_id}/close")
    assert close.status_code == 200, close.text

    zero = client.get("/api/analytics/passive-income")
    assert zero.status_code == 200, zero.text
    body = zero.json()
    assert len(body["points"]) == 1
    assert body["points"][0]["passive_income_actual"] == _rub("0.00")
    assert body["average"]["count_months"] == 1
    assert body["selected_report"]["breakdown"]["total_net_passive_income"] == _rub("0.00")
