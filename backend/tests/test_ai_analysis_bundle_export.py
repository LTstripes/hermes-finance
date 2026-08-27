"""Integration tests for the R07-02 AI Analysis Bundle export."""

from __future__ import annotations

import json
import socket
from calendar import monthrange
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import func, select
from startup_network_guard import NETWORK_FORBIDDEN, install_network_guard

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "ai_analysis_bundle.schema.json"
FORBIDDEN_KEYS = {
    "api_key",
    "api_token",
    "backup_path",
    "cookie",
    "credential",
    "database_id",
    "database_path",
    "debug_payload",
    "external_code",
    "file_hash",
    "filesystem_path",
    "password",
    "provider_account_id",
    "provider_identity_key",
    "provider_instrument_uid",
    "raw_payload",
    "reconciliation_id",
    "secret",
    "session_token",
}
GENERATED_AT = "2026-05-15T12:00:00+03:00"


@pytest.fixture
def app_context(tmp_path: Path) -> Generator[tuple[TestClient, Database], None, None]:
    database = create_database(tmp_path / "ai_analysis_bundle.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _last_day(year: int, month: int) -> str:
    return date(year, month, monthrange(year, month)[1]).isoformat()


def _money(amount: str) -> dict[str, str]:
    return {"amount": amount, "currency": "RUB"}


def _ok(response, status: int = 201) -> dict:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def _create_month(client: TestClient, year: int, month: int, *, source: str = "manual") -> int:
    body = {
        "year": year,
        "month": month,
        "snapshot_date": _last_day(year, month),
        "source": source,
    }
    return _ok(client.post("/api/months", json=body))["id"]


def _close(client: TestClient, month_id: int) -> None:
    _ok(client.post(f"/api/months/{month_id}/close"), status=200)


def _table_counts(database: Database) -> dict[str, int]:
    with database.session_factory() as session:
        return {
            table.name: int(session.scalar(select(func.count()).select_from(table)) or 0)
            for table in Base.metadata.sorted_tables
        }


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _seed_history(client: TestClient) -> dict[str, int]:
    brokerage = _ok(
        client.post(
            "/api/accounts", json={"name": "Synthetic Brokerage", "account_type": "brokerage"}
        )
    )["id"]
    deposit_account = _ok(
        client.post("/api/accounts", json={"name": "Synthetic Deposit", "account_type": "deposit"})
    )["id"]
    iis_account = _ok(
        client.post("/api/accounts", json={"name": "Synthetic IIS", "account_type": "iis"})
    )["id"]
    bond = _ok(
        client.post(
            "/api/instruments",
            json={
                "name": "Synthetic Bond",
                "instrument_type": "bond",
                "isin": "RU000A0JXNU8",
                "ticker": "SYNTH",
                "currency": "RUB",
            },
        )
    )["id"]
    _ok(
        client.post(
            "/api/goals",
            json={
                "name": "Passive income goal",
                "goal_type": "passive_income",
                "target_value": _money("50000.00"),
                "is_main": True,
                "calculation_mode": "monthly_net_passive_income",
            },
        )
    )
    _ok(
        client.put(
            f"/api/iis/{iis_account}/profile",
            json={
                "iis_type": "iis-a",
                "opened_at": "2024-01-15",
                "eligible_close_at": "2027-01-15",
            },
        ),
        status=200,
    )
    _ok(
        client.post(
            f"/api/iis/{iis_account}/contributions",
            json={"tax_year": 2025, "amount": _money("400000.00"), "is_target_reached": True},
        )
    )
    _ok(
        client.post(
            f"/api/iis/{iis_account}/benefits",
            json={
                "tax_year": 2025,
                "benefit_type": "deduction",
                "status": "received",
                "amount": _money("52000.00"),
                "received_at": "2026-04-10",
            },
        )
    )

    sources = {
        (2025, 11): "manual",
        (2025, 12): "excel_migration",
        (2026, 1): "alfa_pdf",
        (2026, 3): "manual",
        (2026, 4): "manual",
        (2026, 5): "manual",
    }
    periods = [
        (2025, 11, True),
        (2025, 12, True),
        (2026, 1, True),
        (2026, 3, True),
        (2026, 4, True),
        (2026, 5, False),
    ]
    month_ids: dict[tuple[int, int], int] = {}
    for year, month, closed in periods:
        month_id = _create_month(client, year, month, source=sources[(year, month)])
        month_ids[(year, month)] = month_id
        _ok(
            client.post(
                "/api/incomes",
                json={
                    "reporting_month_id": month_id,
                    "income_type": "salary",
                    "name": "Synthetic salary",
                    "gross_amount": _money("100000.00"),
                    "tax_amount": _money("13000.00"),
                    "net_amount": _money("87000.00"),
                },
            )
        )
        _ok(
            client.post(
                "/api/expenses",
                json={
                    "reporting_month_id": month_id,
                    "category": "Rent",
                    "amount": _money("20000.00"),
                    "expense_type": "mandatory",
                },
            )
        )
        _ok(
            client.post(
                "/api/savings",
                json={
                    "reporting_month_id": month_id,
                    "destination": "Brokerage top-up",
                    "amount": _money("10000.00"),
                },
            )
        )
        _ok(
            client.post(
                "/api/cash-balances",
                json={
                    "reporting_month_id": month_id,
                    "name": "Wallet",
                    "amount": _money("400000.00"),
                },
            )
        )
        _ok(
            client.post(
                "/api/deposits",
                json={
                    "reporting_month_id": month_id,
                    "account_id": deposit_account,
                    "name": "Fixed deposit",
                    "deposit_type": "deposit",
                    "balance": _money("1000000.00"),
                    "annual_rate": "13.80",
                    "actual_interest_received": _money("7000.00"),
                },
            )
        )
        price_source = "alfa_pdf" if (year, month) == (2026, 1) else "manual"
        _ok(
            client.post(
                "/api/positions",
                json={
                    "reporting_month_id": month_id,
                    "account_id": brokerage,
                    "instrument_id": bond,
                    "quantity": "10",
                    "average_cost_per_unit": _money("90.00"),
                    "market_price_per_unit": _money("100.00"),
                    "accrued_interest": _money("1.00"),
                    "price_date": _last_day(year, month),
                    "price_source": price_source,
                },
            )
        )
        _ok(
            client.post(
                "/api/investment-flows",
                json={
                    "reporting_month_id": month_id,
                    "account_id": brokerage,
                    "instrument_id": bond,
                    "event_date": _last_day(year, month),
                    "flow_type": "coupon",
                    "gross_amount": _money("5000.00"),
                    "tax_amount": _money("650.00"),
                    "commission_amount": _money("0.00"),
                    "net_amount": _money("4350.00"),
                    "source": "manual",
                },
            )
        )
        _ok(
            client.post(
                "/api/debts",
                json={
                    "reporting_month_id": month_id,
                    "debt_type": "credit_card",
                    "name": "Synthetic card",
                    "current_balance": _money("15000.00"),
                    "include_in_liquid_capital": True,
                },
            )
        )
        _ok(
            client.post(
                "/api/properties",
                json={
                    "reporting_month_id": month_id,
                    "name": "Synthetic apartment",
                    "estimated_value": _money("8000000.00"),
                    "mortgage_balance": _money("3200000.00"),
                    "monthly_payment": _money("45000.00"),
                },
            )
        )
        if (year, month) == (2026, 4):
            snapshot = _last_day(year, month)
            for flow_type, expected_date, gross, tax in (
                ("coupon", "2026-06-15", "3000.00", "390.00"),
                ("dividend", "2026-07-20", "2000.00", "260.00"),
                ("redemption", "2026-12-01", "10000.00", "0.00"),
            ):
                payload = {
                    "reporting_month_id": month_id,
                    "account_id": brokerage,
                    "instrument_id": bond,
                    "flow_type": flow_type,
                    "expected_date": expected_date,
                    "gross_amount": _money(gross),
                    "source": "manual",
                    "source_as_of_date": snapshot,
                    "forecast_version": "v1",
                }
                if flow_type != "redemption":
                    payload["expected_tax_amount"] = _money(tax)
                _ok(client.post("/api/expected-flows", json=payload))
        if closed:
            _close(client, month_id)
    return {
        "brokerage": brokerage,
        "deposit": deposit_account,
        "iis": iis_account,
        "latest_closed": month_ids[(2026, 4)],
        "draft": month_ids[(2026, 5)],
    }


def _export(client: TestClient, *, media: str = "json", path: str | None = None):
    target = path or "/api/export/ai-analysis-bundle"
    params: dict[str, str] = {"generated_at": GENERATED_AT}
    if path is None:
        params["media"] = media
    return client.post(target, params=params)


def test_bundle_export_is_schema_valid_full_history_and_read_only(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _seed_history(client)
    before = _table_counts(database)
    install_network_guard()
    with pytest.raises(AssertionError, match=NETWORK_FORBIDDEN):
        socket.create_connection(("example.com", 443), timeout=1)

    response = _export(client)
    assert response.status_code == 200, response.text
    assert (
        "hermes-ai-analysis-bundle-2026-04-30-v1.0.0.json"
        in response.headers["content-disposition"]
    )
    payload = json.loads(response.content.decode("utf-8"))
    _validator().validate(payload)

    periods = [
        (item["period"]["year"], item["period"]["month"]) for item in payload["reporting_history"]
    ]
    statuses = {item["status"] for item in payload["reporting_history"]}
    assert periods == sorted(periods)
    assert (2025, 11) in periods and (2026, 5) in periods
    assert (2026, 2) not in periods
    assert payload["coverage"]["missing_calendar_periods"] == [{"year": 2026, "month": 2}]
    assert statuses == {"closed", "draft"}
    assert payload["current_portfolio"]["selection_reason"] == "latest_closed"
    assert payload["current_portfolio"]["reporting_period"] == {"year": 2026, "month": 4}
    assert payload["current_portfolio"]["reporting_status"] == "closed"
    assert payload["metadata"]["generation_mode"] == "read_only"
    assert payload["schema_name"] == "hermes.finance.ai_analysis_bundle"
    assert payload["schema_version"] == "1.0.0"

    mixed_sources = {
        source for point in payload["reporting_history"] for source in point["provenance_sources"]
    }
    assert "manual" in mixed_sources
    assert "excel_migration" in mixed_sources
    assert "alfa_statement" in mixed_sources

    draft = next(item for item in payload["reporting_history"] if item["status"] == "draft")
    assert "draft_value" in draft["kpis"]["liquid_capital_net"]["reason_codes"]
    assert draft["coverage"]["status"] == "partial"

    assert payload["passive_income"]["rolling_actual_average"]["eligible_month_count"] == 5
    assert payload["passive_income"]["rolling_actual_average"]["is_complete_window"] is False

    calendar = payload["upcoming_cash_flows"]
    non_principal = Decimal(calendar["non_principal_calendar_amount_total"]["value"]["amount"])
    principal = Decimal(calendar["principal_total"]["value"]["amount"])
    total = Decimal(calendar["calendar_total"]["value"]["amount"])
    assert total == non_principal + principal
    flow_types = {item["flow_type"] for item in calendar["items"]}
    assert {"coupon", "dividend", "redemption"} <= flow_types
    redemption = next(item for item in calendar["items"] if item["flow_type"] == "redemption")
    assert redemption["forecast_treatment"] == "excluded_principal"
    assert redemption["included_in_passive_income_forecast"] is False
    dividend = next(item for item in calendar["items"] if item["flow_type"] == "dividend")
    assert dividend["forecast_treatment"] == "represented_by_historical_component"

    refs = [account["ref"] for account in payload["current_portfolio"]["accounts"]]
    assert refs == sorted(refs)
    assert all(ref.startswith("acct-") for ref in refs)
    goal_refs = [goal["ref"] for goal in payload["goals"]]
    assert goal_refs == sorted(goal_refs)
    assert payload["iis_and_tax"]["iis_accounts"]
    assert (
        payload["iis_and_tax"]["salary_tax_context"]["history_coverage"]["status"] == "unavailable"
    )
    assert payload["reporting_history"][-1]["kpis"]["investment_return"]["value_pct"] is None
    assert payload["reporting_history"][-1]["kpis"]["market_value_change"]["value"] is None

    keys = {key for value in _walk(payload) if isinstance(value, dict) for key in value}
    assert keys.isdisjoint(FORBIDDEN_KEYS)
    assert not any(isinstance(value, float) for value in _walk(payload))
    assert _table_counts(database) == before

    again = _export(client)
    assert again.content == response.content
    explicit = _export(client, path="/api/export/ai-analysis-bundle/json")
    assert explicit.status_code == 200, explicit.text
    assert json.loads(explicit.content.decode("utf-8"))["current_portfolio"][
        "selection_reason"
    ] == ("latest_closed")


def test_bundle_export_markdown_uses_same_dto_and_triggers_no_network(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _seed_history(client)
    before = _table_counts(database)
    install_network_guard()
    with pytest.raises(AssertionError, match=NETWORK_FORBIDDEN):
        socket.create_connection(("example.com", 443), timeout=1)
    response = _export(client, media="markdown")
    assert response.status_code == 200, response.text
    assert "text/markdown" in response.headers["content-type"]
    assert (
        "hermes-ai-analysis-bundle-2026-04-30-v1.0.0.md" in response.headers["content-disposition"]
    )
    body = response.content.decode("utf-8")
    assert body.startswith("# Hermes Finance AI Analysis Bundle 1.0.0")
    assert "generation_mode: read_only" in body
    assert "Canonical machine-readable artifact" in body
    alias = _export(client, path="/api/export/ai-analysis-bundle/markdown")
    assert alias.status_code == 200, alias.text
    assert alias.content.decode("utf-8").startswith("# Hermes Finance AI Analysis Bundle 1.0.0")
    assert _table_counts(database) == before


def test_bundle_export_without_months_is_not_found(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    response = client.post("/api/export/ai-analysis-bundle")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_bundle_export_uses_latest_available_when_no_closed_month(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    month_id = _create_month(client, 2026, 5)
    _ok(
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": month_id,
                "name": "Draft cash",
                "amount": _money("1000.00"),
            },
        )
    )
    response = _export(client)
    assert response.status_code == 200, response.text
    payload = json.loads(response.content.decode("utf-8"))
    _validator().validate(payload)
    assert payload["current_portfolio"]["selection_reason"] == "latest_available"
    assert payload["current_portfolio"]["reporting_status"] == "draft"
    assert payload["current_portfolio"]["coverage"]["status"] == "partial"
    assert "draft_value" in payload["current_portfolio"]["coverage"]["reason_codes"]
