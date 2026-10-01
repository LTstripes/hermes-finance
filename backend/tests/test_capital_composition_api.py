"""API tests for R03-12 capital composition history."""

from __future__ import annotations

from collections.abc import Generator
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, CashBalance, PositionSnapshot
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


def _linked_debt(client: TestClient, month_id: int, account_id: int | None, amount: str) -> int:
    response = client.post(
        "/api/debts",
        json={
            "reporting_month_id": month_id,
            "debt_type": "credit_card",
            "name": "Synthetic endpoint card",
            "current_balance": _rub(amount),
            "include_in_liquid_capital": True,
        },
    )
    assert response.status_code == 201, response.text
    debt_id = response.json()["id"]
    if account_id is not None:
        response = client.put(
            f"/api/debts/{debt_id}/linked-account", json={"account_id": account_id}
        )
        assert response.status_code == 200, response.text
    return debt_id


def _assert_explanation_reconciles(body: dict) -> None:
    explanation = body["explanation"]
    assert explanation["reconciles"] is True
    total = sum(
        Decimal(item["amount"]["amount"]) for item in explanation["residual_asset_class_deltas"]
    )
    total += Decimal(explanation["residual_debt_contribution_delta"]["amount"])
    total += sum(Decimal(item["net_contribution_delta"]["amount"]) for item in explanation["pairs"])
    assert total == Decimal(body["liquid_capital_net_delta"]["amount"])


@pytest.mark.parametrize(
    "cash,deposit,debt,expected",
    [
        ("10.00", "30.00", "20.00", "0.00"),
        ("50.00", "110.00", "140.00", "0.00"),
        ("40.00", "60.00", "20.00", "60.00"),
        ("0.00", "0.00", "0.00", "-20.00"),
    ],
)
def test_fixed_pair_set_removes_exact_mixed_components_once(client, cash, deposit, debt, expected):
    accounts = [
        client.post(
            "/api/accounts", json={"name": f"Synthetic account {i}", "account_type": "savings"}
        ).json()["id"]
        for i in range(4)
    ]
    months = [
        _create_month(client, year=2036, month=m, snapshot_date=f"2036-0{m}-28") for m in (1, 2)
    ]
    debt_ids = []
    for i, month_id in enumerate(months):
        _create_cash(client, month_id, "40.00" if i == 0 else cash, account_id=accounts[0])
        _create_deposit(client, month_id, accounts[0], "60.00" if i == 0 else deposit)
        debt_ids.append(_linked_debt(client, month_id, accounts[0], "80.00" if i == 0 else debt))
        # Another comparable zero pair, plus one-sided pairs on opposite endpoints.
        _create_cash(client, month_id, "0.00", account_id=accounts[1])
        _linked_debt(client, month_id, accounts[1], "0.00")
        _create_cash(client, month_id, "7.00", account_id=accounts[2])
        _create_cash(client, month_id, "9.00", account_id=accounts[3])
        _linked_debt(client, month_id, accounts[2] if i == 0 else accounts[3], "3.00")
        _create_cash(client, month_id, "2.00" if i == 0 else "5.00")
        _create_debt(client, month_id, "4.00" if i == 0 else "1.00")
        assert client.post(f"/api/months/{month_id}/close").status_code == 200
    body = _comparison(client)
    explanation = body["explanation"]
    assert debt_ids[0] != debt_ids[1]
    assert [item["account_id"] for item in explanation["pairs"]] == accounts[:2]
    assert explanation["noncomparable_account_ids"] == accounts[2:]
    pair = explanation["pairs"][0]
    assert pair["previous"]["debt_id"] == debt_ids[0]
    assert pair["current"]["debt_id"] == debt_ids[1]
    assert pair["net_contribution_delta"] == _rub(expected)
    residual = {
        item["asset_class"]: item["amount"] for item in explanation["residual_asset_class_deltas"]
    }
    assert residual["cash"] == _rub("3.00")
    assert residual["deposits"] == _rub("0.00")
    assert explanation["residual_debt_contribution_delta"] == _rub("3.00")
    _assert_explanation_reconciles(body)
    # Existing gross allocation remains the source allocation.
    assert body["current"]["allocation"][1]["amount"] == _rub(deposit)


