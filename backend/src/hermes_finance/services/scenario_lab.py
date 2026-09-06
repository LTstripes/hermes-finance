"""Service adapter for Scenario Lab v1 (141-A equity + 141-B deposit rate).

Read-only, no provider/network/fx, no writes. The selected reporting month is
captured once into an immutable :class:`FrozenScenarioBase`; every semantic
calculation then operates on the frozen capture only — no later DB read may
affect base/stressed/impact/support/fingerprints/Goals/forecast/ladder.

Composes canonical read models and pure calculators:
- domain.liquid_capital.calculate_liquid_capital;
- domain.risk_allocation builders (base and stressed allocation);
- domain.deposits.calculate_deposit_expected_monthly_interest_kopecks
  (the single canonical deposit-interest calculator);
- domain.forecast_passive_income.calculate_forecast_passive_income
  (single passive-income forecast model);
- the frozen canonical R07-05 cash-flow ladder captured at base time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from hermes_finance.domain.deposits import (
    calculate_deposit_expected_monthly_interest_kopecks,
)
from hermes_finance.domain.forecast_passive_income import (
    ForecastPassiveIncomeInput,
    calculate_forecast_passive_income,
)
from hermes_finance.domain.goal_achievement import calculate_goal_achievement_forecast
from hermes_finance.domain.liquid_capital import (
    AccountAmount,
    LiquidCapitalInput,
    calculate_liquid_capital,
)
from hermes_finance.domain.risk_allocation import (
    RiskDepositInput,
    RiskPositionInput,
    RiskSupportStatus,
    build_account_allocation,
    build_asset_allocation,
    build_top_positions,
    percentage,
)
from hermes_finance.domain.scenario_frozen_base import (
    FrozenDeposit,
    FrozenLadderMonth,
    FrozenScenarioBase,
    FrozenUpcomingWindow,
)
from hermes_finance.domain.scenario_lab import (
    CALCULATION_VERSION,
    CONTRACT_VERSION,
    SHOCK_SCHEMA_VERSION,
    MetricSupportStatus,
    RowApplicability,
    canonical_drawdown_pct,
    canonical_rate_basis_points,
    classify_applicability,
    normalize_drawdown_pct,
    normalized_rate_string,
    parse_assumed_annual_rate_pct,
    parse_drawdown_pct,
    semantic_fingerprint_payload,
    stressed_market_value_kopecks,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.scenario_frozen_base import materialize_frozen_base

# ---- errors with machine-readable codes ----


class ScenarioLabError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ---- helpers ----


def _sorted_ids(values: list[int]) -> list[int]:
    return sorted(set(values))


def _money_api(kopecks: int) -> str:
    return format(Decimal(kopecks) / Decimal(100), ".2f")


def _money_signed(kopecks: int) -> str:
    if kopecks >= 0:
        return _money_api(kopecks)
    return "-" + _money_api(-kopecks)


def _base_fingerprint(frozen_payload: dict) -> str:
    canonical = json.dumps(
        frozen_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _money_pct(amount_kopecks: int, denominator_kopecks: int) -> str | None:
    value = percentage(amount_kopecks, denominator_kopecks)
    return format(value, ".2f") if value is not None else None


# ---- input validation ----


def _validate_shock_container(shock: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(shock, dict):
        raise ScenarioLabError("invalid_shock_input", "shock must be dict")
    keys = [k for k in shock.keys() if shock[k] is not None]
    if len(keys) != 1:
        raise ScenarioLabError("unsupported_composition_v1", "exactly one shock required")
    only = keys[0]
    if only not in {"equity_drawdown", "deposit_rate_assumption"}:
        raise ScenarioLabError("unsupported_shock_type_v1", f"unsupported shock {only}")
    payload = shock[only]
    if not isinstance(payload, dict):
        raise ScenarioLabError("invalid_shock_input", f"{only} must be dict")
    return only, payload


def _validate_equity_payload(payload: dict[str, Any]) -> None:
    if "drawdown_pct" not in payload:
        raise ScenarioLabError("invalid_drawdown_pct", "drawdown_pct required")
    extra = set(payload.keys()) - {"drawdown_pct"}
    if extra:
        raise ScenarioLabError("invalid_shock_input", f"unexpected fields {extra}")


def _parse_deposit_rate_input(
    payload: dict[str, Any],
) -> tuple[int, str, tuple[int, ...], bool]:
    """Validate deposit_rate_assumption payload.

    Returns ``(rate_basis_points, normalized_rate_string, target_deposit_ids,
    all_eligible)``. Raises ScenarioLabError with machine-readable codes.
    """
    allowed = {"assumed_annual_rate_pct", "all_eligible_deposits", "deposit_ids"}
    if "assumed_annual_rate_pct" not in payload:
        raise ScenarioLabError("invalid_assumed_rate_pct", "assumed_annual_rate_pct required")
    extra = set(payload.keys()) - allowed
    if extra:
        raise ScenarioLabError("invalid_shock_input", f"unexpected fields {extra}")

    raw_rate = payload["assumed_annual_rate_pct"]
    try:
        rate_pct = parse_assumed_annual_rate_pct(raw_rate)
        basis_points = canonical_rate_basis_points(rate_pct)
    except (TypeError, ValueError) as error:
        raise ScenarioLabError("invalid_assumed_rate_pct", str(error)) from error

    has_all = "all_eligible_deposits" in payload and payload["all_eligible_deposits"] is not None
    has_ids = "deposit_ids" in payload and payload["deposit_ids"] is not None

    if has_all and has_ids:
        raise ScenarioLabError(
            "invalid_target_selector", "supply exactly one of all_eligible_deposits or deposit_ids"
        )
    if not has_all and not has_ids:
        raise ScenarioLabError(
            "invalid_target_selector", "exactly one target selector must be supplied"
        )

    if has_all:
        if payload["all_eligible_deposits"] is not True:
            raise ScenarioLabError(
                "invalid_target_selector", "all_eligible_deposits must be true when supplied"
            )
        return basis_points, normalized_rate_string(basis_points), (), True

    raw_ids = payload["deposit_ids"]
    if not isinstance(raw_ids, list):
        raise ScenarioLabError("invalid_deposit_ids", "deposit_ids must be a list of integers")
    deposit_ids: list[int] = []
    for item in raw_ids:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ScenarioLabError(
                "invalid_deposit_ids", f"deposit_ids must contain integers, got {item!r}"
            )
        deposit_ids.append(item)
    if not deposit_ids:
        raise ScenarioLabError("invalid_deposit_ids", "deposit_ids must not be empty")
    unique = _sorted_ids(deposit_ids)
    return basis_points, normalized_rate_string(basis_points), tuple(unique), False


def _resolve_deposit_targets(
    frozen: FrozenScenarioBase,
    all_eligible: bool,
    requested_ids: tuple[int, ...],
) -> tuple[tuple[int, ...], dict[int, FrozenDeposit]]:
    """Resolve the normalized target set exactly once from the frozen base.

    Returns ``(sorted_deposit_ids, deposit_by_id)``. Explicit ids must all
    belong to the frozen month; anything else is rejected deterministically.
    """
    deposit_by_id = {deposit.id: deposit for deposit in frozen.deposits}
    if all_eligible:
        return tuple(sorted(deposit_by_id)), deposit_by_id
    missing = [deposit_id for deposit_id in requested_ids if deposit_id not in deposit_by_id]
    if missing:
        raise ScenarioLabError(
            "foreign_month_deposit_id",
            f"deposit_ids do not belong to the selected frozen reporting month: {missing}",
        )
    return tuple(sorted(requested_ids)), deposit_by_id


# ---- result DTO ----


@dataclass(frozen=True, slots=True)
class ScenarioLabEvaluation:
    contract_version: str
    calculation_version: str
    shock_schema_version: str
    reporting_month: dict
    base_fingerprint: str
    semantic_fingerprint: str
    normalized_shock_input: dict
    normalized_target_scope: dict
    assumptions: tuple[str, ...]
    base: dict
    stressed: dict
    impact: dict
    row_applicability: dict
    metric_support: dict
    coverage: dict
    affected_canonical_refs: dict
    generated_at: str | None
    warnings: tuple[str, ...] = ()
    presentation_metadata: dict | None = None


# ---- shared capital/allocation/goal engine ----


def _allocation_metric_to_dict(metric) -> dict:
    """Canonical R07-06A buckets to the scenario dict shape."""
    buckets = {item.key: item.amount.kopecks for item in metric.items}
    result: dict[str, Any] = {
        "cash_kopecks": buckets.get("cash", 0),
        "cash": _money_api(buckets.get("cash", 0)),
        "deposits_kopecks": buckets.get("deposits", 0),
        "deposits": _money_api(buckets.get("deposits", 0)),
        "unknown_asset_class_kopecks": buckets.get("unknown_asset_class", 0),
        "unknown_asset_class": _money_api(buckets.get("unknown_asset_class", 0)),
        "denominator_kopecks": metric.denominator.kopecks,
    }
    for key in ("stock", "bond", "fund", "currency", "gold", "other"):
        value = buckets.get(key, 0)
        result[f"{key}_kopecks"] = value
        result[key] = _money_api(value)
        share = next((item.share_pct for item in metric.items if item.key == key), None)
        result[f"{key}_share_pct"] = format(share, ".2f") if share is not None else None
    for key in ("cash", "deposits", "unknown_asset_class"):
        share = next((item.share_pct for item in metric.items if item.key == key), None)
        result[f"{key}_share_pct"] = format(share, ".2f") if share is not None else None
    return result


def _account_metric_to_list(metric) -> list[dict]:
    result = []
    for item in metric.items:
        if item.key == "unassigned_cash":
            result.append(
                {
                    "account_id": None,
                    "amount_kopecks": item.amount.kopecks,
                    "amount": _money_api(item.amount.kopecks),
                    "share_pct": format(item.share_pct, ".2f")
                    if item.share_pct is not None
                    else None,
                    "unassigned": True,
                }
            )
        else:
            result.append(
                {
                    "account_id": item.account_id,
                    "amount_kopecks": item.amount.kopecks,
                    "amount": _money_api(item.amount.kopecks),
                    "share_pct": format(item.share_pct, ".2f")
                    if item.share_pct is not None
                    else None,
                }
            )
    result.sort(key=lambda x: (-x["amount_kopecks"], str(x["account_id"])))
    return result


def _top_metric_to_list(metric, row_applicability: dict[str, str]) -> list[dict]:
    result = []
    for item in metric.items:
        result.append(
            {
                "position_id": item.position_id,
                "account_id": item.account_id,
                "instrument_id": item.instrument_id,
                "instrument_type": item.instrument_type,
                "amount_kopecks": item.amount.kopecks,
                "amount": _money_api(item.amount.kopecks),
                "share_pct": format(item.share_pct, ".2f") if item.share_pct is not None else None,
            }
        )
    result.sort(key=lambda x: (-x["amount_kopecks"], x["position_id"]))
    return result


def _capital_components(frozen: FrozenScenarioBase) -> dict[str, Any]:
    """Shared frozen capital inputs (cash/deposits/debts/securities)."""
    cash_total = sum(item.amount_kopecks for item in frozen.cash if item.include_in_capital)
    deposits_total = sum(
        item.balance_kopecks for item in frozen.deposits if item.include_in_capital
    )
    debts_total = sum(
        item.balance_kopecks for item in frozen.debts if item.include_in_liquid_capital
    )
    securities_base = sum(
        item.market_value_kopecks for item in frozen.positions if item.include_in_capital
    )
    deposit_accounts = tuple(
        AccountAmount(account_id=item.account_id, amount=RubleAmount(item.balance_kopecks))
        for item in frozen.deposits
        if item.include_in_capital
    )
    return {
        "cash_total": cash_total,
        "deposits_total": deposits_total,
        "debts_total": debts_total,
        "securities_base": securities_base,
        "deposit_accounts": deposit_accounts,
    }


def _risk_positions(
    frozen: FrozenScenarioBase, values: dict[int, int] | None = None
) -> tuple[RiskPositionInput, ...]:
    return tuple(
        RiskPositionInput(
            position_id=item.id,
            account_id=item.account_id,
            instrument_id=item.instrument_id,
            instrument_type=item.instrument_type,
            amount_kopecks=int((values or {}).get(item.id, item.market_value_kopecks)),
        )
        for item in frozen.positions
        if item.include_in_capital
    )


def _risk_deposits(frozen: FrozenScenarioBase) -> tuple[RiskDepositInput, ...]:
    return tuple(
        RiskDepositInput(account_id=item.account_id, amount_kopecks=int(item.balance_kopecks))
        for item in frozen.deposits
        if item.include_in_capital
    )


def _build_liquid_input(
    frozen: FrozenScenarioBase,
    components: dict[str, Any],
    securities_kopecks: int,
    securities_accounts: tuple[AccountAmount, ...],
) -> LiquidCapitalInput:
    return LiquidCapitalInput(
        cash=RubleAmount(components["cash_total"]),
        deposits=RubleAmount(components["deposits_total"]),
        securities=RubleAmount(securities_kopecks),
        included_debts=RubleAmount(components["debts_total"]),
        other_liquid_assets=RubleAmount(0),
        deposit_accounts=components["deposit_accounts"],
        securities_accounts=securities_accounts,
    )


def _goal_dict(calc, target_kopecks: int) -> dict:
    return {
        "goal_id": calc.goal_id,
        "target_kopecks": target_kopecks,
        "target": _money_api(target_kopecks),
        "current_kopecks": calc.current_value.kopecks if calc.current_value else None,
        "current": _money_api(calc.current_value.kopecks) if calc.current_value else None,
        "remaining_kopecks": calc.remaining_amount.kopecks if calc.remaining_amount else None,
        "remaining": _money_api(calc.remaining_amount.kopecks) if calc.remaining_amount else None,
        "progress_pct": format(calc.progress_pct, ".2f") if calc.progress_pct is not None else None,
        "status": calc.status,
    }


def _goals_for_liquid(frozen: FrozenScenarioBase, liquid_result) -> list[dict]:
    results = []
    for goal in frozen.capital_goals:
        calc = calculate_goal_achievement_forecast(
            goal_id=goal.id,
            reporting_month_id=frozen.reporting_month_id,
            as_of_date=frozen.snapshot_date,
            current_value=liquid_result.liquid_capital_net,
            target_value=RubleAmount(goal.target_kopecks),
            source_forecast_version=None,
        )
        results.append(_goal_dict(calc, goal.target_kopecks))
    return sorted(results, key=lambda item: item["goal_id"])


def _capital_metric_families(
    frozen: FrozenScenarioBase,
    *,
    stressed_values: dict[int, int],
    has_unknown: bool,
    row_applicability: dict[str, str],
    top_n: int,
) -> dict[str, Any]:
    """Compute base+stressed liquid/allocation/top/goals from frozen facts."""
    components = _capital_components(frozen)
    eligible_ids = [item.id for item in frozen.positions if item.include_in_capital]
    base_securities_accounts = tuple(
        AccountAmount(account_id=item.account_id, amount=RubleAmount(item.market_value_kopecks))
        for item in frozen.positions
        if item.include_in_capital
    )
    stressed_securities_accounts = tuple(
        AccountAmount(account_id=item.account_id, amount=RubleAmount(int(stressed_values[item.id])))
        for item in frozen.positions
        if item.include_in_capital
    )

    base_liquid = calculate_liquid_capital(
        _build_liquid_input(
            frozen, components, components["securities_base"], base_securities_accounts
        )
    )
    stressed_securities = sum(int(stressed_values[position_id]) for position_id in eligible_ids)
    stressed_liquid = calculate_liquid_capital(
        _build_liquid_input(frozen, components, stressed_securities, stressed_securities_accounts)
    )

    from hermes_finance.domain.risk_allocation import MetricSupport as RiskMetricSupport

    if has_unknown:
        asset_support = RiskMetricSupport(
            status=RiskSupportStatus.UNKNOWN, reason_codes=("instrument_type_not_authoritative",)
        )
        account_support = RiskMetricSupport(status=RiskSupportStatus.SUPPORTED)
    else:
        asset_support = RiskMetricSupport(status=RiskSupportStatus.SUPPORTED)
        account_support = RiskMetricSupport(status=RiskSupportStatus.SUPPORTED)

    base_positions = _risk_positions(frozen)
    stressed_positions = _risk_positions(frozen, stressed_values)
    deposits = _risk_deposits(frozen)

    base_asset_metric = build_asset_allocation(
        cash_kopecks=components["cash_total"],
        deposits=deposits,
        positions=base_positions,
        liquid_assets_kopecks=base_liquid.total_assets.kopecks,
        support=asset_support,
        excluded=(),
    )
    base_account_metric = build_account_allocation(
        cash_kopecks=components["cash_total"],
        deposits=deposits,
        positions=base_positions,
        liquid_assets_kopecks=base_liquid.total_assets.kopecks,
        support=account_support,
        excluded=(),
        account_names=None,
    )
    base_top_metric = build_top_positions(
        positions=base_positions,
        liquid_assets_kopecks=base_liquid.total_assets.kopecks,
        top_n=top_n,
        issues=(),
        account_names=None,
        instrument_names=None,
    )
    stressed_asset_metric = build_asset_allocation(
        cash_kopecks=components["cash_total"],
        deposits=deposits,
        positions=stressed_positions,
        liquid_assets_kopecks=stressed_liquid.total_assets.kopecks,
        support=asset_support,
        excluded=(),
    )
    stressed_account_metric = build_account_allocation(
        cash_kopecks=components["cash_total"],
        deposits=deposits,
        positions=stressed_positions,
        liquid_assets_kopecks=stressed_liquid.total_assets.kopecks,
        support=account_support,
        excluded=(),
        account_names=None,
    )
    stressed_top_metric = build_top_positions(
        positions=stressed_positions,
        liquid_assets_kopecks=stressed_liquid.total_assets.kopecks,
        top_n=top_n,
        issues=(),
        account_names=None,
        instrument_names=None,
    )

    base_asset = _allocation_metric_to_dict(base_asset_metric)
    stressed_asset = _allocation_metric_to_dict(stressed_asset_metric)

    return {
        "base_liquid": base_liquid,
        "stressed_liquid": stressed_liquid,
        "base_asset": base_asset,
        "stressed_asset": stressed_asset,
        "base_account": _account_metric_to_list(base_account_metric),
        "stressed_account": _account_metric_to_list(stressed_account_metric),
        "base_top": _top_metric_to_list(base_top_metric, row_applicability),
        "stressed_top": _top_metric_to_list(stressed_top_metric, row_applicability),
        "base_goals": _goals_for_liquid(frozen, base_liquid),
        "stressed_goals": _goals_for_liquid(frozen, stressed_liquid),
    }


def _base_stressed_metric_dicts(
    families: dict[str, Any], *, per_position: dict | None = None, extra: dict | None = None
) -> tuple[dict, dict]:
    base = {
        "liquid_assets_kopecks": families["base_liquid"].total_assets.kopecks,
        "liquid_assets": _money_api(families["base_liquid"].total_assets.kopecks),
        "liquid_capital_net_kopecks": families["base_liquid"].liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(families["base_liquid"].liquid_capital_net.kopecks),
        "debts_included_kopecks": families["base_liquid"].total_debts_included.kopecks,
        "debts_included": _money_api(families["base_liquid"].total_debts_included.kopecks),
        "asset_allocation": families["base_asset"],
        "account_allocation": families["base_account"],
        "top_positions": families["base_top"],
        "capital_goals": families["base_goals"],
    }
    stressed = {
        "liquid_assets_kopecks": families["stressed_liquid"].total_assets.kopecks,
        "liquid_assets": _money_api(families["stressed_liquid"].total_assets.kopecks),
        "liquid_capital_net_kopecks": families["stressed_liquid"].liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(families["stressed_liquid"].liquid_capital_net.kopecks),
        "debts_included_kopecks": families["stressed_liquid"].total_debts_included.kopecks,
        "debts_included": _money_api(families["stressed_liquid"].total_debts_included.kopecks),
        "asset_allocation": families["stressed_asset"],
        "account_allocation": families["stressed_account"],
        "top_positions": families["stressed_top"],
        "capital_goals": families["stressed_goals"],
    }
    if per_position is not None:
        base["per_position"] = per_position["base"]
        stressed["per_position"] = per_position["stressed"]
    if extra:
        for key in ("passive_income_effect", "future_cash_flow_rows_unchanged"):
            if key in extra:
                base[key] = extra[key]
                stressed[key] = extra[key]
    return base, stressed


# ---- fingerprint assembly helpers ----


def _strip_account_alloc(entries: list[dict]) -> list[dict]:
    return [
        {
            "account_id": entry["account_id"],
            "amount_kopecks": entry["amount_kopecks"],
            "share_pct": entry.get("share_pct"),
            "unassigned": entry.get("unassigned", False),
        }
        for entry in sorted(entries, key=lambda v: (str(v["account_id"]), v["amount_kopecks"]))
    ]


def _strip_top(entries: list[dict]) -> list[dict]:
    return [
        {
            "position_id": entry["position_id"],
            "account_id": entry["account_id"],
            "instrument_id": entry["instrument_id"],
            "instrument_type": entry["instrument_type"],
            "amount_kopecks": entry["amount_kopecks"],
            "share_pct": entry.get("share_pct"),
        }
        for entry in sorted(entries, key=lambda v: v["position_id"])
    ]


def _strip_goals(entries: list[dict]) -> list[dict]:
    return sorted(
        [
            {
                "goal_id": goal["goal_id"],
                "target_kopecks": goal["target_kopecks"],
                "current_kopecks": goal["current_kopecks"],
                "remaining_kopecks": goal["remaining_kopecks"],
                "progress_pct": goal["progress_pct"],
                "status": goal["status"],
            }
            for goal in entries
        ],
        key=lambda v: v["goal_id"],
    )


def _fingerprint_base_families(
    families: dict[str, Any],
    *,
    per_position_kopecks: dict[str, dict] | None = None,
    extra_families: dict | None = None,
) -> dict:
    payload = {
        "liquid_assets_kopecks": families["base_liquid"].total_assets.kopecks,
        "liquid_capital_net_kopecks": families["base_liquid"].liquid_capital_net.kopecks,
        "debts_included_kopecks": families["base_liquid"].total_debts_included.kopecks,
        "asset_allocation": {
            key: value
            for key, value in families["base_asset"].items()
            if key.endswith("_kopecks") or key.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(families["base_account"]),
        "top_positions": _strip_top(families["base_top"]),
        "capital_goals": _strip_goals(families["base_goals"]),
    }
    if per_position_kopecks is not None:
        payload["per_position"] = per_position_kopecks
    if extra_families:
        payload.update(extra_families)
    return payload


def _fingerprint_stressed_families(
    families: dict[str, Any],
    *,
    per_position_kopecks: dict[str, dict] | None = None,
    extra_families: dict | None = None,
) -> dict:
    payload = {
        "liquid_assets_kopecks": families["stressed_liquid"].total_assets.kopecks,
        "liquid_capital_net_kopecks": families["stressed_liquid"].liquid_capital_net.kopecks,
        "debts_included_kopecks": families["stressed_liquid"].total_debts_included.kopecks,
        "asset_allocation": {
            key: value
            for key, value in families["stressed_asset"].items()
            if key.endswith("_kopecks") or key.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(families["stressed_account"]),
        "top_positions": _strip_top(families["stressed_top"]),
        "capital_goals": _strip_goals(families["stressed_goals"]),
    }
    if per_position_kopecks is not None:
        payload["per_position"] = per_position_kopecks
    if extra_families:
        payload.update(extra_families)
    return payload


def _strip_deposit_rows(rows: dict[str, dict]) -> dict:
    return {
        key: {
            "deposit_id": row["deposit_id"],
            "account_id": row["account_id"],
            "deposit_type": row["deposit_type"],
            "balance_kopecks": row["balance_kopecks"],
            "annual_rate_basis_points": row["annual_rate_basis_points"],
            "expected_monthly_interest_kopecks": row["expected_monthly_interest_kopecks"],
        }
        for key, row in sorted(rows.items(), key=lambda kv: int(kv[0]))
    }


def _ladder_month_dict(month: FrozenLadderMonth) -> dict:
    return {
        "year": month.year,
        "month": month.month,
        "coupon_kopecks": month.coupon_kopecks,
        "coupon": _money_api(month.coupon_kopecks),
        "dividend_kopecks": month.dividend_kopecks,
        "dividend": _money_api(month.dividend_kopecks),
        "deposit_interest_kopecks": month.deposit_interest_kopecks,
        "deposit_interest": _money_api(month.deposit_interest_kopecks),
        "other_capital_income_kopecks": month.other_capital_income_kopecks,
        "other_capital_income": _money_api(month.other_capital_income_kopecks),
        "redemption_principal_kopecks": month.redemption_principal_kopecks,
        "redemption_principal": _money_api(month.redemption_principal_kopecks),
        "passive_income_kopecks": month.passive_income_kopecks,
        "passive_income": _money_api(month.passive_income_kopecks),
        "total_cash_flow_kopecks": month.total_cash_flow_kopecks,
        "total_cash_flow": _money_api(month.total_cash_flow_kopecks),
        "is_approximate": month.is_approximate,
    }


def _window_dict(window: FrozenUpcomingWindow) -> dict:
    return {
        "days": window.days,
        "from_date": window.from_date.isoformat(),
        "to_date": window.to_date.isoformat(),
        "passive_income_kopecks": window.passive_income_kopecks,
        "passive_income": _money_api(window.passive_income_kopecks),
        "redemption_principal_kopecks": window.redemption_principal_kopecks,
        "redemption_principal": _money_api(window.redemption_principal_kopecks),
        "total_cash_flow_kopecks": window.total_cash_flow_kopecks,
        "total_cash_flow": _money_api(window.total_cash_flow_kopecks),
        "events": [
            {
                "expected_date": event.expected_date.isoformat(),
                "flow_type": event.flow_type,
                "component": event.component,
                "account_id": event.account_id,
                "instrument_id": event.instrument_id,
                "expected_net_amount_kopecks": event.expected_net_amount_kopecks,
                "is_approximate": event.is_approximate,
                "source_kind": event.source_kind,
                "source_id": event.source_id,
            }
            for event in window.events
        ],
    }


def _window_fingerprint(window: FrozenUpcomingWindow) -> dict:
    return {
        "passive_income_kopecks": window.passive_income_kopecks,
        "redemption_principal_kopecks": window.redemption_principal_kopecks,
        "total_cash_flow_kopecks": window.total_cash_flow_kopecks,
        "events": [
            {
                "expected_date": event.expected_date.isoformat(),
                "flow_type": event.flow_type,
                "component": event.component,
                "expected_net_amount_kopecks": event.expected_net_amount_kopecks,
            }
            for event in window.events
        ],
    }


def _ladder_fingerprint(frozen: FrozenScenarioBase) -> dict:
    return {
        "months": [
            {
                "year": month.year,
                "month": month.month,
                "coupon_kopecks": month.coupon_kopecks,
                "dividend_kopecks": month.dividend_kopecks,
                "deposit_interest_kopecks": month.deposit_interest_kopecks,
                "other_capital_income_kopecks": month.other_capital_income_kopecks,
                "redemption_principal_kopecks": month.redemption_principal_kopecks,
                "passive_income_kopecks": month.passive_income_kopecks,
                "total_cash_flow_kopecks": month.total_cash_flow_kopecks,
                "is_approximate": month.is_approximate,
            }
            for month in frozen.ladder.months
        ],
        "upcoming_14_days": _window_fingerprint(frozen.ladder.upcoming_14_days),
        "upcoming_30_days": _window_fingerprint(frozen.ladder.upcoming_30_days),
    }


def _ladder_dict_fingerprint(ladder_dict: dict, frozen: FrozenScenarioBase) -> dict:
    """Fingerprint of a projected ladder dict + frozen upcoming windows."""
    return {
        "months": [
            {
                "year": month["year"],
                "month": month["month"],
                "coupon_kopecks": month["coupon_kopecks"],
                "dividend_kopecks": month["dividend_kopecks"],
                "deposit_interest_kopecks": month["deposit_interest_kopecks"],
                "other_capital_income_kopecks": month["other_capital_income_kopecks"],
                "redemption_principal_kopecks": month["redemption_principal_kopecks"],
                "passive_income_kopecks": month["passive_income_kopecks"],
                "total_cash_flow_kopecks": month["total_cash_flow_kopecks"],
                "is_approximate": month["is_approximate"],
            }
            for month in ladder_dict["months"]
        ],
        "upcoming_14_days": _window_fingerprint(frozen.ladder.upcoming_14_days),
        "upcoming_30_days": _window_fingerprint(frozen.ladder.upcoming_30_days),
    }


# ---- equity_drawdown evaluation ----


def _evaluate_equity(
    session: Session,
    reporting_month_id: int,
    payload: dict[str, Any],
    *,
    top_n: int,
    generated_at: datetime | None,
) -> ScenarioLabEvaluation:
    _validate_equity_payload(payload)
    raw_pct = parse_drawdown_pct(payload["drawdown_pct"])
    canonical_pct = canonical_drawdown_pct(raw_pct)
    pct_str = normalize_drawdown_pct(canonical_pct)

    frozen = materialize_frozen_base(session, reporting_month_id)
    position_rows = tuple(sorted(frozen.positions, key=lambda item: item.id))
    eligible_ids = _sorted_ids([item.id for item in position_rows if item.include_in_capital])
    capital_deposit_ids = _sorted_ids(
        [item.id for item in frozen.deposits if item.include_in_capital]
    )

    normalized_target_scope = {
        "selector": "all_eligible",
        "eligible_position_ids": eligible_ids,
        "eligible_deposit_ids": capital_deposit_ids,
    }

    row_applicability: dict[str, str] = {}
    base_per_position: dict[str, dict] = {}
    stressed_per_position: dict[str, dict] = {}
    impact_per_position: dict[str, dict] = {}
    stressed_values: dict[int, int] = {}
    coverage_applied = 0
    coverage_not = 0
    coverage_unknown = 0
    known_scope_delta = 0

    for position in position_rows:
        position_id = position.id
        include_in_capital = bool(position.include_in_capital)
        base_value = int(position.market_value_kopecks)
        if not include_in_capital:
            stressed_values[position_id] = base_value
            continue
        applicability = classify_applicability(position.instrument_type)
        row_applicability[str(position_id)] = applicability.value
        if applicability == RowApplicability.APPLIED:
            stressed_value = stressed_market_value_kopecks(base_value, canonical_pct)
            delta = stressed_value - base_value
            coverage_applied += 1
            known_scope_delta += delta
        elif applicability == RowApplicability.UNKNOWN:
            stressed_value = base_value
            delta = 0
            coverage_unknown += 1
        else:
            stressed_value = base_value
            delta = 0
            coverage_not += 1
        stressed_values[position_id] = stressed_value
        base_per_position[str(position_id)] = {
            "market_value_kopecks": base_value,
            "market_value": _money_api(base_value),
            "account_id": position.account_id,
            "instrument_id": position.instrument_id,
            "instrument_type": position.instrument_type,
            "include_in_capital": include_in_capital,
        }
        stressed_per_position[str(position_id)] = {
            "market_value_kopecks": stressed_value,
            "market_value": _money_api(stressed_value),
            "account_id": position.account_id,
            "instrument_id": position.instrument_id,
            "instrument_type": position.instrument_type,
            "include_in_capital": include_in_capital,
        }
        impact_per_position[str(position_id)] = {
            "delta_kopecks": delta,
            "delta": _money_signed(delta),
            "applicability": applicability.value,
        }

    coverage = {
        "total_positions": len(eligible_ids),
        "eligible_positions": len(eligible_ids),
        "applied": coverage_applied,
        "not_applicable": coverage_not,
        "unknown": coverage_unknown,
        "known_scope_impact_kopecks": known_scope_delta,
        "known_scope_impact": _money_signed(known_scope_delta),
    }

    has_unknown = coverage_unknown > 0
    families = _capital_metric_families(
        frozen,
        stressed_values=stressed_values,
        has_unknown=has_unknown,
        row_applicability=row_applicability,
        top_n=top_n,
    )
    per_position = {
        "base": {
            key: value
            for key, value in sorted(base_per_position.items(), key=lambda kv: int(kv[0]))
        },
        "stressed": {
            key: value
            for key, value in sorted(stressed_per_position.items(), key=lambda kv: int(kv[0]))
        },
    }
    extra = {
        "passive_income_effect": {
            "status": "unavailable",
            "reason": "no_deterministic_income_relationship",
        },
        "future_cash_flow_rows_unchanged": True,
    }
    base_metrics, stressed_metrics = _base_stressed_metric_dicts(
        families, per_position=per_position, extra=extra
    )

    impact = {
        "liquid_assets_delta_kopecks": (
            stressed_metrics["liquid_assets_kopecks"] - base_metrics["liquid_assets_kopecks"]
        ),
        "liquid_assets_delta": _money_signed(
            stressed_metrics["liquid_assets_kopecks"] - base_metrics["liquid_assets_kopecks"]
        ),
        "liquid_capital_net_delta_kopecks": (
            stressed_metrics["liquid_capital_net_kopecks"]
            - base_metrics["liquid_capital_net_kopecks"]
        ),
        "liquid_capital_net_delta": _money_signed(
            stressed_metrics["liquid_capital_net_kopecks"]
            - base_metrics["liquid_capital_net_kopecks"]
        ),
        "known_scope_impact_kopecks": known_scope_delta,
        "known_scope_impact": _money_signed(known_scope_delta),
        "per_position": {
            key: value
            for key, value in sorted(impact_per_position.items(), key=lambda kv: int(kv[0]))
        },
    }

    if has_unknown:
        aggregate_status = MetricSupportStatus.UNKNOWN
        aggregate_reason = ["instrument_type_not_authoritative"]
    else:
        aggregate_status = MetricSupportStatus.SUPPORTED
        aggregate_reason = []
    metric_support = {
        "liquid_assets": {"status": aggregate_status.value, "reason_codes": aggregate_reason},
        "liquid_capital_net": {"status": aggregate_status.value, "reason_codes": aggregate_reason},
        "asset_allocation": {"status": aggregate_status.value, "reason_codes": aggregate_reason},
        "account_allocation": {"status": aggregate_status.value, "reason_codes": aggregate_reason},
        "top_positions": {"status": aggregate_status.value, "reason_codes": aggregate_reason},
        "capital_goals": {"status": aggregate_status.value, "reason_codes": aggregate_reason},
        "per_position": {"status": "supported", "reason_codes": []},
        "passive_income_effect": {
            "status": "unavailable",
            "reason_codes": ["no_deterministic_income_relationship"],
        },
        "dividends": {"status": "supported", "reason_codes": []},
        "coupons": {"status": "supported", "reason_codes": []},
        "redemption": {"status": "supported", "reason_codes": []},
        "future_cash_flows": {"status": "supported", "reason_codes": []},
        "debts": {"status": "supported", "reason_codes": []},
    }

    assumptions = (
        "dividends_unchanged",
        "coupons_unchanged",
        "deposit_income_unchanged",
        "future_cash_flow_rows_unchanged",
        "no_fund_lookthrough",
        "no_fx",
        "no_probabilistic_forecast",
        "redemption_unchanged",
    )

    involved_account_ids = _sorted_ids(
        [item.account_id for item in position_rows] + [item.account_id for item in frozen.deposits]
    )
    account_names = dict(
        (account_id, name)
        for account_id, name in frozen.account_names
        if account_id in set(involved_account_ids)
    )
    instrument_names = dict(
        (instrument_id, name)
        for instrument_id, name in frozen.instrument_names
        if instrument_id in {item.instrument_id for item in position_rows}
    )
    affected_refs = {
        "reporting_month_id": reporting_month_id,
        "position_ids": _sorted_ids([item.id for item in position_rows]),
        "account_ids": involved_account_ids,
        "instrument_ids": _sorted_ids([item.instrument_id for item in position_rows]),
        "deposit_ids": capital_deposit_ids,
        "cash_ids": _sorted_ids([item.id for item in frozen.cash]),
    }

    reporting_month_dict = {
        "id": frozen.reporting_month_id,
        "year": frozen.year,
        "month": frozen.month,
        "snapshot_date": frozen.snapshot_date.isoformat(),
        "status": frozen.status,
    }
    normalized_shock = {"shock_type": "equity_drawdown", "drawdown_pct": pct_str}

    semantic_fingerprint = semantic_fingerprint_payload(
        contract_version=CONTRACT_VERSION,
        calculation_version=CALCULATION_VERSION,
        shock_schema_version=SHOCK_SCHEMA_VERSION,
        reporting_month=reporting_month_dict,
        base_fingerprint=frozen.base_fingerprint,
        normalized_shock=normalized_shock,
        normalized_target_scope=normalized_target_scope,
        assumptions=list(assumptions),
        base=_fingerprint_base_families(
            families,
            per_position_kopecks={
                key: {"market_value_kopecks": value["market_value_kopecks"]}
                for key, value in sorted(base_per_position.items(), key=lambda kv: int(kv[0]))
            },
            extra_families={
                "passive_income_effect": extra["passive_income_effect"],
            },
        ),
        stressed=_fingerprint_stressed_families(
            families,
            per_position_kopecks={
                key: {"market_value_kopecks": value["market_value_kopecks"]}
                for key, value in sorted(stressed_per_position.items(), key=lambda kv: int(kv[0]))
            },
            extra_families={
                "passive_income_effect": extra["passive_income_effect"],
            },
        ),
        impact=impact,
        row_applicability=dict(sorted(row_applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_refs=dict(sorted(affected_refs.items())),
    )

    generated_at_str = (
        generated_at.astimezone(timezone.utc).isoformat() if generated_at is not None else None
    )
    return ScenarioLabEvaluation(
        contract_version=CONTRACT_VERSION,
        calculation_version=CALCULATION_VERSION,
        shock_schema_version=SHOCK_SCHEMA_VERSION,
        reporting_month=reporting_month_dict,
        base_fingerprint=frozen.base_fingerprint,
        semantic_fingerprint=semantic_fingerprint,
        normalized_shock_input=normalized_shock,
        normalized_target_scope=normalized_target_scope,
        assumptions=assumptions,
        base=base_metrics,
        stressed=stressed_metrics,
        impact=impact,
        row_applicability=dict(sorted(row_applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_canonical_refs=dict(sorted(affected_refs.items())),
        generated_at=generated_at_str,
        warnings=(),
        presentation_metadata={
            "account_names": dict(sorted(account_names.items())),
            "instrument_names": dict(sorted(instrument_names.items())),
        },
    )


# ---- deposit_rate_assumption evaluation ----


def _project_deposit_rows(
    frozen: FrozenScenarioBase,
    *,
    target_ids: tuple[int, ...],
    target_set: set[int],
    rate_basis_points: int,
) -> tuple[dict, dict, dict, dict, int]:
    """Project base/stressed deposit rows and per-deposit impact.

    Returns ``(base_rows, stressed_rows, impact_rows, applicability, delta)``.
    ``delta`` is the total stressed monthly interest minus total persisted
    monthly interest over ALL frozen deposits (0 when the month has none).
    """
    base_rows: dict[str, dict] = {}
    stressed_rows: dict[str, dict] = {}
    impact_rows: dict[str, dict] = {}
    applicability: dict[str, str] = {}

    base_total = 0
    stressed_total = 0
    for deposit in sorted(frozen.deposits, key=lambda item: item.id):
        deposit_id = deposit.id
        is_target = deposit_id in target_set
        persisted_rate = deposit.annual_rate_basis_points
        persisted_interest = deposit.expected_monthly_interest_kopecks
        if is_target:
            stressed_interest = calculate_deposit_expected_monthly_interest_kopecks(
                deposit.balance_kopecks, rate_basis_points
            )
            stressed_rate = rate_basis_points
            applicability[str(deposit_id)] = "applied"
        else:
            stressed_interest = persisted_interest
            stressed_rate = persisted_rate
            applicability[str(deposit_id)] = "not_applicable"
        base_total += persisted_interest
        stressed_total += stressed_interest
        base_rows[str(deposit_id)] = {
            "deposit_id": deposit_id,
            "account_id": deposit.account_id,
            "deposit_type": deposit.deposit_type,
            "balance_kopecks": deposit.balance_kopecks,
            "balance": _money_api(deposit.balance_kopecks),
            "annual_rate_basis_points": persisted_rate,
            "annual_rate_pct": normalized_rate_string(persisted_rate),
            "expected_monthly_interest_kopecks": persisted_interest,
            "expected_monthly_interest": _money_api(persisted_interest),
        }
        stressed_rows[str(deposit_id)] = {
            "deposit_id": deposit_id,
            "account_id": deposit.account_id,
            "deposit_type": deposit.deposit_type,
            "balance_kopecks": deposit.balance_kopecks,
            "balance": _money_api(deposit.balance_kopecks),
            "annual_rate_basis_points": stressed_rate,
            "annual_rate_pct": normalized_rate_string(stressed_rate),
            "expected_monthly_interest_kopecks": stressed_interest,
            "expected_monthly_interest": _money_api(stressed_interest),
        }
        impact_rows[str(deposit_id)] = {
            "delta_kopecks": stressed_interest - persisted_interest,
            "delta": _money_signed(stressed_interest - persisted_interest),
            "applicability": applicability[str(deposit_id)],
        }
    return base_rows, stressed_rows, impact_rows, applicability, stressed_total - base_total


def _project_forecast(
    frozen: FrozenScenarioBase,
    *,
    base_deposit_monthly: int | None,
    stressed_deposit_monthly: int | None,
) -> tuple[dict, dict]:
    """Project base and stressed forecast passive income.

    The only modified ForecastPassiveIncomeInput component is the selected
    month's deposit monthly-interest sum; everything else is frozen canonical
    input. Returns base and stressed result dicts.
    """

    def _run(deposit_sum: int | None) -> dict:
        from hermes_finance.domain.forecast_passive_income import ExpectedFlow
        from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome

        result = calculate_forecast_passive_income(
            ForecastPassiveIncomeInput(
                expected_flows=tuple(
                    ExpectedFlow(
                        flow_type=flow.flow_type,
                        net_amount_kopecks=flow.net_amount_kopecks,
                        is_approximate=flow.is_approximate,
                    )
                    for flow in frozen.forecast.expected_flows
                ),
                dividend_months=tuple(
                    MonthlyPassiveIncome(
                        year=item.year, month=item.month, amount=RubleAmount(item.amount_kopecks)
                    )
                    for item in frozen.forecast.dividend_months
                ),
                history_start_month=frozen.forecast.history_start_month,
                deposit_snapshot_monthly_interest_kopecks=deposit_sum,
            )
        )
        breakdown = result.breakdown
        return {
            "annual_total_kopecks": result.annual_total.kopecks,
            "annual_total": result.annual_total.to_api(),
            "monthly_total_kopecks": result.monthly_total.kopecks,
            "monthly_total": result.monthly_total.to_api(),
            "breakdown": {
                "expected_deposit_interest_kopecks": breakdown.expected_deposit_interest.kopecks,
                "expected_deposit_interest": breakdown.expected_deposit_interest.to_api(),
                "expected_coupon_net_kopecks": breakdown.expected_coupon_net.kopecks,
                "expected_coupon_net": breakdown.expected_coupon_net.to_api(),
                "expected_dividend_component_kopecks": (
                    breakdown.expected_dividend_component.kopecks
                ),
                "expected_dividend_component": breakdown.expected_dividend_component.to_api(),
                "other_expected_capital_income_kopecks": (
                    breakdown.other_expected_capital_income.kopecks
                ),
                "other_expected_capital_income": breakdown.other_expected_capital_income.to_api(),
            },
            "is_approximate": result.is_approximate,
        }

    return _run(base_deposit_monthly), _run(stressed_deposit_monthly)


def _project_ladder(frozen: FrozenScenarioBase, *, deposit_monthly: int | None) -> dict:
    """Small pure projection over the frozen canonical ladder output.

    Only the approximate monthly ``deposit_interest`` component may change:
    the replacement monthly estimate is the given deposit sum. ``None`` means
    the selected month has no deposit snapshots and the frozen ladder output
    is returned unchanged. Dated events and upcoming windows stay untouched —
    no deposit payment date is fabricated.
    """
    months: list[dict] = []
    for month in frozen.ladder.months:
        if deposit_monthly is None:
            month_dict = _ladder_month_dict(month)
        else:
            coupon = month.coupon_kopecks
            dividend = month.dividend_kopecks
            other = month.other_capital_income_kopecks
            redemption = month.redemption_principal_kopecks
            passive = coupon + dividend + deposit_monthly + other
            total = passive + redemption
            month_dict = {
                "year": month.year,
                "month": month.month,
                "coupon_kopecks": coupon,
                "coupon": _money_api(coupon),
                "dividend_kopecks": dividend,
                "dividend": _money_api(dividend),
                "deposit_interest_kopecks": deposit_monthly,
                "deposit_interest": _money_api(deposit_monthly),
                "other_capital_income_kopecks": other,
                "other_capital_income": _money_api(other),
                "redemption_principal_kopecks": redemption,
                "redemption_principal": _money_api(redemption),
                "passive_income_kopecks": passive,
                "passive_income": _money_api(passive),
                "total_cash_flow_kopecks": total,
                "total_cash_flow": _money_api(total),
                "is_approximate": month.is_approximate,
            }
        months.append(month_dict)
    return {
        "as_of_date": frozen.ladder.as_of_date.isoformat(),
        "forecast_version": frozen.ladder.forecast_version,
        "months": months,
        "upcoming_14_days": _window_dict(frozen.ladder.upcoming_14_days),
        "upcoming_30_days": _window_dict(frozen.ladder.upcoming_30_days),
    }


def _evaluate_deposit_rate(
    session: Session,
    reporting_month_id: int,
    payload: dict[str, Any],
    *,
    top_n: int,
    generated_at: datetime | None,
) -> ScenarioLabEvaluation:
    rate_basis_points, rate_string, requested_ids, all_eligible = _parse_deposit_rate_input(payload)

    frozen = materialize_frozen_base(session, reporting_month_id)
    frozen_ids, deposit_by_id = _resolve_deposit_targets(frozen, all_eligible, requested_ids)
    if all_eligible:
        selector = "all_eligible_deposits"
        target_ids = tuple(deposit_by_id)
    else:
        selector = "deposit_ids"
        target_ids = tuple(sorted(requested_ids))
    target_set = set(target_ids)

    normalized_target_scope = {
        "selector": selector,
        "deposit_ids": list(target_ids),
        "eligible_deposit_ids": list(tuple(sorted(deposit_by_id))),
    }

    base_rows, stressed_rows, impact_rows, applicability, total_delta = _project_deposit_rows(
        frozen,
        target_ids=target_ids,
        target_set=target_set,
        rate_basis_points=rate_basis_points,
    )

    if frozen.deposits:
        base_deposit_monthly = sum(
            deposit.expected_monthly_interest_kopecks for deposit in frozen.deposits
        )
        stressed_deposit_monthly = sum(
            stressed_rows[str(deposit.id)]["expected_monthly_interest_kopecks"]
            for deposit in frozen.deposits
        )
    else:
        base_deposit_monthly = None
        stressed_deposit_monthly = None

    base_forecast, stressed_forecast = _project_forecast(
        frozen,
        base_deposit_monthly=base_deposit_monthly,
        stressed_deposit_monthly=stressed_deposit_monthly,
    )
    base_ladder = _project_ladder(frozen, deposit_monthly=base_deposit_monthly)
    stressed_ladder = _project_ladder(frozen, deposit_monthly=stressed_deposit_monthly)

    # Capital metrics: deposit-rate shock never changes principal/eligibility.
    families = _capital_metric_families(
        frozen,
        stressed_values={item.id: item.market_value_kopecks for item in frozen.positions},
        has_unknown=False,
        row_applicability={},
        top_n=top_n,
    )
    base_metrics, stressed_metrics = _base_stressed_metric_dicts(families)
    base_metrics["per_deposit"] = {
        key: value for key, value in sorted(base_rows.items(), key=lambda kv: int(kv[0]))
    }
    stressed_metrics["per_deposit"] = {
        key: value for key, value in sorted(stressed_rows.items(), key=lambda kv: int(kv[0]))
    }
    base_metrics["forecast_passive_income"] = base_forecast
    stressed_metrics["forecast_passive_income"] = stressed_forecast
    base_metrics["cash_flow_ladder"] = base_ladder
    stressed_metrics["cash_flow_ladder"] = stressed_ladder
    base_metrics["passive_income_goal_effect"] = {
        "status": "unchanged",
        "basis": "historical_actual_rolling_average",
        "affected": False,
    }
    stressed_metrics["passive_income_goal_effect"] = {
        "status": "unchanged",
        "basis": "historical_actual_rolling_average",
        "affected": False,
    }
    base_metrics["future_cash_flow_rows_unchanged"] = True
    stressed_metrics["future_cash_flow_rows_unchanged"] = True

    applied_count = sum(1 for value in applicability.values() if value == "applied")
    not_applicable_count = sum(1 for value in applicability.values() if value == "not_applicable")
    forecast_delta_kopecks = (
        stressed_forecast["annual_total_kopecks"] - base_forecast["annual_total_kopecks"]
    )
    impact = {
        "liquid_assets_delta_kopecks": 0,
        "liquid_assets_delta": "0.00",
        "liquid_capital_net_delta_kopecks": 0,
        "liquid_capital_net_delta": "0.00",
        "monthly_interest_delta_kopecks": total_delta,
        "monthly_interest_delta": _money_signed(total_delta),
        "annual_deposit_interest_delta_kopecks": total_delta * 12,
        "annual_deposit_interest_delta": _money_signed(total_delta * 12),
        "forecast_annual_total_delta_kopecks": forecast_delta_kopecks,
        "forecast_annual_total_delta": _money_signed(forecast_delta_kopecks),
        "known_scope_monthly_interest_delta_kopecks": total_delta,
        "known_scope_monthly_interest_delta": _money_signed(total_delta),
        "per_deposit": {
            key: value for key, value in sorted(impact_rows.items(), key=lambda kv: int(kv[0]))
        },
    }
    coverage = {
        "total_deposits": len(frozen.deposits),
        "eligible_deposits": len(deposit_by_id),
        "applied": applied_count,
        "not_applicable": not_applicable_count,
        "unknown": 0,
        "known_scope_monthly_interest_delta_kopecks": total_delta,
        "known_scope_monthly_interest_delta": _money_signed(total_delta),
    }

    metric_support = {
        "liquid_assets": {"status": "supported", "reason_codes": []},
        "liquid_capital_net": {"status": "supported", "reason_codes": []},
        "asset_allocation": {"status": "supported", "reason_codes": []},
        "account_allocation": {"status": "supported", "reason_codes": []},
        "top_positions": {"status": "supported", "reason_codes": []},
        "capital_goals": {"status": "supported", "reason_codes": []},
        "deposit_interest": {"status": "supported", "reason_codes": []},
        "forecast_passive_income": {"status": "supported", "reason_codes": []},
        "future_cash_flow_ladder": {"status": "supported", "reason_codes": []},
        "passive_income_goal": {
            "status": "unchanged",
            "reason_codes": ["actual_based_goal_not_affected_by_hypothetical_rate"],
        },
        "coupons": {"status": "supported", "reason_codes": []},
        "dividends": {"status": "supported", "reason_codes": []},
        "other_capital_income": {"status": "supported", "reason_codes": []},
        "redemption": {"status": "supported", "reason_codes": []},
        "historical_actual_passive_income": {"status": "supported", "reason_codes": []},
        "debts": {"status": "supported", "reason_codes": []},
    }

    assumptions = (
        "principal_unchanged",
        "liquid_capital_unchanged",
        "allocation_unchanged",
        "capital_goals_unchanged",
        "historical_actual_income_unchanged",
        "current_actual_based_goal_unchanged",
        "coupons_unchanged",
        "dividends_unchanged",
        "other_capital_income_unchanged",
        "redemption_unchanged",
        "no_fabricated_deposit_dates",
        "no_reinvestment_assumption",
        "no_tax_assumption",
        "no_provider_network_access",
    )

    involved_account_ids = _sorted_ids(
        [item.account_id for item in frozen.deposits]
        + [item.account_id for item in frozen.positions]
    )
    account_names = dict(
        (account_id, name)
        for account_id, name in frozen.account_names
        if account_id in set(involved_account_ids)
    )
    instrument_names = dict(
        (instrument_id, name)
        for instrument_id, name in frozen.instrument_names
        if instrument_id in {item.instrument_id for item in frozen.positions}
    )
    deposit_names = {deposit.id: deposit.name for deposit in frozen.deposits}
    affected_refs = {
        "reporting_month_id": reporting_month_id,
        "deposit_ids": _sorted_ids([item.id for item in frozen.deposits]),
        "account_ids": involved_account_ids,
        "position_ids": _sorted_ids([item.id for item in frozen.positions]),
        "instrument_ids": _sorted_ids([item.instrument_id for item in frozen.positions]),
        "cash_ids": _sorted_ids([item.id for item in frozen.cash]),
    }

    reporting_month_dict = {
        "id": frozen.reporting_month_id,
        "year": frozen.year,
        "month": frozen.month,
        "snapshot_date": frozen.snapshot_date.isoformat(),
        "status": frozen.status,
    }
    normalized_shock = {
        "shock_type": "deposit_rate_assumption",
        "assumed_annual_rate_pct": rate_string,
        "annual_rate_basis_points": rate_basis_points,
    }

    forecast_fingerprint_base = {
        "annual_total_kopecks": base_forecast["annual_total_kopecks"],
        "monthly_total_kopecks": base_forecast["monthly_total_kopecks"],
        "breakdown": {
            "expected_deposit_interest_kopecks": base_forecast["breakdown"][
                "expected_deposit_interest_kopecks"
            ],
            "expected_coupon_net_kopecks": base_forecast["breakdown"][
                "expected_coupon_net_kopecks"
            ],
            "expected_dividend_component_kopecks": base_forecast["breakdown"][
                "expected_dividend_component_kopecks"
            ],
            "other_expected_capital_income_kopecks": base_forecast["breakdown"][
                "other_expected_capital_income_kopecks"
            ],
        },
        "is_approximate": base_forecast["is_approximate"],
    }
    forecast_fingerprint_stressed = {
        "annual_total_kopecks": stressed_forecast["annual_total_kopecks"],
        "monthly_total_kopecks": stressed_forecast["monthly_total_kopecks"],
        "breakdown": {
            "expected_deposit_interest_kopecks": stressed_forecast["breakdown"][
                "expected_deposit_interest_kopecks"
            ],
            "expected_coupon_net_kopecks": stressed_forecast["breakdown"][
                "expected_coupon_net_kopecks"
            ],
            "expected_dividend_component_kopecks": stressed_forecast["breakdown"][
                "expected_dividend_component_kopecks"
            ],
            "other_expected_capital_income_kopecks": stressed_forecast["breakdown"][
                "other_expected_capital_income_kopecks"
            ],
        },
        "is_approximate": stressed_forecast["is_approximate"],
    }

    semantic_fingerprint = semantic_fingerprint_payload(
        contract_version=CONTRACT_VERSION,
        calculation_version=CALCULATION_VERSION,
        shock_schema_version=SHOCK_SCHEMA_VERSION,
        reporting_month=reporting_month_dict,
        base_fingerprint=frozen.base_fingerprint,
        normalized_shock=normalized_shock,
        normalized_target_scope=normalized_target_scope,
        assumptions=list(assumptions),
        base=_fingerprint_base_families(
            families,
            extra_families={
                "per_deposit": _strip_deposit_rows(base_rows),
                "forecast_passive_income": forecast_fingerprint_base,
                "cash_flow_ladder": _ladder_dict_fingerprint(base_ladder, frozen),
            },
        ),
        stressed=_fingerprint_stressed_families(
            families,
            extra_families={
                "per_deposit": _strip_deposit_rows(stressed_rows),
                "forecast_passive_income": forecast_fingerprint_stressed,
                "cash_flow_ladder": _ladder_dict_fingerprint(stressed_ladder, frozen),
            },
        ),
        impact=impact,
        row_applicability=dict(sorted(applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_refs=dict(sorted(affected_refs.items())),
    )

    generated_at_str = (
        generated_at.astimezone(timezone.utc).isoformat() if generated_at is not None else None
    )
    return ScenarioLabEvaluation(
        contract_version=CONTRACT_VERSION,
        calculation_version=CALCULATION_VERSION,
        shock_schema_version=SHOCK_SCHEMA_VERSION,
        reporting_month=reporting_month_dict,
        base_fingerprint=frozen.base_fingerprint,
        semantic_fingerprint=semantic_fingerprint,
        normalized_shock_input=normalized_shock,
        normalized_target_scope=normalized_target_scope,
        assumptions=assumptions,
        base=base_metrics,
        stressed=stressed_metrics,
        impact=impact,
        row_applicability=dict(sorted(applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_canonical_refs=dict(sorted(affected_refs.items())),
        generated_at=generated_at_str,
        warnings=(),
        presentation_metadata={
            "account_names": dict(sorted(account_names.items())),
            "instrument_names": dict(sorted(instrument_names.items())),
            "deposit_names": dict(sorted(deposit_names.items())),
        },
    )


# ---- entry point ----


def evaluate_scenario_lab(
    session: Session,
    reporting_month_id: int,
    shock: dict[str, Any],
    *,
    top_n: int = 5,
    generated_at: datetime | None = None,
) -> ScenarioLabEvaluation:
    """Evaluate exactly one deterministic scenario shock.

    Supported shocks:
    - ``{"equity_drawdown": {"drawdown_pct": "20.00"}}``
    - ``{"deposit_rate_assumption": {"assumed_annual_rate_pct": "12",
      "all_eligible_deposits": True}}``
    - ``{"deposit_rate_assumption": {"assumed_annual_rate_pct": "12",
      "deposit_ids": [1, 2]}}``

    Combined shocks raise ``unsupported_composition_v1``. Read-only: no
    commit, no writes, no provider/network access.
    """
    if not isinstance(top_n, int) or isinstance(top_n, bool):
        raise ScenarioLabError("invalid_top_n", "top_n must be int")
    if not 1 <= top_n <= 100:
        raise ScenarioLabError("invalid_top_n", "top_n 1..100")

    shock_type, payload = _validate_shock_container(shock)
    if shock_type == "equity_drawdown":
        return _evaluate_equity(
            session, reporting_month_id, payload, top_n=top_n, generated_at=generated_at
        )
    return _evaluate_deposit_rate(
        session, reporting_month_id, payload, top_n=top_n, generated_at=generated_at
    )
