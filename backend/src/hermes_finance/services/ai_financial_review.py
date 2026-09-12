"""Read-only assembler for the #331 canonical AI financial review export.

The report is an adapter around accepted backend read models.  It composes
the full ``portfolio_review_package`` (envelope source) with its underlying
``ai_analysis_bundle`` (financial source) wherever the package projection is
narrower, and adds direct allowlisted persisted rows only for facts the two
sources do not project: per-debt/per-property rows with the #336 terms,
monthly comments, owner-entered entity notes, saving allocations, actual
expense lines and the #336 planned-budget comparison.

The adapter deliberately does not calculate a second financial model,
refresh providers, persist an export, call cloud/LLM services, or mutate
reporting data.  Free text is carried with provenance and is never parsed
as a number or used in a calculation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from sqlalchemy.orm import Session

from hermes_finance import __version__
from hermes_finance.domain.values import PercentageRate, RubleAmount
from hermes_finance.services.accounts import list_accounts
from hermes_finance.services.ai_analysis_bundle import (
    SCHEMA_VERSION as BUNDLE_SCHEMA_VERSION,
)
from hermes_finance.services.ai_analysis_bundle import (
    _slug as _bundle_slug,
)
from hermes_finance.services.ai_analysis_bundle import (
    assemble_ai_analysis_bundle,
)
from hermes_finance.services.cash import list_cash_balances
from hermes_finance.services.comments import list_monthly_comments
from hermes_finance.services.debts import list_debts
from hermes_finance.services.deposits import list_deposit_snapshots
from hermes_finance.services.expenses import list_expense_entries, list_saving_allocations
from hermes_finance.services.goals import list_goals
from hermes_finance.services.instruments import list_instruments
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.planned_budget import (
    list_planned_budget_lines,
    plan_vs_actual,
)
from hermes_finance.services.portfolio_review_package import (
    SCHEMA_VERSION as PACKAGE_SCHEMA_VERSION,
)
from hermes_finance.services.portfolio_review_package import (
    assemble_portfolio_review_package,
)
from hermes_finance.services.positions import list_position_snapshots
from hermes_finance.services.properties import list_property_snapshots
from hermes_finance.services.reporting_months import list_reporting_months
from hermes_finance.services.risk_allocation import DEFAULT_TOP_N

SCHEMA_NAME = "hermes.finance.ai_financial_review"
SCHEMA_VERSION = "1.0.0"
SCHEMA_URI = "https://hermes-finance.local/schema/ai-financial-review/1.0.0/schema.json"
ORDERING_CONTRACT = "periods_then_refs_then_semantic_keys_are_sorted_as_defined_by_contract"
TEXT_POLICY = "owner_text_is_context_only_and_is_never_parsed_into_authoritative_values"
RESULT_RULE = "without_tax_benefit_plus_received_tax_benefits_only"
INTEGRATED_CONTRACTS = ("#336 financial context contract",)
ACTUAL_HISTORY_METRIC_PATH = "sections.historical_dynamics.data.history[].passive_income_actual"

_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_FORECAST_BREAKDOWN_KEYS = (
    ("expected_deposit_interest", "deposit_interest"),
    ("expected_coupon_component", "bond_coupons"),
    ("expected_dividend_component", "dividends"),
    ("other_expected_capital_income", "other_capital_income"),
)

_WARNING_SCOPE_MAP = {
    "sections.capital": "sections.current_capital",
    "sections.dynamics": "sections.historical_dynamics",
    "sections.positions": "sections.current_portfolio",
    "sections.freshness": "sections.current_portfolio",
    "sections.passive_income": "sections.passive_income",
    "sections.future_cash_flows": "sections.future_cash_flows",
    "sections.context": "sections.iis_and_tax",
    "sections.allocation": "sections.allocation_and_concentration",
    "sections.deterministic_insights": "sections.data_quality",
}

_WARNING_CODE_MAP = {
    "quote_stale": "stale_valuation",
}

_FIELD_STATE_PATH_MAP = {
    "sections.capital.data.total_net_worth": ("sections.current_capital.data.total_net_worth"),
    "sections.dynamics.data.history[].investment_return": (
        "sections.historical_dynamics.data.history[].investment_return"
    ),
    "sections.dynamics.data.history[].market_value_change": (
        "sections.historical_dynamics.data.history[].market_value_change"
    ),
    "sections.allocation": "sections.allocation_and_concentration",
    "sections.deterministic_insights": "sections.data_quality",
}

_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}

_PLANNED_BUDGET_NOT_ENTERED = "planned_budget_not_entered"
_PLANNED_BUDGET_MESSAGE = "No planned budget lines were entered; this is not a zero budget."


class AiFinancialReviewValidationError(RuntimeError):
    """Generated AI financial review failed the declared schema."""


def _schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "ai_financial_review.schema.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("ai_financial_review.schema.json was not found next to the repository")


def _schema() -> dict[str, object]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def validate_ai_financial_review(report: dict[str, object]) -> None:
    """Validate an assembled report before returning it to a caller."""
    try:
        Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(report)
    except ValidationError as error:
        raise AiFinancialReviewValidationError(
            "generated AI financial review failed schema validation"
        ) from error


def canonical_json(report: dict[str, object]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2) + "\n"


def ai_financial_review_filename(*, as_of_date: date, media: str) -> str:
    """Return a stable local filename for a report download."""
    if media not in {"json"}:
        raise ValueError("media must be json")
    return f"hermes-ai-financial-review-{as_of_date.isoformat()}.{media}"


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AiFinancialReviewValidationError(f"authoritative {label} is not an object")
    return dict(value)


def _list(value: object, *, label: str) -> list[object]:
    if not isinstance(value, list):
        raise AiFinancialReviewValidationError(f"authoritative {label} is not an array")
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


def _canonical_reason_codes(value: object) -> list[str]:
    return sorted({_WARNING_CODE_MAP.get(code, code) for code in _reason_codes(value)})


def _money(kopecks: int) -> dict[str, str]:
    return {"amount": RubleAmount(kopecks).to_api(), "currency": "RUB"}


def _available_money_metric(kopecks: int, *, source: str) -> dict[str, object]:
    return {
        "value": _money(kopecks),
        "availability": "available",
        "precision": "exact",
        "source": source,
        "reason_codes": [],
    }


def _unavailable_money_metric(*, source: str, reason_codes: object) -> dict[str, object]:
    return {
        "value": None,
        "availability": "unavailable",
        "precision": "unknown",
        "source": source,
        "reason_codes": _reason_codes(reason_codes),
    }


def _rate_metric(basis_points: int | None, *, unknown_code: str) -> dict[str, object]:
    """Map a persisted #336 nullable rate to the contract rate metric.

    ``None`` is unknown and never becomes an explicit zero; an explicit zero
    stays an exact zero fact.
    """

    if basis_points is None:
        return {
            "value_pct": None,
            "availability": "unavailable",
            "precision": "unknown",
            "source": "persisted_snapshot",
            "reason_codes": [unknown_code],
        }
    value_pct = PercentageRate(basis_points).to_api()
    if basis_points == 0:
        value_pct = "0"
    return {
        "value_pct": value_pct,
        "availability": "available",
        "precision": "exact",
        "source": "persisted_snapshot",
        "reason_codes": [],
    }


def _date_metric(value: date | None, *, unknown_code: str = "date_unknown") -> dict[str, object]:
    if value is None:
        return {"value": None, "availability": "unavailable", "reason_codes": [unknown_code]}
    text = value.isoformat()
    if _DATE_PATTERN.fullmatch(text) is None:
        raise AiFinancialReviewValidationError("authoritative date is not ISO-8601")
    return {"value": text, "availability": "available", "reason_codes": []}


def _text(value: object, *, limit: int = 2000) -> str | None:
    """Carry owner text verbatim (up to the contract cap), never parsing it."""

    if not isinstance(value, str):
        return None
    result = value.strip()
    if not result:
        return None
    return result[:limit]


def _note_refs(
    *,
    source_type: str,
    source_ref: str,
    used: set[str],
) -> str:
    return _bundle_slug(
        f"note-{source_type.replace('_', '-')}",
        source_ref,
        used,
    )


def _section(*, status: str, reasons: object, data: object) -> dict[str, object]:
    normalized_reasons = _reason_codes(reasons)
    if status in {"included", "partial"} and data is None:
        raise AiFinancialReviewValidationError("included review section has no data")
    if status == "unavailable" and data is not None:
        raise AiFinancialReviewValidationError("unavailable review section has data")
    return {"status": status, "reason_codes": normalized_reasons, "data": data}


def _coverage_from_section(section: Mapping[str, object]) -> dict[str, object]:
    status = section.get("status")
    mapped = {"included": "complete", "partial": "partial"}.get(str(status), "unavailable")
    return {"status": mapped, "reason_codes": _reason_codes(section.get("reason_codes"))}


def _capital_data(
    package_capital: Mapping[str, object],
    bundle_points: Mapping[tuple[int, int], Mapping[str, object]],
) -> dict[str, object]:
    data = _mapping(package_capital.get("data"), label="package capital data")
    period = _mapping(data.get("reporting_period"), label="capital period")
    key = (int(period["year"]), int(period["month"]))
    cash_flow: dict[str, object] = _unavailable_money_metric(
        source="backend_derived", reason_codes=["authoritative_value_unavailable"]
    )
    point = bundle_points.get(key)
    if point is not None:
        kpis = _mapping(point.get("kpis"), label="bundle history KPIs")
        candidate = kpis.get("cash_flow_after_allocations")
        if isinstance(candidate, Mapping):
            cash_flow = dict(candidate)
    return {
        "reporting_period": {"year": key[0], "month": key[1]},
        "snapshot_date": data.get("snapshot_date"),
        "liquid_assets_total": data.get("liquid_assets_total"),
        "included_debts": data.get("included_debts"),
        "liquid_capital_net": data.get("liquid_capital_net"),
        "property_equity": data.get("property_equity"),
        "total_net_worth": data.get("total_net_worth"),
        "cash_flow_after_allocations": cash_flow,
    }


def _dynamics_data(
    package_dynamics: Mapping[str, object],
    bundle_points: Mapping[tuple[int, int], Mapping[str, object]],
) -> dict[str, object]:
    data = _mapping(package_dynamics.get("data"), label="package dynamics data")
    history = []
    for value in _list(data.get("history"), label="package dynamics history"):
        point = _mapping(value, label="package dynamics point")
        period = _mapping(point.get("period"), label="dynamics period")
        key = (int(period["year"]), int(period["month"]))
        bundle_point = bundle_points.get(key)
        if bundle_point is None:
            raise AiFinancialReviewValidationError(
                "selected history period is absent from the bundle"
            )
        kpis = _mapping(bundle_point.get("kpis"), label="bundle history KPIs")
        breakdown = _mapping(
            kpis.get("passive_income_actual_breakdown"),
            label="bundle passive breakdown",
        )
        cash_flow = _mapping(kpis.get("cash_flow_after_allocations"), label="bundle cash flow")
        history.append(
            {
                "period": {"year": key[0], "month": key[1]},
                "status": point.get("status"),
                "snapshot_date": point.get("snapshot_date"),
                "coverage": point.get("coverage"),
                "liquid_assets_total": point.get("liquid_assets_total"),
                "included_debts": point.get("included_debts"),
                "liquid_capital_net": point.get("liquid_capital_net"),
                "passive_income_actual": point.get("passive_income_actual"),
                "passive_income_actual_breakdown": {
                    "deposit_interest": breakdown.get("deposit_interest"),
                    "bond_coupons": breakdown.get("bond_coupons"),
                    "dividends": breakdown.get("dividends"),
                    "other_capital_income": breakdown.get("other_capital_income"),
                },
                "active_income_net": point.get("active_income_net"),
                "mandatory_expenses": point.get("mandatory_expenses"),
                "saving_allocations": point.get("saving_allocations"),
                "cash_flow_after_allocations": dict(cash_flow),
                "property_equity": point.get("property_equity"),
                "market_value_change": point.get("market_value_change"),
                "investment_return": point.get("investment_return"),
                "warning_codes": point.get("warning_codes"),
            }
        )
    history.sort(key=lambda item: (item["period"]["year"], item["period"]["month"]))
    return {
        "history": history,
        "missing_calendar_periods": data.get("missing_calendar_periods"),
    }


def _portfolio_data(
    session: Session,
    package_positions: Mapping[str, object],
    bundle_portfolio: Mapping[str, object],
    package_freshness_data: Mapping[str, object],
    *,
    account_ref_by_id: Mapping[int, str],
    instrument_ref_by_id: Mapping[int, str],
    current_month_id: int,
) -> tuple[dict[str, object], list[tuple[str, str]]]:
    """Lift the envelope portfolio and enrich it with persisted row facts.

    Returns the portfolio data plus ``(instrument_ref, note)`` pairs for
    positions carrying an owner note.  Deposit/cash notes stay in their
    portfolio rows: those rows have no export-local ref in the accepted
    contract, so no new ref scheme is invented for them.
    """

    data = _mapping(package_positions.get("data"), label="package positions data")

    position_rows = {
        (row.account_id, row.instrument_id): row
        for row in list_position_snapshots(session)
        if row.reporting_month_id == current_month_id
    }
    deposit_groups: dict[tuple[object, str], list[object]] = {}
    for row in sorted(
        (
            item
            for item in list_deposit_snapshots(session)
            if item.reporting_month_id == current_month_id
        ),
        key=lambda item: (item.account_id, item.name, item.id),
    ):
        deposit_groups.setdefault((account_ref_by_id.get(row.account_id), row.name), []).append(row)

    bundle_cash_items = [
        _mapping(value, label="bundle cash")
        for value in _list(bundle_portfolio.get("cash_balances"), label="bundle cash")
    ]
    cash_ref_by_name: dict[str, object] = {}
    for item in bundle_cash_items:
        name = item.get("name")
        if isinstance(name, str) and name not in cash_ref_by_name:
            cash_ref_by_name[name] = item.get("account_ref")
    canonical_cash_ref = next(
        (
            item.get("account_ref")
            for item in bundle_cash_items
            if item.get("account_ref") is not None
        ),
        None,
    )
    cash_groups: dict[tuple[object, str], list[object]] = {}
    for row in sorted(
        (
            item
            for item in list_cash_balances(session)
            if item.reporting_month_id == current_month_id
        ),
        key=lambda item: (item.name, item.id),
    ):
        cash_ref = cash_ref_by_name.get(row.name, canonical_cash_ref)
        if cash_ref is None:
            cash_ref = account_ref_by_id.get(row.account_id)
        cash_groups.setdefault((cash_ref, row.name), []).append(row)

    accounts = [dict(item) for item in _list(data.get("accounts"), label="package accounts")]
    accounts.sort(key=lambda item: str(item.get("ref")))
    instruments = [
        dict(item) for item in _list(data.get("instruments"), label="package instruments")
    ]
    instruments.sort(key=lambda item: str(item.get("ref")))

    positions = []
    position_notes: list[tuple[str, str]] = []
    for value in _list(data.get("items"), label="package position items"):
        item = _mapping(value, label="position item")
        account_ref = item.get("account_ref")
        instrument_ref = item.get("instrument_ref")
        row = None
        for (account_id, instrument_id), candidate in position_rows.items():
            if (
                account_ref_by_id.get(account_id) == account_ref
                and instrument_ref_by_id.get(instrument_id) == instrument_ref
            ):
                row = candidate
                break
        average_cost: dict[str, object]
        price_source = "manual"
        notes: str | None = None
        if row is not None:
            average_cost = _available_money_metric(
                int(row.average_cost_per_unit_kopecks), source="persisted_snapshot"
            )
            price_source = row.price_source
            notes = _text(row.notes)
            if notes is not None and isinstance(instrument_ref, str):
                position_notes.append((instrument_ref, notes))
        else:
            average_cost = _unavailable_money_metric(
                source="persisted_snapshot",
                reason_codes=["authoritative_value_unavailable"],
            )
        positions.append(
            {
                "account_ref": account_ref,
                "instrument_ref": instrument_ref,
                "quantity": item.get("quantity"),
                "average_acquisition_cost_per_unit": average_cost,
                "market_price_per_unit": item.get("market_price_per_unit"),
                "market_value": item.get("market_value"),
                "cost_basis": item.get("cost_basis"),
                "unrealized_result": item.get("unrealized_result"),
                "accrued_interest": item.get("accrued_interest"),
                "price_date": item.get("price_date"),
                "price_source": price_source,
                "valuation_provenance": item.get("valuation_provenance"),
                "notes": notes,
            }
        )
    positions.sort(key=lambda item: (str(item["account_ref"]), str(item["instrument_ref"])))

    deposits = []
    for value in _list(bundle_portfolio.get("deposits"), label="bundle deposits"):
        item = _mapping(value, label="deposit")
        account_ref = item.get("account_ref")
        name = item.get("name")
        group = deposit_groups.get((account_ref, name), [])
        row = group.pop(0) if group else None
        deposits.append(
            {
                "account_ref": account_ref,
                "name": name,
                "deposit_type": item.get("deposit_type"),
                "balance": item.get("balance"),
                "annual_rate_pct": item.get("annual_rate_pct"),
                "expected_monthly_interest": item.get("expected_monthly_interest"),
                "actual_interest_received": item.get("actual_interest_received"),
                "provenance": item.get("provenance"),
                "notes": _text(row.notes) if row is not None else None,
            }
        )
    deposits.sort(key=lambda item: (str(item["account_ref"]), str(item["name"])))

    cash_balances = []
    for item in bundle_cash_items:
        account_ref = item.get("account_ref")
        name = item.get("name")
        group = cash_groups.get((account_ref, name), [])
        row = group.pop(0) if group else None
        cash_balances.append(
            {
                "account_ref": account_ref,
                "name": name,
                "amount": item.get("amount"),
                "include_in_capital": item.get("include_in_capital"),
                "provenance": item.get("provenance"),
                "notes": _text(row.notes) if row is not None else None,
            }
        )
    cash_balances.sort(key=lambda item: (str(item["account_ref"]), str(item["name"])))

    valuation = _mapping(
        bundle_portfolio.get("valuation_freshness"),
        label="bundle valuation freshness",
    )
    freshness = {
        "evaluated_on": package_freshness_data.get("evaluated_on"),
        "quote_valuation_target_date": package_freshness_data.get("quote_valuation_target_date"),
        "families": package_freshness_data.get("families"),
        "oldest_price_date": valuation.get("oldest_price_date"),
        "latest_price_date": valuation.get("latest_price_date"),
        "stale_valuation_count": valuation.get("stale_valuation_count"),
        "position_count": valuation.get("position_count"),
        "stale_valuation_share": valuation.get("stale_valuation_share"),
    }
    return (
        {
            "reporting_period": data.get("reporting_period"),
            "snapshot_date": data.get("snapshot_date"),
            "accounts": accounts,
            "instruments": instruments,
            "positions": positions,
            "deposits": deposits,
            "cash_balances": cash_balances,
            "missing_snapshot_account_refs": bundle_portfolio.get("missing_snapshot_account_refs"),
            "freshness": freshness,
        },
        sorted(position_notes),
    )


def _passive_data(
    package_passive: Mapping[str, object],
    bundle_points: Mapping[tuple[int, int], Mapping[str, object]],
    reporting_period: tuple[int, int],
) -> dict[str, object]:
    data = _mapping(package_passive.get("data"), label="package passive data")
    forecast_source = _mapping(data.get("forecast"), label="package passive forecast")
    breakdown_source = _mapping(
        forecast_source.get("breakdown"), label="package forecast breakdown"
    )
    breakdown = {
        target: breakdown_source.get(source) for source, target in _FORECAST_BREAKDOWN_KEYS
    }
    forecast = {
        "forecast_version": forecast_source.get("forecast_version"),
        "as_of_date": forecast_source.get("as_of_date"),
        "annual_total": forecast_source.get("annual_total"),
        "monthly_total": forecast_source.get("monthly_total"),
        "breakdown": breakdown,
        "dividend_component_source": forecast_source.get("dividend_component_source"),
        "deposit_projection_method": forecast_source.get("deposit_projection_method"),
        "warning_codes": forecast_source.get("warning_codes"),
    }
    current_point = bundle_points.get(reporting_period)
    if current_point is None:
        raise AiFinancialReviewValidationError("selected history period is absent from the bundle")
    current_breakdown = _mapping(
        _mapping(current_point.get("kpis"), label="bundle history KPIs").get(
            "passive_income_actual_breakdown"
        ),
        label="bundle current passive breakdown",
    )
    return {
        "actual_history_metric_path": ACTUAL_HISTORY_METRIC_PATH,
        "current_month_breakdown": {
            "deposit_interest": current_breakdown.get("deposit_interest"),
            "bond_coupons": current_breakdown.get("bond_coupons"),
            "dividends": current_breakdown.get("dividends"),
            "other_capital_income": current_breakdown.get("other_capital_income"),
        },
        "rolling_actual_average": data.get("rolling_actual_average"),
        "forecast": forecast,
    }


def _future_cash_flows_data(package_future: Mapping[str, object]) -> dict[str, object]:
    data = _mapping(package_future.get("data"), label="package future cash flows")
    items = []
    for value in _list(data.get("items"), label="package cash-flow items"):
        item = _mapping(value, label="cash-flow item")
        tax_status = item.get("personal_tax_status")
        if tax_status == "known_or_accounted":
            tax_status = "known"
        items.append({**dict(item), "personal_tax_status": tax_status})
    items.sort(key=lambda item: (str(item.get("expected_date")), str(item.get("event_ref"))))
    return {
        "window_start": data.get("window_start"),
        "window_end_exclusive": data.get("window_end_exclusive"),
        "forecast_version": data.get("forecast_version"),
        "non_principal_calendar_amount_total": data.get("non_principal_calendar_amount_total"),
        "principal_total": data.get("principal_total"),
        "calendar_total": data.get("calendar_total"),
        "items": items,
        "warning_codes": data.get("warning_codes"),
    }


def _goal_deadlines_by_ref(
    session: Session,
    *,
    account_ref_by_id: Mapping[int, str],
    instrument_ref_by_id: Mapping[int, str],
    current_month_id: int,
) -> dict[str, date | None]:
    """Join persisted goal deadlines to the bundle's export-local goal refs."""

    used_refs = set(account_ref_by_id.values()) | set(instrument_ref_by_id.values())
    account_rows = list_accounts(session)
    if not any(row.account_type == "cash" for row in account_rows):
        if any(row.reporting_month_id == current_month_id for row in list_cash_balances(session)):
            _bundle_slug("acct", "cash-balances", used_refs)

    deadlines: dict[str, date | None] = {}
    for goal in sorted(
        list_goals(session, include_inactive=True), key=lambda item: (item.name, item.id)
    ):
        ref = _bundle_slug("goal", goal.name, used_refs)
        deadlines[ref] = goal.target_date
    return deadlines