def test_pair_explanation_reopen_relink_reclose_fresh_readback(client):
    accounts = [
        client.post(
            "/api/accounts", json={"name": f"Synthetic relink {i}", "account_type": "cash"}
        ).json()["id"]
        for i in (1, 2)
    ]
    months = [
        _create_month(client, year=2037, month=m, snapshot_date=f"2037-0{m}-28") for m in (1, 2)
    ]
    debts = []
    for month_id in months:
        for account_id in accounts:
            _create_cash(client, month_id, "100.00", account_id=account_id)
        debts.append(_linked_debt(client, month_id, accounts[0], "80.00"))
        assert client.post(f"/api/months/{month_id}/close").status_code == 200
    original = _comparison(client)
    assert len(original["explanation"]["pairs"]) == 1
    assert client.post(f"/api/months/{months[0]}/reopen").status_code == 200
    assert _comparison(client)["explanation"] is None
    assert (
        client.put(
            f"/api/debts/{debts[0]}/linked-account", json={"account_id": accounts[1]}
        ).status_code
        == 200
    )
    assert client.post(f"/api/months/{months[0]}/close").status_code == 200
    relinked = _comparison(client)
    assert relinked["explanation"]["pairs"] == []
    assert relinked["explanation"]["noncomparable_account_ids"] == accounts
    assert relinked["liquid_capital_net_delta"] == original["liquid_capital_net_delta"]
    _assert_explanation_reconciles(relinked)
    assert client.post(f"/api/months/{months[0]}/reopen").status_code == 200
    assert (
        client.put(
            f"/api/debts/{debts[0]}/linked-account", json={"account_id": accounts[0]}
        ).status_code
        == 200
    )
    # Existing uniqueness guard prevents removal of A twice.
    another = _linked_debt(client, months[0], None, "0.00")
    assert (
        client.put(
            f"/api/debts/{another}/linked-account", json={"account_id": accounts[0]}
        ).status_code
        == 409
    )
    assert client.post(f"/api/months/{months[0]}/close").status_code == 200
    assert _comparison(client)["explanation"] == original["explanation"]


def test_explanation_partial_coverage_and_invalid_missing_pair_fail_closed(client):
    known = client.post(
        "/api/accounts", json={"name": "Synthetic known", "account_type": "cash"}
    ).json()["id"]
    client.post("/api/accounts", json={"name": "Synthetic missing", "account_type": "cash"})
    months = [
        _create_month(client, year=2038, month=m, snapshot_date=f"2038-0{m}-28") for m in (1, 2)
    ]
    for month_id in months:
        _create_cash(client, month_id, "0.00", account_id=known)
        _linked_debt(client, month_id, known, "0.00")
        assert client.post(f"/api/months/{month_id}/close").status_code == 200
    body = _comparison(client)
    assert body["liquid_capital_net_delta_coverage"]["status"] == "partial"
    assert body["explanation"]["pairs"][0]["net_contribution_delta"] == _rub("0.00")
    _assert_explanation_reconciles(body)
    with client.app.state.database.session_factory() as session:
        # Synthetic corrupted persisted evidence must never become a zero pair.
        session.query(CashBalance).filter(CashBalance.reporting_month_id == months[0]).delete()
        session.commit()
    response = client.get("/api/analytics/closed-report-comparison")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "linked_pair_read_model_unavailable"


def test_explanation_without_any_snapshot_is_unavailable(client):
    for m in (1, 2):
        month_id = _create_month(client, year=2039, month=m, snapshot_date=f"2039-0{m}-28")
        assert client.post(f"/api/months/{month_id}/close").status_code == 200
    body = _comparison(client)
    assert body["liquid_capital_net_delta_coverage"]["status"] == "unavailable"
    assert body["explanation"] is None


