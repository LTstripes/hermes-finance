"""Schema contract tests for the #331 canonical AI financial review export."""

from __future__ import annotations

import copy
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from hermes_finance.services import ai_review_payloads as payloads
from hermes_finance.services.ai_financial_review import (
    AiFinancialReviewValidationError,
    canonical_json,
    validate_ai_financial_review,
)

pytestmark = [pytest.mark.import_export, pytest.mark.ci_integrations]

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "ai_financial_review.schema.json"
FIXTURE_PATH = REPO_ROOT / "docs" / "schemas" / "ai_financial_review.synthetic.json"
SCHEMAS = SCHEMA_PATH.parent


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


def test_v1_3_linked_pairs_are_optional_but_canonical_fixture_emits_them() -> None:
    fixture = _load(FIXTURE_PATH)
    current_capital = fixture["sections"]["current_capital"]["data"]
    history = fixture["sections"]["historical_dynamics"]["data"]["history"]

    assert "linked_pairs" in current_capital
    assert history
    assert all("linked_pairs" in point for point in history)

    without_linked_pairs = copy.deepcopy(fixture)
    without_linked_pairs["sections"]["current_capital"]["data"].pop("linked_pairs")
    for point in without_linked_pairs["sections"]["historical_dynamics"]["data"]["history"]:
        point.pop("linked_pairs")

    _validate(without_linked_pairs)