def _goals_data(
    package_context: Mapping[str, object],
    deadlines_by_ref: Mapping[str, date | None],
) -> dict[str, object]:
    goals_source = _list(package_context.get("goals"), label="package goals")
    items = []
    for value in goals_source:
        item = _mapping(value, label="goal")
        ref = item.get("ref")
        if isinstance(ref, str) and ref in deadlines_by_ref:
            deadline = _date_metric(deadlines_by_ref[ref], unknown_code="no_deadline")
        else:
            deadline = {
                "value": None,
                "availability": "unavailable",
                "reason_codes": ["deadline_unmatched"],
            }
        item_data = dict(item)
        items.append(
            {
                "ref": item_data.get("ref"),
                "name": item_data.get("name"),
                "goal_type": item_data.get("goal_type"),
                "is_primary": item_data.get("is_primary"),
                "target": item_data.get("target"),
                "current_value": item_data.get("current_value"),
                "gap": item_data.get("gap"),
                "progress": item_data.get("progress"),
                "deadline": deadline,
                "projection_status": item_data.get("projection_status"),
                "estimated_achievement_date": item_data.get("estimated_achievement_date"),
                "method_version": item_data.get("method_version"),
                "source_metric_path": item_data.get("source_metric_path"),
                "warning_codes": item_data.get("warning_codes"),
            }
        )
    items.sort(key=lambda item: str(item.get("ref")))
    return {"items": items}


