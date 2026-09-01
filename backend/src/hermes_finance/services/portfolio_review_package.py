"""Read-only assembler for the R08 portfolio-review package.

The package is an adapter around accepted Hermes read models.  It deliberately
does not calculate financial values, refresh providers, persist an export, or
carry open-ended diagnostic/provider data across the privacy boundary.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from sqlalchemy.orm import Session

from hermes_finance import __version__
from hermes_finance.domain.goal_achievement import GOAL_ACHIEVEMENT_METHOD_VERSION
from hermes_finance.domain.risk_allocation import RiskSupportStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.accounts import list_accounts
from hermes_finance.services.ai_analysis_bundle import _slug as _bundle_slug
from hermes_finance.services.ai_analysis_bundle import assemble_ai_analysis_bundle
from hermes_finance.services.deterministic_insights import (
    DETERMINISTIC_INSIGHTS_CONTRACT_VERSION,
    DETERMINISTIC_INSIGHTS_RULESET_VERSION,
    build_deterministic_insights,
)
from hermes_finance.services.freshness_provenance import (
    FreshnessSeverity,
    FreshnessStatus,
    build_freshness_provenance_summary,
)
from hermes_finance.services.instruments import list_instruments
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.reporting_months import list_reporting_months
from hermes_finance.services.risk_allocation import (
    DEFAULT_TOP_N,
    risk_allocation_for_month,
)

SCHEMA_NAME = "hermes.finance.portfolio_review_package"
SCHEMA_VERSION = "1.0.0"
SCHEMA_URI = "https://hermes-finance.local/schema/portfolio-review-package/1.0.0/schema.json"
ORDERING_CONTRACT = "sections_and_arrays_are_sorted_as_defined_by_contract"
FRESHNESS_PROVENANCE_VERSION = "r07-07-v1"
RISK_ALLOCATION_VERSION = "r07-06a-v1"

CORE_SECTIONS = (
    "capital",
    "positions",
    "dynamics",
    "passive_income",
    "future_cash_flows",
    "freshness",
)
FULL_ONLY_SECTIONS = ("allocation", "context", "deterministic_insights")
ALL_SECTIONS = (*CORE_SECTIONS, *FULL_ONLY_SECTIONS)

Profile = Literal["concise", "full"]

_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_REF_PATTERN = re.compile(r"^acct-[a-z0-9-]+$")
_INSTRUMENT_REF_PATTERN = re.compile(r"^inst-[a-z0-9-]+$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_RATIO_PATTERN = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]{1,4})?$")
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?:[a-z]:\\|file://|api[_ -]?token|password|secret|credential|raw[_ -]?payload|stack trace)",
    re.IGNORECASE,
)
_MONEY_SOURCES = {
    "backend_derived",
    "persisted_configuration",
    "persisted_snapshot",
    "persisted_actual",
    "persisted_expected",
    "merged_payout_calendar",
}
_PROVIDERS = {None, "t_invest", "alfa_pro", "alfa_statement"}
_PROVENANCE_KINDS = {"manual", "provider", "statement", "migration", "backend_derived"}
_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}
_FRESHNESS_DEGRADED = {
    FreshnessStatus.STALE,
    FreshnessStatus.MIXED,
    FreshnessStatus.UNAVAILABLE,
    FreshnessStatus.UNKNOWN,
}
_WARNING_MESSAGES = {
    "authoritative_market_value_change_unavailable": (
        "No accepted aggregate market-value-change read model exists; liquid-capital change is not substituted."
    ),
    "cash_flow_adjusted_return_unavailable": (
        "Cash-flow-adjusted investment return is unavailable and is not inferred from capital changes."
    ),
    "incomplete_12_month_window": (
        "Fewer than 12 eligible closed months are available for the rolling actual average."
    ),
    "deposit_projection_approximate": (
        "Deposit forecast uses persisted monthly estimates; maturity and rate changes are not modelled."
    ),
    "reporting_history_gap": (
        "One or more calendar months between the first and last reporting period have no reporting month."
    ),
    "quote_stale": (
        "At least one persisted valuation is outside the accepted quote freshness window."
    ),
    "alfa_pro_observation_not_persisted": (
        "Alfa PRO observation time is not persisted, so freshness cannot be classified."
    ),
    "personal_tax_unknown": (
        "At least one expected income amount does not include a known personal-tax treatment."
    ),
    "salary_tax_history_incomplete": (
        "Salary-tax history is incomplete; current tax thresholds are not evaluated."
    ),
    "unresolved_provider_mapping": (
        "A provider/manual duplicate remains in the existing safe manual-only calendar state."
    ),
}
_INFO_WARNINGS = {
    "authoritative_market_value_change_unavailable",
    "cash_flow_adjusted_return_unavailable",
    "deposit_projection_approximate",
    "alfa_pro_observation_not_persisted",
}


class PortfolioReviewPackageValidationError(RuntimeError):
    """Generated portfolio-review package failed the declared schema."""


def _schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "portfolio_review_package.schema.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "portfolio_review_package.schema.json was not found next to the repository"
    )


def _schema() -> dict[str, object]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def validate_portfolio_review_package(package: dict[str, object]) -> None:
    """Validate an assembled package before returning it to a caller."""
    try:
        Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(package)
    except ValidationError as error:
        raise PortfolioReviewPackageValidationError(
            "generated portfolio-review package failed schema validation"
        ) from error


def canonical_json(package: dict[str, object]) -> str:
    return json.dumps(package, ensure_ascii=False, indent=2) + "\n"


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PortfolioReviewPackageValidationError(f"authoritative {label} is not an object")
    return dict(value)


def _list(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise PortfolioReviewPackageValidationError(f"authoritative {label} is not an array")
    return value


def _reason_codes(value: object) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return sorted(
        {
            item
            for item in value
            if isinstance(item, str) and _CODE_PATTERN.fullmatch(item) is not None
        }
    )


def _text(value: object, *, fallback: str, limit: int = 500) -> str:
    if isinstance(value, str):
        result = value.strip()
        if result and _SENSITIVE_TEXT_PATTERN.search(result) is None:
            return result[:limit]
    return fallback[:limit]


def _period(value: object) -> dict[str, int]:
    source = _mapping(value, label="period")
    year = source.get("year")
    month = source.get("month")
    if (
        isinstance(year, int)
        and not isinstance(year, bool)
        and isinstance(month, int)
        and not isinstance(month, bool)
    ):
        return {"year": year, "month": month}
    raise PortfolioReviewPackageValidationError("authoritative period is incomplete")


def _safe_source(value: object, *, fallback: str) -> str:
    return value if isinstance(value, str) and value in _MONEY_SOURCES else fallback


def _money(value: object) -> dict[str, str]:
    if isinstance(value, RubleAmount):
        return {"amount": value.to_api(), "currency": "RUB"}
    source = _mapping(value, label="money")
    amount = source.get("amount")
    currency = source.get("currency")
    if not isinstance(amount, str) or currency != "RUB":
        raise PortfolioReviewPackageValidationError("authoritative money value is not RUB")
    return {"amount": amount, "currency": "RUB"}


def _unavailable_money_metric(*, source: str, reason_codes: object) -> dict[str, object]:
    return {
        "value": None,
        "availability": "unavailable",
        "precision": "unknown",
        "source": _safe_source(source, fallback="backend_derived"),
        "reason_codes": _reason_codes(reason_codes),
    }


def _money_metric(
    value: object,
    *,
    fallback_source: str = "backend_derived",
    fallback_reason: str = "authoritative_value_unavailable",
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return _unavailable_money_metric(
            source=fallback_source,
            reason_codes=[fallback_reason],
        )
    source = _safe_source(value.get("source"), fallback=fallback_source)
    reasons = _reason_codes(value.get("reason_codes"))
    availability = value.get("availability")
    if availability == "unavailable":
        return _unavailable_money_metric(source=source, reason_codes=reasons)
    if availability != "available":
        return _unavailable_money_metric(
            source=source,
            reason_codes=[*reasons, fallback_reason],
        )
    try:
        money = _money(value.get("value"))
    except PortfolioReviewPackageValidationError:
        return _unavailable_money_metric(
            source=source,
            reason_codes=[*reasons, fallback_reason],
        )
    precision = value.get("precision")
    if precision not in {"exact", "approximate"}:
        return _unavailable_money_metric(
            source=source,
            reason_codes=[*reasons, fallback_reason],
        )
    return {
        "value": money,
        "availability": "available",
        "precision": precision,
        "source": source,
        "reason_codes": reasons,
    }


def _unavailable_ratio(*, reason_codes: object) -> dict[str, object]:
    return {
        "value_pct": None,
        "availability": "unavailable",
        "precision": "unknown",
        "source": "backend_derived",
        "reason_codes": _reason_codes(reason_codes),
    }


def _ratio(
    value: object, *, precision: str = "exact", reason_codes: object = ()
) -> dict[str, object]:
    if value is None:
        return _unavailable_ratio(reason_codes=reason_codes)
    if isinstance(value, Decimal):
        text = format(value, "f")
    elif isinstance(value, str):
        text = value
    else:
        return _unavailable_ratio(reason_codes=[*_reason_codes(reason_codes), "ratio_unavailable"])
    if not text or _RATIO_PATTERN.fullmatch(text) is None:
        return _unavailable_ratio(reason_codes=[*_reason_codes(reason_codes), "ratio_unavailable"])
    return {
        "value_pct": text,
        "availability": "available",
        "precision": precision if precision in {"exact", "approximate"} else "exact",
        "source": "backend_derived",
        "reason_codes": _reason_codes(reason_codes),
    }


def _ratio_metric(
    value: object, *, fallback_reason: str = "authoritative_ratio_unavailable"
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return _unavailable_ratio(reason_codes=[fallback_reason])
    reasons = _reason_codes(value.get("reason_codes"))
    if value.get("availability") == "unavailable":
        return _unavailable_ratio(reason_codes=reasons)
    if value.get("availability") != "available":
        return _unavailable_ratio(reason_codes=[*reasons, fallback_reason])
    precision = value.get("precision")
    if precision not in {"exact", "approximate"}:
        return _unavailable_ratio(reason_codes=[*reasons, fallback_reason])
    return _ratio(
        value.get("value_pct"),
        precision=precision,
        reason_codes=reasons,
    )


def _date_metric(value: object, *, fallback_reason: str = "date_unavailable") -> dict[str, object]:
    if isinstance(value, Mapping):
        reasons = _reason_codes(value.get("reason_codes"))
        if value.get("availability") == "unavailable":
            return {"value": None, "availability": "unavailable", "reason_codes": reasons}
        candidate = value.get("value")
        if (
            value.get("availability") == "available"
            and isinstance(candidate, str)
            and _DATE_PATTERN.fullmatch(candidate) is not None
        ):
            return {"value": candidate, "availability": "available", "reason_codes": reasons}
        return {
            "value": None,
            "availability": "unavailable",
            "reason_codes": [*reasons, fallback_reason],
        }
    if isinstance(value, str) and _DATE_PATTERN.fullmatch(value):
        return {"value": value, "availability": "available", "reason_codes": []}
    return {"value": None, "availability": "unavailable", "reason_codes": [fallback_reason]}


def _provenance(value: object) -> dict[str, object]:
    source = _mapping(value, label="provenance") if isinstance(value, Mapping) else {}
    source_kind = source.get("source_kind")
    if source_kind not in _PROVENANCE_KINDS:
        source_kind = "manual"
    provider = source.get("provider") if source.get("provider") in _PROVIDERS else None
    observed_at = source.get("observed_at")
    if not isinstance(observed_at, str) or not _DATE_TIME_PATTERN.match(observed_at):
        observed_at = None
    return {
        "source_kind": source_kind,
        "provider": provider,
        "observed_at": observed_at,
    }


def _coverage(value: object) -> dict[str, object]:
    source = _mapping(value, label="coverage") if isinstance(value, Mapping) else {}
    status = source.get("status")
    if status not in {"complete", "partial", "unavailable"}:
        status = "unavailable"
    return {"status": status, "reason_codes": _reason_codes(source.get("reason_codes"))}


def _selected_month(months: list[object]) -> tuple[object, str]:
    if not months:
        raise LookupError("no reporting months available")
    ordered = sorted(
        months,
        key=lambda item: (getattr(item, "year"), getattr(item, "month"), getattr(item, "id")),
    )
    closed = [item for item in ordered if getattr(item, "status") == "closed"]
    if closed:
        return max(closed, key=lambda item: (item.year, item.month, item.id)), "latest_closed"
    return max(ordered, key=lambda item: (item.year, item.month, item.id)), "latest_available"


def _export_ref_maps(session: Session) -> tuple[dict[int, str], dict[int, str]]:
    """Recreate the source bundle's local ref assignment without exporting IDs."""
    accounts = sorted(
        list_accounts(session), key=lambda item: (item.name, item.account_type, item.id)
    )
    instruments = sorted(
        list_instruments(session), key=lambda item: (item.name, item.instrument_type, item.id)
    )
    used: set[str] = set()
    account_refs = {row.id: _bundle_slug("acct", row.name, used) for row in accounts}
    instrument_refs = {row.id: _bundle_slug("inst", row.name, used) for row in instruments}
    return account_refs, instrument_refs


