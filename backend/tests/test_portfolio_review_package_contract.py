"""R08-AI01 synthetic portfolio-review package contract tests."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Iterator

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

pytestmark = pytest.mark.import_export

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "portfolio_review_package.schema.json"
FIXTURE_PATH = REPO_ROOT / "docs" / "portfolio_review_package.synthetic.json"

CORE_SECTIONS = (
    "capital",
    "positions",
    "dynamics",
    "passive_income",
    "future_cash_flows",
    "freshness",
)
FULL_ONLY_SECTIONS = ("allocation", "context", "deterministic_insights")

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


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_load(SCHEMA_PATH), format_checker=FormatChecker())


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _amount(metric: dict[str, object]) -> str:
    value = metric["value"]
    assert isinstance(value, dict)
    return str(value["amount"])


def _concise_projection(full: dict[str, object]) -> dict[str, object]:
    concise = deepcopy(full)
    concise["profile"] = "concise"
    scope = concise["scope"]
    assert isinstance(scope, dict)
    scope["requested_sections"] = list(CORE_SECTIONS)

    sections = concise["sections"]
    assert isinstance(sections, dict)
    field_states = concise["field_states"]
    assert isinstance(field_states, list)
    for section_name in FULL_ONLY_SECTIONS:
        sections[section_name] = {
            "status": "omitted",
            "reason_codes": ["profile_concise"],
            "data": None,
        }
        field_states.append(
            {
                "path": f"sections.{section_name}",
                "status": "omitted",
                "reason_codes": ["profile_concise"],
                "message": "The concise profile omits this extended review section.",
            }
        )
    return concise


def test_schema_and_full_synthetic_fixture_validate() -> None:
    fixture = _load(FIXTURE_PATH)
    _validator().validate(fixture)

    assert fixture["schema_name"] == "hermes.finance.portfolio_review_package"
    assert fixture["schema_version"] == "1.0.0"
    assert fixture["profile"] == "full"
    sections = fixture["sections"]
    assert isinstance(sections, dict)
    assert set(sections) == set((*CORE_SECTIONS, *FULL_ONLY_SECTIONS))
    assert all(section["data"] is not None for section in sections.values())


def test_concise_profile_keeps_review_core_and_marks_omissions() -> None:
    concise = _concise_projection(_load(FIXTURE_PATH))
    _validator().validate(concise)

    sections = concise["sections"]
    assert isinstance(sections, dict)
    for section_name in CORE_SECTIONS:
        assert sections[section_name]["status"] in {"included", "partial"}
        assert sections[section_name]["data"] is not None
    for section_name in FULL_ONLY_SECTIONS:
        assert sections[section_name] == {
            "status": "omitted",
            "reason_codes": ["profile_concise"],
            "data": None,
        }

    field_states = concise["field_states"]
    omitted_paths = {item["path"] for item in field_states if item["status"] == "omitted"}
    assert omitted_paths == {f"sections.{name}" for name in FULL_ONLY_SECTIONS}


def test_fixture_answers_core_portfolio_review_questions() -> None:
    fixture = _load(FIXTURE_PATH)
    sections = fixture["sections"]
    assert isinstance(sections, dict)

    capital = sections["capital"]["data"]
    assert isinstance(capital, dict)
    assert _amount(capital["liquid_capital_net"]) == "2300000.00"
    assert _amount(capital["property_equity"]) == "5000000.00"
    assert Decimal(_amount(capital["liquid_assets_total"])) - Decimal(
        _amount(capital["included_debts"])
    ) == Decimal(_amount(capital["liquid_capital_net"]))

    positions = sections["positions"]["data"]
    assert isinstance(positions, dict)
    assert len(positions["items"]) == 3
    assert {item["instrument_ref"] for item in positions["items"]} == {
        "inst-bond-a",
        "inst-gold",
        "inst-stock-a",
    }

    dynamics = sections["dynamics"]["data"]
    assert isinstance(dynamics, dict)
    history = dynamics["history"]
    assert len(history) == 3
    assert [item["period"] for item in history] == [
        {"year": 2026, "month": 1},
        {"year": 2026, "month": 3},
        {"year": 2026, "month": 4},
    ]
    assert dynamics["missing_calendar_periods"] == [{"year": 2026, "month": 2}]
    assert _amount(history[0]["liquid_capital_net"]) == "1850000.00"
    assert _amount(history[-1]["liquid_capital_net"]) == "2300000.00"

    passive_income = sections["passive_income"]["data"]
    assert isinstance(passive_income, dict)
    assert (
        passive_income["actual_history_metric_path"]
        == "sections.dynamics.data.history[].passive_income_actual"
    )
    assert _amount(passive_income["rolling_actual_average"]["value"]) == "15000.00"
    assert _amount(passive_income["forecast"]["monthly_total"]) == "22800.00"
    assert (
        Decimal(_amount(passive_income["forecast"]["annual_total"]))
        == Decimal(_amount(passive_income["forecast"]["monthly_total"])) * 12
    )

    future = sections["future_cash_flows"]["data"]
    assert isinstance(future, dict)
    non_principal = _amount(future["non_principal_calendar_amount_total"])
    principal = _amount(future["principal_total"])
    total = _amount(future["calendar_total"])
    assert total == "191000.00"
    assert int(total.split(".")[0]) == int(non_principal.split(".")[0]) + int(
        principal.split(".")[0]
    )
    assert Decimal(total) == Decimal(non_principal) + Decimal(principal)
    redemption = next(item for item in future["items"] if item["flow_type"] == "redemption")
    assert redemption["amount_semantics"] == "principal"
    assert redemption["included_in_passive_income_forecast"] is False
    provider_income_items = [
        item
        for item in future["items"]
        if item["provenance"]["provider"] and item["flow_type"] != "redemption"
    ]
    assert provider_income_items
    assert all(item["personal_tax_status"] == "unknown" for item in provider_income_items)
    assert redemption["personal_tax_status"] == "not_applicable"

    freshness = sections["freshness"]["data"]
    assert isinstance(freshness, dict)
    assert freshness["quote_valuation_target_date"] == "2026-04-30"
    family_ids = {family["family_id"] for family in freshness["families"]}
    assert family_ids == {
        "market_quotes",
        "t_invest_payouts",
        "alfa_pro_positions",
        "alfa_statement_payouts",
        "manual_month_data",
        "deposit_cash_snapshots",
    }
    assert any(family["status"] == "mixed" for family in freshness["families"])
    assert any(family["status"] == "unknown" for family in freshness["families"])

    warning_codes = {warning["code"] for warning in fixture["warnings"]}
    assert {
        "quote_stale",
        "incomplete_12_month_window",
        "reporting_history_gap",
        "cash_flow_adjusted_return_unavailable",
    } <= warning_codes


def test_unavailable_values_are_explicit_and_never_numeric() -> None:
    fixture = _load(FIXTURE_PATH)
    capital = fixture["sections"]["capital"]["data"]
    assert capital["total_net_worth"] == {
        "value": None,
        "availability": "unavailable",
        "precision": "unknown",
        "source": "backend_derived",
        "reason_codes": ["no_authoritative_aggregate"],
    }
    for point in fixture["sections"]["dynamics"]["data"]["history"]:
        assert point["market_value_change"]["value"] is None
        assert point["market_value_change"]["precision"] == "unknown"
        assert point["investment_return"]["value_pct"] is None
        assert point["investment_return"]["precision"] == "unknown"

    unavailable_metrics = [
        value
        for value in _walk(fixture)
        if isinstance(value, dict) and value.get("availability") == "unavailable"
    ]
    assert unavailable_metrics
    assert all(value["precision"] == "unknown" for value in unavailable_metrics)
    assert all(
        value.get("value") is None or value.get("value_pct") is None
        for value in unavailable_metrics
    )


def test_schema_rejects_inconsistent_section_state_and_unknown_fields() -> None:
    fixture = _load(FIXTURE_PATH)

    inconsistent = deepcopy(fixture)
    inconsistent["sections"]["allocation"]["status"] = "omitted"
    with pytest.raises(ValidationError):
        _validator().validate(inconsistent)

    unknown = deepcopy(fixture)
    unknown["sections"]["capital"]["data"]["technical_path"] = "not allowed"
    with pytest.raises(ValidationError):
        _validator().validate(unknown)


def test_fixture_is_stably_ordered_and_privacy_safe() -> None:
    fixture = _load(FIXTURE_PATH)
    sections = fixture["sections"]
    positions = sections["positions"]["data"]
    assert [account["ref"] for account in positions["accounts"]] == sorted(
        account["ref"] for account in positions["accounts"]
    )
    assert [instrument["ref"] for instrument in positions["instruments"]] == sorted(
        instrument["ref"] for instrument in positions["instruments"]
    )
    assert [(item["account_ref"], item["instrument_ref"]) for item in positions["items"]] == sorted(
        (item["account_ref"], item["instrument_ref"]) for item in positions["items"]
    )
    assert [
        item["expected_date"] for item in sections["future_cash_flows"]["data"]["items"]
    ] == sorted(item["expected_date"] for item in sections["future_cash_flows"]["data"]["items"])
    assert [item["period"] for item in sections["dynamics"]["data"]["history"]] == sorted(
        (item["period"] for item in sections["dynamics"]["data"]["history"]),
        key=lambda period: (period["year"], period["month"]),
    )

    keys = {key for value in _walk(fixture) if isinstance(value, dict) for key in value}
    assert keys.isdisjoint(FORBIDDEN_KEYS)
    serialized = json.dumps(fixture, ensure_ascii=False).lower()
    assert "d:\\" not in serialized
    assert "c:\\" not in serialized
    assert "file://" not in serialized
    assert not any(isinstance(value, float) for value in _walk(fixture))