def _debts_data(
    session: Session,
    package_context: Mapping[str, object],
    bundle_debts: Mapping[str, object],
    *,
    reporting_period: tuple[int, int],
    current_month_id: int,
) -> tuple[dict[str, object], list[str], list[tuple[str, str, str]]]:
    """Build per-row debt/property facts with #336 terms and owner notes.

    Returns the section data, section reason codes, and ``(kind, ref, note)``
    triples (``kind`` is ``debt`` or ``property``) for the owner-context notes.
    """

    context_debts = _mapping(
        package_context.get("debts_and_real_estate"), label="package debt context"
    )
    property_context = _mapping(context_debts.get("property"), label="package property context")

    used: set[str] = set()
    debts = []
    note_triples: list[tuple[str, str, str]] = []
    debt_unknown_rate = False
    for row in sorted(
        (item for item in list_debts(session) if item.reporting_month_id == current_month_id),
        key=lambda item: (item.name, item.debt_type, item.id),
    ):
        rate = _rate_metric(row.annual_rate_basis_points, unknown_code="annual_rate_unknown")
        if rate["availability"] != "available":
            debt_unknown_rate = True
        ref = _bundle_slug("debt", row.name, used)
        notes = _text(row.notes)
        if notes is not None:
            note_triples.append(("debt", ref, notes))
        debts.append(
            {
                "ref": ref,
                "debt_type": row.debt_type,
                "name": row.name,
                "current_balance": _available_money_metric(
                    int(row.current_balance_kopecks), source="persisted_snapshot"
                ),
                "include_in_liquid_capital": bool(row.include_in_liquid_capital),
                "annual_rate": rate,
                "next_due_date": _date_metric(row.next_due_date),
                "contract_end_date": _date_metric(row.contract_end_date),
                "notes": notes,
            }
        )
    debts.sort(key=lambda item: str(item["ref"]))

    real_estate = []
    mortgage_unknown_rate = False
    for row in sorted(
        (
            item
            for item in list_property_snapshots(session)
            if item.reporting_month_id == current_month_id
        ),
        key=lambda item: (item.name, item.id),
    ):
        rate = _rate_metric(
            row.mortgage_annual_rate_basis_points,
            unknown_code="mortgage_rate_unknown",
        )
        if rate["availability"] != "available":
            mortgage_unknown_rate = True
        ref = _bundle_slug("property", row.name, used)
        notes = _text(row.notes)
        if notes is not None:
            note_triples.append(("property", ref, notes))
        real_estate.append(
            {
                "ref": ref,
                "name": row.name,
                "estimated_value": _available_money_metric(
                    int(row.estimated_value_kopecks), source="persisted_snapshot"
                ),
                "mortgage_balance": _available_money_metric(
                    int(row.mortgage_balance_kopecks), source="persisted_snapshot"
                ),
                "monthly_payment": _available_money_metric(
                    int(row.monthly_payment_kopecks), source="persisted_snapshot"
                ),
                "mortgage_annual_rate": rate,
                "notes": notes,
            }
        )
    real_estate.sort(key=lambda item: str(item["ref"]))

    reasons: list[str] = []
    if debt_unknown_rate:
        reasons.append("annual_rate_unknown")
    if mortgage_unknown_rate:
        reasons.append("mortgage_rate_unknown")
    mortgage_coverage = context_debts.get("mortgage_coverage")
    if isinstance(mortgage_coverage, Mapping):
        if mortgage_coverage.get("availability") != "available":
            reasons.extend(_reason_codes(mortgage_coverage.get("reason_codes")))
    reasons = sorted(reasons)

    bundle_property_quality = bundle_debts.get("property_data_quality")
    if isinstance(bundle_property_quality, Mapping):
        property_quality = dict(bundle_property_quality)
    else:
        property_quality = {
            "warning_codes": [],
            "structured_snapshot_authoritative": True,
        }
    data = {
        "reporting_period": {"year": reporting_period[0], "month": reporting_period[1]},
        "debts": debts,
        "real_estate": real_estate,
        "property_equity": property_context.get("property_equity"),
        "mortgage_coverage": context_debts.get("mortgage_coverage"),
        "liquidity_rule": "real_estate_and_mortgage_are_excluded_from_liquid_capital",
        "property_data_quality": property_quality,
    }
    return data, reasons, note_triples