def _dynamics_point(value: object) -> dict[str, object]:
    source = _mapping(value, label="reporting history point")
    kpis = _mapping(source.get("kpis"), label="reporting history KPIs")
    return {
        "period": _period(source.get("period")),
        "status": source.get("status"),
        "snapshot_date": source.get("snapshot_date"),
        "coverage": _coverage(source.get("coverage")),
        "liquid_assets_total": _money_metric(kpis.get("liquid_assets_total")),
        "included_debts": _money_metric(kpis.get("included_debts")),
        "liquid_capital_net": _money_metric(kpis.get("liquid_capital_net")),
        "passive_income_actual": _money_metric(kpis.get("passive_income_actual")),
        "active_income_net": _money_metric(kpis.get("active_income_net")),
        "mandatory_expenses": _money_metric(kpis.get("mandatory_expenses")),
        "saving_allocations": _money_metric(kpis.get("saving_allocations")),
        "monthly_cash_balance": _money_metric(kpis.get("monthly_cash_balance")),
        "property_equity": _money_metric(kpis.get("property_equity")),
        "market_value_change": _money_metric(
            kpis.get("market_value_change"),
            fallback_reason="authoritative_market_value_change_unavailable",
        ),
        "investment_return": _ratio_metric(
            kpis.get("investment_return"),
            fallback_reason="cash_flow_adjusted_return_unavailable",
        ),
        "warning_codes": _reason_codes(source.get("warning_codes")),
    }