def test_v1_5_current_returns_are_optional_and_v1_4_remains_readable() -> None:
    previous = _load(FIXTURE_PATH)
    previous["schema_version"] = "1.4.0"
    previous["$schema"] = previous["$schema"].replace("1.5.0", "1.4.0")
    previous["sections"].pop("returns_overall", None)
    previous["coverage"]["domains"].pop("returns_overall", None)
    _validate(previous)

    additive = copy.deepcopy(previous)
    additive["schema_version"] = "1.5.0"
    additive["$schema"] = additive["$schema"].replace("1.4.0", "1.5.0")
    _validate(additive)


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
    not_entered_with_line["sections"]["budget_and_saving"]["data"]["planned_budget"]["lines"] = [
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


@pytest.fixture
def report():
    return json.loads((SCHEMAS / "ai_financial_review.synthetic.json").read_text("utf-8"))


def instrument(report):
    return report["sections"]["source_returns"]["data"]["accounts"][0]["intervals"][0][
        "instruments"
    ][0]


def test_v2_strict_fixture_expands_to_the_same_legacy_facts(report):
    normalized = payloads.normalize_source_payloads(report)
    validate_ai_financial_review(normalized)
    assert payloads.expand_source_payloads(normalized) == report
    assert json.loads(canonical_json(payloads.expand_source_payloads(normalized))) == report
    assert normalized == json.loads(
        (SCHEMAS / "ai_financial_review.v2.synthetic.json").read_text("utf-8")
    )
    validate_ai_financial_review(report)


def test_equal_events_remain_two_occurrences_and_window_variants_stay_distinct(report):
    row = instrument(report)
    event = deepcopy(row["events"][0])
    crossing = deepcopy(event)
    crossing.update(counted=False, cash_scope="cross_boundary", quantity_delta=None)
    for leg in crossing["cash_legs"]:
        leg.update(account_cash=None, instrument_flow=None, included_in_interval=False)
    row["events"] = [event, deepcopy(event), crossing]
    normalized = payloads.normalize_source_payloads(report)
    refs = instrument(normalized)["event_refs"]
    assert len(refs) == 3 and refs[0] == refs[1] and refs[2] != refs[0]
    restored = payloads.expand_source_payloads(normalized)
    assert restored == report
    assert len(instrument(restored)["events"]) == 3
    assert instrument(restored)["events"][2]["producer_eligible"] is True
    assert instrument(restored)["events"][2]["cash_legs"][0]["account_cash"] is None
    # Sharing a payload never shares a mutable reconstructed occurrence.
    instrument(restored)["events"][0]["reason_codes"].append("changed_by_consumer")
    assert instrument(restored)["events"][1]["reason_codes"] == []
    assert payloads.expand_source_payloads(normalized) == report
    validate_ai_financial_review(normalized)


def test_source_context_order_and_metadata_variants_are_not_entity_deduplication(report):
    account = report["sections"]["source_returns"]["data"]["accounts"][0]
    second = deepcopy(account["intervals"][0])
    second["ref"] += "-alternate"
    second["instruments"][0]["name"] = "Synthetic alternate source spelling"
    second["instruments"][0]["assumptions"] = ["synthetic_unconfirmed_revision"]
    account["intervals"].append(second)
    normalized = payloads.normalize_source_payloads(report)
    refs = [
        row["instruments"][0]
        for row in normalized["sections"]["source_returns"]["data"]["accounts"][0]["intervals"]
    ]
    assert refs[0]["instrument_ref"] != refs[1]["instrument_ref"]
    assert refs[0]["result_ref"] != refs[1]["result_ref"]
    assert payloads.expand_source_payloads(normalized) == report
    reordered = deepcopy(report)
    reordered["sections"]["source_returns"]["data"]["accounts"][0]["intervals"].reverse()
    other = payloads.normalize_source_payloads(reordered)
    assert other["source_payloads"] == normalized["source_payloads"]
    assert payloads.expand_source_payloads(other) == reordered


def test_gold_revisions_and_unknown_zero_values_are_not_traversed_or_reconciled(report):
    from test_ai_analysis_bundle_source_returns import _gold_history_fixture

    from hermes_finance.services import ai_source_returns

    history = ai_source_returns._gold_history(
        _gold_history_fixture(),
        1,
        {40: "returns-gold-account-1"},
        {90: "returns-gold-instrument-1"},
    )
    # The stable event ref is reused by a corrected history revision. Its old
    # actual amount remains a different fact; NULL tax never becomes zero.
    history["revisions"][0]["events"][0]["amount"]["amount"] = "312.34"
    assert history["events"][0]["ref"] == history["revisions"][0]["events"][0]["ref"]
    assert history["events"][0]["amount"] != history["revisions"][0]["events"][0]["amount"]
    report["sections"]["returns_overall"]["data"]["gold"]["histories"] = [history]
    validate_ai_financial_review(report)
    normalized = payloads.normalize_source_payloads(report)
    validate_ai_financial_review(normalized)
    assert normalized["sections"]["returns_overall"]["data"]["gold"]["histories"] == [history]
    assert payloads.expand_source_payloads(normalized) == report


@pytest.mark.parametrize(
    "mutation", ["dangling", "wrong_table", "isin", "changed_payload", "orphan", "cycle"]
)
def test_reference_corruption_cannot_validate(report, mutation):
    normalized = payloads.normalize_source_payloads(report)
    row = instrument(normalized)
    tables = normalized["source_payloads"]
    if mutation == "dangling":
        row["event_refs"].append("event-" + "0" * 32)
    elif mutation == "wrong_table":
        row["result_ref"] = row["opening_ref"]
    elif mutation == "isin":
        row["isin"] = "SYNTHETIC-DIFFERENT"
    elif mutation == "changed_payload":
        tables["events"][row["event_refs"][0]]["counted"] = False
    elif mutation == "orphan":
        value = deepcopy(next(iter(tables["events"].values())))
        value["reason_codes"] = ["synthetic_orphan"]
        tables["events"][payloads._ref("events", value)] = value
    else:
        tables["events"][row["event_refs"][0]]["event_refs"] = row["event_refs"]
    with pytest.raises(AiFinancialReviewValidationError):
        validate_ai_financial_review(normalized)


def test_hash_collision_fails_instead_of_overwriting_distinct_facts(report, monkeypatch):
    original = payloads._ref
    monkeypatch.setattr(
        payloads,
        "_ref",
        lambda table, value: "event-" + "0" * 32 if table == "events" else original(table, value),
    )
    other = deepcopy(instrument(report)["events"][0])
    other["reason_codes"] = ["synthetic_different_revision"]
    instrument(report)["events"].append(other)
    with pytest.raises(payloads.PayloadReferenceError, match="collision"):
        payloads.normalize_source_payloads(report)


def test_unknown_fields_cannot_be_silently_dropped(report):
    instrument(report)["future_financial_fact"] = {"amount": "17.50"}
    with pytest.raises(payloads.PayloadReferenceError, match="unexpected"):
        payloads.normalize_source_payloads(report)


def test_v2_keeps_every_unchanged_v1_schema_definition_strict():
    old = json.loads((SCHEMAS / "ai_financial_review.schema.json").read_text("utf-8"))
    new = json.loads((SCHEMAS / "ai_financial_review.v2.schema.json").read_text("utf-8"))
    assert new["additionalProperties"] is False
    for name, definition in old["$defs"].items():
        if name != "source_instrument":
            assert new["$defs"][name] == definition, name


def test_historical_v1_4_report_remains_losslessly_expandable(report):
    report["schema_version"] = "1.4.0"
    report["$schema"] = report["$schema"].replace("1.5.0", "1.4.0")
    report["sections"].pop("returns_overall")
    report["coverage"]["domains"].pop("returns_overall")
    validate_ai_financial_review(report)
    normalized = payloads.normalize_source_payloads(report)
    validate_ai_financial_review(normalized)
    assert payloads.expand_source_payloads(normalized) == report