def _iis_data(
    package_context: Mapping[str, object],
    bundle_iis: Mapping[str, object],
) -> tuple[dict[str, object], list[str]]:
    context_iis = _mapping(package_context.get("iis_and_tax"), label="package IIS context")
    bundle_coverage = _mapping(bundle_iis.get("iis_coverage"), label="bundle IIS coverage")
    coverage = {
        "status": bundle_coverage.get("status"),
        "reason_codes": _reason_codes(bundle_coverage.get("reason_codes")),
    }
    accounts = []
    for value in _list(context_iis.get("iis_accounts"), label="package IIS accounts"):
        item = _mapping(value, label="IIS account")
        accounts.append({**dict(item), "result_rule": RESULT_RULE})
    accounts.sort(key=lambda item: str(item.get("account_ref")))
    salary = _mapping(context_iis.get("salary_tax_context"), label="salary-tax context")
    reasons = set(coverage["reason_codes"]) if coverage["status"] != "complete" else set()
    reasons.update(_reason_codes(salary.get("warning_codes")))
    history_coverage = salary.get("history_coverage")
    if isinstance(history_coverage, Mapping) and history_coverage.get("status") != "complete":
        reasons.update(_reason_codes(history_coverage.get("reason_codes")))
    data = {
        "iis_coverage": coverage,
        "iis_accounts": accounts,
        "salary_tax_context": dict(salary),
    }
    return data, sorted(reasons)