def _position_data(current_portfolio: Mapping[str, object]) -> dict[str, object]:
    accounts = []
    for value in _list(current_portfolio.get("accounts"), label="portfolio accounts"):
        source = _mapping(value, label="account")
        accounts.append(
            {
                "ref": source.get("ref"),
                "name": source.get("name"),
                "account_type": source.get("account_type"),
                "status": source.get("status"),
                "include_in_capital": source.get("include_in_capital"),
                "include_in_returns": source.get("include_in_returns"),
            }
        )
    accounts.sort(key=lambda item: str(item["ref"]))

    instruments = []
    for value in _list(current_portfolio.get("instruments"), label="portfolio instruments"):
        source = _mapping(value, label="instrument")
        instruments.append(
            {
                "ref": source.get("ref"),
                "name": source.get("name"),
                "instrument_type": source.get("instrument_type"),
                "isin": source.get("isin"),
                "ticker": source.get("ticker"),
                "currency": source.get("currency"),
            }
        )
    instruments.sort(key=lambda item: str(item["ref"]))

    positions = []
    for value in _list(current_portfolio.get("positions"), label="portfolio positions"):
        source = _mapping(value, label="position")
        positions.append(
            {
                "account_ref": source.get("account_ref"),
                "instrument_ref": source.get("instrument_ref"),
                "quantity": source.get("quantity"),
                "market_price_per_unit": _money_metric(source.get("market_price_per_unit")),
                "market_value": _money_metric(source.get("market_value")),
                "cost_basis": _money_metric(source.get("cost_basis")),
                "unrealized_result": _money_metric(source.get("unrealized_result")),
                "accrued_interest": _money_metric(source.get("accrued_interest")),
                "price_date": _date_metric(source.get("price_date")),
                "valuation_provenance": _provenance(source.get("valuation_provenance")),
            }
        )
    positions.sort(key=lambda item: (str(item["account_ref"]), str(item["instrument_ref"])))

    deposits = []
    for value in _list(current_portfolio.get("deposits"), label="portfolio deposits"):
        source = _mapping(value, label="deposit")
        deposits.append(
            {
                "account_ref": source.get("account_ref"),
                "name": source.get("name"),
                "deposit_type": source.get("deposit_type"),
                "balance": _money_metric(source.get("balance")),
                "annual_rate_pct": source.get("annual_rate_pct"),
                "expected_monthly_interest": _money_metric(source.get("expected_monthly_interest")),
                "actual_interest_received": _money_metric(source.get("actual_interest_received")),
                "provenance": _provenance(source.get("provenance")),
            }
        )
    deposits.sort(key=lambda item: (str(item["account_ref"]), str(item["name"])))

    cash_balances = []
    for value in _list(current_portfolio.get("cash_balances"), label="portfolio cash"):
        source = _mapping(value, label="cash balance")
        cash_balances.append(
            {
                "account_ref": source.get("account_ref"),
                "name": source.get("name"),
                "amount": _money_metric(source.get("amount")),
                "include_in_capital": source.get("include_in_capital"),
                "provenance": _provenance(source.get("provenance")),
            }
        )
    cash_balances.sort(key=lambda item: (str(item["account_ref"]), str(item["name"])))

    return {
        "reporting_period": _period(current_portfolio.get("reporting_period")),
        "snapshot_date": current_portfolio.get("snapshot_date"),
        "accounts": accounts,
        "instruments": instruments,
        "items": positions,
        "deposits": deposits,
        "cash_balances": cash_balances,
    }


def _capital_data(current_point: Mapping[str, object]) -> dict[str, object]:
    return {
        "reporting_period": current_point["period"],
        "snapshot_date": current_point["snapshot_date"],
        "liquid_assets_total": current_point["liquid_assets_total"],
        "included_debts": current_point["included_debts"],
        "liquid_capital_net": current_point["liquid_capital_net"],
        "property_equity": current_point["property_equity"],
        "total_net_worth": _unavailable_money_metric(
            source="backend_derived",
            reason_codes=["no_authoritative_aggregate"],
        ),
    }


def _dynamics_data(history: list[dict[str, object]], missing: object) -> dict[str, object]:
    ordered = sorted(
        history,
        key=lambda item: (
            item["period"]["year"],
            item["period"]["month"],
        ),
    )
    return {"history": ordered, "missing_calendar_periods": [_period(item) for item in missing]}


def _passive_data(passive_source: Mapping[str, object]) -> dict[str, object]:
    rolling_source = _mapping(passive_source.get("rolling_actual_average"), label="rolling average")
    forecast_source = _mapping(passive_source.get("forecast"), label="passive forecast")
    breakdown_source = _mapping(forecast_source.get("breakdown"), label="forecast breakdown")
    rolling = {
        "value": _money_metric(rolling_source.get("value")),
        "eligible_month_count": rolling_source.get("eligible_month_count"),
        "target_window_months": rolling_source.get("target_window_months"),
        "is_complete_window": rolling_source.get("is_complete_window"),
        "history_start_period": _period(rolling_source.get("history_start_period")),
        "periods_used": [
            _period(item)
            for item in _list(rolling_source.get("periods_used"), label="rolling periods")
        ],
        "source": rolling_source.get("source"),
    }
    forecast = {
        "forecast_version": forecast_source.get("forecast_version"),
        "as_of_date": forecast_source.get("as_of_date"),
        "annual_total": _money_metric(forecast_source.get("annual_total")),
        "monthly_total": _money_metric(forecast_source.get("monthly_total")),
        "breakdown": {
            "expected_deposit_interest": _money_metric(
                breakdown_source.get("expected_deposit_interest")
            ),
            "expected_coupon_component": _money_metric(
                breakdown_source.get("expected_coupon_component")
            ),
            "expected_dividend_component": _money_metric(
                breakdown_source.get("expected_dividend_component")
            ),
            "other_expected_capital_income": _money_metric(
                breakdown_source.get("other_expected_capital_income")
            ),
        },
        "dividend_component_source": forecast_source.get("dividend_component_source"),
        "deposit_projection_method": forecast_source.get("deposit_projection_method"),
        "warning_codes": _reason_codes(forecast_source.get("warning_codes")),
    }
    return {
        "actual_history_metric_path": "sections.dynamics.data.history[].passive_income_actual",
        "rolling_actual_average": rolling,
        "forecast": forecast,
    }


