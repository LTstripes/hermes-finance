"""Read-only AI Analysis Bundle assembler (R07-02).

Maps existing authoritative backend services into the accepted #128 contract.
Does not recompute financial formulas and never sends the bundle anywhere.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from hermes_finance import __version__
from hermes_finance.domain.goal_achievement import GOAL_ACHIEVEMENT_METHOD_VERSION
from hermes_finance.domain.values import PercentageRate, RubleAmount
from hermes_finance.services.applied_payouts import PayoutCountingDecision
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    AppSettings,
    IisContribution,
    IisProfile,
    IncomeEntry,
    PositionQuoteProvenance,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    TaxBenefit,
)
from hermes_finance.services.accounts import list_accounts
from hermes_finance.services.cash import list_cash_balances
from hermes_finance.services.cash_balance import cash_balance_for_month
from hermes_finance.services.debts import total_debts, total_included_debts
from hermes_finance.services.deposits import list_deposit_snapshots
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.goal_achievement import build_goal_achievement_summary
from hermes_finance.services.iis_result import iis_result
from hermes_finance.services.instruments import list_instruments
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.passive_income_average import passive_income_average
from hermes_finance.services.payout_calendar import (
    MergedPayoutCalendarItem,
    PayoutCalendarSource,
    merged_payout_calendar,
)
from hermes_finance.services.positions import list_position_snapshots
from hermes_finance.services.properties import (
    mortgage_coverage,
    property_equity,
    total_mortgage_balance,
    total_property_value,
)
from hermes_finance.services.reporting_months import list_reporting_months
from hermes_finance.services.salary import calculate_salary_tax
from hermes_finance.services.salary_tax_context import (
    SalaryTaxHistoryIncompleteError,
    get_salary_tax_year_context,
)
from hermes_finance.services.settings import parse_passive_income_history_start_month
from hermes_finance.services.tax_brackets import get_or_create_default_tax_brackets
from hermes_finance.domain.incomes import IncomeType

SCHEMA_NAME = "hermes.finance.ai_analysis_bundle"
SCHEMA_VERSION = "1.0.0"
SCHEMA_URI = "https://hermes-finance.local/schema/ai-analysis-bundle/1.0.0/schema.json"
ORDERING_CONTRACT = "arrays_are_stably_sorted_as_defined_by_contract"
ACTUAL_HISTORY_METRIC_PATH = "reporting_history[].kpis.passive_income_actual"
LIQUIDITY_RULE = "real_estate_and_mortgage_are_excluded_from_liquid_capital"
IIS_RESULT_RULE = "only_received_tax_benefits_are_added_to_actual_result"
DIVIDEND_COMPONENT_SOURCE = "actual_closed_month_dividend_average_annualized"
DEPOSIT_PROJECTION_METHOD = "persisted_monthly_estimate_times_12_plus_expected_interest"
MONTHLY_SUMMARY_VERSION = "v2"
ISIN_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}

_SOURCE_KIND = {
    "manual": ("manual", None),
    "excel_migration": ("migration", None),
    "alfa_pdf": ("statement", "alfa_statement"),
    "t_invest": ("provider", "t_invest"),
    "moex": ("backend_derived", None),
    "alfa_pro": ("provider", "alfa_pro"),
    "alfa_statement": ("statement", "alfa_statement"),
}

_MONTH_SOURCE = {
    "manual": "manual",
    "excel_migration": "excel_migration",
    "alfa_pdf": "alfa_statement",
}

_PROVIDER_ENUM = {None, "t_invest", "alfa_pro", "alfa_statement"}


class NoReportingHistoryError(LookupError):
    """No reporting month exists to assemble a full-history bundle."""


class AiAnalysisBundleUnavailableError(NoReportingHistoryError):
    """Backward-compatible alias for empty history."""


class AiAnalysisBundleValidationError(ValueError):
    """Generated bundle failed the declared schema before download."""


def _schema_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "ai_analysis_bundle.schema.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("ai_analysis_bundle.schema.json was not found next to the repository")


def _schema() -> dict[str, object]:
    return json.loads(_schema_path().read_text(encoding="utf-8"))


def validate_bundle(bundle: dict[str, object]) -> None:
    try:
        Draft202012Validator(_schema(), format_checker=FormatChecker()).validate(bundle)
    except ValidationError as error:
        raise AiAnalysisBundleValidationError(
            "generated AI analysis bundle failed schema validation"
        ) from error


def canonical_json(bundle: dict[str, object]) -> str:
    return json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"


def bundle_filename(*, as_of_date: date, media: str) -> str:
    extension = "md" if media == "markdown" else "json"
    return f"hermes-ai-analysis-bundle-{as_of_date.isoformat()}-v{SCHEMA_VERSION}.{extension}"


def _money(kopecks: int) -> dict[str, str]:
    return {"amount": RubleAmount(kopecks).to_api(), "currency": "RUB"}


def _metric(
    kopecks: int | None,
    *,
    source: str,
    precision: str = "exact",
    reason_codes: list[str] | tuple[str, ...] = (),
    available: bool | None = None,
) -> dict[str, object]:
    codes = sorted(set(reason_codes))
    if available is False or kopecks is None:
        return {
            "value": None,
            "availability": "unavailable",
            "precision": "unknown",
            "source": source,
            "reason_codes": codes,
        }
    return {
        "value": _money(kopecks),
        "availability": "available",
        "precision": precision,
        "source": source,
        "reason_codes": codes,
    }


def _ratio(
    value: Decimal | None,
    *,
    reason_codes: list[str] | tuple[str, ...] = (),
    available: bool | None = None,
) -> dict[str, object]:
    codes = sorted(set(reason_codes))
    if available is False or value is None:
        return {
            "value_pct": None,
            "availability": "unavailable",
            "precision": "unknown",
            "source": "backend_derived",
            "reason_codes": codes,
        }
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
        if "." not in text:
            text = f"{text}.00"
        elif len(text.split(".")[1]) == 1:
            text = f"{text}0"
    else:
        text = f"{text}.00"
    return {
        "value_pct": text,
        "availability": "available",
        "precision": "exact",
        "source": "backend_derived",
        "reason_codes": codes,
    }


def _period(year: int, month: int) -> dict[str, int]:
    return {"year": year, "month": month}


def _slug(prefix: str, name: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "item"
    candidate = f"{prefix}-{base}"
    index = 2
    while candidate in used:
        candidate = f"{prefix}-{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _dt(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return (
        datetime(value.year, value.month, value.day, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    )


def _provenance(source: str | None, observed_at: datetime | date | None) -> dict[str, object]:
    kind, provider = _SOURCE_KIND.get(source or "manual", ("manual", None))
    if provider not in _PROVIDER_ENUM:
        provider = None
        kind = "manual"
    return {"source_kind": kind, "provider": provider, "observed_at": _dt(observed_at)}


def _coverage(status: str, *reasons: str) -> dict[str, object]:
    return {"status": status, "reason_codes": sorted(set(reasons))}


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(month=2, day=28, year=day.year + 1)


def _missing_periods(months: list[ReportingMonth]) -> list[dict[str, int]]:
    ordered = sorted(months, key=lambda item: (item.year, item.month))
    first = ordered[0]
    last = ordered[-1]
    have = {(item.year, item.month) for item in ordered}
    missing: list[dict[str, int]] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        if (year, month) not in have:
            missing.append(_period(year, month))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return missing


def _select_current(months: list[ReportingMonth]) -> tuple[ReportingMonth, str]:
    closed = [item for item in months if item.status == "closed"]
    if closed:
        current = max(closed, key=lambda item: (item.year, item.month, item.id))
        return current, "latest_closed"
    current = max(months, key=lambda item: (item.year, item.month, item.id))
    return current, "latest_available"


def _settings(session: Session) -> AppSettings | None:
    return session.scalar(select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID))


def _salary_tax_history_incomplete(session: Session, month: ReportingMonth) -> bool:
    if month.month == 1:
        return False
    context = get_salary_tax_year_context(session, month.year)
    first_required = context.effective_from_month if context is not None else 1
    known = set(
        session.scalars(
            select(ReportingMonth.month).where(
                ReportingMonth.year == month.year,
                ReportingMonth.month >= first_required,
                ReportingMonth.month < month.month,
                ReportingMonth.status == "closed",
            )
        )
    )
    return bool(set(range(first_required, month.month)) - {int(value) for value in known})


def assemble_ai_analysis_bundle(
    session: Session,
    *,
    generated_at: datetime | None = None,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> dict[str, object]:
    months = list_reporting_months(session)
    if not months:
        raise NoReportingHistoryError("no reporting months available")

    ordered_months = sorted(months, key=lambda item: (item.year, item.month, item.id))
    current, selection_reason = _select_current(ordered_months)
    settings = _settings(session)
    for year in sorted({item.year for item in ordered_months}):
        get_or_create_default_tax_brackets(session, year, commit=False)
    zone = ZoneInfo(settings.timezone if settings is not None else "Europe/Moscow")
    generated = generated_at or datetime.now(tz=zone)
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=zone)

    account_rows = sorted(
        list_accounts(session), key=lambda item: (item.name, item.account_type, item.id)
    )
    instrument_rows = sorted(
        list_instruments(session), key=lambda item: (item.name, item.instrument_type, item.id)
    )
    used_refs: set[str] = set()
    account_refs = {row.id: _slug("acct", row.name, used_refs) for row in account_rows}
    instrument_refs = {row.id: _slug("inst", row.name, used_refs) for row in instrument_rows}

    cash_type_account = next((row for row in account_rows if row.account_type == "cash"), None)
    if cash_type_account is None:
        synthetic_cash_ref = _slug("acct", "cash-balances", used_refs)
    else:
        synthetic_cash_ref = account_refs[cash_type_account.id]

    warnings: list[dict[str, str]] = []

    def add_warning(code: str, severity: str, scope: str, message: str) -> None:
        item = {"code": code, "severity": severity, "scope": scope, "message": message[:500]}
        if item not in warnings:
            warnings.append(item)

    add_warning(
        "authoritative_market_value_change_unavailable",
        "info",
        "reporting_history",
        "No accepted aggregate market-value-change service exists; liquid-capital changes are not substituted for it.",
    )
    add_warning(
        "cash_flow_adjusted_return_unavailable",
        "info",
        "reporting_history",
        "Cash-flow-adjusted investment return is unavailable; market value change must not be interpreted as investment return.",
    )

    history: list[dict[str, object]] = []
    previous_month: ReportingMonth | None = None
    for month in ordered_months:
        capital = liquid_capital_for_month(session, month.id)
        passive = passive_income_for_month(session, month.id)
        cash = cash_balance_for_month(session, month.id)
        equity = property_equity(session, month.id)
        point_warnings: list[str] = []
        coverage_reasons: list[str] = []
        draft_codes: list[str] = []
        if month.status == "draft":
            coverage_reasons.append("draft_month_incomplete")
            point_warnings.append("draft_month_incomplete")
            draft_codes.append("draft_value")
        if previous_month is not None:
            expected_year, expected_month = previous_month.year, previous_month.month + 1
            if expected_month == 13:
                expected_year += 1
                expected_month = 1
            if (month.year, month.month) != (expected_year, expected_month):
                coverage_reasons.append("previous_calendar_period_missing")
                point_warnings.append("previous_calendar_period_missing")
        previous_month = month
        provenance_sources = set()
        mapped = _MONTH_SOURCE.get(month.source)
        if mapped:
            provenance_sources.add(mapped)
        for snapshot in list_position_snapshots(session):
            if snapshot.reporting_month_id != month.id:
                continue
            if snapshot.price_source == "t_invest":
                provenance_sources.add("t_invest")
            elif snapshot.price_source == "alfa_pdf":
                provenance_sources.add("alfa_statement")
            elif snapshot.price_source == "manual":
                provenance_sources.add("manual")
        history.append(
            {
                "period": _period(month.year, month.month),
                "status": month.status,
                "snapshot_date": month.snapshot_date.isoformat(),
                "coverage": _coverage(
                    "partial" if coverage_reasons else "complete", *coverage_reasons
                ),
                "provenance_sources": sorted(provenance_sources),
                "kpis": {
                    "liquid_assets_total": _metric(
                        capital.total_assets.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "included_debts": _metric(
                        capital.total_debts_included.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "liquid_capital_net": _metric(
                        capital.liquid_capital_net.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "passive_income_actual": _metric(
                        passive.total_net_passive_income.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "passive_income_actual_breakdown": {
                        "deposit_interest": _metric(
                            passive.breakdown.deposit_interest.kopecks,
                            source="backend_derived",
                            reason_codes=draft_codes,
                        ),
                        "bond_coupons": _metric(
                            passive.breakdown.bond_coupons.kopecks,
                            source="backend_derived",
                            reason_codes=draft_codes,
                        ),
                        "dividends": _metric(
                            passive.breakdown.dividends.kopecks,
                            source="backend_derived",
                            reason_codes=draft_codes,
                        ),
                        "other_capital_income": _metric(
                            passive.breakdown.other_capital_income.kopecks,
                            source="backend_derived",
                            reason_codes=draft_codes,
                        ),
                    },
                    "active_income_net": _metric(
                        cash.breakdown.salary_net.kopecks
                        + cash.breakdown.bonus_net.kopecks
                        + cash.breakdown.side_income_net.kopecks
                        + cash.breakdown.other_income.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "mandatory_expenses": _metric(
                        cash.breakdown.mandatory_expenses.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "saving_allocations": _metric(
                        cash.breakdown.saving_allocations.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "monthly_cash_balance": _metric(
                        cash.total.kopecks,
                        source="backend_derived",
                        reason_codes=draft_codes,
                    ),
                    "property_equity": _metric(
                        equity.kopecks, source="backend_derived", reason_codes=draft_codes
                    ),
                    "market_value_change": _metric(
                        None,
                        source="backend_derived",
                        reason_codes=["authoritative_market_value_change_unavailable"],
                    ),
                    "investment_return": _ratio(
                        None,
                        reason_codes=["cash_flow_adjusted_return_unavailable"],
                    ),
                },
                "warning_codes": sorted(set(point_warnings)),
            }
        )

    average = passive_income_average(session)
    average_reasons: list[str] = []
    if not average.is_complete_12m:
        average_reasons.append("incomplete_12_month_window")
        add_warning(
            "incomplete_12_month_window",
            "warning",
            "passive_income",
            "Fewer than 12 eligible closed months are available for the rolling actual average.",
        )
    start_tuple = parse_passive_income_history_start_month(
        settings.passive_income_history_start_month if settings is not None else None
    )
    if start_tuple is None and ordered_months:
        start_period = _period(ordered_months[0].year, ordered_months[0].month)
    elif start_tuple is None:
        start_period = _period(current.year, current.month)
    else:
        start_period = _period(start_tuple[0], start_tuple[1])
    periods_used = [_period(item.year, item.month) for item in average.months]
    rolling = {
        "value": _metric(
            average.average.kopecks if average.count_months else None,
            source="backend_derived",
            reason_codes=average_reasons,
            available=average.count_months > 0,
        ),
        "eligible_month_count": average.count_months,
        "target_window_months": 12,
        "is_complete_window": average.is_complete_12m,
        "history_start_period": start_period,
        "periods_used": periods_used,
        "source": "eligible_closed_reporting_months",
    }

    forecast = forecast_passive_income(session, current.id, forecast_version)
    forecast_reasons = []
    deposit_method = DEPOSIT_PROJECTION_METHOD
    if forecast.is_approximate:
        forecast_reasons.append("deposit_projection_approximate")
        add_warning(
            "deposit_projection_approximate",
            "info",
            "passive_income",
            "Deposit forecast annualises persisted monthly estimates; maturity and rate changes are not modelled.",
        )
    if not average.is_complete_12m:
        forecast_reasons.append("incomplete_dividend_history")
    breakdown = forecast.breakdown
    forecast_block = {
        "forecast_version": forecast_version,
        "as_of_date": current.snapshot_date.isoformat(),
        "annual_total": _metric(
            forecast.annual_total.kopecks,
            source="backend_derived",
            precision="approximate" if forecast.is_approximate else "exact",
            reason_codes=forecast_reasons,
        ),
        "monthly_total": _metric(
            forecast.monthly_total.kopecks,
            source="backend_derived",
            precision="approximate" if forecast.is_approximate else "exact",
            reason_codes=forecast_reasons,
        ),
        "breakdown": {
            "expected_deposit_interest": _metric(
                breakdown.expected_deposit_interest.kopecks,
                source="backend_derived",
                precision="approximate",
                reason_codes=["deposit_projection_approximate"],
            ),
            "expected_coupon_component": _metric(
                breakdown.expected_coupon_net.kopecks, source="backend_derived"
            ),
            "expected_dividend_component": _metric(
                breakdown.expected_dividend_component.kopecks,
                source="backend_derived",
                precision="approximate",
                reason_codes=["incomplete_dividend_history"] if not average.is_complete_12m else (),
            ),
            "other_expected_capital_income": _metric(
                breakdown.other_expected_capital_income.kopecks, source="backend_derived"
            ),
        },
        "dividend_component_source": DIVIDEND_COMPONENT_SOURCE,
        "deposit_projection_method": deposit_method,
        "warning_codes": sorted(set(forecast_reasons)),
    }

    quote_by_snapshot = {
        row.position_snapshot_id: row
        for row in session.scalars(select(PositionQuoteProvenance)).all()
    }
    selected_positions = [
        row for row in list_position_snapshots(session) if row.reporting_month_id == current.id
    ]
    selected_deposits = [
        row for row in list_deposit_snapshots(session) if row.reporting_month_id == current.id
    ]
    selected_cash = [
        row for row in list_cash_balances(session) if row.reporting_month_id == current.id
    ]

    accounts_out = [
        {
            "ref": account_refs[row.id],
            "name": row.name,
            "account_type": row.account_type,
            "status": row.status,
            "include_in_capital": row.include_in_capital,
            "include_in_returns": row.include_in_returns,
        }
        for row in account_rows
    ]
    if cash_type_account is None and selected_cash:
        accounts_out.append(
            {
                "ref": synthetic_cash_ref,
                "name": "Cash balances",
                "account_type": "cash",
                "status": "active",
                "include_in_capital": True,
                "include_in_returns": False,
            }
        )
    accounts_out.sort(key=lambda item: item["ref"])

    instruments_out = [
        {
            "ref": instrument_refs[row.id],
            "name": row.name,
            "instrument_type": row.instrument_type,
            "isin": (
                row.isin
                if row.isin and ISIN_PATTERN.fullmatch(row.isin)
                else None
            ),
            "ticker": row.ticker,
            "currency": "RUB",
        }
        for row in instrument_rows
    ]
    instruments_out.sort(key=lambda item: item["ref"])

    positions_out = []
    for row in sorted(
        selected_positions, key=lambda item: (item.account_id, item.instrument_id, item.id)
    ):
        quote = quote_by_snapshot.get(row.id)
        if quote is not None and quote.provider in _PROVIDER_ENUM:
            valuation = {
                "source_kind": "provider",
                "provider": quote.provider,
                "observed_at": _dt(quote.applied_at_utc),
            }
            if quote.freshness == "stale":
                add_warning(
                    "stale_quote",
                    "warning",
                    "current_portfolio",
                    "At least one position quote is marked stale; persisted valuation remains authoritative.",
                )
        else:
            valuation = _provenance(row.price_source, row.updated_at)
        quantity = format(row.quantity, "f").rstrip("0").rstrip(".")
        if quantity in {"", "-"}:
            quantity = "0"
        positions_out.append(
            {
                "account_ref": account_refs[row.account_id],
                "instrument_ref": instrument_refs[row.instrument_id],
                "quantity": quantity,
                "market_price_per_unit": _metric(
                    row.market_price_per_unit_kopecks, source="persisted_snapshot"
                ),
                "market_value": _metric(row.market_value_kopecks, source="persisted_snapshot"),
                "cost_basis": _metric(row.cost_basis_kopecks, source="persisted_snapshot"),
                "unrealized_result": _metric(
                    row.unrealized_result_kopecks, source="persisted_snapshot"
                ),
                "accrued_interest": _metric(
                    int(row.accrued_interest_kopecks or 0), source="persisted_snapshot"
                ),
                "price_date": row.price_date.isoformat(),
                "valuation_provenance": valuation,
            }
        )
    positions_out.sort(key=lambda item: (item["account_ref"], item["instrument_ref"]))

    deposits_out = []
    for row in sorted(selected_deposits, key=lambda item: (item.account_id, item.name, item.id)):
        deposits_out.append(
            {
                "account_ref": account_refs[row.account_id],
                "name": row.name,
                "deposit_type": row.deposit_type,
                "balance": _metric(row.balance_kopecks, source="persisted_snapshot"),
                "annual_rate_pct": PercentageRate(row.annual_rate_basis_points).to_api(),
                "expected_monthly_interest": _metric(
                    row.expected_monthly_interest_kopecks,
                    source="persisted_snapshot",
                    precision="approximate",
                    reason_codes=["maturity_not_modelled"],
                ),
                "actual_interest_received": _metric(
                    row.actual_interest_received_kopecks, source="persisted_actual"
                ),
                "provenance": _provenance("manual", row.updated_at),
            }
        )
    deposits_out.sort(key=lambda item: (item["account_ref"], item["name"]))

    cash_out = []
    for row in sorted(selected_cash, key=lambda item: (item.name, item.id)):
        cash_out.append(
            {
                "account_ref": (
                    account_refs[cash_type_account.id]
                    if cash_type_account is not None
                    else synthetic_cash_ref
                ),
                "name": row.name,
                "amount": _metric(row.amount_kopecks, source="persisted_snapshot"),
                "include_in_capital": row.include_in_capital,
                "provenance": _provenance("manual", current.updated_at),
            }
        )
    cash_out.sort(key=lambda item: (item["account_ref"], item["name"]))

    portfolio_coverage = _coverage("complete")
    if selection_reason == "latest_available" and current.status == "draft":
        portfolio_coverage = _coverage("partial", "draft_value")

    current_portfolio = {
        "reporting_period": _period(current.year, current.month),
        "snapshot_date": current.snapshot_date.isoformat(),
        "reporting_status": current.status,
        "selection_reason": selection_reason,
        "coverage": portfolio_coverage,
        "accounts": accounts_out,
        "instruments": instruments_out,
        "positions": positions_out,
        "deposits": deposits_out,
        "cash_balances": cash_out,
    }

    goal_items = build_goal_achievement_summary(session, current.id, include_inactive=True)
    goals_out = []
    for item in sorted(goal_items, key=lambda entry: (entry.goal.name, entry.goal.id)):
        forecast_item = item.achievement_forecast
        codes = []
        if average.count_months < 12 and item.goal.goal_type == "passive_income":
            codes.append("incomplete_12_month_window")
        if forecast_item.status == "not_projectable":
            codes.append("no_trajectory_model")
        source_path = (
            "passive_income.rolling_actual_average.value"
            if item.goal.goal_type == "passive_income"
            else "reporting_history[].kpis.liquid_capital_net"
        )
        status_map = {
            "achieved": "achieved",
            "not_projectable": "not_projectable",
            "inactive": "inactive",
            "unsupported": "unsupported",
        }
        goals_out.append(
            {
                "ref": _slug("goal", item.goal.name, used_refs),
                "name": item.goal.name,
                "goal_type": item.goal.goal_type,
                "is_primary": item.goal.is_main,
                "target": _metric(item.goal.target_value_kopecks, source="persisted_configuration"),
                "current_value": _metric(
                    forecast_item.current_value.kopecks if forecast_item.current_value else None,
                    source="backend_derived",
                    reason_codes=codes,
                    available=forecast_item.current_value is not None,
                ),
                "gap": _metric(
                    forecast_item.remaining_amount.kopecks
                    if forecast_item.remaining_amount is not None
                    else None,
                    source="backend_derived",
                    available=forecast_item.remaining_amount is not None,
                ),
                "progress": _ratio(
                    forecast_item.progress_pct,
                    reason_codes=codes if forecast_item.progress_pct is None else (),
                    available=forecast_item.progress_pct is not None,
                ),
                "projection_status": status_map.get(forecast_item.status, "not_projectable"),
                "estimated_achievement_date": (
                    forecast_item.estimated_achievement_date.isoformat()
                    if forecast_item.estimated_achievement_date is not None
                    else None
                ),
                "method_version": forecast_item.method_version or GOAL_ACHIEVEMENT_METHOD_VERSION,
                "source_metric_path": source_path,
                "warning_codes": sorted(set(codes)),
            }
        )
    goals_out.sort(key=lambda item: item["ref"])

    included = total_included_debts(session, current.id)
    all_debts = total_debts(session, current.id)
    mortgage = total_mortgage_balance(session, current.id)
    property_value = total_property_value(session, current.id)
    equity = property_equity(session, current.id)
    coverage_pct, _gap = mortgage_coverage(
        session,
        current.id,
        capital_for := liquid_capital_for_month(session, current.id).liquid_capital_net,
    )
    payment_total = int(
        session.scalar(
            select(func.coalesce(func.sum(PropertySnapshot.monthly_payment_kopecks), 0)).where(
                PropertySnapshot.reporting_month_id == current.id
            )
        )
        or 0
    )
    excluded = RubleAmount(all_debts.kopecks - included.kopecks)
    debts_and_real_estate = {
        "reporting_period": _period(current.year, current.month),
        "debts": {
            "included_in_liquid_capital": _metric(included.kopecks, source="backend_derived"),
            "excluded_from_liquid_capital": _metric(
                excluded.kopecks,
                source="persisted_snapshot",
                reason_codes=["mortgage_is_reference_only"] if mortgage.kopecks else (),
            ),
        },
        "real_estate": {
            "estimated_value": _metric(property_value.kopecks, source="persisted_snapshot"),
            "mortgage_balance": _metric(mortgage.kopecks, source="persisted_snapshot"),
            "property_equity": _metric(equity.kopecks, source="backend_derived"),
            "monthly_payment": _metric(payment_total, source="persisted_snapshot"),
        },
        "mortgage_coverage": _ratio(
            coverage_pct,
            available=coverage_pct is not None,
            reason_codes=[] if coverage_pct is not None else ["no_mortgage"],
        ),
        "liquidity_rule": LIQUIDITY_RULE,
    }

    iis_accounts = []
    profiles = session.scalars(select(IisProfile).order_by(IisProfile.id)).all()
    for profile in profiles:
        result = iis_result(session, account_id=profile.account_id, reporting_month_id=current.id)
        contributions = session.scalars(
            select(IisContribution)
            .where(IisContribution.account_id == profile.account_id)
            .order_by(IisContribution.tax_year)
        ).all()
        benefits = {status: 0 for status in ("planned", "submitted", "received", "rejected")}
        for benefit in session.scalars(
            select(TaxBenefit).where(TaxBenefit.account_id == profile.account_id)
        ).all():
            benefits[benefit.status] = benefits.get(benefit.status, 0) + benefit.amount_kopecks
        iis_accounts.append(
            {
                "account_ref": account_refs[profile.account_id],
                "iis_type": profile.iis_type,
                "opened_at": profile.opened_at.isoformat(),
                "eligible_close_at": (
                    profile.eligible_close_at.isoformat() if profile.eligible_close_at else None
                ),
                "contributions_by_tax_year": [
                    {
                        "tax_year": row.tax_year,
                        "amount": _money(row.amount_kopecks),
                        "is_target_reached": row.is_target_reached,
                    }
                    for row in contributions
                ],
                "tax_benefits": {key: _money(value) for key, value in benefits.items()},
                "portfolio_result_without_tax_benefit": _metric(
                    result.portfolio_result_without_tax_benefit.kopecks, source="backend_derived"
                ),
                "portfolio_result_with_received_tax_benefit": _metric(
                    result.portfolio_result_with_tax_benefit.kopecks, source="backend_derived"
                ),
                "result_rule": IIS_RESULT_RULE,
            }
        )
    iis_accounts.sort(key=lambda item: item["account_ref"])

    salary_warning_codes: list[str] = []
    context = get_salary_tax_year_context(session, current.year)
    if _salary_tax_history_incomplete(session, current):
        salary_warning_codes = ["salary_tax_history_incomplete"]
        add_warning(
            "salary_tax_history_incomplete",
            "warning",
            "iis_and_tax",
            "Salary-tax YTD cannot be computed because prior months in the tax year are missing or not closed.",
        )
        salary_tax_context = {
            "tax_year": current.year,
            "history_coverage": _coverage("unavailable", "salary_tax_history_incomplete"),
            "opening_context_available": context is not None,
            "taxable_gross_ytd": _metric(
                None, source="backend_derived", reason_codes=["salary_tax_history_incomplete"]
            ),
            "current_marginal_rate_pct": _ratio(
                None, reason_codes=["salary_tax_history_incomplete"], available=False
            ),
            "warning_codes": ["salary_tax_history_incomplete"],
        }
    else:
        nested = session.begin_nested()
        try:
            get_or_create_default_tax_brackets(session, current.year, commit=False)
            tax = calculate_salary_tax(session, current.id)
        except SalaryTaxHistoryIncompleteError:
            nested.rollback()
            salary_warning_codes = ["salary_tax_history_incomplete"]
            add_warning(
                "salary_tax_history_incomplete",
                "warning",
                "iis_and_tax",
                "Salary-tax YTD cannot be computed because prior months in the tax year are missing or not closed.",
            )
            salary_tax_context = {
                "tax_year": current.year,
                "history_coverage": _coverage("unavailable", "salary_tax_history_incomplete"),
                "opening_context_available": context is not None,
                "taxable_gross_ytd": _metric(
                    None,
                    source="backend_derived",
                    reason_codes=["salary_tax_history_incomplete"],
                ),
                "current_marginal_rate_pct": _ratio(
                    None, reason_codes=["salary_tax_history_incomplete"], available=False
                ),
                "warning_codes": ["salary_tax_history_incomplete"],
            }
            tax = None
        else:
            nested.rollback()
        if not salary_warning_codes:
            ytd = 0
            if current.month != 1:
                if context is not None and current.month >= context.effective_from_month:
                    ytd += context.opening_taxable_gross_kopecks
            prior = session.execute(
                select(func.coalesce(func.sum(IncomeEntry.gross_amount_kopecks), 0))
                .select_from(ReportingMonth)
                .outerjoin(
                    IncomeEntry,
                    and_(
                        IncomeEntry.reporting_month_id == ReportingMonth.id,
                        IncomeEntry.income_type == IncomeType.SALARY.value,
                    ),
                )
                .where(
                    ReportingMonth.year == current.year,
                    ReportingMonth.month < current.month,
                    ReportingMonth.status == "closed",
                )
            ).scalar_one()
            ytd += int(prior or 0)
            payment = session.execute(
                select(func.coalesce(func.sum(IncomeEntry.gross_amount_kopecks), 0)).where(
                    IncomeEntry.reporting_month_id == current.id,
                    IncomeEntry.income_type == IncomeType.SALARY.value,
                )
            ).scalar_one()
            ytd += int(payment or 0)
            marginal = None
            if tax is not None:
                for part in tax.parts:
                    if part.taxable_kopecks > 0:
                        marginal = Decimal(part.rate_bps) / Decimal(100)
            salary_tax_context = {
                "tax_year": current.year,
                "history_coverage": _coverage("complete"),
                "opening_context_available": context is not None,
                "taxable_gross_ytd": _metric(ytd, source="backend_derived"),
                "current_marginal_rate_pct": _ratio(marginal, available=marginal is not None),
                "warning_codes": [],
            }

    calendar = merged_payout_calendar(
        session, reporting_month_id=current.id, forecast_version=forecast_version
    )
    window_start = current.snapshot_date
    window_end = _one_year_after(window_start)
    flow_items: list[dict[str, object]] = []
    flow_used: set[str] = set()
    principal_total = 0
    non_principal_total = 0
    calendar_provider_ids: set[int] = set()
    for bucket in calendar:
        for item in bucket.items:
            flow_items.append(
                _calendar_item(item, account_refs, instrument_refs, used_refs | flow_used)
            )
            flow_used.add(flow_items[-1]["event_ref"])
            if item.source_kind is PayoutCalendarSource.PROVIDER:
                calendar_provider_ids.add(item.source_id)
            if item.flow_type == "redemption":
                principal_total += item.expected_net_amount.kopecks
            else:
                non_principal_total += item.expected_net_amount.kopecks

    skipped_providers = list(
        session.scalars(
            select(AppliedProviderPayout).where(
                AppliedProviderPayout.reporting_month_id == current.id,
                AppliedProviderPayout.lifecycle == "active",
                AppliedProviderPayout.payment_date >= window_start,
                AppliedProviderPayout.payment_date < window_end,
            )
        )
    )
    unresolved_scopes: set[tuple[int, int, str]] = set()
    for payout in skipped_providers:
        if payout.id in calendar_provider_ids:
            continue
        reconciliation = session.scalar(
            select(AppliedPayoutReconciliation).where(
                AppliedPayoutReconciliation.applied_payout_id == payout.id
            )
        )
        if (
            reconciliation is not None
            and reconciliation.counting_decision == PayoutCountingDecision.COUNT_MANUAL.value
        ):
            continue
        unresolved_scopes.add((payout.account_id, payout.instrument_id, payout.event_kind))
    if unresolved_scopes:
        for item, source in zip(
            flow_items,
            [entry for bucket in calendar for entry in bucket.items],
            strict=False,
        ):
            if (
                source.source_kind is PayoutCalendarSource.MANUAL
                and (source.account_id, source.instrument_id, source.flow_type) in unresolved_scopes
            ):
                item["duplicate_resolution"] = "unresolved_manual_only"
    flow_items.sort(key=lambda item: (item["expected_date"], item["event_ref"]))

    payout_warnings: list[str] = []
    if any(item["duplicate_resolution"] == "unresolved_manual_only" for item in flow_items):
        payout_warnings.append("unresolved_provider_mapping")
        add_warning(
            "unresolved_provider_mapping",
            "warning",
            "upcoming_cash_flows",
            "An unresolved provider/manual duplicate uses the existing safe manual-only calendar behaviour.",
        )

    upcoming = {
        "window_start": window_start.isoformat(),
        "window_end_exclusive": window_end.isoformat(),
        "forecast_version": forecast_version,
        "non_principal_calendar_amount_total": _metric(
            non_principal_total, source="merged_payout_calendar"
        ),
        "principal_total": _metric(principal_total, source="merged_payout_calendar"),
        "calendar_total": _metric(
            non_principal_total + principal_total, source="merged_payout_calendar"
        ),
        "items": flow_items,
        "warning_codes": sorted(set(payout_warnings)),
    }

    missing = _missing_periods(ordered_months)
    if missing:
        add_warning(
            "reporting_history_gap",
            "warning",
            "coverage",
            "One or more calendar months between the first and last reporting period have no reporting month.",
        )

    closed_count = sum(1 for item in ordered_months if item.status == "closed")
    draft_count = sum(1 for item in ordered_months if item.status == "draft")
    domains = {
        "capital": _coverage("complete"),
        "passive_income": _coverage("partial" if average_reasons else "complete", *average_reasons),
        "salary_tax": _coverage(
            "unavailable" if salary_warning_codes else "complete", *salary_warning_codes
        ),
        "portfolio": portfolio_coverage,
        "payouts": _coverage("partial" if payout_warnings else "complete", *payout_warnings),
    }
    coverage = {
        "first_reporting_period": _period(ordered_months[0].year, ordered_months[0].month),
        "last_reporting_period": _period(ordered_months[-1].year, ordered_months[-1].month),
        "closed_month_count": closed_count,
        "draft_month_count": draft_count,
        "missing_calendar_periods": missing,
        "domains": domains,
    }

    warnings.sort(
        key=lambda item: (_SEVERITY_RANK.get(item["severity"], 9), item["code"], item["scope"])
    )

    bundle = {
        "$schema": SCHEMA_URI,
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "generated_at": generated.isoformat(),
            "as_of_date": current.snapshot_date.isoformat(),
            "base_currency": "RUB",
            "application": {"name": "Hermes Finance", "version": __version__},
            "generation_mode": "read_only",
            "calculation_versions": {
                "monthly_summary": MONTHLY_SUMMARY_VERSION,
                "passive_income_forecast": forecast_version,
                "goal_achievement": GOAL_ACHIEVEMENT_METHOD_VERSION,
            },
            "ordering_contract": ORDERING_CONTRACT,
        },
        "coverage": coverage,
        "reporting_history": history,
        "current_portfolio": current_portfolio,
        "passive_income": {
            "actual_history_metric_path": ACTUAL_HISTORY_METRIC_PATH,
            "rolling_actual_average": rolling,
            "forecast": forecast_block,
        },
        "goals": goals_out,
        "debts_and_real_estate": debts_and_real_estate,
        "iis_and_tax": {"iis_accounts": iis_accounts, "salary_tax_context": salary_tax_context},
        "upcoming_cash_flows": upcoming,
        "warnings": warnings,
    }
    validate_bundle(bundle)
    return bundle


def _calendar_item(
    item: MergedPayoutCalendarItem,
    account_refs: dict[int, str],
    instrument_refs: dict[int, str],
    used_refs: set[str],
) -> dict[str, object]:
    flow_type = item.flow_type
    if flow_type == "redemption":
        semantics = "principal"
        tax_status = "not_applicable"
        treatment = "excluded_principal"
        in_forecast = False
        reasons: list[str] = []
        approximate = item.is_approximate
    elif flow_type == "dividend":
        semantics = (
            "provider_announced_amount_tax_unknown"
            if item.source_kind == PayoutCalendarSource.PROVIDER
            else (
                "owner_expected_net"
                if item.expected_tax_amount is not None
                else "owner_expected_amount_tax_unknown"
            )
        )
        tax_status = "unknown" if "unknown" in semantics else "known_or_accounted"
        treatment = "represented_by_historical_component"
        in_forecast = False
        reasons = ["personal_tax_unknown"] if tax_status == "unknown" else []
        approximate = True if tax_status == "unknown" else item.is_approximate
    else:
        if item.source_kind == PayoutCalendarSource.PROVIDER:
            semantics = "provider_announced_amount_tax_unknown"
            tax_status = "unknown"
            reasons = ["personal_tax_unknown"]
            approximate = True
        elif item.expected_tax_amount is None:
            semantics = "owner_expected_amount_tax_unknown"
            tax_status = "unknown"
            reasons = ["personal_tax_unknown"]
            approximate = True
        else:
            semantics = "owner_expected_net"
            tax_status = "known_or_accounted"
            reasons = []
            approximate = item.is_approximate
        treatment = "included"
        in_forecast = True

    decision = item.counting_decision
    if decision == "count_manual":
        resolution = "count_manual"
    elif decision == "count_provider":
        resolution = "count_provider"
    elif decision == "keep_both":
        resolution = "keep_both"
    else:
        resolution = "none"

    provider = item.provider if item.provider in _PROVIDER_ENUM else None
    source_kind = "provider" if item.source_kind == PayoutCalendarSource.PROVIDER else "manual"
    if source_kind == "provider" and provider is None:
        source_kind = "manual"

    event_ref = _slug("flow", f"{item.expected_date.isoformat()}-{flow_type}", used_refs)
    return {
        "event_ref": event_ref,
        "expected_date": item.expected_date.isoformat(),
        "flow_type": flow_type,
        "account_ref": account_refs[item.account_id],
        "instrument_ref": instrument_refs.get(item.instrument_id) if item.instrument_id else None,
        "amount": _money(item.expected_net_amount.kopecks),
        "amount_semantics": semantics,
        "personal_tax_status": tax_status,
        "is_approximate": approximate,
        "reason_codes": sorted(set(reasons)),
        "provenance": {
            "source_kind": source_kind,
            "provider": provider,
            "observed_at": None,
        },
        "duplicate_resolution": resolution,
        "included_in_calendar_total": True,
        "included_in_passive_income_forecast": in_forecast,
        "forecast_treatment": treatment,
    }


def render_bundle_markdown(bundle: dict[str, object]) -> str:
    metadata = bundle["metadata"]
    coverage = bundle["coverage"]
    lines = [
        f"# Hermes Finance AI Analysis Bundle {bundle['schema_version']}",
        "",
        f"- generated_at: {metadata['generated_at']}",
        f"- as_of_date: {metadata['as_of_date']}",
        f"- generation_mode: {metadata['generation_mode']}",
        f"- application: {metadata['application']['name']} {metadata['application']['version']}",
        "",
        "## Coverage",
        "",
        f"- first: {coverage['first_reporting_period']['year']:04d}-{coverage['first_reporting_period']['month']:02d}",
        f"- last: {coverage['last_reporting_period']['year']:04d}-{coverage['last_reporting_period']['month']:02d}",
        f"- closed_month_count: {coverage['closed_month_count']}",
        f"- draft_month_count: {coverage['draft_month_count']}",
        f"- missing_calendar_periods: {len(coverage['missing_calendar_periods'])}",
        "",
        "## Warnings",
        "",
    ]
    for warning in bundle["warnings"]:
        lines.append(
            f"- `{warning['code']}` ({warning['severity']}, {warning['scope']}): {warning['message']}"
        )
    if not bundle["warnings"]:
        lines.append("- none")
    lines.append("")
    lines.append(
        "Canonical machine-readable artifact is the JSON bundle assembled from the same DTO."
    )
    lines.append("")
    return "\n".join(lines)
