import copy
import json
import re
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "ai_analysis_bundle.schema.json"
FIXTURE_PATH = REPO_ROOT / "docs" / "ai_analysis_bundle.synthetic.json"

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
MONEY_PATTERN = re.compile(r"^-?(0|[1-9][0-9]*)\.[0-9]{2}$")


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schema() -> dict[str, object]:
    return _load_json(SCHEMA_PATH)


@pytest.fixture(scope="module")
def bundle() -> dict[str, object]:
    return _load_json(FIXTURE_PATH)


def _validator(schema: dict[str, object]) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _amount(money: dict[str, str]) -> Decimal:
    assert money["currency"] == "RUB"
    assert MONEY_PATTERN.fullmatch(money["amount"])
    return Decimal(money["amount"])


def _metric_amount(metric: dict[str, object]) -> Decimal:
    value = metric["value"]
    assert isinstance(value, dict)
    return _amount(value)


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_schema_is_valid_draft_2020_12_and_fixture_validates(
    schema: dict[str, object], bundle: dict[str, object]
) -> None:
    Draft202012Validator.check_schema(schema)
    _validator(schema).validate(bundle)


def test_schema_fails_closed_for_unknown_or_inconsistent_fields(
    schema: dict[str, object], bundle: dict[str, object]
) -> None:
    leaked = copy.deepcopy(bundle)
    leaked["api_token"] = "synthetic-but-forbidden"
    with pytest.raises(ValidationError):
        _validator(schema).validate(leaked)

    nested_leak = copy.deepcopy(bundle)
    nested_leak["metadata"]["calculation_versions"]["api_token"] = "synthetic-but-forbidden"
    with pytest.raises(ValidationError):
        _validator(schema).validate(nested_leak)

    inconsistent = copy.deepcopy(bundle)
    metric = inconsistent["iis_and_tax"]["salary_tax_context"]["taxable_gross_ytd"]
    metric["value"] = {"amount": "1.00", "currency": "RUB"}
    with pytest.raises(ValidationError):
        _validator(schema).validate(inconsistent)

    principal_as_income = copy.deepcopy(bundle)
    redemption = next(
        item
        for item in principal_as_income["upcoming_cash_flows"]["items"]
        if item["flow_type"] == "redemption"
    )
    redemption["included_in_passive_income_forecast"] = True
    with pytest.raises(ValidationError):
        _validator(schema).validate(principal_as_income)

    provider_as_exact_net = copy.deepcopy(bundle)
    provider_flow = next(
        item
        for item in provider_as_exact_net["upcoming_cash_flows"]["items"]
        if item["provenance"]["source_kind"] == "provider" and item["flow_type"] != "redemption"
    )
    provider_flow["amount_semantics"] = "owner_expected_net"
    provider_flow["personal_tax_status"] = "known_or_accounted"
    provider_flow["is_approximate"] = False
    provider_flow["reason_codes"] = []
    with pytest.raises(ValidationError):
        _validator(schema).validate(provider_as_exact_net)


def test_schema_represents_unavailable_breakdown_components(
    schema: dict[str, object], bundle: dict[str, object]
) -> None:
    unavailable_component = copy.deepcopy(bundle)
    component = unavailable_component["passive_income"]["forecast"]["breakdown"][
        "expected_coupon_component"
    ]
    component.update(
        value=None,
        availability="unavailable",
        precision="unknown",
        reason_codes=["provider_tax_semantics_unavailable"],
    )
    _validator(schema).validate(unavailable_component)

    unavailable_actual_component = copy.deepcopy(bundle)
    actual_component = unavailable_actual_component["reporting_history"][0]["kpis"][
        "passive_income_actual_breakdown"
    ]["dividends"]
    actual_component.update(
        value=None,
        availability="unavailable",
        precision="unknown",
        reason_codes=["actual_component_unavailable"],
    )
    _validator(schema).validate(unavailable_actual_component)


def test_fixture_is_multi_year_multi_status_and_preserves_unknown_gaps(
    bundle: dict[str, object],
) -> None:
    history = bundle["reporting_history"]
    periods = [(item["period"]["year"], item["period"]["month"]) for item in history]
    statuses = {item["status"] for item in history}

    assert periods == sorted(periods)
    assert len({year for year, _ in periods}) >= 2
    assert statuses == {"closed", "draft"}
    assert bundle["coverage"]["missing_calendar_periods"] == [{"year": 2026, "month": 2}]
    assert (2026, 2) not in periods


def test_actual_passive_income_and_rolling_average_reconcile(
    bundle: dict[str, object],
) -> None:
    history = bundle["reporting_history"]
    closed = [item for item in history if item["status"] == "closed"]
    closed_actuals: list[Decimal] = []

    for point in history:
        kpis = point["kpis"]
        breakdown = kpis["passive_income_actual_breakdown"]
        component_total = sum((_metric_amount(value) for value in breakdown.values()), Decimal(0))
        actual = _metric_amount(kpis["passive_income_actual"])
        assert component_total == actual
        if point["status"] == "closed":
            closed_actuals.append(actual)

    rolling = bundle["passive_income"]["rolling_actual_average"]
    assert rolling["eligible_month_count"] == len(closed) == 5
    assert rolling["is_complete_window"] is False
    assert _metric_amount(rolling["value"]) == sum(closed_actuals, Decimal(0)) / len(closed)
    assert bundle["passive_income"]["actual_history_metric_path"] == (
        "reporting_history[].kpis.passive_income_actual"
    )