def _flow_item(value: object) -> dict[str, object]:
    source = _mapping(value, label="cash-flow item")
    provenance = _provenance(source.get("provenance"))
    resolution = source.get("duplicate_resolution")
    if resolution == "keep_both":
        resolution = "count_provider" if provenance["source_kind"] == "provider" else "count_manual"
    if resolution not in {"none", "count_provider", "count_manual", "unresolved_manual_only"}:
        resolution = "none"
    return {
        "event_ref": source.get("event_ref"),
        "expected_date": source.get("expected_date"),
        "flow_type": source.get("flow_type"),
        "account_ref": source.get("account_ref"),
        "instrument_ref": source.get("instrument_ref"),
        "amount": _money(source.get("amount")),
        "amount_semantics": source.get("amount_semantics"),
        "personal_tax_status": source.get("personal_tax_status"),
        "is_approximate": source.get("is_approximate"),
        "reason_codes": _reason_codes(source.get("reason_codes")),
        "provenance": provenance,
        "duplicate_resolution": resolution,
        "included_in_calendar_total": True,
        "included_in_passive_income_forecast": source.get("included_in_passive_income_forecast"),
        "forecast_treatment": source.get("forecast_treatment"),
    }


def _future_cash_flows_data(source: Mapping[str, object]) -> dict[str, object]:
    items = [_flow_item(item) for item in _list(source.get("items"), label="cash-flow items")]
    items.sort(key=lambda item: (str(item["expected_date"]), str(item["event_ref"])))
    return {
        "window_start": source.get("window_start"),
        "window_end_exclusive": source.get("window_end_exclusive"),
        "forecast_version": source.get("forecast_version"),
        "non_principal_calendar_amount_total": _money_metric(
            source.get("non_principal_calendar_amount_total"),
            fallback_source="merged_payout_calendar",
        ),
        "principal_total": _money_metric(
            source.get("principal_total"),
            fallback_source="merged_payout_calendar",
        ),
        "calendar_total": _money_metric(
            source.get("calendar_total"),
            fallback_source="merged_payout_calendar",
        ),
        "items": items,
        "warning_codes": _reason_codes(source.get("warning_codes")),
    }


def _freshness_data(summary) -> tuple[dict[str, object], list[str]]:
    families = []
    section_reasons: set[str] = set()
    for family in sorted(summary.families, key=lambda item: item.family_id.value):
        family_reasons = sorted({reason.code.value for reason in family.reasons})
        coverage = family.coverage
        families.append(
            {
                "family_id": family.family_id.value,
                "status": family.status.value,
                "providers": sorted(
                    provider for provider in family.providers if provider in _PROVIDERS
                ),
                "coverage": {
                    "row_count": coverage.row_count,
                    "current_count": coverage.current_count,
                    "stale_count": coverage.stale_count,
                    "unavailable_count": coverage.unavailable_count,
                    "unknown_count": coverage.unknown_count,
                    "missing_count": coverage.missing_count,
                    "manual_count": coverage.manual_count,
                    "provider_count": coverage.provider_count,
                },
                "reason_codes": family_reasons,
            }
        )
        warning_reasons = {
            reason.code.value
            for reason in family.reasons
            if reason.severity is FreshnessSeverity.WARNING
        }
        if family.status in {
            FreshnessStatus.STALE,
            FreshnessStatus.MIXED,
            FreshnessStatus.UNAVAILABLE,
        }:
            section_reasons.update(warning_reasons)
        elif family.status is FreshnessStatus.UNKNOWN:
            meaningful = set(family_reasons) - {"source_timestamp_unavailable"}
            section_reasons.update(meaningful or {"freshness_unknown"})

    for reason in summary.reasons:
        if reason.severity is FreshnessSeverity.WARNING:
            section_reasons.add(reason.code.value)
    return (
        {
            "evaluated_on": summary.evaluated_on.isoformat(),
            "quote_valuation_target_date": summary.quote_valuation_target_date.isoformat(),
            "families": families,
            "reason_codes": sorted(section_reasons),
        },
        sorted(section_reasons),
    )


def _support_state(support) -> dict[str, object]:
    status = getattr(getattr(support, "status", None), "value", None)
    if status == RiskSupportStatus.SUPPORTED.value:
        state = "complete"
    elif status == RiskSupportStatus.UNAVAILABLE.value:
        state = "unavailable"
    else:
        state = "partial"
    return {"status": state, "reason_codes": _reason_codes(getattr(support, "reason_codes", ()))}


def _key_slug(value: object, *, fallback: str, used: set[str], max_length: int) -> str:
    raw = value if isinstance(value, str) else ""
    candidate = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    if not candidate or not candidate[0].isalpha():
        candidate = re.sub(r"[^a-z0-9]+", "_", fallback.lower()).strip("_") or "item"
    if not candidate[0].isalpha():
        candidate = f"item_{candidate}"
    candidate = candidate[:max_length].rstrip("_") or "item"
    base = candidate
    index = 2
    while candidate in used:
        suffix = f"_{index}"
        candidate = f"{base[: max_length - len(suffix)]}{suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _safe_risk_label(item, account_names: dict[int, str], instrument_names: dict[int, str]) -> str:
    instrument_id = getattr(item, "instrument_id", None)
    account_id = getattr(item, "account_id", None)
    if instrument_id in instrument_names:
        return instrument_names[instrument_id][:128]
    if account_id in account_names:
        return account_names[account_id][:128]
    raw = getattr(item, "label", None)
    if isinstance(raw, str) and not re.search(
        r"\b(?:account|instrument|position)\s*:?\s*\d+\b", raw, re.I
    ):
        return raw.strip()[:128] or "Unknown item"
    return "Unknown item"


