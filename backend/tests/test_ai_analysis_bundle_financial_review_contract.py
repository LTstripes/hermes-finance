"""Schema contract tests for the #331 canonical AI financial review export."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

pytestmark = [pytest.mark.import_export, pytest.mark.ci_integrations]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "ai_financial_review.schema.json"
FIXTURE_PATH = REPO_ROOT / "docs" / "ai_financial_review.synthetic.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_load(SCHEMA_PATH), format_checker=FormatChecker())


def _validate(document: dict[str, Any]) -> None:
    _validator().validate(document)


def _at(document: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    value: Any = document
    for key in path:
        value = value[int(key)] if isinstance(value, list) else value[key]
    assert isinstance(value, dict)
    return value


def test_synthetic_fixture_validates_and_explicit_zero_is_available() -> None:
    fixture = _load(FIXTURE_PATH)
    _validate(fixture)

    rate_zero = _at(
        fixture,
        ("sections", "debts_and_real_estate", "data", "debts", "0", "annual_rate"),
    )
    assert rate_zero == {
        "value_pct": "0",
        "availability": "available",
        "precision": "exact",
        "source": "persisted_snapshot",
        "reason_codes": [],
    }
    assert (
        fixture["sections"]["historical_dynamics"]["data"]["history"][0][
            "passive_income_actual_breakdown"
        ]["dividends"]["value"]["amount"]
        == "0.00"
    )


@pytest.mark.parametrize(
    ("path", "updates"),
    [
        (
            ("sections", "current_capital", "data", "liquid_assets_total"),
            {"availability": "available", "value": None},
        ),
        (
            ("sections", "current_capital", "data", "total_net_worth"),
            {"availability": "unavailable", "value": {"amount": "1.00", "currency": "RUB"}},
        ),
        (
            ("sections", "current_capital", "data", "total_net_worth"),
            {"precision": "exact"},
        ),
        (
            (
                "sections",
                "current_portfolio",
                "data",
                "freshness",
                "stale_valuation_share",
            ),
            {"availability": "available", "value_pct": None},
        ),
        (
            (
                "sections",
                "current_portfolio",
                "data",
                "freshness",
                "stale_valuation_share",
            ),
            {"availability": "unavailable", "value_pct": "0"},
        ),
        (
            (
                "sections",
                "current_portfolio",
                "data",
                "freshness",
                "stale_valuation_share",
            ),
            {"availability": "unavailable", "value_pct": None, "precision": "exact"},
        ),
        (
            ("sections", "debts_and_real_estate", "data", "debts", "0", "annual_rate"),
            {"availability": "available", "value_pct": None},
        ),
        (
            (
                "sections",
                "debts_and_real_estate",
                "data",
                "real_estate",
                "0",
                "mortgage_annual_rate",
            ),
            {"availability": "unavailable", "value_pct": "0"},
        ),
        (
            (
                "sections",
                "debts_and_real_estate",
                "data",
                "real_estate",
                "0",
                "mortgage_annual_rate",
            ),
            {"precision": "exact"},
        ),
        (
            (
                "sections",
                "debts_and_real_estate",
                "data",
                "debts",
                "0",
                "contract_end_date",
            ),
            {"availability": "unavailable", "value": "2026-12-31"},
        ),
        (
            (
                "sections",
                "debts_and_real_estate",
                "data",
                "debts",
                "0",
                "next_due_date",
            ),
            {"availability": "available", "value": None},
        ),
        (
            ("sections", "current_capital", "data", "liquid_assets_total"),
            {"value": {"amount": "1.00", "currency": "USD"}},
        ),
    ],
)
def test_schema_rejects_inconsistent_metric_state(
    path: tuple[str, ...], updates: dict[str, Any]
) -> None:
    candidate = copy.deepcopy(_load(FIXTURE_PATH))
    _at(candidate, path).update(updates)

    with pytest.raises(ValidationError):
        _validate(candidate)


def test_all_section_envelopes_require_state_compatible_data() -> None:
    fixture = _load(FIXTURE_PATH)
    sections = fixture["sections"]

    for section_name, section in sections.items():
        included_without_data = copy.deepcopy(fixture)
        included_target = included_without_data["sections"][section_name]
        included_target["data"] = None
        with pytest.raises(ValidationError):
            _validate(included_without_data)

        unavailable_with_data = copy.deepcopy(fixture)
        unavailable_target = unavailable_with_data["sections"][section_name]
        unavailable_target["status"] = "unavailable"
        unavailable_target["data"] = section["data"]
        with pytest.raises(ValidationError):
            _validate(unavailable_with_data)

        unavailable_without_data = copy.deepcopy(fixture)
        unavailable_target = unavailable_without_data["sections"][section_name]
        unavailable_target["status"] = "unavailable"
        unavailable_target["data"] = None
        _validate(unavailable_without_data)


def test_planned_budget_state_controls_lines_and_allows_actual_only_rows() -> None:
    fixture = _load(FIXTURE_PATH)
    budget = fixture["sections"]["budget_and_saving"]["data"]["planned_budget"]

    not_entered_with_line = copy.deepcopy(fixture)
    not_entered_with_line["sections"]["budget_and_saving"]["data"]["planned_budget"][
        "lines"
    ] = [
        {
            "ref": "planned-budget-housing",
            "period": {"year": 2026, "month": 8},
            "category": "Housing",
            "planned_amount": {"amount": "100000.00", "currency": "RUB"},
            "expense_type": "mandatory",
            "notes": None,
        }
    ]
    with pytest.raises(ValidationError):
        _validate(not_entered_with_line)

    entered_without_lines = copy.deepcopy(fixture)
    entered_budget = entered_without_lines["sections"]["budget_and_saving"]["data"][
        "planned_budget"
    ]
    entered_budget["state"] = "entered"
    entered_budget["lines"] = []
    with pytest.raises(ValidationError):
        _validate(entered_without_lines)

    actual_only = copy.deepcopy(fixture)
    actual_only_budget = actual_only["sections"]["budget_and_saving"]["data"]["planned_budget"]
    actual_only_budget["plan_vs_actual"] = [
        {
            "period": {"year": 2026, "month": 8},
            "category": "Housing",
            "expense_type": "mandatory",
            "planned_amount": None,
            "actual_amount": {"amount": "130000.00", "currency": "RUB"},
        }
    ]
    _validate(actual_only)

    assert budget["state"] == "not_entered"
    assert budget["lines"] == []
