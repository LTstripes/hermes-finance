"""Synthetic assistant-facing question evaluation for the R08 package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

pytestmark = [pytest.mark.import_export, pytest.mark.network_free]

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = REPO_ROOT / "docs" / "portfolio_review_package.synthetic.json"
EVALUATION_PATH = REPO_ROOT / "docs" / "portfolio_review_package.assistant-evaluation.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _amount(metric: dict[str, object]) -> str:
    value = metric["value"]
    assert isinstance(value, dict)
    return f"{value['amount']} {value['currency']}"


def test_synthetic_assistant_questions_have_expected_ground_truth() -> None:
    package = _load(PACKAGE_PATH)
    evaluation = _load(EVALUATION_PATH)
    sections = package["sections"]
    assert isinstance(sections, dict)
    assert evaluation["profile"] == "concise"

    answers: dict[str, object] = {
        "selected_period": "2026-04",
        "liquid_capital_net": _amount(sections["capital"]["data"]["liquid_capital_net"]),
        "position_count": str(len(sections["positions"]["data"]["items"])),
        "passive_income_forecast": _amount(
            sections["passive_income"]["data"]["forecast"]["monthly_total"]
        ),
        "future_calendar_total": _amount(
            sections["future_cash_flows"]["data"]["calendar_total"]
        ),
        "redemption_semantics": "no"
        if next(
            item
            for item in sections["future_cash_flows"]["data"]["items"]
            if item["flow_type"] == "redemption"
        )["included_in_passive_income_forecast"]
        is False
        else "yes",
        "total_net_worth": "unavailable"
        if sections["capital"]["data"]["total_net_worth"]["value"] is None
        else "available",
        "concise_profile_omissions": ["allocation", "context", "deterministic_insights"],
    }

    questions = evaluation["questions"]
    assert isinstance(questions, list)
    assert {item["id"] for item in questions} == set(answers)
    for item in questions:
        assert answers[item["id"]] == item["expected"]


def test_evaluation_fixture_is_safe_and_package_contract_remains_valid() -> None:
    package = _load(PACKAGE_PATH)
    evaluation = _load(EVALUATION_PATH)
    schema = _load(REPO_ROOT / "docs" / "portfolio_review_package.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(package)

    serialized = json.dumps(evaluation, ensure_ascii=False).lower()
    assert "d:\\" not in serialized
    assert "c:\\" not in serialized
    assert "file://" not in serialized
    assert "token" not in serialized
    assert "raw_payload" not in serialized