def _risk_allocation_data(
    result,
    position_data: Mapping[str, object],
    *,
    account_ref_by_id: Mapping[int, str],
    instrument_ref_by_id: Mapping[int, str],
    reporting_period: Mapping[str, int],
) -> dict[str, object]:
    # The source DTO carries numeric IDs while the package carries only the
    # export-local refs.  Name-based maps are used only as a display fallback;
    # the authoritative IDs never cross the package boundary.
    account_name_by_id = {
        item.account_id: item.label
        for item in result.allocation_by_account.items
        if item.account_id is not None and item.label
    }
    account_name_by_id.update(
        {
            item.account_id: item.account_name
            for metric in (
                result.top_positions,
                result.payout_concentration,
                result.redemption_concentration,
            )
            for item in metric.items
            if item.account_id is not None and item.account_name
        }
    )
    instrument_name_by_id = {
        item.instrument_id: item.instrument_name
        for metric in (
            result.top_positions,
            result.payout_concentration,
            result.redemption_concentration,
        )
        for item in metric.items
        if item.instrument_id is not None and item.instrument_name
    }
    cash_refs = sorted(
        {
            str(item["account_ref"])
            for item in _list(position_data.get("cash_balances"), label="package cash")
            if isinstance(item, Mapping) and isinstance(item.get("account_ref"), str)
        }
    )

    def allocation_item(item, used: set[str], *, allow_raw_key: bool) -> dict[str, object]:
        label = _safe_risk_label(item, account_name_by_id, instrument_name_by_id)
        raw_key = getattr(item, "key", None) if allow_raw_key else label
        if allow_raw_key and (
            not isinstance(raw_key, str)
            or _KEY_PATTERN.fullmatch(raw_key) is None
            or any(character.isdigit() for character in raw_key)
        ):
            raw_key = label
        account_ref = account_ref_by_id.get(getattr(item, "account_id", None))
        if (
            account_ref is None
            and getattr(item, "key", None) == "unassigned_cash"
            and len(cash_refs) == 1
        ):
            account_ref = cash_refs[0]
        instrument_ref = instrument_ref_by_id.get(getattr(item, "instrument_id", None))
        return {
            "key": _key_slug(raw_key, fallback=label, used=used, max_length=64),
            "label": label or "Unknown item",
            "amount": _money(getattr(item, "amount")),
            "share_pct": _ratio(
                getattr(item, "share_pct"),
                reason_codes=["zero_denominator"] if getattr(item, "share_pct") is None else (),
            ),
            "account_ref": account_ref,
            "instrument_ref": instrument_ref,
            "instrument_type": getattr(item, "instrument_type", None),
        }

    def allocation_metric(metric) -> dict[str, object]:
        used: set[str] = set()
        items = [
            allocation_item(item, used, allow_raw_key=metric is result.allocation_by_asset_class)
            for item in metric.items
        ]
        items.sort(
            key=lambda item: (-int(str(item["amount"]["amount"]).replace(".", "")), item["key"])
        )
        excluded = sorted(
            {
                reason
                for issue in metric.excluded
                for reason in getattr(issue.support, "reason_codes", ())
                if isinstance(reason, str) and _CODE_PATTERN.fullmatch(reason)
            }
        )
        return {
            "support": _support_state(metric.support),
            "denominator": _money(metric.denominator),
            "covered_amount": _money(metric.covered_amount),
            "unallocated_amount": _money(metric.unallocated_amount),
            "coverage_pct": _ratio(
                metric.coverage_pct,
                reason_codes=["zero_denominator"] if metric.coverage_pct is None else (),
            ),
            "items": items,
            "excluded_reason_codes": excluded,
        }

    def concentration_metric(metric) -> dict[str, object]:
        used: set[str] = set()
        items = []
        for item in metric.items:
            label = _safe_risk_label(item, account_name_by_id, instrument_name_by_id)
            items.append(
                {
                    "key": _key_slug(label, fallback="item", used=used, max_length=96),
                    "label": label,
                    "amount": _money(item.amount),
                    "share_pct": _ratio(
                        item.share_pct,
                        precision="approximate" if metric.is_approximate else "exact",
                        reason_codes=(["zero_denominator"] if item.share_pct is None else ()),
                    ),
                    "account_ref": account_ref_by_id.get(item.account_id),
                    "instrument_ref": instrument_ref_by_id.get(item.instrument_id),
                    "instrument_type": item.instrument_type,
                    "event_count": item.event_count,
                    "is_approximate": item.is_approximate,
                }
            )
        items.sort(
            key=lambda item: (-int(str(item["amount"]["amount"]).replace(".", "")), item["key"])
        )
        excluded = sorted(
            {
                reason
                for issue in metric.excluded
                for reason in getattr(issue.support, "reason_codes", ())
                if isinstance(reason, str) and _CODE_PATTERN.fullmatch(reason)
            }
        )
        return {
            "support": _support_state(metric.support),
            "denominator": _money(metric.denominator),
            "top_n": metric.top_n,
            "top_amount": _money(metric.top_amount),
            "top_share_pct": _ratio(
                metric.top_share_pct,
                precision="approximate" if metric.is_approximate else "exact",
                reason_codes=["zero_denominator"] if metric.top_share_pct is None else (),
            ),
            "items": items,
            "excluded_reason_codes": excluded,
            "is_approximate": metric.is_approximate,
        }

    return {
        "reporting_period": dict(reporting_period),
        "as_of_date": result.as_of_date.isoformat(),
        "allocation_by_asset_class": allocation_metric(result.allocation_by_asset_class),
        "allocation_by_account": allocation_metric(result.allocation_by_account),
        "top_positions": concentration_metric(result.top_positions),
        "payout_concentration": concentration_metric(result.payout_concentration),
        "redemption_concentration": concentration_metric(result.redemption_concentration),
    }


def _goal_source_path(value: object) -> str:
    if isinstance(value, str) and value == "passive_income.rolling_actual_average.value":
        return "sections.passive_income.data.rolling_actual_average.value"
    if isinstance(value, str) and value.startswith("reporting_history"):
        return "sections.dynamics.data.history[].liquid_capital_net"
    return "backend_authoritative_read_model"