@pytest.mark.parametrize("excluded_endpoint,pair_delta", [(0, "120.00"), (1, "0.00")])
def test_pair_residuals_after_cash_exclusion_preserves_deposit_evidence(
    client, excluded_endpoint, pair_delta
):
    account_id = client.post(
        "/api/accounts", json={"name": "Synthetic included components", "account_type": "savings"}
    ).json()["id"]
    months = [
        _create_month(client, year=2042, month=m, snapshot_date=f"2042-0{m}-28") for m in (1, 2)
    ]
    cash_ids = []
    for i, month_id in enumerate(months):
        response = client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": month_id,
                "account_id": account_id,
                "name": "Synthetic paired cash",
                "amount": _rub("60.00"),
            },
        )
        assert response.status_code == 201, response.text
        cash_ids.append(response.json()["id"])
        _create_deposit(client, month_id, account_id, "40.00")
        _linked_debt(client, month_id, account_id, "80.00" if i == 0 else "20.00")
        _create_cash(client, month_id, "10.00" if i == 0 else "15.00")
        assert client.post(f"/api/months/{month_id}/close").status_code == 200
    assert _comparison(client)["explanation"]["pairs"][0]["net_contribution_delta"] == _rub("60.00")
    month_id = months[excluded_endpoint]
    assert client.post(f"/api/months/{month_id}/reopen").status_code == 200
    response = client.patch(
        f"/api/cash-balances/{cash_ids[excluded_endpoint]}", json={"include_in_capital": False}
    )
    assert response.status_code == 200, response.text
    assert response.json()["include_in_capital"] is False
    assert client.post(f"/api/months/{month_id}/close").status_code == 200
    body = _comparison(client)
    pair = body["explanation"]["pairs"][0]
    assert pair["previous"]["account_balance"] == _rub(
        "40.00" if excluded_endpoint == 0 else "100.00"
    )
    assert pair["current"]["account_balance"] == _rub(
        "40.00" if excluded_endpoint == 1 else "100.00"
    )
    assert pair["net_contribution_delta"] == _rub(pair_delta)
    residual = {
        item["asset_class"]: item["amount"]
        for item in body["explanation"]["residual_asset_class_deltas"]
    }
    assert residual["cash"] == _rub("5.00")
    assert residual["deposits"] == _rub("0.00")
    assert body["explanation"]["residual_debt_contribution_delta"] == _rub("0.00")
    assert body["explanation"]["noncomparable_account_ids"] == []
    _assert_explanation_reconciles(body)


def test_comparison_link_projection_uses_same_snapshot_as_canonical_totals(client, monkeypatch):
    accounts = [
        client.post(
            "/api/accounts", json={"name": f"Synthetic coherent {i}", "account_type": "cash"}
        ).json()["id"]
        for i in (1, 2)
    ]
    months = [
        _create_month(client, year=2041, month=m, snapshot_date=f"2041-0{m}-28") for m in (1, 2)
    ]
    debts = []
    for month_id in months:
        for account_id in accounts:
            _create_cash(client, month_id, "100.00", account_id=account_id)
        debts.append(_linked_debt(client, month_id, accounts[0], "80.00"))
        assert client.post(f"/api/months/{month_id}/close").status_code == 200
    database = client.app.state.database
    with database.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"
    real_pairs = capital_composition_service.linked_pairs_for_months
    committed = False

    def interleaved(*args, **kwargs):
        nonlocal committed
        if not committed:
            committed = True
            from hermes_finance.services.debts import link_debt_to_account
            from hermes_finance.services.reporting_months import close_reporting_month

            with database.session_factory() as writer:
                reopen_reporting_month(writer, months[0])
                link_debt_to_account(writer, debts[0], accounts[1])
                close_reporting_month(writer, months[0])
        return real_pairs(*args, **kwargs)

    monkeypatch.setattr(capital_composition_service, "linked_pairs_for_months", interleaved)
    before = _comparison(client)
    assert len(before["explanation"]["pairs"]) == 1
    _assert_explanation_reconciles(before)
    fresh = _comparison(client)
    assert fresh["explanation"]["pairs"] == []
    assert fresh["explanation"]["noncomparable_account_ids"] == accounts
    _assert_explanation_reconciles(fresh)


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
