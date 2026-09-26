"""API tests for R03-12 capital composition history."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, PositionSnapshot
from hermes_finance.services import capital_composition as capital_composition_service
from hermes_finance.services.positions import update_position_snapshot
from hermes_finance.services.reporting_months import reopen_reporting_month


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database = create_database(tmp_path / "capital_composition.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as test_client:
            yield test_client
    finally:
        database.engine.dispose()


def _rub(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _create_month(client: TestClient, *, year: int, month: int, snapshot_date: str) -> int:
    response = client.post(
        "/api/months",
        json={"year": year, "month": month, "snapshot_date": snapshot_date},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_position(
    client: TestClient,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    amount: str,
    price_date: str,
) -> None:
    response = client.post(
        "/api/positions",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "instrument_id": instrument_id,
            "quantity": "1",
            "average_cost_per_unit": _rub("1.00"),
            "market_price_per_unit": _rub(amount),
            "price_source": "manual",
            "price_date": price_date,
        },
    )
    assert response.status_code == 201, response.text


def _create_cash(
    client: TestClient,
    month_id: int,
    amount: str,
    *,
    account_id: int | None = None,
) -> None:
    response = client.post(
        "/api/cash-balances",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "name": f"Cash {month_id}",
            "amount": _rub(amount),
        },
    )
    assert response.status_code == 201, response.text


def _create_deposit(client: TestClient, month_id: int, account_id: int, amount: str) -> None:
    response = client.post(
        "/api/deposits",
        json={
            "reporting_month_id": month_id,
            "account_id": account_id,
            "name": f"Deposit {month_id}",
            "deposit_type": "deposit",
            "balance": _rub(amount),
            "annual_rate": "0.00",
            "actual_interest_received": _rub("0.00"),
        },
    )
    assert response.status_code == 201, response.text


def _create_debt(client: TestClient, month_id: int, amount: str) -> None:
    response = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": f"Debt {month_id}",
            "current_balance": _rub(amount),
            "include_in_liquid_capital": True,
        },
    )
    assert response.status_code == 201, response.text


def _comparison(client: TestClient) -> dict[str, object]:
    response = client.get("/api/analytics/closed-report-comparison")
    assert response.status_code == 200, response.text
    return response.json()


def test_known_capital_subtotal_carries_account_coverage_through_all_read_models(
    client: TestClient,
) -> None:
    account_a = client.post(
        "/api/accounts", json={"name": "Known account", "account_type": "cash"}
    ).json()["id"]
    account_b = client.post(
        "/api/accounts", json={"name": "Required account", "account_type": "cash"}
    ).json()["id"]
    first = _create_month(client, year=2033, month=1, snapshot_date="2033-01-31")
    _create_cash(client, first, "100.00", account_id=account_a)
    _create_cash(client, first, "0.00", account_id=account_b)
    assert client.post(f"/api/months/{first}/close").status_code == 200

    second = _create_month(client, year=2033, month=2, snapshot_date="2033-02-28")
    _create_cash(client, second, "120.00", account_id=account_a)
    _create_cash(client, second, "5.00")  # Synthetic cash contributes, but cannot cover B.
    assert client.post(f"/api/months/{second}/close").status_code == 200

    history = client.get("/api/analytics/capital-composition").json()["points"]
    assert [point["liquid_capital_net"] for point in history] == [_rub("100.00"), _rub("125.00")]
    assert history[0]["portfolio_source_coverage"] == {
        "status": "complete",
        "reason_codes": [],
        "missing_account_ids": [],
    }
    partial = history[1]["portfolio_source_coverage"]
    assert partial == {
        "status": "partial",
        "reason_codes": ["active_account_snapshot_missing"],
        "missing_account_ids": [account_b],
    }

    comparison = _comparison(client)
    assert comparison["current"]["portfolio_source_coverage"] == partial
    assert comparison["previous"]["portfolio_source_coverage"]["status"] == "complete"
    assert comparison["liquid_capital_net_delta"] == _rub("25.00")
    assert comparison["liquid_capital_net_delta_coverage"]["status"] == "partial"
    assert comparison["liquid_capital_net_delta_coverage"]["reason_codes"] == [
        "active_account_snapshot_missing"
    ]

    summary = client.get(f"/api/months/{second}/summary").json()
    assert summary["liquid_capital"]["liquid_capital_net"] == _rub("125.00")
    assert summary["liquid_capital"]["portfolio_source_coverage"] == partial
    assert summary["liquid_capital_delta"] == _rub("25.00")
    assert summary["liquid_capital_delta_coverage"]["status"] == "partial"

    dashboard = client.get(f"/api/months/{second}/dashboard").json()
    assert dashboard["kpis"]["liquid_capital_net"] == _rub("125.00")
    assert dashboard["kpis"]["portfolio_source_coverage"] == partial
    assert dashboard["historical_series"][-1]["portfolio_source_coverage"] == partial


def test_closed_history_uses_one_snapshot_when_month_is_reopened_mid_read(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = client.post(
        "/api/accounts",
        json={"name": "Snapshot account", "account_type": "brokerage"},
    ).json()["id"]
    instrument_id = client.post(
        "/api/instruments",
        json={"name": "Snapshot stock", "instrument_type": "stock"},
    ).json()["id"]
    month_id = _create_month(client, year=2032, month=2, snapshot_date="2032-02-29")
    _create_position(
        client,
        month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        amount="100.00",
        price_date="2032-02-29",
    )
    closed = client.post(f"/api/months/{month_id}/close")
    assert closed.status_code == 200, closed.text

    database = client.app.state.database
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"

    real_liquid_capital_for_months = capital_composition_service.liquid_capital_for_months
    writer_committed = False

    def interleaved_liquid_capital_for_months(*args, **kwargs):
        nonlocal writer_committed
        if not writer_committed:
            writer_committed = True
            with database.session_factory() as writer:
                reopen_reporting_month(writer, month_id)
                position_id = writer.scalar(
                    select(PositionSnapshot.id).where(
                        PositionSnapshot.reporting_month_id == month_id
                    )
                )
                assert position_id is not None
                update_position_snapshot(
                    writer,
                    position_id,
                    market_price_per_unit="200.00",
                )
        return real_liquid_capital_for_months(*args, **kwargs)

    monkeypatch.setattr(
        capital_composition_service,
        "liquid_capital_for_months",
        interleaved_liquid_capital_for_months,
    )

    response = client.get("/api/analytics/capital-composition")
    assert response.status_code == 200, response.text
    points = response.json()["points"]
    assert len(points) == 1
    point = points[0]
    allocation = {item["asset_class"]: item["amount"] for item in point["allocation"]}
    assert point["liquid_assets_total"] == _rub("100.00")
    assert point["liquid_capital_net"] == _rub("100.00")
    assert allocation["stocks"] == _rub("100.00")

    fresh = client.get("/api/analytics/capital-composition")
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["points"] == []


def test_capital_composition_closed_history_gap_and_known_zero(client: TestClient) -> None:
    account = client.post(
        "/api/accounts",
        json={"name": "Synthetic brokerage", "account_type": "brokerage"},
    ).json()
    bond = client.post(
        "/api/instruments",
        json={"name": "Synthetic bond", "instrument_type": "bond"},
    ).json()
    stock = client.post(
        "/api/instruments",
        json={"name": "Synthetic stock", "instrument_type": "stock"},
    ).json()
    gold = client.post(
        "/api/instruments",
        json={"name": "Synthetic gold", "instrument_type": "gold"},
    ).json()

    may_id = _create_month(client, year=2031, month=5, snapshot_date="2031-05-31")
    _create_cash(client, may_id, "100000.00")
    _create_deposit(client, may_id, account["id"], "400000.00")
    _create_position(
        client,
        month_id=may_id,
        account_id=account["id"],
        instrument_id=stock["id"],
        amount="300000.00",
        price_date="2031-05-31",
    )
    _create_position(
        client,
        month_id=may_id,
        account_id=account["id"],
        instrument_id=bond["id"],
        amount="700000.00",
        price_date="2031-05-31",
    )
    _create_position(
        client,
        month_id=may_id,
        account_id=account["id"],
        instrument_id=gold["id"],
        amount="200000.00",
        price_date="2031-05-31",
    )
    _create_debt(client, may_id, "100000.00")
    close_may = client.post(f"/api/months/{may_id}/close")
    assert close_may.status_code == 200, close_may.text

    june_id = _create_month(client, year=2031, month=6, snapshot_date="2031-06-30")
    _create_cash(client, june_id, "999999.00")
    # June intentionally remains DRAFT and must not become a historical zero or point.

    july_id = _create_month(client, year=2031, month=7, snapshot_date="2031-07-31")
    _create_cash(client, july_id, "120000.00")
    _create_deposit(client, july_id, account["id"], "450000.00")
    _create_position(
        client,
        month_id=july_id,
        account_id=account["id"],
        instrument_id=bond["id"],
        amount="800000.00",
        price_date="2031-07-31",
    )
    _create_position(
        client,
        month_id=july_id,
        account_id=account["id"],
        instrument_id=gold["id"],
        amount="230000.00",
        price_date="2031-07-31",
    )
    _create_debt(client, july_id, "50000.00")
    close_july = client.post(f"/api/months/{july_id}/close")
    assert close_july.status_code == 200, close_july.text

    response = client.get("/api/analytics/capital-composition")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["asset_classes"] == [
        "cash",
        "deposits",
        "stocks",
        "bonds",
        "gold_other",
    ]
    assert [(point["year"], point["month"]) for point in body["points"]] == [
        (2031, 5),
        (2031, 7),
    ]
    assert {point["reporting_month_id"] for point in body["points"]} == {may_id, july_id}
    assert june_id not in {point["reporting_month_id"] for point in body["points"]}

    may = body["points"][0]
    may_allocation = {item["asset_class"]: item["amount"] for item in may["allocation"]}
    assert list(may_allocation) == body["asset_classes"]
    assert may_allocation["cash"] == _rub("100000.00")
    assert may_allocation["deposits"] == _rub("400000.00")
    assert may_allocation["stocks"] == _rub("300000.00")
    assert may_allocation["bonds"] == _rub("700000.00")
    assert may_allocation["gold_other"] == _rub("200000.00")
    assert may["liquid_assets_total"] == _rub("1700000.00")
    assert may["included_debts"] == _rub("100000.00")
    assert may["liquid_capital_net"] == _rub("1600000.00")

    july = body["points"][1]
    july_allocation = {item["asset_class"]: item["amount"] for item in july["allocation"]}
    assert july_allocation["stocks"] == _rub("0.00")
    assert july_allocation["cash"] == _rub("120000.00")
    assert july_allocation["deposits"] == _rub("450000.00")
    assert july_allocation["bonds"] == _rub("800000.00")
    assert july_allocation["gold_other"] == _rub("230000.00")
    assert july["liquid_assets_total"] == _rub("1600000.00")
    assert july["included_debts"] == _rub("50000.00")
    assert july["liquid_capital_net"] == _rub("1550000.00")

    dashboard = client.get(f"/api/months/{july_id}/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["asset_allocation"] == july["allocation"]


def test_reopened_month_disappears_from_capital_composition_history(client: TestClient) -> None:
    month_id = _create_month(client, year=2032, month=1, snapshot_date="2032-01-31")
    _create_cash(client, month_id, "1000.00")
    close = client.post(f"/api/months/{month_id}/close")
    assert close.status_code == 200, close.text

    before = client.get("/api/analytics/capital-composition")
    assert [point["reporting_month_id"] for point in before.json()["points"]] == [month_id]

    reopen = client.post(f"/api/months/{month_id}/reopen")
    assert reopen.status_code == 200, reopen.text

    after = client.get("/api/analytics/capital-composition")
    assert after.status_code == 200, after.text
    assert after.json()["points"] == []
    assert after.json()["asset_classes"] == [
        "cash",
        "deposits",
        "stocks",
        "bonds",
        "gold_other",
    ]


def test_closed_report_comparison_uses_closed_pair_and_reconciles_deltas(
    client: TestClient,
) -> None:
    account = client.post(
        "/api/accounts",
        json={"name": "Synthetic comparison brokerage", "account_type": "brokerage"},
    ).json()
    bond = client.post(
        "/api/instruments",
        json={"name": "Synthetic comparison bond", "instrument_type": "bond"},
    ).json()
    stock = client.post(
        "/api/instruments",
        json={"name": "Synthetic comparison stock", "instrument_type": "stock"},
    ).json()
    gold = client.post(
        "/api/instruments",
        json={"name": "Synthetic comparison gold", "instrument_type": "gold"},
    ).json()

    previous_id = _create_month(client, year=2033, month=1, snapshot_date="2033-01-31")
    _create_cash(client, previous_id, "100000.00")
    _create_deposit(client, previous_id, account["id"], "400000.00")
    _create_position(
        client,
        month_id=previous_id,
        account_id=account["id"],
        instrument_id=stock["id"],
        amount="300000.00",
        price_date="2033-01-31",
    )
    _create_position(
        client,
        month_id=previous_id,
        account_id=account["id"],
        instrument_id=bond["id"],
        amount="700000.00",
        price_date="2033-01-31",
    )
    _create_position(
        client,
        month_id=previous_id,
        account_id=account["id"],
        instrument_id=gold["id"],
        amount="200000.00",
        price_date="2033-01-31",
    )
    _create_debt(client, previous_id, "100000.00")
    assert client.post(f"/api/months/{previous_id}/close").status_code == 200

    draft_id = _create_month(client, year=2033, month=2, snapshot_date="2033-02-28")
    _create_cash(client, draft_id, "9999999.00")

    current_id = _create_month(client, year=2033, month=3, snapshot_date="2033-03-31")
    _create_cash(client, current_id, "120000.00")
    _create_deposit(client, current_id, account["id"], "450000.00")
    _create_position(
        client,
        month_id=current_id,
        account_id=account["id"],
        instrument_id=bond["id"],
        amount="800000.00",
        price_date="2033-03-31",
    )
    _create_position(
        client,
        month_id=current_id,
        account_id=account["id"],
        instrument_id=gold["id"],
        amount="230000.00",
        price_date="2033-03-31",
    )
    _create_debt(client, current_id, "50000.00")
    assert client.post(f"/api/months/{current_id}/close").status_code == 200

    body = _comparison(client)
    assert body["comparison_basis"] == "latest_closed_to_previous_closed"
    assert body["availability"] == "available"
    assert body["asset_classes"] == ["cash", "deposits", "stocks", "bonds", "gold_other"]
    assert body["current"]["reporting_month_id"] == current_id
    assert body["current"]["status"] == "closed"
    assert body["previous"]["reporting_month_id"] == previous_id
    assert body["previous"]["status"] == "closed"
    assert draft_id not in {
        body["current"]["reporting_month_id"],
        body["previous"]["reporting_month_id"],
    }

    deltas = {item["asset_class"]: item["amount"] for item in body["asset_class_deltas"]}
    assert deltas == {
        "cash": _rub("20000.00"),
        "deposits": _rub("50000.00"),
        "stocks": _rub("-300000.00"),
        "bonds": _rub("100000.00"),
        "gold_other": _rub("30000.00"),
    }
    assert body["current"]["liquid_assets_total"] == _rub("1600000.00")
    assert body["current"]["included_debts"] == _rub("50000.00")
    assert body["current"]["liquid_capital_net"] == _rub("1550000.00")
    assert body["liquid_assets_total_delta"] == _rub("-100000.00")
    assert body["included_debts_delta"] == _rub("-50000.00")
    assert body["liquid_capital_net_delta"] == _rub("-50000.00")
    assert body["net_liquid_capital_reconciles"] is True


def test_closed_report_comparison_exposes_first_closed_report_without_zero_baseline(
    client: TestClient,
) -> None:
    month_id = _create_month(client, year=2034, month=1, snapshot_date="2034-01-31")
    _create_cash(client, month_id, "1000.00")
    assert client.post(f"/api/months/{month_id}/close").status_code == 200

    body = _comparison(client)
    assert body["availability"] == "previous_closed_report_unavailable"
    assert body["current"]["reporting_month_id"] == month_id
    assert body["current"]["status"] == "closed"
    assert body["previous"] is None
    assert body["asset_class_deltas"] is None
    assert body["liquid_capital_net_delta"] is None
    assert body["net_liquid_capital_reconciles"] is None


def test_closed_report_comparison_is_explicitly_unavailable_without_closed_reports(
    client: TestClient,
) -> None:
    body = _comparison(client)

    assert body["availability"] == "no_closed_report"
    assert body["current"] is None
    assert body["previous"] is None
    assert body["asset_class_deltas"] is None
    assert body["liquid_capital_net_delta"] is None
    assert body["net_liquid_capital_reconciles"] is None


def test_closed_report_comparison_does_not_double_count_linked_debt(
    client: TestClient,
) -> None:
    account = client.post(
        "/api/accounts",
        json={"name": "Synthetic linked cash", "account_type": "cash"},
    ).json()

    previous_id = _create_month(client, year=2035, month=1, snapshot_date="2035-01-31")
    _create_cash(client, previous_id, "100.00", account_id=account["id"])
    previous_debt = client.post(
        "/api/debts",
        json={
            "reporting_month_id": previous_id,
            "debt_type": "credit_card",
            "name": "Synthetic linked debt previous",
            "current_balance": _rub("40.00"),
            "include_in_liquid_capital": True,
        },
    ).json()
    assert (
        client.put(
            f"/api/debts/{previous_debt['id']}/linked-account",
            json={"account_id": account["id"]},
        ).status_code
        == 200
    )
    assert client.post(f"/api/months/{previous_id}/close").status_code == 200

    current_id = _create_month(client, year=2035, month=2, snapshot_date="2035-02-28")
    _create_cash(client, current_id, "150.00", account_id=account["id"])
    current_debt = client.post(
        "/api/debts",
        json={
            "reporting_month_id": current_id,
            "debt_type": "credit_card",
            "name": "Synthetic linked debt current",
            "current_balance": _rub("60.00"),
            "include_in_liquid_capital": True,
        },
    ).json()
    assert (
        client.put(
            f"/api/debts/{current_debt['id']}/linked-account",
            json={"account_id": account["id"]},
        ).status_code
        == 200
    )
    assert client.post(f"/api/months/{current_id}/close").status_code == 200

    body = _comparison(client)
    assert body["current"]["liquid_assets_total"] == _rub("150.00")
    assert body["current"]["included_debts"] == _rub("60.00")
    assert body["current"]["liquid_capital_net"] == _rub("90.00")
    assert body["current"]["linked_pair_assets"] == _rub("150.00")
    assert body["current"]["linked_pair_debts"] == _rub("60.00")
    assert body["liquid_capital_net_delta"] == _rub("30.00")
    assert body["linked_pair_debts_delta"] == _rub("20.00")
    assert body["net_liquid_capital_reconciles"] is True
