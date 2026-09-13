"""Integration tests for the R07-02 AI Analysis Bundle export."""

from __future__ import annotations

import json
import socket
from calendar import monthrange
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from startup_network_guard import NETWORK_FORBIDDEN, install_network_guard

from hermes_finance.database import Database, create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    Base,
    CashBalance,
    Debt,
    DepositSnapshot,
    Goal,
    MonthlyComment,
    PositionSnapshot,
    SavingAllocation,
)
from hermes_finance.services import ai_analysis_bundle as bundle_service

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "ai_analysis_bundle.schema.json"
FINANCIAL_REVIEW_SCHEMA_PATH = REPO_ROOT / "docs" / "ai_financial_review.schema.json"
PORTFOLIO_REVIEW_SCHEMA_PATH = REPO_ROOT / "docs" / "portfolio_review_package.schema.json"
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


_WRITE_SQL = ("INSERT", "UPDATE", "DELETE", "REPLACE")


@contextmanager
def _forbid_sql_writes(engine: Engine) -> Iterator[None]:
    def _before_cursor_execute(
        _conn,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb in _WRITE_SQL:
            raise AssertionError(f"export issued persistence write: {statement[:240]}")

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


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


def _financial_review_validator() -> Draft202012Validator:
    schema = json.loads(FINANCIAL_REVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _portfolio_review_validator() -> Draft202012Validator:
    schema = json.loads(PORTFOLIO_REVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
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


def _seed_issue_285_august_fixture(client: TestClient) -> int:
    brokerage = _ok(
        client.post(
            "/api/accounts",
            json={"name": "Synthetic August Brokerage", "account_type": "brokerage"},
        )
    )["id"]
    missing_account = _ok(
        client.post(
            "/api/accounts", json={"name": "Synthetic Missing Account", "account_type": "brokerage"}
        )
    )["id"]
    _ok(
        client.post(
            "/api/accounts", json={"name": "Synthetic Unconfigured IIS", "account_type": "iis"}
        )
    )
    instrument = _ok(
        client.post(
            "/api/instruments",
            json={
                "name": "Synthetic August Fund",
                "instrument_type": "fund",
                "isin": "RU000A0JXNV6",
                "ticker": "SYN-AUG",
                "currency": "RUB",
            },
        )
    )["id"]
    month_ids: dict[int, int] = {}
    for month in range(1, 9):
        month_id = _create_month(client, 2026, month)
        month_ids[month] = month_id
        if month == 4:
            _ok(
                client.post(
                    "/api/cash-balances",
                    json={
                        "reporting_month_id": month_id,
                        "name": "Synthetic exact zero cash",
                        "amount": _money("0.00"),
                    },
                )
            )
        if month == 7:
            _ok(
                client.post(
                    "/api/properties",
                    json={
                        "reporting_month_id": month_id,
                        "name": "Synthetic apartment",
                        "estimated_value": _money("8000000.00"),
                        "mortgage_balance": _money("0.00"),
                        "monthly_payment": _money("45000.00"),
                        "notes": "Synthetic note with a conflicting mortgage balance 999999.99",
                    },
                )
            )
        if month == 8:
            _ok(
                client.post(
                    "/api/incomes",
                    json={
                        "reporting_month_id": month_id,
                        "income_type": "salary",
                        "name": "Synthetic August salary",
                        "gross_amount": _money("450000.00"),
                        "tax_amount": _money("81000.00"),
                        "net_amount": _money("382000.00"),
                    },
                )
            )
            _ok(
                client.post(
                    "/api/positions",
                    json={
                        "reporting_month_id": month_id,
                        "account_id": brokerage,
                        "instrument_id": instrument,
                        "quantity": "10",
                        "average_cost_per_unit": _money("90.00"),
                        "market_price_per_unit": _money("100.00"),
                        "accrued_interest": _money("0.00"),
                        "price_date": "2026-07-31",
                        "price_source": "manual",
                    },
                )
            )
            for _ in range(2):
                _ok(
                    client.post(
                        "/api/properties",
                        json={
                            "reporting_month_id": month_id,
                            "name": "Synthetic apartment",
                            "estimated_value": _money("8000000.00"),
                            "mortgage_balance": _money("0.00"),
                            "monthly_payment": _money("45000.00"),
                            "notes": "Synthetic conflicting note, never authoritative",
                        },
                    )
                )
        _close(client, month_id)
    assert missing_account > 0
    return month_ids[8]


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

    with _forbid_sql_writes(database.engine):
        response = _export(client)
    assert response.status_code == 200, response.text
    assert (
        "hermes-ai-analysis-bundle-2026-04-30-v1.2.0.json"
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
    assert payload["schema_version"] == "1.2.0"

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


def test_latest_closed_selection_refreshes_after_close_in_same_process(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    _seed_history(client)

    before = _export(client).json()
    assert before["current_portfolio"]["reporting_period"] == {"year": 2026, "month": 4}
    assert before["current_portfolio"]["selection_reason"] == "latest_closed"
    review_before = client.get(
        "/api/export/ai-financial-review", params={"generated_at": GENERATED_AT}
    )
    assert review_before.status_code == 200, review_before.text
    assert review_before.json()["scope"]["reporting_period"] == {"year": 2026, "month": 4}

    june = _create_month(client, 2026, 6)
    _close(client, june)
    july = _create_month(client, 2026, 7)
    august = _create_month(client, 2026, 8)

    after = _export(client).json()
    assert after["current_portfolio"]["reporting_period"] == {"year": 2026, "month": 6}
    assert after["current_portfolio"]["selection_reason"] == "latest_closed"
    assert after["current_portfolio"]["reporting_status"] == "closed"
    review_after = client.get(
        "/api/export/ai-financial-review", params={"generated_at": GENERATED_AT}
    )
    assert review_after.status_code == 200, review_after.text
    assert review_after.json()["scope"]["reporting_period"] == {"year": 2026, "month": 6}
    assert (
        next(
            item
            for item in after["reporting_history"]
            if item["period"] == {"year": 2026, "month": 7}
        )["status"]
        == "draft"
    )
    assert (
        next(
            item
            for item in after["reporting_history"]
            if item["period"] == {"year": 2026, "month": 8}
        )["status"]
        == "draft"
    )

    _close(client, august)

    final = _export(client).json()
    assert final["current_portfolio"]["reporting_period"] == {"year": 2026, "month": 8}
    assert final["current_portfolio"]["selection_reason"] == "latest_closed"
    review_final = client.get(
        "/api/export/ai-financial-review", params={"generated_at": GENERATED_AT}
    )
    assert review_final.status_code == 200, review_final.text
    assert review_final.json()["scope"]["reporting_period"] == {"year": 2026, "month": 8}
    assert july != august


def test_future_dated_valuation_is_unavailable_in_period_aggregates(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    seed = _seed_history(client)
    _ok(
        client.post(
            "/api/goals",
            json={
                "name": "Capital goal",
                "goal_type": "capital",
                "target_value": _money("2000000.00"),
                "calculation_mode": "liquid_capital_net",
            },
        )
    )
    with database.session_factory() as session:
        position = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == seed["draft"],
            )
        )
        assert position is not None
        position.account_id = seed["iis"]
        position.price_date = date(2026, 6, 1)
        session.commit()
    _close(client, seed["draft"])

    bundle_response = _export(client)
    assert bundle_response.status_code == 200, bundle_response.text
    bundle = bundle_response.json()
    _validator().validate(bundle)

    current = bundle["current_portfolio"]
    assert current["reporting_period"] == {"year": 2026, "month": 5}
    assert current["coverage"]["status"] == "partial"
    assert "future_dated_valuation" in current["coverage"]["reason_codes"]
    assert "future_dated_valuation" in current["valuation_freshness"]["reason_codes"]
    position_data = current["positions"][0]
    assert position_data["market_price_per_unit"]["value"] is None
    assert position_data["market_value"]["value"] is None
    assert position_data["unrealized_result"]["value"] is None
    assert position_data["accrued_interest"]["value"] is None
    assert position_data["cost_basis"]["value"]["amount"] == "900.00"
    assert position_data["price_date"] == "2026-06-01"
    assert bundle["reporting_history"][-1]["kpis"]["liquid_assets_total"]["value"] is None
    assert bundle["reporting_history"][-1]["kpis"]["liquid_capital_net"]["value"] is None
    assert bundle["coverage"]["domains"]["capital"]["status"] == "partial"
    assert any(item["code"] == "future_dated_valuation" for item in bundle["warnings"])
    capital_goal = next(item for item in bundle["goals"] if item["name"] == "Capital goal")
    assert capital_goal["target"]["value"]["amount"] == "2000000.00"
    assert capital_goal["current_value"]["availability"] == "unavailable"
    assert capital_goal["gap"]["availability"] == "unavailable"
    assert capital_goal["progress"]["availability"] == "unavailable"
    assert capital_goal["warning_codes"] == ["future_dated_valuation"]
    insights = bundle["deterministic_insights"]["items"]
    assert "portfolio_concentration" not in {item["code"] for item in insights}
    assert "partial_asset_class_coverage" not in {item["code"] for item in insights}
    mortgage_coverage = bundle["debts_and_real_estate"]["mortgage_coverage"]
    assert mortgage_coverage["availability"] == "unavailable"
    assert mortgage_coverage["reason_codes"] == ["future_dated_valuation"]
    iis_account = bundle["iis_and_tax"]["iis_accounts"][0]
    assert iis_account["portfolio_result_without_tax_benefit"]["availability"] == "unavailable"
    assert (
        iis_account["portfolio_result_with_received_tax_benefit"]["availability"] == "unavailable"
    )
    assert iis_account["tax_benefits"]["received"]["amount"] == "52000.00"
    assert "future_dated_valuation" in bundle["iis_and_tax"]["iis_coverage"]["reason_codes"]

    package_response = client.get(
        "/api/export/portfolio-review-package",
        params={"profile": "full", "generated_at": GENERATED_AT},
    )
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    _portfolio_review_validator().validate(package)
    assert package["sections"]["allocation"]["status"] == "partial"
    assert package["sections"]["allocation"]["reason_codes"] == ["future_dated_valuation"]
    package_allocation = package["sections"]["allocation"]["data"]
    assert package_allocation["top_positions"]["support"]["status"] == "unavailable"
    assert package_allocation["top_positions"]["denominator"] is None
    assert package_allocation["top_positions"]["top_amount"] is None
    assert package_allocation["allocation_by_asset_class"]["denominator"] is None
    assert package_allocation["allocation_by_asset_class"]["covered_amount"] is None
    assert package_allocation["allocation_by_asset_class"]["unallocated_amount"] is None
    assert package_allocation["payout_concentration"]["excluded_reason_codes"] == []
    assert package["sections"]["deterministic_insights"]["status"] == "partial"

    review_response = client.get(
        "/api/export/ai-financial-review",
        params={"generated_at": GENERATED_AT},
    )
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    _financial_review_validator().validate(review)
    assert review["scope"]["selection_reason"] == "latest_closed"
    assert "future_dated_valuation" in review["sections"]["current_capital"]["reason_codes"]
    assert review["sections"]["current_portfolio"]["status"] == "partial"
    assert "future_dated_valuation" in review["sections"]["current_portfolio"]["reason_codes"]
    assert review["sections"]["allocation_and_concentration"]["status"] == "partial"
    assert review["sections"]["allocation_and_concentration"]["reason_codes"] == [
        "future_dated_valuation"
    ]
    allocation_data = review["sections"]["allocation_and_concentration"]["data"]
    assert allocation_data["allocation_by_asset_class"]["support"]["status"] == "unavailable"
    assert allocation_data["allocation_by_account"]["support"]["status"] == "unavailable"
    assert allocation_data["top_positions"]["support"]["status"] == "unavailable"
    assert allocation_data["top_positions"]["denominator"] is None
    assert allocation_data["top_positions"]["top_amount"] is None
    assert allocation_data["payout_concentration"]["support"]["status"] != "unavailable"
    assert review["sections"]["goals"]["status"] == "partial"
    assert "future_dated_valuation" in review["sections"]["goals"]["reason_codes"]
    assert review["sections"]["debts_and_real_estate"]["status"] == "partial"
    assert "future_dated_valuation" in review["sections"]["debts_and_real_estate"]["reason_codes"]
    assert review["sections"]["iis_and_tax"]["status"] == "partial"
    assert "future_dated_valuation" in review["sections"]["iis_and_tax"]["reason_codes"]


def test_future_dated_valuation_on_excluded_account_does_not_degrade_capital_or_risk(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    seed = _seed_history(client)
    with database.session_factory() as session:
        account = session.get(Account, seed["brokerage"])
        position = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == seed["draft"],
            )
        )
        assert account is not None
        assert position is not None
        account.include_in_capital = False
        position.price_date = date(2026, 6, 1)
        session.commit()
    _close(client, seed["draft"])

    bundle = _export(client).json()
    _validator().validate(bundle)
    position_data = bundle["current_portfolio"]["positions"][0]
    assert position_data["market_value"]["availability"] == "unavailable"
    assert position_data["market_value"]["reason_codes"] == ["future_dated_valuation"]
    current_history = bundle["reporting_history"][-1]
    assert current_history["kpis"]["liquid_assets_total"]["availability"] == "available"
    assert (
        "future_dated_valuation"
        not in current_history["kpis"]["liquid_assets_total"]["reason_codes"]
    )
    assert "future_dated_valuation" not in bundle["coverage"]["domains"]["capital"]["reason_codes"]

    package_response = client.get(
        "/api/export/portfolio-review-package",
        params={"profile": "full", "generated_at": GENERATED_AT},
    )
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    _portfolio_review_validator().validate(package)
    allocation = package["sections"]["allocation"]
    assert allocation["status"] == "included"
    assert "future_dated_valuation" not in allocation["reason_codes"]
    assert allocation["data"]["allocation_by_asset_class"]["denominator"] is not None


def test_issue_285_august_fixture_preserves_data_quality_semantics(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    _seed_issue_285_august_fixture(client)

    response = _export(client)
    assert response.status_code == 200, response.text
    payload = json.loads(response.content.decode("utf-8"))
    _validator().validate(payload)

    january = next(
        point
        for point in payload["reporting_history"]
        if point["period"] == {"year": 2026, "month": 1}
    )
    april = next(
        point
        for point in payload["reporting_history"]
        if point["period"] == {"year": 2026, "month": 4}
    )
    assert january["kpis"]["liquid_capital_net"]["value"] is None
    assert "portfolio_snapshot_missing" in january["kpis"]["liquid_capital_net"]["reason_codes"]
    assert april["kpis"]["liquid_capital_net"]["value"]["amount"] == "0.00"

    august = payload["reporting_history"][-1]
    salary = august["kpis"]["salary"]
    assert salary["gross"]["value"]["amount"] == "450000.00"
    assert salary["calculated_tax"]["value"]["amount"] == "58500.00"
    assert salary["calculated_net"]["value"]["amount"] == "391500.00"
    assert salary["actual_net"]["value"]["amount"] == "382000.00"
    assert salary["consistency"] == "mismatch"
    assert "salary_net_mismatch" in salary["reason_codes"]

    portfolio = payload["current_portfolio"]
    assert portfolio["coverage"]["status"] == "partial"
    assert portfolio["missing_snapshot_account_refs"]
    freshness = portfolio["valuation_freshness"]
    assert freshness["oldest_price_date"] == "2026-07-31"
    assert freshness["latest_price_date"] == "2026-07-31"
    assert freshness["stale_valuation_count"] == 1
    assert freshness["stale_valuation_share"]["value_pct"] == "100.00"
    assert "stale_valuation" in freshness["reason_codes"]

    iis = payload["iis_and_tax"]
    assert iis["iis_accounts"] == []
    assert iis["iis_coverage"]["status"] == "partial"
    assert iis["iis_coverage"]["reason_codes"] == ["iis_tax_data_unconfigured"]
    assert iis["active_account_refs"]

    property_quality = payload["debts_and_real_estate"]["property_data_quality"]
    assert property_quality["structured_snapshot_authoritative"] is True
    assert set(property_quality["warning_codes"]) == {
        "duplicate_property_snapshot",
        "property_equity_suspicious_jump",
    }
    assert "notes" not in json.dumps(payload, ensure_ascii=False)

    kpis = august["kpis"]
    assert kpis["cash_flow_after_allocations"] == kpis["monthly_cash_balance"]
    warning_codes = [warning["code"] for warning in payload["warnings"]]
    assert len(warning_codes) == len(set(warning_codes))


def test_cash_snapshot_detection_is_account_specific(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    covered_account = _ok(
        client.post(
            "/api/accounts",
            json={"name": "Synthetic Covered Cash", "account_type": "cash"},
        )
    )["id"]
    _ok(
        client.post(
            "/api/accounts",
            json={"name": "Synthetic Missing Cash", "account_type": "cash"},
        )
    )
    month_id = _create_month(client, 2026, 8)
    _ok(
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": month_id,
                "account_id": covered_account,
                "name": "Synthetic covered cash snapshot",
                "amount": _money("125000.00"),
            },
        )
    )
    _close(client, month_id)

    response = _export(client)
    assert response.status_code == 200, response.text
    payload = response.json()
    _validator().validate(payload)

    account_refs = {item["name"]: item["ref"] for item in payload["current_portfolio"]["accounts"]}
    missing_ref = account_refs["Synthetic Missing Cash"]
    assert (
        account_refs["Synthetic Covered Cash"]
        not in payload["current_portfolio"]["missing_snapshot_account_refs"]
    )
    assert payload["current_portfolio"]["missing_snapshot_account_refs"] == [missing_ref]
    assert any(
        warning["code"] == "active_account_snapshot_missing" for warning in payload["warnings"]
    )


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
        "hermes-ai-analysis-bundle-2026-04-30-v1.2.0.md" in response.headers["content-disposition"]
    )
    body = response.content.decode("utf-8")
    assert body.startswith("# Hermes Finance AI Analysis Bundle 1.2.0")
    assert "generation_mode: read_only" in body
    assert "Canonical machine-readable artifact" in body
    alias = _export(client, path="/api/export/ai-analysis-bundle/markdown")
    assert alias.status_code == 200, alias.text
    assert alias.content.decode("utf-8").startswith("# Hermes Finance AI Analysis Bundle 1.2.0")
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


def test_bundle_schema_validation_failure_is_http_500_without_payload_or_mutation(
    app_context: tuple[TestClient, Database],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, database = app_context
    _seed_history(client)
    before = _table_counts(database)
    real_validate = bundle_service.validate_bundle

    def _fail_closed(bundle: dict[str, object]) -> None:
        broken = dict(bundle)
        broken["schema_name"] = "not-the-declared-contract"
        real_validate(broken)

    monkeypatch.setattr(bundle_service, "validate_bundle", _fail_closed)
    failing_client = TestClient(client.app, raise_server_exceptions=False)
    with _forbid_sql_writes(database.engine):
        response = _export(failing_client)
    assert response.status_code == 500
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" not in disposition.lower()
    assert b"hermes.finance.ai_analysis_bundle" not in response.content
    assert b"hermes-ai-analysis-bundle-" not in response.content
    assert _table_counts(database) == before


def test_ai_financial_review_route_is_schema_valid_and_read_only(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _seed_history(client)
    before = _table_counts(database)
    baseline_bundle = _export(client).content
    baseline_package = client.get(
        "/api/export/portfolio-review-package",
        params={"profile": "full", "generated_at": GENERATED_AT},
    )
    assert baseline_package.status_code == 200, baseline_package.text

    install_network_guard()
    with pytest.raises(AssertionError, match=NETWORK_FORBIDDEN):
        socket.create_connection(("example.com", 443), timeout=1)
    with _forbid_sql_writes(database.engine):
        response = client.get(
            "/api/export/ai-financial-review",
            params={"generated_at": GENERATED_AT},
        )

    assert response.status_code == 200, response.text
    payload = json.loads(response.content.decode("utf-8"))
    _financial_review_validator().validate(payload)
    assert payload["schema_name"] == "hermes.finance.ai_financial_review"
    assert payload["schema_version"] == "1.0.0"
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert payload["metadata"]["generation_mode"] == "read_only"
    assert payload["metadata"]["source_contracts"] == [
        {
            "name": "hermes.finance.ai_analysis_bundle",
            "version": "1.2.0",
            "role": "financial_source",
        },
        {
            "name": "hermes.finance.portfolio_review_package",
            "version": "1.0.0",
            "role": "envelope_source",
        },
    ]

    sections = payload["sections"]
    history = sections["historical_dynamics"]["data"]["history"]
    assert [(item["period"]["year"], item["period"]["month"]) for item in history] == sorted(
        (item["period"]["year"], item["period"]["month"]) for item in history
    )
    assert payload["scope"]["missing_calendar_periods"] == [{"year": 2026, "month": 2}]
    assert sections["current_capital"]["data"]["total_net_worth"]["value"] is None
    assert sections["current_capital"]["data"]["total_net_worth"]["availability"] == "unavailable"

    portfolio = sections["current_portfolio"]["data"]
    assert [item["ref"] for item in portfolio["accounts"]] == sorted(
        item["ref"] for item in portfolio["accounts"]
    )
    assert [item["ref"] for item in portfolio["instruments"]] == sorted(
        item["ref"] for item in portfolio["instruments"]
    )
    bond = next(item for item in portfolio["instruments"] if item["name"] == "Synthetic Bond")
    assert bond["isin"] == "RU000A0JXNU8"
    assert sections["current_portfolio"]["data"]["freshness"]["stale_valuation_count"] == 0

    passive = sections["passive_income"]["data"]
    assert set(passive["forecast"]["breakdown"]) == {
        "deposit_interest",
        "bond_coupons",
        "dividends",
        "other_capital_income",
    }
    assert set(passive["current_month_breakdown"]) == set(passive["forecast"]["breakdown"])

    flows = sections["future_cash_flows"]["data"]["items"]
    assert {item["flow_type"]: item["personal_tax_status"] for item in flows} == {
        "coupon": "known",
        "dividend": "known",
        "redemption": "not_applicable",
    }
    redemption = next(item for item in flows if item["flow_type"] == "redemption")
    assert redemption["amount_semantics"] == "principal"
    assert redemption["forecast_treatment"] == "excluded_principal"

    goal = sections["goals"]["data"]["items"][0]
    assert goal["deadline"]["value"] is None
    assert goal["deadline"]["reason_codes"] == ["no_deadline"]
    assert sections["iis_and_tax"]["data"]["iis_accounts"][0]["iis_type"] == "iis-a"
    assert sections["iis_and_tax"]["data"]["iis_accounts"][0]["eligible_close_at"] == ("2027-01-15")

    planned = sections["budget_and_saving"]["data"]["planned_budget"]
    assert planned["state"] == "not_entered"
    assert planned["lines"] == []
    assert planned["plan_vs_actual"]
    assert planned["plan_vs_actual"][0]["planned_amount"] is None
    assert sections["data_quality"]["status"] == "partial"
    assert "reporting_history_gap" in sections["data_quality"]["reason_codes"]
    assert "planned_budget_not_entered" in sections["data_quality"]["reason_codes"]

    assert [item["path"] for item in payload["field_states"]] == sorted(
        item["path"] for item in payload["field_states"]
    )
    warning_codes = [item["code"] for item in payload["warnings"]]
    assert len(warning_codes) == len(set(warning_codes))
    assert _table_counts(database) == before

    again = client.get(
        "/api/export/ai-financial-review",
        params={"generated_at": GENERATED_AT},
    )
    assert again.status_code == 200, again.text
    assert again.content == response.content
    download = client.get(
        "/api/export/ai-financial-review/json",
        params={"generated_at": GENERATED_AT},
    )
    assert download.status_code == 200, download.text
    assert download.content == response.content
    assert download.headers["content-disposition"] == (
        'attachment; filename="hermes-ai-financial-review-2026-04-30.json"'
    )

    after_bundle = _export(client).content
    after_package = client.get(
        "/api/export/portfolio-review-package",
        params={"profile": "full", "generated_at": GENERATED_AT},
    )
    assert after_package.status_code == 200, after_package.text
    assert after_bundle == baseline_bundle
    assert after_package.content == baseline_package.content
    assert _table_counts(database) == before

    keys = {key for value in _walk(payload) if isinstance(value, dict) for key in value}
    assert keys.isdisjoint(FORBIDDEN_KEYS)
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "d:\\" not in serialized
    assert "c:\\" not in serialized
    assert "file://" not in serialized
    assert "account:" not in serialized
    assert "position:" not in serialized
    assert not any(isinstance(value, float) for value in _walk(payload))


def test_ai_financial_review_routes_disable_caching(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    _seed_history(client)

    for path in ("/api/export/ai-financial-review", "/api/export/ai-financial-review/json"):
        response = client.get(path, params={"generated_at": GENERATED_AT})

        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"


def test_allocation_money_null_is_limited_to_unavailable_support(
    app_context: tuple[TestClient, Database],
) -> None:
    client, _database = app_context
    _seed_history(client)

    package_response = client.get(
        "/api/export/portfolio-review-package",
        params={"profile": "full", "generated_at": GENERATED_AT},
    )
    assert package_response.status_code == 200, package_response.text
    package = package_response.json()
    allocation = package["sections"]["allocation"]["data"]["allocation_by_asset_class"]
    assert allocation["support"]["status"] == "complete"
    allocation["denominator"] = None
    assert not _portfolio_review_validator().is_valid(package)
    package = package_response.json()
    top_positions = package["sections"]["allocation"]["data"]["top_positions"]
    assert top_positions["support"]["status"] == "complete"
    top_positions["top_amount"] = None
    assert not _portfolio_review_validator().is_valid(package)

    review_response = client.get(
        "/api/export/ai-financial-review",
        params={"generated_at": GENERATED_AT},
    )
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    allocation = review["sections"]["allocation_and_concentration"]["data"][
        "allocation_by_asset_class"
    ]
    assert allocation["support"]["status"] == "complete"
    allocation["denominator"] = None
    assert not _financial_review_validator().is_valid(review)
    review = review_response.json()
    top_positions = review["sections"]["allocation_and_concentration"]["data"]["top_positions"]
    assert top_positions["support"]["status"] == "complete"
    top_positions["top_amount"] = None
    assert not _financial_review_validator().is_valid(review)


def test_ai_financial_review_preserves_authoritative_context_and_zero_unknown_states(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    seed = _seed_history(client)
    _ok(client.post(f"/api/months/{seed['latest_closed']}/reopen"), status=200)
    gold = _ok(
        client.post(
            "/api/instruments",
            json={"name": "Synthetic Gold", "instrument_type": "gold"},
        )
    )["id"]
    _ok(
        client.post(
            "/api/positions",
            json={
                "reporting_month_id": seed["latest_closed"],
                "account_id": seed["brokerage"],
                "instrument_id": gold,
                "quantity": "2",
                "average_cost_per_unit": _money("70000.00"),
                "market_price_per_unit": _money("76000.00"),
                "price_date": "2026-04-30",
                "price_source": "manual",
                "notes": "Physical gold position",
            },
        )
    )
    _close(client, seed["latest_closed"])
    _ok(
        client.post(
            "/api/goals",
            json={
                "name": "Passive income goal",
                "goal_type": "passive_income",
                "target_value": _money("50000.00"),
                "target_date": "2031-12-31",
                "is_main": False,
                "calculation_mode": "monthly_net_passive_income",
            },
        )
    )

    with database.session_factory() as session:
        bond_position = session.scalars(
            select(PositionSnapshot)
            .where(
                PositionSnapshot.reporting_month_id == seed["latest_closed"],
                PositionSnapshot.account_id == seed["brokerage"],
            )
            .order_by(PositionSnapshot.id)
        ).first()
        debt = session.scalar(
            select(Debt).where(
                Debt.reporting_month_id == seed["latest_closed"],
                Debt.name == "Synthetic card",
            )
        )
        saving = session.scalar(
            select(SavingAllocation).where(
                SavingAllocation.reporting_month_id == seed["latest_closed"],
            )
        )
        goal = session.scalars(
            select(Goal).where(Goal.name == "Passive income goal").order_by(Goal.id)
        ).first()
        comment = MonthlyComment(
            reporting_month_id=seed["latest_closed"],
            position=1,
            text="Comment amount 987654.32 is context, not a financial row.",
        )
        assert bond_position is not None
        assert debt is not None
        assert saving is not None
        assert goal is not None
        bond_position.notes = "Bond note is owner context."
        debt.annual_rate_basis_points = 0
        debt.notes = "Debt note is owner context."
        saving.notes = "Reserve destination note."
        goal.target_date = date(2030, 12, 31)
        session.add(comment)
        session.commit()

    before = _table_counts(database)
    with _forbid_sql_writes(database.engine):
        response = client.get(
            "/api/export/ai-financial-review",
            params={"generated_at": GENERATED_AT},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    _financial_review_validator().validate(payload)

    portfolio = payload["sections"]["current_portfolio"]["data"]
    instruments = {item["name"]: item for item in portfolio["instruments"]}
    assert instruments["Synthetic Bond"]["isin"] == "RU000A0JXNU8"
    assert instruments["Synthetic Gold"]["instrument_type"] == "gold"
    assert instruments["Synthetic Gold"]["isin"] is None
    gold_position = next(
        item
        for item in portfolio["positions"]
        if item["instrument_ref"] == instruments["Synthetic Gold"]["ref"]
    )
    assert gold_position["quantity"] == "2"
    assert gold_position["average_acquisition_cost_per_unit"]["value"]["amount"] == ("70000.00")
    assert gold_position["market_price_per_unit"]["value"]["amount"] == "76000.00"
    assert gold_position["cost_basis"]["value"]["amount"] == "140000.00"
    assert gold_position["market_value"]["value"]["amount"] == "152000.00"

    debt = payload["sections"]["debts_and_real_estate"]["data"]["debts"][0]
    assert debt["annual_rate"] == {
        "value_pct": "0",
        "availability": "available",
        "precision": "exact",
        "source": "persisted_snapshot",
        "reason_codes": [],
    }
    property_item = payload["sections"]["debts_and_real_estate"]["data"]["real_estate"][0]
    assert property_item["mortgage_annual_rate"]["value_pct"] is None
    assert property_item["mortgage_annual_rate"]["availability"] == "unavailable"
    assert "mortgage_rate_unknown" in property_item["mortgage_annual_rate"]["reason_codes"]

    goals = payload["sections"]["goals"]["data"]["items"]
    assert sorted(item["deadline"]["value"] for item in goals) == [
        "2030-12-31",
        "2031-12-31",
    ]
    comments = payload["sections"]["user_context"]["data"]["monthly_comments"]
    assert comments[0]["text"] == "Comment amount 987654.32 is context, not a financial row."
    assert json.dumps(payload, ensure_ascii=False).count("987654.32") == 1
    assert (
        payload["sections"]["budget_and_saving"]["data"]["saving_allocations"][0]["notes"]
        == "Reserve destination note."
    )
    assert any(
        item["text"] == "Bond note is owner context." and item["source_type"] == "position"
        for item in payload["sections"]["user_context"]["data"]["entity_notes"]
    )
    iis = payload["sections"]["iis_and_tax"]["data"]["iis_accounts"][0]
    assert iis["iis_type"] == "iis-a"
    assert iis["opened_at"] == "2024-01-15"
    assert iis["eligible_close_at"] == "2027-01-15"
    assert iis["tax_benefits"]["received"]["amount"] == "52000.00"
    assert _table_counts(database) == before


def test_ai_financial_review_matches_duplicate_rows_fifo_and_synthetic_cash_ref(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    seed = _seed_history(client)
    with database.session_factory() as session:
        deposit = session.scalar(
            select(DepositSnapshot).where(
                DepositSnapshot.reporting_month_id == seed["latest_closed"],
                DepositSnapshot.account_id == seed["deposit"],
                DepositSnapshot.name == "Fixed deposit",
            )
        )
        cash = session.scalar(
            select(CashBalance).where(
                CashBalance.reporting_month_id == seed["latest_closed"],
                CashBalance.name == "Wallet",
            )
        )
        assert deposit is not None
        assert cash is not None
        deposit.notes = "first deposit row"
        cash.notes = "first cash row"
        session.commit()

    _ok(client.post(f"/api/months/{seed['latest_closed']}/reopen"), status=200)
    _ok(
        client.post(
            "/api/deposits",
            json={
                "reporting_month_id": seed["latest_closed"],
                "account_id": seed["deposit"],
                "name": "Fixed deposit",
                "deposit_type": "deposit",
                "balance": _money("1000000.00"),
                "annual_rate": "13.80",
                "actual_interest_received": _money("7000.00"),
                "notes": "second deposit row",
            },
        )
    )
    _ok(
        client.post(
            "/api/cash-balances",
            json={
                "reporting_month_id": seed["latest_closed"],
                "account_id": seed["brokerage"],
                "name": "Wallet",
                "amount": _money("400000.00"),
                "notes": "second cash row",
            },
        )
    )
    _close(client, seed["latest_closed"])

    before = _table_counts(database)
    response = client.get(
        "/api/export/ai-financial-review",
        params={"generated_at": GENERATED_AT},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    _financial_review_validator().validate(payload)
    portfolio = payload["sections"]["current_portfolio"]["data"]
    deposits = [item for item in portfolio["deposits"] if item["name"] == "Fixed deposit"]
    cash_rows = [item for item in portfolio["cash_balances"] if item["name"] == "Wallet"]
    assert [item["notes"] for item in deposits] == [
        "first deposit row",
        "second deposit row",
    ]
    assert [item["notes"] for item in cash_rows] == ["first cash row", "second cash row"]
    assert len({item["account_ref"] for item in cash_rows}) == 1
    assert cash_rows[0]["account_ref"].startswith("acct-cash-balances")
    assert _table_counts(database) == before


def test_ai_financial_review_merges_freshness_summary_and_bundle_valuation_fields(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    _seed_issue_285_august_fixture(client)
    before = _table_counts(database)

    with _forbid_sql_writes(database.engine):
        response = client.get(
            "/api/export/ai-financial-review",
            params={"generated_at": GENERATED_AT},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    _financial_review_validator().validate(payload)

    section = payload["sections"]["current_portfolio"]
    freshness = section["data"]["freshness"]
    assert section["status"] == "partial"
    assert "stale_valuation" in section["reason_codes"]
    assert (
        "active_account_snapshot_missing"
        in payload["coverage"]["domains"]["portfolio"]["reason_codes"]
    )
    assert "stale_valuation" in payload["coverage"]["domains"]["portfolio"]["reason_codes"]
    assert freshness["stale_valuation_count"] == 1
    assert freshness["position_count"] == 1
    assert freshness["oldest_price_date"] == "2026-07-31"
    assert freshness["latest_price_date"] == "2026-07-31"
    assert freshness["stale_valuation_share"]["value_pct"] == "100.00"
    assert freshness["families"]
    assert any(item["family_id"] == "market_quotes" for item in freshness["families"])
    assert any(item["code"] == "stale_valuation" for item in payload["warnings"])
    assert "stale_valuation" in payload["sections"]["data_quality"]["reason_codes"]
    assert _table_counts(database) == before