def _insight_provenance(value: object) -> dict[str, object]:
    provider = value if isinstance(value, str) else None
    if provider not in {None, "t_invest", "alfa_pro", "alfa_statement"}:
        provider = None
    return {"source_kind": "backend_derived", "provider": provider, "observed_at": None}


def _quality_data(
    package_insights: Mapping[str, object],
    *,
    planned_budget_entered: bool,
) -> tuple[dict[str, object] | None, list[str], str]:
    status = str(package_insights.get("status"))
    reasons = _reason_codes(package_insights.get("reason_codes"))
    if status == "unavailable":
        return None, reasons, status

    data = _mapping(package_insights.get("data"), label="package insights data")
    items = []
    for value in _list(data.get("items"), label="package insight items"):
        item = _mapping(value, label="insight item")
        provenance = [
            _insight_provenance(entry.get("provider"))
            if isinstance(entry, Mapping)
            else _insight_provenance(None)
            for entry in _list(item.get("provenance"), label="insight provenance")
        ]
        items.append(
            {
                "code": item.get("code"),
                "type": item.get("type"),
                "severity": item.get("severity"),
                "message": item.get("message"),
                "source": item.get("source"),
                "as_of": item.get("as_of"),
                "provenance": provenance,
                "reason": item.get("reason"),
            }
        )
    if not planned_budget_entered:
        reasons = sorted(set(reasons) | {_PLANNED_BUDGET_NOT_ENTERED})
    if status not in {"included", "partial", "unavailable"}:
        status = "partial" if reasons else "included"
    elif reasons and status == "included":
        status = "partial"
    if status == "unavailable":
        return None, reasons, status
    return {"deterministic_insights": items}, reasons, status


def _user_context_data(
    session: Session,
    *,
    history_month_ids: Mapping[tuple[int, int], int],
    reporting_period: tuple[int, int],
    position_notes: list[tuple[str, str]],
    debt_notes: list[tuple[str, str, str]],
    expense_notes: list[tuple[str, str]],
    saving_notes: list[tuple[str, str]],
    plan_notes: list[tuple[str, str]],
) -> dict[str, object]:
    """Carry persisted monthly comments and owner-entered notes as context.

    ``debt_notes`` entries are ``(kind, ref, text)`` triples where ``kind``
    is ``debt`` or ``property``.  Text is preserved verbatim (up to the
    contract cap) and never parsed into an authoritative value.
    """

    comments = []
    for period in sorted(history_month_ids):
        month_id = history_month_ids[period]
        for comment in list_monthly_comments(session, month_id):
            text = _text(comment.text)
            if text is None:
                continue
            comments.append(
                {
                    "ref": f"comment-{period[0]:04d}-{period[1]:02d}-{comment.position}",
                    "period": {"year": period[0], "month": period[1]},
                    "position": int(comment.position),
                    "text": text,
                    "source": "persisted_user_note",
                }
            )
    comments.sort(
        key=lambda item: (
            item["period"]["year"],
            item["period"]["month"],
            item["position"],
        )
    )

    typed_notes: list[tuple[str, list[tuple[str, ...]]]] = [
        ("position", [(ref, text) for ref, text in position_notes]),
        ("debt", [(ref, text) for kind, ref, text in debt_notes if kind == "debt"]),
        (
            "property",
            [(ref, text) for kind, ref, text in debt_notes if kind == "property"],
        ),
        ("expense", list(expense_notes)),
        ("saving_allocation", list(saving_notes)),
        ("planned_budget", list(plan_notes)),
    ]
    used: set[str] = set()
    entity_notes = []
    for source_type, entries in typed_notes:
        for source_ref, text in sorted(entries):
            entity_notes.append(
                {
                    "ref": _note_refs(source_type=source_type, source_ref=source_ref, used=used),
                    "source_type": source_type,
                    "source_ref": source_ref,
                    "period": {
                        "year": reporting_period[0],
                        "month": reporting_period[1],
                    },
                    "text": text,
                    "source": "persisted_user_note",
                }
            )
    entity_notes.sort(key=lambda item: str(item["ref"]))
    return {
        "monthly_comments": comments,
        "entity_notes": entity_notes,
        "text_policy": TEXT_POLICY,
    }