def _context_data(source: Mapping[str, object]) -> tuple[dict[str, object], list[str]]:
    goals = []
    for value in _list(source.get("goals"), label="goals"):
        item = _mapping(value, label="goal")
        goals.append(
            {
                "ref": item.get("ref"),
                "name": item.get("name"),
                "goal_type": item.get("goal_type"),
                "is_primary": item.get("is_primary"),
                "target": _money_metric(item.get("target")),
                "current_value": _money_metric(item.get("current_value")),
                "gap": _money_metric(item.get("gap")),
                "progress": _ratio_metric(item.get("progress")),
                "projection_status": item.get("projection_status"),
                "estimated_achievement_date": item.get("estimated_achievement_date"),
                "method_version": item.get("method_version", GOAL_ACHIEVEMENT_METHOD_VERSION),
                "source_metric_path": _goal_source_path(item.get("source_metric_path")),
                "warning_codes": _reason_codes(item.get("warning_codes")),
            }
        )
    goals.sort(key=lambda item: str(item["ref"]))

    debts_source = _mapping(source.get("debts_and_real_estate"), label="debt/property context")
    debts = _mapping(debts_source.get("debts"), label="debt context")
    property_source = _mapping(debts_source.get("real_estate"), label="property context")
    debts_data = {
        "reporting_period": _period(debts_source.get("reporting_period")),
        "included_debts": _money_metric(debts.get("included_in_liquid_capital")),
        "excluded_debts": _money_metric(debts.get("excluded_from_liquid_capital")),
        "property": {
            "estimated_value": _money_metric(property_source.get("estimated_value")),
            "mortgage_balance": _money_metric(property_source.get("mortgage_balance")),
            "property_equity": _money_metric(property_source.get("property_equity")),
            "monthly_payment": _money_metric(property_source.get("monthly_payment")),
        },
        "mortgage_coverage": _ratio_metric(debts_source.get("mortgage_coverage")),
        "liquidity_rule": "real_estate_and_mortgage_are_excluded_from_liquid_capital",
    }

    iis_source = _mapping(source.get("iis_and_tax"), label="IIS/tax context")
    iis_accounts = []
    for value in _list(iis_source.get("iis_accounts"), label="IIS accounts"):
        item = _mapping(value, label="IIS account")
        benefits = _mapping(item.get("tax_benefits"), label="IIS tax benefits")
        contributions = []
        for contribution in _list(item.get("contributions_by_tax_year"), label="IIS contributions"):
            contribution_source = _mapping(contribution, label="IIS contribution")
            contributions.append(
                {
                    "tax_year": contribution_source.get("tax_year"),
                    "amount": _money(contribution_source.get("amount")),
                    "is_target_reached": contribution_source.get("is_target_reached"),
                }
            )
        contributions.sort(key=lambda entry: entry["tax_year"])
        iis_accounts.append(
            {
                "account_ref": item.get("account_ref"),
                "iis_type": item.get("iis_type"),
                "opened_at": item.get("opened_at"),
                "eligible_close_at": item.get("eligible_close_at"),
                "contributions_by_tax_year": contributions,
                "tax_benefits": {
                    key: _money(benefits.get(key))
                    for key in ("planned", "submitted", "received", "rejected")
                },
                "portfolio_result_without_tax_benefit": _money_metric(
                    item.get("portfolio_result_without_tax_benefit")
                ),
                "portfolio_result_with_received_tax_benefit": _money_metric(
                    item.get("portfolio_result_with_received_tax_benefit")
                ),
                "result_rule": item.get("result_rule"),
            }
        )
    iis_accounts.sort(key=lambda item: str(item["account_ref"]))

    salary = _mapping(iis_source.get("salary_tax_context"), label="salary-tax context")
    salary_data = {
        "tax_year": salary.get("tax_year"),
        "history_coverage": _coverage(salary.get("history_coverage")),
        "opening_context_available": salary.get("opening_context_available"),
        "taxable_gross_ytd": _money_metric(salary.get("taxable_gross_ytd")),
        "current_marginal_rate_pct": _ratio_metric(salary.get("current_marginal_rate_pct")),
        "warning_codes": _reason_codes(salary.get("warning_codes")),
    }
    reasons = set(salary_data["warning_codes"])
    if salary_data["history_coverage"]["status"] != "complete":
        reasons.update(salary_data["history_coverage"]["reason_codes"])
    return (
        {
            "goals": goals,
            "debts_and_real_estate": debts_data,
            "iis_and_tax": {"iis_accounts": iis_accounts, "salary_tax_context": salary_data},
        },
        sorted(reasons),
    )


_INSIGHT_SOURCES = {
    "close_readiness",
    "freshness_provenance",
    "merged_payout_calendar",
    "risk_allocation",
    "tax_iis_planner.salary_tax",
}
_INSIGHT_PROVENANCE_SOURCES = {
    "reporting_month",
    "close_readiness",
    "freshness_provenance",
    "merged_payout_calendar",
    "risk_allocation",
    "tax_iis_planner",
}


def _insight_source(value: object) -> str:
    source = value if isinstance(value, str) else ""
    if source in _INSIGHT_SOURCES:
        return source
    if source.startswith("risk_allocation"):
        return "risk_allocation"
    if source.startswith("freshness_provenance"):
        return "freshness_provenance"
    if source.startswith("merged_payout_calendar"):
        return "merged_payout_calendar"
    if source.startswith("tax_iis_planner") or source == "salary_tax_context":
        return "tax_iis_planner.salary_tax"
    return "close_readiness"


def _insight_provenance_source(value: object, fallback: str) -> str:
    source = value if isinstance(value, str) else ""
    if source in _INSIGHT_PROVENANCE_SOURCES:
        return source
    if source.startswith("risk_allocation"):
        return "risk_allocation"
    if source.startswith("freshness_provenance"):
        return "freshness_provenance"
    if source.startswith("merged_payout_calendar"):
        return "merged_payout_calendar"
    if source.startswith("tax_iis_planner") or source == "salary_tax_context":
        return "tax_iis_planner"
    return fallback if fallback in _INSIGHT_PROVENANCE_SOURCES else "reporting_month"


def _deterministic_data(result) -> dict[str, object]:
    items = []
    for index, item in enumerate(result.insights, start=1):
        source = _insight_source(item.source)
        item_type = item.type
        if item_type == "close_readiness":
            item_type = "close_guard"
        elif item_type in {"asset_class_coverage", "salary_tax"}:
            item_type = "coverage"
        if item_type not in {
            "close_guard",
            "freshness_warning",
            "payout_reconciliation",
            "concentration",
            "coverage",
        }:
            item_type = "coverage"
        code = (
            item.code
            if isinstance(item.code, str) and _CODE_PATTERN.fullmatch(item.code)
            else f"insight_{index}"
        )
        severity = getattr(item.severity, "value", item.severity)
        if severity not in {"info", "warning", "error"}:
            severity = "info"
        provenance = []
        seen_provenance: set[tuple[str, str | None]] = set()
        for provenance_item in item.provenance:
            provenance_source = _insight_provenance_source(
                provenance_item.source,
                "tax_iis_planner" if source == "tax_iis_planner.salary_tax" else source,
            )
            provider = provenance_item.provider if provenance_item.provider in _PROVIDERS else None
            key = (provenance_source, provider)
            if key in seen_provenance:
                continue
            seen_provenance.add(key)
            provenance.append({"source": provenance_source, "provider": provider})
        if not provenance:
            fallback_source = (
                "tax_iis_planner" if source == "tax_iis_planner.salary_tax" else source
            )
            provenance.append({"source": fallback_source, "provider": None})
        items.append(
            {
                "code": code,
                "type": item_type,
                "severity": severity,
                "message": _text(
                    item.message,
                    fallback="A deterministic insight is available from an accepted backend read model.",
                ),
                "source": source,
                "as_of": item.as_of.isoformat() if isinstance(item.as_of, date) else None,
                "provenance": provenance,
                "reason": _text(
                    item.reason,
                    fallback="The accepted backend read model returned this deterministic signal.",
                ),
            }
        )
    items.sort(
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            item["code"],
            item["source"],
            item["reason"],
        )
    )
    return {
        "contract_version": DETERMINISTIC_INSIGHTS_CONTRACT_VERSION,
        "ruleset_version": DETERMINISTIC_INSIGHTS_RULESET_VERSION,
        "forecast_version": result.forecast_version,
        "items": items,
    }


