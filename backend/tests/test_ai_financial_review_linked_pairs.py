"""Synthetic #366-D coverage for linked pairs in the AI financial review."""

from __future__ import annotations

import json
from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import update

from hermes_finance.database import Database, create_database
from hermes_finance.domain import AccountType, DebtType
from hermes_finance.main import create_app
from hermes_finance.persistence import Account, Base, Debt
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.debts import create_debt, link_debt_to_account
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

pytestmark = [pytest.mark.import_export, pytest.mark.ci_integrations]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "ai_financial_review.schema.json"
GENERATED_AT = "2038-06-01T12:00:00+03:00"
LINKED_PAIR_ERROR_CODE = "linked_pair_read_model_unavailable"

_FORBIDDEN_KEYS = {
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


@pytest.fixture
def app_context(tmp_path: Path) -> Generator[tuple[TestClient, Database], None, None]:
    database = create_database(tmp_path / "ai_financial_review_linked_pairs.db")
    Base.metadata.create_all(database.engine)
    try:
        with TestClient(create_app(database)) as client:
            yield client, database
    finally:
        database.engine.dispose()


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _month(session, *, year: int, month: int):
    return create_reporting_month(
        session,
        year=year,
        month=month,
        snapshot_date=date(year, month, 28),
    )


def _linked_pair(
    session,
    *,
    month_id: int,
    account_name: str,
    asset_balance: str,
    debt_name: str,
    debt_balance: str,
    link: bool = True,
) -> tuple[Account, Debt]:
    account = create_account(
        session,
        name=account_name,
        account_type=AccountType.CASH,
    )
    create_cash_balance(
        session,
        reporting_month_id=month_id,
        account_id=account.id,
        name=f"{account_name} balance",
        amount=asset_balance,
    )
    debt = create_debt(
        session,
        reporting_month_id=month_id,
        debt_type=DebtType.CREDIT_CARD,
        name=debt_name,
        current_balance=debt_balance,
    )
    if link:
        link_debt_to_account(session, debt.id, account.id)
    return account, debt


def _report(client: TestClient) -> dict[str, Any]:
    response = client.get(
        "/api/export/ai-financial-review",
        params={"generated_at": GENERATED_AT},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    _validator().validate(payload)
    return payload


def _metric_amount(metric: dict[str, Any]) -> str:
    assert metric["availability"] == "available"
    assert metric["precision"] == "exact"
    return metric["value"]["amount"]


def _assert_report_privacy(payload: dict[str, Any]) -> None:
    keys = {key for value in _walk(payload) if isinstance(value, dict) for key in value}
    assert keys.isdisjoint(_FORBIDDEN_KEYS)
    pair_rows = payload["sections"]["current_capital"]["data"]["linked_pairs"]
    assert all("id" not in row for row in pair_rows)
    assert all("account_id" not in row and "debt_id" not in row for row in pair_rows)
    assert all(row["account_ref"].startswith("acct-") for row in pair_rows)
    assert all(row["debt_ref"].startswith("debt-") for row in pair_rows)
    assert all(row["ref"].startswith("linked-pair-") for row in pair_rows)
    assert not any(isinstance(value, float) for value in _walk(payload))


def test_linked_pairs_surface_canonical_balances_and_counting_semantics(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    with database.session_factory() as session:
        month = _month(session, year=2038, month=5)
        specs = (
            ("Synthetic pair A greater", "1000.00", "Synthetic debt A greater", "300.00"),
            ("Synthetic pair A equal", "1000.00", "Synthetic debt A equal", "1000.00"),
            ("Synthetic pair A less", "300.00", "Synthetic debt A less", "1000.00"),
            ("Synthetic pair A zero", "0.00", "Synthetic debt A zero", "1000.00"),
            ("Synthetic pair D zero", "1000.00", "Synthetic debt D zero", "0.00"),
        )
        pairs = [
            _linked_pair(
                session,
                month_id=month.id,
                account_name=account_name,
                asset_balance=asset_balance,
                debt_name=debt_name,
                debt_balance=debt_balance,
            )
            for account_name, asset_balance, debt_name, debt_balance in specs
        ]
        close_reporting_month(session, month.id)

    payload = _report(client)
    current = payload["sections"]["current_capital"]["data"]
    linked_pairs = current["linked_pairs"]
    assert payload["schema_version"] == "1.3.0"
    assert "linked_pair_read_model" in payload["provenance_summary"]["financial_sources"]
    assert len(linked_pairs) == len(specs)
    assert [item["ref"] for item in linked_pairs] == sorted(item["ref"] for item in linked_pairs)
    assert len({item["ref"] for item in linked_pairs}) == len(specs)

    expected_by_account = {
        pair[0].name: (asset_balance, debt_balance)
        for pair, (_, asset_balance, _, debt_balance) in zip(pairs, specs, strict=True)
    }
    actual_by_account = {item["account_name"]: item for item in linked_pairs}
    assert set(actual_by_account) == set(expected_by_account)
    for account_name, (asset_balance, debt_balance) in expected_by_account.items():
        row = actual_by_account[account_name]
        assert _metric_amount(row["gross_asset_balance"]) == asset_balance
        assert _metric_amount(row["gross_linked_debt_balance"]) == debt_balance
        assert row["gross_asset_balance"]["source"] == "linked_pair_read_model"
        assert row["gross_linked_debt_balance"]["source"] == "linked_pair_read_model"
        assert row["net_economic_contribution"]["source"] == "linked_pair_read_model"
        assert _metric_amount(row["net_economic_contribution"]) == (
            Decimal(asset_balance) - Decimal(debt_balance)
        ).quantize(Decimal("0.00")).__format__("f")
        assert row["double_count_prevention"] == {
            "status": "canonical_totals_include_gross_pair_facts",
            "gross_asset_treatment": "included_in_liquid_assets_total",
            "gross_debt_treatment": "included_in_included_debts",
            "net_contribution_treatment": "explanatory_only",
            "additional_capital_adjustment": "none",
            "reason_codes": [
                "linked_pair_gross_facts_in_canonical_totals",
                "linked_pair_net_contribution_explanatory_only",
                "linked_pair_no_additional_capital_adjustment",
            ],
        }

    assert _metric_amount(current["liquid_assets_total"]) == "3300.00"
    assert _metric_amount(current["included_debts"]) == "3300.00"
    assert _metric_amount(current["liquid_capital_net"]) == "0.00"
    assert sum(
        (Decimal(item["net_economic_contribution"]["value"]["amount"]) for item in linked_pairs),
        Decimal("0.00"),
    ) == Decimal("0.00")

    history = payload["sections"]["historical_dynamics"]["data"]["history"]
    assert [item["ref"] for item in history[-1]["linked_pairs"]] == [
        item["ref"] for item in linked_pairs
    ]
    assert {item["debt_ref_scope"] for item in linked_pairs} == {"current_snapshot"}
    assert {item["debt_ref_scope"] for item in history[-1]["linked_pairs"]} == {"historical_period"}
    _assert_report_privacy(payload)


def test_duplicate_names_keep_export_local_pair_refs_integrity(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    with database.session_factory() as session:
        month = _month(session, year=2038, month=5)
        _linked_pair(
            session,
            month_id=month.id,
            account_name="Synthetic duplicate account",
            asset_balance="100.00",
            debt_name="Synthetic duplicate debt",
            debt_balance="10.00",
        )
        _linked_pair(
            session,
            month_id=month.id,
            account_name="Synthetic duplicate account",
            asset_balance="200.00",
            debt_name="Synthetic duplicate debt",
            debt_balance="20.00",
        )
        close_reporting_month(session, month.id)

    payload = _report(client)
    pairs = payload["sections"]["current_capital"]["data"]["linked_pairs"]
    assert len(pairs) == 2
    assert len({row["account_ref"] for row in pairs}) == 2
    assert len({row["debt_ref"] for row in pairs}) == 2
    assert len({row["ref"] for row in pairs}) == 2
    assert {row["debt_ref_scope"] for row in pairs} == {"current_snapshot"}

    accounts = {
        row["ref"]: row for row in payload["sections"]["current_portfolio"]["data"]["accounts"]
    }
    debts = {row["ref"] for row in payload["sections"]["debts_and_real_estate"]["data"]["debts"]}
    assert {row["account_ref"] for row in pairs} <= set(accounts)
    assert {row["debt_ref"] for row in pairs} <= debts
    assert {row["account_name"] for row in pairs} == {"Synthetic duplicate account"}
    assert {row["debt_name"] for row in pairs} == {"Synthetic duplicate debt"}

    for row in pairs:
        account = accounts[row["account_ref"]]
        assert account["name"] == row["account_name"]
        assert account["account_type"] == row["account_type"]
        assert row["debt_ref"].startswith("debt-")
    assert {row["gross_asset_balance"]["value"]["amount"] for row in pairs} == {
        "100.00",
        "200.00",
    }
    assert {row["gross_linked_debt_balance"]["value"]["amount"] for row in pairs} == {
        "10.00",
        "20.00",
    }
    _assert_report_privacy(payload)


def test_history_is_month_local_and_does_not_backfill_changed_links(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    with database.session_factory() as session:
        account = create_account(
            session,
            name="Synthetic history account",
            account_type=AccountType.CASH,
        )
        debt_names = []
        for month_number, debt_name, debt_balance, link in (
            (1, "Synthetic history first debt", "200.00", True),
            (2, "Synthetic history unlinked debt", "300.00", False),
            (3, "Synthetic history changed debt", "400.00", True),
        ):
            month = _month(session, year=2038, month=month_number)
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name=f"Synthetic history cash {month_number}",
                amount="1000.00",
            )
            debt = create_debt(
                session,
                reporting_month_id=month.id,
                debt_type=DebtType.CREDIT_CARD,
                name=debt_name,
                current_balance=debt_balance,
            )
            debt_names.append(debt_name)
            if link:
                link_debt_to_account(session, debt.id, account.id)
            close_reporting_month(session, month.id)

    payload = _report(client)
    current = payload["sections"]["current_capital"]["data"]["linked_pairs"]
    history = payload["sections"]["historical_dynamics"]["data"]["history"]
    assert [(point["period"]["year"], point["period"]["month"]) for point in history] == [
        (2038, 1),
        (2038, 2),
        (2038, 3),
    ]
    assert [row["debt_name"] for row in history[0]["linked_pairs"]] == [debt_names[0]]
    assert history[1]["linked_pairs"] == []
    assert [row["debt_name"] for row in history[2]["linked_pairs"]] == [debt_names[2]]
    assert [row["ref"] for row in current] == [row["ref"] for row in history[2]["linked_pairs"]]
    assert current[0]["debt_ref_scope"] == "current_snapshot"
    assert history[2]["linked_pairs"][0]["debt_ref_scope"] == "historical_period"
    assert current[0]["debt_ref"] != history[2]["linked_pairs"][0]["debt_ref"]
    assert debt_names[0] not in {row["debt_name"] for row in history[2]["linked_pairs"]}
    _assert_report_privacy(payload)


def test_cloned_same_name_debt_refs_are_period_scoped_in_history(
    app_context: tuple[TestClient, Database],
) -> None:
    client, database = app_context
    with database.session_factory() as session:
        account = create_account(
            session,
            name="Synthetic cloned debt account",
            account_type=AccountType.CASH,
        )
        for month_number, debt_balance in (
            (1, "100.00"),
            (2, "200.00"),
            (3, "300.00"),
        ):
            month = _month(session, year=2038, month=month_number)
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name=f"Synthetic cloned debt cash {month_number}",
                amount="1000.00",
            )
            debt = create_debt(
                session,
                reporting_month_id=month.id,
                debt_type=DebtType.CREDIT_CARD,
                name="Synthetic cloned credit card",
                current_balance=debt_balance,
            )
            link_debt_to_account(session, debt.id, account.id)
            close_reporting_month(session, month.id)

    payload = _report(client)
    current = payload["sections"]["current_capital"]["data"]
    current_pair = current["linked_pairs"][0]
    current_debts = payload["sections"]["debts_and_real_estate"]["data"]["debts"]
    current_debt_refs = {row["ref"] for row in current_debts}

    assert len(current["linked_pairs"]) == 1
    assert current_pair["debt_ref_scope"] == "current_snapshot"
    assert current_pair["debt_ref"] == "debt-synthetic-cloned-credit-card"
    assert current_pair["debt_ref"] in current_debt_refs
    current_debt = next(row for row in current_debts if row["name"] == current_pair["debt_name"])
    assert current_pair["debt_ref"] == current_debt["ref"]
    assert current_pair["debt_type"] == current_debt["debt_type"]

    history = payload["sections"]["historical_dynamics"]["data"]["history"]
    historical_pairs = [point["linked_pairs"][0] for point in history]
    assert [point["period"] for point in history] == [
        {"year": 2038, "month": 1},
        {"year": 2038, "month": 2},
        {"year": 2038, "month": 3},
    ]
    assert {row["debt_ref_scope"] for row in historical_pairs} == {"historical_period"}
    assert len({row["debt_ref"] for row in historical_pairs}) == 3
    assert all(row["debt_ref"].startswith("debt-history-2038-") for row in historical_pairs)
    assert all(row["debt_ref"] not in current_debt_refs for row in historical_pairs)
    assert all(row["debt_ref"] != current_pair["debt_ref"] for row in historical_pairs)
    _assert_report_privacy(payload)


def _seed_invalid_link(session, *, missing_balance: bool) -> None:
    month = _month(session, year=2038, month=5)
    account = create_account(
        session,
        name="Synthetic invalid linked account",
        account_type=AccountType.CASH,
    )
    if not missing_balance:
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic invalid linked cash",
            amount="100.00",
        )
    debt = create_debt(
        session,
        reporting_month_id=month.id,
        debt_type=DebtType.CREDIT_CARD,
        name="Synthetic invalid linked debt",
        current_balance="20.00",
    )
    if missing_balance:
        session.execute(update(Debt).where(Debt.id == debt.id).values(linked_account_id=account.id))
        session.commit()
    else:
        link_debt_to_account(session, debt.id, account.id)
        session.execute(
            update(Account).where(Account.id == account.id).values(include_in_capital=False)
        )
        session.commit()
    close_reporting_month(session, month.id)


@pytest.mark.parametrize("missing_balance", [True, False], ids=["missing-balance", "invalid-link"])
def test_invalid_canonical_linked_pair_fails_whole_report_closed(
    app_context: tuple[TestClient, Database],
    missing_balance: bool,
) -> None:
    client, database = app_context
    with database.session_factory() as session:
        _seed_invalid_link(session, missing_balance=missing_balance)

    failing_client = TestClient(client.app, raise_server_exceptions=False)
    try:
        response = failing_client.get(
            "/api/export/ai-financial-review",
            params={"generated_at": GENERATED_AT},
        )
    finally:
        failing_client.close()

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == LINKED_PAIR_ERROR_CODE
    assert "sections" not in body
    assert "linked_pairs" not in body
    assert "account_id" not in response.text
    assert "debt_id" not in response.text