def _budget_data(
    session: Session,
    *,
    reporting_period: tuple[int, int],
    current_month_id: int,
) -> tuple[dict[str, object], list[str], bool, dict[str, list[tuple[str, str]]]]:
    """Build saving/actual/plan facts with the authoritative plan-vs-actual.

    Returns the section data, section reason codes, whether a plan was
    entered, and ``(ref, note)`` pairs per note-carrying row kind.
    """

    used: set[str] = set()
    note_pairs: dict[str, list[tuple[str, str]]] = {
        "saving_allocation": [],
        "expense": [],
        "planned_budget": [],
    }
    saving_allocations = []
    for row in sorted(
        (
            item
            for item in list_saving_allocations(session)
            if item.reporting_month_id == current_month_id
        ),
        key=lambda item: (item.destination, item.id),
    ):
        ref = _bundle_slug("allocation", row.destination, used)
        notes = _text(row.notes)
        if notes is not None:
            note_pairs["saving_allocation"].append((ref, notes))
        saving_allocations.append(
            {
                "ref": ref,
                "period": {"year": reporting_period[0], "month": reporting_period[1]},
                "destination": row.destination,
                "amount": _money(int(row.amount_kopecks)),
                "notes": notes,
            }
        )
    saving_allocations.sort(key=lambda item: str(item["ref"]))

    actual_expenses = []
    for row in sorted(
        (
            item
            for item in list_expense_entries(session)
            if item.reporting_month_id == current_month_id
        ),
        key=lambda item: (item.category, item.expense_type, item.id),
    ):
        ref = _bundle_slug("expense", f"{row.category}-{row.expense_type}", used)
        notes = _text(row.notes)
        if notes is not None:
            note_pairs["expense"].append((ref, notes))
        actual_expenses.append(
            {
                "ref": ref,
                "period": {"year": reporting_period[0], "month": reporting_period[1]},
                "category": row.category,
                "amount": _money(int(row.amount_kopecks)),
                "expense_type": row.expense_type,
                "is_recurring": bool(row.is_recurring),
                "notes": notes,
            }
        )
    actual_expenses.sort(key=lambda item: str(item["ref"]))

    plan_lines = []
    for row in sorted(
        (
            item
            for item in list_planned_budget_lines(session)
            if item.reporting_month_id == current_month_id
        ),
        key=lambda item: (item.category, item.expense_type, item.id),
    ):
        ref = _bundle_slug("planned-budget", f"{row.category}-{row.expense_type}", used)
        notes = _text(row.notes)
        if notes is not None:
            note_pairs["planned_budget"].append((ref, notes))
        plan_lines.append(
            {
                "ref": ref,
                "period": {"year": reporting_period[0], "month": reporting_period[1]},
                "category": row.category,
                "planned_amount": _money(int(row.planned_amount_kopecks)),
                "expense_type": row.expense_type,
                "notes": notes,
            }
        )
    plan_lines.sort(key=lambda item: str(item["ref"]))

    plan_rows = []
    for row in plan_vs_actual(session, current_month_id):
        plan_rows.append(
            {
                "period": {"year": reporting_period[0], "month": reporting_period[1]},
                "category": row.category,
                "expense_type": row.expense_type,
                "planned_amount": _money(row.planned.kopecks) if row.planned is not None else None,
                "actual_amount": _money(row.actual.kopecks) if row.actual is not None else None,
            }
        )
    plan_rows.sort(key=lambda item: (str(item["category"]), str(item["expense_type"])))

    entered = bool(plan_lines)
    if entered:
        planned_budget: dict[str, object] = {
            "state": "entered",
            "reason_codes": [],
            "lines": plan_lines,
            "plan_vs_actual": plan_rows,
        }
        reasons: list[str] = []
    else:
        planned_budget = {
            "state": "not_entered",
            "reason_codes": [_PLANNED_BUDGET_NOT_ENTERED],
            "lines": [],
            "plan_vs_actual": plan_rows,
        }
        reasons = [_PLANNED_BUDGET_NOT_ENTERED]
    data = {
        "saving_allocations": saving_allocations,
        "actual_expenses": actual_expenses,
        "planned_budget": planned_budget,
    }
    return data, reasons, entered, note_pairs


def _remap_warnings(
    package_warnings: object,
    *,
    extra: list[dict[str, str]],
) -> list[dict[str, str]]:
    collected: dict[tuple[str, str], dict[str, str]] = {}
    for value in _list(package_warnings, label="package warnings"):
        warning = _mapping(value, label="package warning")
        code = warning.get("code")
        scope = warning.get("scope")
        if not isinstance(code, str) or _CODE_PATTERN.fullmatch(code) is None:
            continue
        code = _WARNING_CODE_MAP.get(code, code)
        scope_text = str(scope) if isinstance(scope, str) else "sections"
        scope_text = _WARNING_SCOPE_MAP.get(scope_text, scope_text)
        severity = warning.get("severity")
        if severity not in _SEVERITY_RANK:
            severity = "info"
        message = warning.get("message")
        if not isinstance(message, str) or not message:
            message = "An accepted backend read model reported a limited value."
        collected[(code, scope_text)] = {
            "code": code,
            "severity": severity,
            "scope": scope_text,
            "message": message[:500],
        }
    for warning in extra:
        collected[(warning["code"], warning["scope"])] = warning
    return sorted(
        collected.values(),
        key=lambda item: (
            _SEVERITY_RANK[item["severity"]],
            item["code"],
            item["scope"],
        ),
    )


def _remap_field_states(package_states: object) -> list[dict[str, object]]:
    states = []
    for value in _list(package_states, label="package field states"):
        state = _mapping(value, label="package field state")
        path = state.get("path")
        if not isinstance(path, str):
            continue
        status = state.get("status")
        if status not in {"partial", "unavailable"}:
            continue
        states.append(
            {
                "path": _FIELD_STATE_PATH_MAP.get(path, path),
                "status": status,
                "reason_codes": _reason_codes(state.get("reason_codes")),
                "message": str(state.get("message", ""))[:500],
            }
        )
    return states