def _section(*, status: str, reasons: object, data: object) -> dict[str, object]:
    normalized_reasons = _reason_codes(reasons)
    if status in {"included", "partial"} and data is None:
        raise PortfolioReviewPackageValidationError("included package section has no data")
    if status in {"unavailable", "omitted"} and data is not None:
        raise PortfolioReviewPackageValidationError("unavailable package section has data")
    return {"status": status, "reason_codes": normalized_reasons, "data": data}


def _field_state(path: str, status: str, reasons: object, message: str) -> dict[str, object]:
    return {
        "path": path,
        "status": status,
        "reason_codes": _reason_codes(reasons),
        "message": message[:500],
    }


def _warning_scope(scope: object, code: str) -> str:
    if code == "quote_stale":
        return "sections.freshness"
    if isinstance(scope, str) and scope.startswith("sections."):
        return scope
    return {
        "reporting_history": "sections.dynamics",
        "coverage": "sections.dynamics",
        "passive_income": "sections.passive_income",
        "current_portfolio": "sections.positions",
        "upcoming_cash_flows": "sections.future_cash_flows",
        "iis_and_tax": "sections.context",
    }.get(str(scope), "sections")


def _warnings(
    base: Mapping[str, object], section_reasons: Mapping[str, list[str]]
) -> list[dict[str, str]]:
    collected: dict[tuple[str, str], dict[str, str]] = {}

    def add(code: str, severity: str, scope: str, message: object = None) -> None:
        if _CODE_PATTERN.fullmatch(code) is None:
            return
        if severity not in _SEVERITY_RANK:
            severity = "info"
        key = (code, scope)
        collected[key] = {
            "code": code,
            "severity": severity,
            "scope": scope,
            "message": _WARNING_MESSAGES.get(
                code,
                "An accepted backend read model reported a limited value.",
            )[:500],
        }

    for value in _list(base.get("warnings", []), label="bundle warnings"):
        warning = _mapping(value, label="bundle warning")
        code = warning.get("code")
        if code == "stale_quote":
            code = "quote_stale"
        if not isinstance(code, str):
            continue
        add(
            code,
            str(warning.get("severity", "info")),
            _warning_scope(warning.get("scope"), code),
            warning.get("message"),
        )

    for scope, reasons in section_reasons.items():
        for code in reasons:
            if code == "total_net_worth_unavailable":
                continue
            severity = "info" if code in _INFO_WARNINGS else "warning"
            add(code, severity, f"sections.{scope}")
    return sorted(
        collected.values(),
        key=lambda item: (_SEVERITY_RANK[item["severity"]], item["code"], item["scope"]),
    )