def test_capital_portfolio_property_and_iis_semantics_reconcile(
    bundle: dict[str, object],
) -> None:
    closed_current = next(
        item for item in bundle["reporting_history"] if item["period"] == {"year": 2026, "month": 4}
    )
    kpis = closed_current["kpis"]
    assert _metric_amount(kpis["liquid_assets_total"]) - _metric_amount(
        kpis["included_debts"]
    ) == _metric_amount(kpis["liquid_capital_net"])

    portfolio = bundle["current_portfolio"]
    position_total = sum(
        (_metric_amount(item["market_value"]) for item in portfolio["positions"]), Decimal(0)
    )
    deposit_total = sum(
        (_metric_amount(item["balance"]) for item in portfolio["deposits"]), Decimal(0)
    )
    cash_total = sum(
        (
            _metric_amount(item["amount"])
            for item in portfolio["cash_balances"]
            if item["include_in_capital"]
        ),
        Decimal(0),
    )
    assert position_total + deposit_total + cash_total == _metric_amount(
        kpis["liquid_assets_total"]
    )

    property_data = bundle["debts_and_real_estate"]
    real_estate = property_data["real_estate"]
    assert _metric_amount(real_estate["estimated_value"]) - _metric_amount(
        real_estate["mortgage_balance"]
    ) == _metric_amount(real_estate["property_equity"])
    assert property_data["liquidity_rule"] == (
        "real_estate_and_mortgage_are_excluded_from_liquid_capital"
    )

    iis = bundle["iis_and_tax"]["iis_accounts"][0]
    received = _amount(iis["tax_benefits"]["received"])
    assert _metric_amount(iis["portfolio_result_without_tax_benefit"]) + received == (
        _metric_amount(iis["portfolio_result_with_received_tax_benefit"])
    )


def test_forecast_and_upcoming_flow_counting_cannot_double_count(
    bundle: dict[str, object],
) -> None:
    forecast = bundle["passive_income"]["forecast"]
    breakdown_total = sum(
        (_metric_amount(value) for value in forecast["breakdown"].values()), Decimal(0)
    )
    assert breakdown_total == _metric_amount(forecast["annual_total"])
    expected_monthly = (breakdown_total / Decimal(12)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    assert expected_monthly == _metric_amount(forecast["monthly_total"])

    calendar = bundle["upcoming_cash_flows"]
    included = [item for item in calendar["items"] if item["included_in_calendar_total"]]
    principal = [item for item in included if item["flow_type"] == "redemption"]
    passive = [item for item in included if item["flow_type"] != "redemption"]
    assert sum((_amount(item["amount"]) for item in principal), Decimal(0)) == (
        _metric_amount(calendar["principal_total"])
    )
    assert sum((_amount(item["amount"]) for item in passive), Decimal(0)) == (
        _metric_amount(calendar["non_principal_calendar_amount_total"])
    )
    assert _metric_amount(calendar["principal_total"]) + _metric_amount(
        calendar["non_principal_calendar_amount_total"]
    ) == _metric_amount(calendar["calendar_total"])

    for item in calendar["items"]:
        if item["flow_type"] == "redemption":
            assert item["included_in_passive_income_forecast"] is False
            assert item["forecast_treatment"] == "excluded_principal"
            assert item["amount_semantics"] == "principal"
            assert item["personal_tax_status"] == "not_applicable"
        elif item["flow_type"] == "dividend":
            assert item["included_in_passive_income_forecast"] is False
            assert item["forecast_treatment"] == "represented_by_historical_component"
        else:
            assert item["included_in_passive_income_forecast"] is True
            assert item["forecast_treatment"] == "included"

        if item["provenance"]["source_kind"] == "provider" and item["flow_type"] != "redemption":
            assert item["amount_semantics"] == "provider_announced_amount_tax_unknown"
            assert item["personal_tax_status"] == "unknown"
            assert item["is_approximate"] is True
            assert "personal_tax_unknown" in item["reason_codes"]

    assert len({item["event_ref"] for item in calendar["items"]}) == len(calendar["items"])
    assert any(
        item["duplicate_resolution"] == "unresolved_manual_only" for item in calendar["items"]
    )


def test_fixture_contains_no_binary_floats_or_forbidden_technical_keys(
    bundle: dict[str, object],
) -> None:
    assert not any(isinstance(value, float) for value in _walk(bundle))

    keys = {key for value in _walk(bundle) if isinstance(value, dict) for key in value}
    assert keys.isdisjoint(FORBIDDEN_KEYS)

    warning_codes = [item["code"] for item in bundle["warnings"]]
    assert warning_codes == sorted(warning_codes)


def test_export_local_references_are_complete_and_stably_sorted(
    bundle: dict[str, object],
) -> None:
    portfolio = bundle["current_portfolio"]
    account_refs = [item["ref"] for item in portfolio["accounts"]]
    instrument_refs = [item["ref"] for item in portfolio["instruments"]]
    assert account_refs == sorted(account_refs)
    assert instrument_refs == sorted(instrument_refs)
    assert len(account_refs) == len(set(account_refs))
    assert len(instrument_refs) == len(set(instrument_refs))

    for position in portfolio["positions"]:
        assert position["account_ref"] in account_refs
        assert position["instrument_ref"] in instrument_refs
        quantity = Decimal(position["quantity"])
        price = _metric_amount(position["market_price_per_unit"])
        accrued = _metric_amount(position["accrued_interest"])
        assert quantity * price + accrued == _metric_amount(position["market_value"])
        assert _metric_amount(position["market_value"]) - _metric_amount(
            position["cost_basis"]
        ) == _metric_amount(position["unrealized_result"])
    for deposit in portfolio["deposits"]:
        assert deposit["account_ref"] in account_refs
    for cash in portfolio["cash_balances"]:
        assert cash["account_ref"] in account_refs
    for flow in bundle["upcoming_cash_flows"]["items"]:
        assert flow["account_ref"] in account_refs
        assert flow["instrument_ref"] is None or flow["instrument_ref"] in instrument_refs