def assemble_ai_financial_review(
    session: Session,
    *,
    generated_at: datetime | None = None,
    evaluated_on: date | None = None,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, object]:
    """Compose the canonical AI financial review from accepted read models."""

    version = forecast_version.strip()
    if not version:
        raise ValueError("forecast_version must not be empty")

    bundle = assemble_ai_analysis_bundle(
        session,
        generated_at=generated_at,
        forecast_version=version,
    )
    package = assemble_portfolio_review_package(
        session,
        profile="full",
        generated_at=generated_at,
        evaluated_on=evaluated_on,
        forecast_version=version,
        top_n=top_n,
        _source_bundle=bundle,
    )

    package_metadata = _mapping(package.get("metadata"), label="package metadata")
    package_scope = _mapping(package.get("scope"), label="package scope")
    package_sections = _mapping(package.get("sections"), label="package sections")

    bundle_points: dict[tuple[int, int], Mapping[str, object]] = {}
    for value in _list(bundle.get("reporting_history"), label="bundle history"):
        point = _mapping(value, label="bundle history point")
        period = _mapping(point.get("period"), label="bundle history period")
        bundle_points[(int(period["year"]), int(period["month"]))] = point
    bundle_portfolio = _mapping(bundle.get("current_portfolio"), label="bundle current portfolio")
    bundle_iis = _mapping(bundle.get("iis_and_tax"), label="bundle IIS and tax")

    scope_period = _mapping(package_scope.get("reporting_period"), label="scope reporting period")
    reporting_period = (int(scope_period["year"]), int(scope_period["month"]))
    history_start = _mapping(package_scope.get("history_start_period"), label="scope history start")
    history_end = _mapping(package_scope.get("history_end_period"), label="package history end")

    months = list_reporting_months(session)
    month_by_period = {(month.year, month.month): month for month in months}
    current_month = month_by_period.get(reporting_period)
    if current_month is None:
        raise AiFinancialReviewValidationError("selected reporting period has no reporting month")
    current_month_id = int(current_month.id)

    history_month_ids = {
        (int(month.year), int(month.month)): int(month.id)
        for month in months
        if (int(month.year), int(month.month)) in bundle_points
    }

    used_refs: set[str] = set()
    account_ref_by_id: dict[int, str] = {}
    for row in sorted(
        list_accounts(session), key=lambda item: (item.name, item.account_type, item.id)
    ):
        account_ref_by_id[row.id] = _bundle_slug("acct", row.name, used_refs)
    instrument_ref_by_id: dict[int, str] = {}
    for row in sorted(
        list_instruments(session),
        key=lambda item: (item.name, item.instrument_type, item.id),
    ):
        instrument_ref_by_id[row.id] = _bundle_slug("inst", row.name, used_refs)
    goal_deadlines_by_ref = _goal_deadlines_by_ref(
        session,
        account_ref_by_id=account_ref_by_id,
        instrument_ref_by_id=instrument_ref_by_id,
        current_month_id=current_month_id,
    )

    package_capital = _mapping(package_sections.get("capital"), label="capital section")
    package_dynamics = _mapping(package_sections.get("dynamics"), label="dynamics section")
    package_positions = _mapping(package_sections.get("positions"), label="positions section")
    package_passive = _mapping(package_sections.get("passive_income"), label="passive section")
    package_future = _mapping(package_sections.get("future_cash_flows"), label="future section")
    package_allocation = _mapping(package_sections.get("allocation"), label="allocation section")
    package_context = _mapping(
        _mapping(package_sections.get("context"), label="context section").get("data"),
        label="package context data",
    )
    package_insights = _mapping(
        package_sections.get("deterministic_insights"), label="insights section"
    )
    package_freshness = _mapping(package_sections.get("freshness"), label="freshness section")

    capital_data = _capital_data(package_capital, bundle_points)
    dynamics_data = _dynamics_data(package_dynamics, bundle_points)
    freshness_section_data = _mapping(package_freshness.get("data"), label="package freshness data")
    portfolio_data, position_notes = _portfolio_data(
        session,
        package_positions,
        bundle_portfolio,
        freshness_section_data,
        account_ref_by_id=account_ref_by_id,
        instrument_ref_by_id=instrument_ref_by_id,
        current_month_id=current_month_id,
    )
    passive_data = _passive_data(package_passive, bundle_points, reporting_period)
    future_data = _future_cash_flows_data(package_future)
    goals_data = _goals_data(package_context, goal_deadlines_by_ref)
    goals_reasons = {
        code
        for item in goals_data["items"]
        if isinstance(item, Mapping)
        for field in ("current_value", "gap", "progress")
        for code in _reason_codes(
            _mapping(item.get(field), label=f"goal {field}").get("reason_codes")
        )
    }
    goals_reasons.update(
        code
        for item in goals_data["items"]
        if isinstance(item, Mapping)
        for code in _reason_codes(item.get("warning_codes"))
    )
    goals_reasons = sorted(goals_reasons)

    allocation_data = package_allocation.get("data")
    if package_allocation.get("status") == "unavailable":
        allocation_data = None

    bundle_debts = _mapping(
        bundle.get("debts_and_real_estate"), label="bundle debts and real estate"
    )
    debts_data, debts_reasons, debt_property_notes = _debts_data(
        session,
        package_context,
        bundle_debts,
        reporting_period=reporting_period,
        current_month_id=current_month_id,
    )
    iis_data, iis_reasons = _iis_data(package_context, bundle_iis)
    budget_data, budget_reasons, plan_entered, budget_note_pairs = _budget_data(
        session,
        reporting_period=reporting_period,
        current_month_id=current_month_id,
    )
    quality_data, quality_reasons, quality_status = _quality_data(
        package_insights, planned_budget_entered=plan_entered
    )

    portfolio_reasons = set(_reason_codes(package_positions.get("reason_codes")))
    portfolio_reasons.update(_canonical_reason_codes(package_freshness.get("reason_codes")))
    portfolio_freshness = _mapping(
        portfolio_data.get("freshness"), label="review portfolio freshness"
    )
    if int(portfolio_freshness.get("stale_valuation_count") or 0) > 0:
        portfolio_reasons.add("stale_valuation")
    portfolio_reasons = sorted(portfolio_reasons)
    if portfolio_reasons and str(package_positions.get("status")) == "included":
        portfolio_status = "partial"
    else:
        portfolio_status = str(package_positions.get("status"))

    quality_reasons = sorted(set(quality_reasons) | set(portfolio_reasons))
    if package_scope.get("missing_calendar_periods"):
        quality_reasons = sorted(set(quality_reasons) | {"reporting_history_gap"})
    if quality_status == "included" and quality_reasons:
        quality_status = "partial"

    user_context = _user_context_data(
        session,
        history_month_ids=history_month_ids,
        reporting_period=reporting_period,
        position_notes=position_notes,
        debt_notes=debt_property_notes,
        expense_notes=budget_note_pairs["expense"],
        saving_notes=budget_note_pairs["saving_allocation"],
        plan_notes=budget_note_pairs["planned_budget"],
    )

    sections: dict[str, dict[str, object]] = {
        "current_capital": _section(
            status=str(package_capital.get("status")),
            reasons=package_capital.get("reason_codes"),
            data=capital_data,
        ),
        "historical_dynamics": _section(
            status=str(package_dynamics.get("status")),
            reasons=package_dynamics.get("reason_codes"),
            data=dynamics_data,
        ),
        "current_portfolio": _section(
            status=portfolio_status,
            reasons=portfolio_reasons,
            data=portfolio_data,
        ),
        "allocation_and_concentration": _section(
            status=str(package_allocation.get("status")),
            reasons=package_allocation.get("reason_codes"),
            data=allocation_data,
        ),
        "passive_income": _section(
            status=str(package_passive.get("status")),
            reasons=package_passive.get("reason_codes"),
            data=passive_data,
        ),
        "future_cash_flows": _section(
            status=str(package_future.get("status")),
            reasons=package_future.get("reason_codes"),
            data=future_data,
        ),
        "goals": _section(
            status="partial" if goals_reasons else "included",
            reasons=goals_reasons,
            data=goals_data,
        ),
        "debts_and_real_estate": _section(
            status="partial" if debts_reasons else "included",
            reasons=debts_reasons,
            data=debts_data,
        ),
        "iis_and_tax": _section(
            status="partial" if iis_reasons else "included",
            reasons=iis_reasons,
            data=iis_data,
        ),
        "user_context": _section(status="included", reasons=[], data=user_context),
        "budget_and_saving": _section(
            status="partial" if budget_reasons else "included",
            reasons=budget_reasons,
            data=budget_data,
        ),
        "data_quality": _section(
            status=quality_status,
            reasons=quality_reasons,
            data=quality_data,
        ),
    }

    coverage = {
        "domains": {
            "capital": _coverage_from_section(sections["current_capital"]),
            "history": _coverage_from_section(sections["historical_dynamics"]),
            "portfolio": _coverage_from_section(sections["current_portfolio"]),
            "passive_income": _coverage_from_section(sections["passive_income"]),
            "future_cash_flows": _coverage_from_section(sections["future_cash_flows"]),
            "goals": _coverage_from_section(sections["goals"]),
            "debts_and_real_estate": _coverage_from_section(sections["debts_and_real_estate"]),
            "iis_and_tax": _coverage_from_section(sections["iis_and_tax"]),
            "user_context": _coverage_from_section(sections["user_context"]),
            "budget_and_saving": _coverage_from_section(sections["budget_and_saving"]),
        }
    }

    extra_warnings: list[dict[str, str]] = []
    if not plan_entered:
        extra_warnings.append(
            {
                "code": _PLANNED_BUDGET_NOT_ENTERED,
                "severity": "info",
                "scope": "sections.budget_and_saving",
                "message": _PLANNED_BUDGET_MESSAGE,
            }
        )
    warnings = _remap_warnings(package.get("warnings"), extra=extra_warnings)

    field_states = _remap_field_states(package.get("field_states"))
    missing_periods = _list(
        package_scope.get("missing_calendar_periods"),
        label="scope missing periods",
    )
    for index, value in enumerate(missing_periods):
        period = _mapping(value, label="missing period")
        field_states.append(
            {
                "path": f"scope.missing_calendar_periods[{index}]",
                "status": "partial",
                "reason_codes": ["reporting_history_gap"],
                "message": "The calendar month is absent from persisted reporting history.",
            }
        )
        _ = period
    field_states.sort(key=lambda item: str(item["path"]))

    financial_sources: list[str] = []
    for source in (
        "backend_derived",
        "persisted_snapshot",
        "persisted_actual",
        "persisted_expected",
        "merged_payout_calendar",
    ):
        if source not in financial_sources:
            financial_sources.append(source)

    calculation_versions = _mapping(
        package_metadata.get("calculation_versions"), label="calculation versions"
    )
    application = package_metadata.get("application")
    application_version: object = __version__
    if isinstance(application, Mapping) and isinstance(application.get("version"), str):
        application_version = application.get("version")
    generated_raw = package_metadata.get("generated_at")
    if not isinstance(generated_raw, str):
        raise AiFinancialReviewValidationError("package generation clock is unavailable")

    report = {
        "$schema": SCHEMA_URI,
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "generated_at": generated_raw,
            "as_of_date": package_metadata.get("as_of_date"),
            "base_currency": "RUB",
            "application": {"name": "Hermes Finance", "version": application_version},
            "generation_mode": "read_only",
            "source_contracts": [
                {
                    "name": "hermes.finance.ai_analysis_bundle",
                    "version": str(BUNDLE_SCHEMA_VERSION),
                    "role": "financial_source",
                },
                {
                    "name": "hermes.finance.portfolio_review_package",
                    "version": str(PACKAGE_SCHEMA_VERSION),
                    "role": "envelope_source",
                },
            ],
            "integrated_contracts": list(INTEGRATED_CONTRACTS),
            "calculation_versions": {
                "monthly_summary": calculation_versions.get("monthly_summary"),
                "passive_income_forecast": calculation_versions.get("passive_income_forecast"),
                "goal_achievement": calculation_versions.get("goal_achievement"),
                "freshness_provenance": calculation_versions.get("freshness_provenance"),
                "risk_allocation": calculation_versions.get("risk_allocation"),
                "deterministic_insights": calculation_versions.get("deterministic_insights"),
            },
            "ordering_contract": ORDERING_CONTRACT,
        },
        "scope": {
            "reporting_period": {
                "year": reporting_period[0],
                "month": reporting_period[1],
            },
            "reporting_status": package_scope.get("reporting_status"),
            "selection_reason": package_scope.get("selection_reason"),
            "history_start_period": {
                "year": int(history_start["year"]),
                "month": int(history_start["month"]),
            },
            "history_end_period": {
                "year": int(history_end["year"]),
                "month": int(history_end["month"]),
            },
            "missing_calendar_periods": package_scope.get("missing_calendar_periods"),
        },
        "coverage": coverage,
        "provenance_summary": {
            "financial_sources": financial_sources,
            "owner_context_sources": ["persisted_user_note"],
            "excluded_sources": [
                "database_ids",
                "provider_payloads",
                "credentials",
                "technical_paths",
            ],
        },
        "sections": sections,
        "field_states": field_states,
        "warnings": warnings,
    }
    validate_ai_financial_review(report)
    return report