def assemble_portfolio_review_package(
    session: Session,
    *,
    profile: Profile = "full",
    generated_at: datetime | None = None,
    evaluated_on: date | None = None,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, object]:
    """Compose the v1 package from existing backend-authoritative read models."""
    if profile not in {"concise", "full"}:
        raise ValueError("profile must be concise or full")
    version = forecast_version.strip()
    if not version:
        raise ValueError("forecast_version must not be empty")

    base = assemble_ai_analysis_bundle(
        session,
        generated_at=generated_at,
        forecast_version=version,
    )
    base_metadata = _mapping(base.get("metadata"), label="AI bundle metadata")
    base_scope = _mapping(base.get("coverage"), label="AI bundle coverage")
    current_portfolio = _mapping(base.get("current_portfolio"), label="AI bundle current portfolio")
    months = list_reporting_months(session)
    current_month, selection_reason = _selected_month(months)
    history = [
        _dynamics_point(item)
        for item in _list(base.get("reporting_history"), label="AI bundle reporting history")
    ]
    current_period = _period(current_portfolio.get("reporting_period"))
    current_point = next(
        (item for item in history if item["period"] == current_period),
        None,
    )
    if current_point is None:
        raise PortfolioReviewPackageValidationError(
            "selected current period is absent from history"
        )

    generated_raw = base_metadata.get("generated_at")
    if not isinstance(generated_raw, str):
        raise PortfolioReviewPackageValidationError("AI bundle generation clock is unavailable")
    generated_clock = datetime.fromisoformat(generated_raw.replace("Z", "+00:00"))
    evaluation_day = evaluated_on or generated_clock.date()

    position_data = _position_data(current_portfolio)
    account_ref_by_id, instrument_ref_by_id = _export_ref_maps(session)
    freshness_summary = build_freshness_provenance_summary(
        session,
        current_month.id,
        today=evaluation_day,
        generated_at=generated_clock,
    )
    freshness_data, freshness_reasons = _freshness_data(freshness_summary)

    sections: dict[str, dict[str, object]] = {}
    section_reasons: dict[str, list[str]] = {}
    capital_reasons = ["total_net_worth_unavailable"]
    sections["capital"] = _section(
        status="partial",
        reasons=capital_reasons,
        data=_capital_data(current_point),
    )
    section_reasons["capital"] = capital_reasons

    position_coverage = _coverage(current_portfolio.get("coverage"))
    position_reasons = list(position_coverage["reason_codes"])
    position_status = "partial" if position_coverage["status"] != "complete" else "included"
    sections["positions"] = _section(
        status=position_status,
        reasons=position_reasons,
        data=position_data,
    )
    section_reasons["positions"] = position_reasons

    missing_periods = base_scope.get("missing_calendar_periods", [])
    dynamics_data = _dynamics_data(history, missing_periods)
    dynamics_reasons = set(
        dynamics_data["missing_calendar_periods"] and ["reporting_history_gap"] or []
    )
    for point in history:
        dynamics_reasons.update(point["coverage"]["reason_codes"])
    dynamics_reasons = sorted(dynamics_reasons)
    sections["dynamics"] = _section(
        status="partial" if dynamics_reasons else "included",
        reasons=dynamics_reasons,
        data=dynamics_data,
    )
    section_reasons["dynamics"] = dynamics_reasons

    passive_source = _mapping(base.get("passive_income"), label="AI bundle passive income")
    passive_data = _passive_data(passive_source)
    rolling_value = passive_data["rolling_actual_average"]["value"]
    passive_reasons = set(rolling_value["reason_codes"])
    passive_reasons.update(
        code
        for code in passive_data["forecast"]["warning_codes"]
        if code != "incomplete_dividend_history"
    )
    if (
        passive_data["rolling_actual_average"]["eligible_month_count"] == 0
        and rolling_value["availability"] == "unavailable"
    ):
        passive_reasons.add("no_eligible_closed_months")
    passive_reasons = sorted(passive_reasons)
    sections["passive_income"] = _section(
        status="partial" if passive_reasons else "included",
        reasons=passive_reasons,
        data=passive_data,
    )
    section_reasons["passive_income"] = passive_reasons

    future_source = _mapping(base.get("upcoming_cash_flows"), label="AI bundle cash flows")
    future_data = _future_cash_flows_data(future_source)
    future_reasons = set(future_data["warning_codes"])
    for item in future_data["items"]:
        if item["personal_tax_status"] == "unknown":
            future_reasons.add("personal_tax_unknown")
    future_reasons = sorted(future_reasons)
    sections["future_cash_flows"] = _section(
        status="partial" if future_reasons else "included",
        reasons=future_reasons,
        data=future_data,
    )
    section_reasons["future_cash_flows"] = future_reasons

    sections["freshness"] = _section(
        status="partial" if freshness_reasons else "included",
        reasons=freshness_reasons,
        data=freshness_data,
    )
    section_reasons["freshness"] = freshness_reasons

    field_states = [
        _field_state(
            "sections.capital.data.total_net_worth",
            "unavailable",
            ["no_authoritative_aggregate"],
            "No accepted backend aggregate exists for total net worth.",
        ),
        _field_state(
            "sections.dynamics.data.history[].investment_return",
            "unavailable",
            ["cash_flow_adjusted_return_unavailable"],
            "Cash-flow-adjusted investment return is not an accepted v1 read model.",
        ),
        _field_state(
            "sections.dynamics.data.history[].market_value_change",
            "unavailable",
            ["authoritative_market_value_change_unavailable"],
            "No accepted aggregate market-value-change read model exists.",
        ),
    ]

    if profile == "full":
        try:
            risk_result = risk_allocation_for_month(
                session,
                current_month.id,
                top_n=top_n,
                forecast_version=version,
            )
        except LookupError:
            risk_result = None
        if risk_result is None:
            allocation_reasons = ["risk_allocation_unavailable"]
            sections["allocation"] = _section(
                status="unavailable", reasons=allocation_reasons, data=None
            )
            field_states.append(
                _field_state(
                    "sections.allocation",
                    "unavailable",
                    allocation_reasons,
                    "The accepted risk-allocation read model was unavailable for this snapshot.",
                )
            )
            section_reasons["allocation"] = allocation_reasons
        else:
            sections["allocation"] = _section(
                status="included",
                reasons=[],
                data=_risk_allocation_data(
                    risk_result,
                    position_data,
                    account_ref_by_id=account_ref_by_id,
                    instrument_ref_by_id=instrument_ref_by_id,
                    reporting_period=current_period,
                ),
            )
            section_reasons["allocation"] = []

        context_source = _mapping(base, label="AI bundle")
        context_data, context_reasons = _context_data(context_source)
        sections["context"] = _section(
            status="partial" if context_reasons else "included",
            reasons=context_reasons,
            data=context_data,
        )
        section_reasons["context"] = context_reasons

        try:
            insights_result = build_deterministic_insights(
                session,
                current_month.id,
                evaluated_on=evaluation_day,
                forecast_version=version,
            )
        except LookupError:
            insights_result = None
        if insights_result is None:
            insight_reasons = ["deterministic_insights_unavailable"]
            sections["deterministic_insights"] = _section(
                status="unavailable", reasons=insight_reasons, data=None
            )
            field_states.append(
                _field_state(
                    "sections.deterministic_insights",
                    "unavailable",
                    insight_reasons,
                    "The accepted deterministic-insights read model was unavailable.",
                )
            )
            section_reasons["deterministic_insights"] = insight_reasons
        else:
            sections["deterministic_insights"] = _section(
                status="included",
                reasons=[],
                data=_deterministic_data(insights_result),
            )
            section_reasons["deterministic_insights"] = []
    else:
        for name in FULL_ONLY_SECTIONS:
            sections[name] = _section(
                status="omitted",
                reasons=["profile_concise"],
                data=None,
            )
            field_states.append(
                _field_state(
                    f"sections.{name}",
                    "omitted",
                    ["profile_concise"],
                    "The concise profile omits this extended review section.",
                )
            )
            section_reasons[name] = ["profile_concise"]

    field_states.sort(key=lambda item: item["path"])
    calculation_versions = _mapping(
        base_metadata.get("calculation_versions"), label="calculation versions"
    )
    metadata = {
        "generated_at": generated_raw,
        "as_of_date": base_metadata.get("as_of_date"),
        "base_currency": "RUB",
        "application": {
            "name": "Hermes Finance",
            "version": base_metadata.get("application", {}).get("version")
            if isinstance(base_metadata.get("application"), Mapping)
            else __version__,
        },
        "generation_mode": "read_only",
        "source_contract_name": "hermes.finance.ai_analysis_bundle",
        "source_contract_version": "1.0.0",
        "calculation_versions": {
            "monthly_summary": str(calculation_versions.get("monthly_summary", "v2")),
            "passive_income_forecast": str(
                calculation_versions.get("passive_income_forecast", version)
            ),
            "goal_achievement": str(
                calculation_versions.get("goal_achievement", GOAL_ACHIEVEMENT_METHOD_VERSION)
            ),
            "freshness_provenance": FRESHNESS_PROVENANCE_VERSION,
            "risk_allocation": RISK_ALLOCATION_VERSION,
            "deterministic_insights": DETERMINISTIC_INSIGHTS_CONTRACT_VERSION,
        },
        "ordering_contract": ORDERING_CONTRACT,
    }
    package = {
        "$schema": SCHEMA_URI,
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "profile": profile,
        "scope": {
            "reporting_period": current_period,
            "reporting_status": current_portfolio.get("reporting_status"),
            "selection_reason": selection_reason,
            "history_start_period": history[0]["period"],
            "history_end_period": history[-1]["period"],
            "missing_calendar_periods": [_period(item) for item in missing_periods],
            "requested_sections": list(ALL_SECTIONS if profile == "full" else CORE_SECTIONS),
        },
        "sections": {name: sections[name] for name in ALL_SECTIONS},
        "field_states": field_states,
        "warnings": _warnings(base, section_reasons),
    }
    validate_portfolio_review_package(package)
    return package
