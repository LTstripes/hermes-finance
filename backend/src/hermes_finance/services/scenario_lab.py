"""Service adapter for Scenario Lab 141-A — equity_drawdown only.

Read-only, no provider/network/fx, no writes. Composes canonical read models.
Uses pure canonical Risk projection builder from domain/risk_allocation for
both base and stressed allocations (R1), implements R2-R5 fixes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.goal_achievement import calculate_goal_achievement_forecast
from hermes_finance.domain.liquid_capital import (
    AccountAmount,
    LiquidCapitalInput,
    calculate_liquid_capital,
)
from hermes_finance.domain.risk_allocation import (
    MetricSupport,
    RiskDepositInput,
    RiskPositionInput,
    build_account_allocation,
    build_asset_allocation,
    build_top_positions,
)
from hermes_finance.domain.scenario_lab import (
    CALCULATION_VERSION,
    CONTRACT_VERSION,
    SHOCK_SCHEMA_VERSION,
    MetricSupportStatus,
    RowApplicability,
    canonical_drawdown_pct,
    classify_applicability,
    normalize_drawdown_pct,
    parse_drawdown_pct,
    semantic_fingerprint_payload,
    stressed_market_value_kopecks,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    Account,
    CashBalance,
    Debt,
    DepositSnapshot,
    Goal,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError

# ---- errors with machine-readable codes ----


class ScenarioLabError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ---- helpers ----


def _validate_single_shock(shock: dict[str, Any]) -> None:
    if not isinstance(shock, dict):
        raise ScenarioLabError("invalid_shock_input", "shock must be dict")
    keys = [k for k in shock.keys() if shock[k] is not None]
    if len(keys) != 1:
        raise ScenarioLabError("unsupported_composition_v1", "exactly one shock required")
    only = keys[0]
    if only != "equity_drawdown":
        raise ScenarioLabError("unsupported_shock_type_v1", f"unsupported shock {only}")
    payload = shock[only]
    if not isinstance(payload, dict):
        raise ScenarioLabError("invalid_shock_input", "equity_drawdown must be dict")
    if "drawdown_pct" not in payload:
        raise ScenarioLabError("invalid_drawdown_pct", "drawdown_pct required")
    extra = set(payload.keys()) - {"drawdown_pct"}
    if extra:
        raise ScenarioLabError("invalid_shock_input", f"unexpected fields {extra}")


def _sorted_ids(values: list[int]) -> list[int]:
    return sorted(set(values))


def _base_fingerprint(frozen_payload: dict) -> str:
    canonical = json.dumps(
        frozen_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _money_api(kopecks: int) -> str:
    return format(Decimal(kopecks) / Decimal(100), ".2f")


# ---- main evaluation ----


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


def evaluate_scenario_lab(
    session: Session,
    reporting_month_id: int,
    shock: dict[str, Any],
    *,
    top_n: int = 5,
    generated_at: datetime | None = None,
) -> ScenarioLabEvaluation:
    """Evaluate deterministic equity_drawdown scenario.

    Shock example: {"equity_drawdown": {"drawdown_pct": "20.00"}}
    Combined shocks -> raises ScenarioLabError code unsupported_composition_v1.
    Invalid pct -> raises code invalid_drawdown_pct.
    Read-only: no commit, no network.
    """
    _validate_single_shock(shock)
    payload = shock["equity_drawdown"]
    raw_pct = parse_drawdown_pct(payload["drawdown_pct"])
    # R3: lossless canonical via string manipulation
    canonical_pct = canonical_drawdown_pct(raw_pct)
    pct_str = normalize_drawdown_pct(canonical_pct)

    if not isinstance(top_n, int) or isinstance(top_n, bool):
        raise ScenarioLabError("invalid_top_n", "top_n must be int")
    if not 1 <= top_n <= 100:
        raise ScenarioLabError("invalid_top_n", "top_n 1..100")

    with session.no_autoflush:
        month: ReportingMonth | None = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

        cash_rows = list(
            session.scalars(
                select(CashBalance)
                .where(CashBalance.reporting_month_id == reporting_month_id)
                .order_by(CashBalance.id)
            )
        )
        deposit_rows = list(
            session.execute(
                select(DepositSnapshot, Account.name, Account.include_in_capital)
                .join(Account, DepositSnapshot.account_id == Account.id)
                .where(DepositSnapshot.reporting_month_id == reporting_month_id)
                .order_by(DepositSnapshot.id)
            ).all()
        )
        pos_rows = list(
            session.execute(
                select(PositionSnapshot, Instrument.name, Instrument.instrument_type)
                .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
                .where(PositionSnapshot.reporting_month_id == reporting_month_id)
                .order_by(PositionSnapshot.id)
            ).all()
        )
        pos_accounts = {
            row[0].id: session.get(Account, row[0].account_id).include_in_capital
            if session.get(Account, row[0].account_id) is not None
            else True
            for row in pos_rows
        }
        account_names: dict[int, str] = {}
        instrument_names: dict[int, str] = {}
        for dep, name, _inc in deposit_rows:
            account_names[dep.account_id] = name
        for snap, inst_name, _type in pos_rows:
            acc = session.get(Account, snap.account_id)
            if acc is not None:
                account_names[snap.account_id] = acc.name
            instrument_names[snap.instrument_id] = inst_name

        debt_rows = list(
            session.scalars(
                select(Debt).where(Debt.reporting_month_id == reporting_month_id).order_by(Debt.id)
            )
        )
        all_goals = list(session.scalars(select(Goal).order_by(Goal.id)).all())
        capital_goals = [
            g
            for g in all_goals
            if g.is_active
            and g.goal_type == "capital"
            and g.calculation_mode == "liquid_capital_net"
        ]

    frozen_payload = {
        "reporting_month": {
            "id": month.id,
            "year": month.year,
            "month": month.month,
            "snapshot_date": month.snapshot_date.isoformat(),
            "status": month.status,
        },
        "cash": [
            {
                "id": c.id,
                "amount_kopecks": c.amount_kopecks,
                "currency": c.currency,
                "include_in_capital": c.include_in_capital,
            }
            for c in sorted(cash_rows, key=lambda x: x.id)
        ],
        "deposits": [
            {
                "id": d.id,
                "account_id": d.account_id,
                "balance_kopecks": d.balance_kopecks,
                "include_in_capital": bool(inc),
            }
            for d, _name, inc in sorted(deposit_rows, key=lambda x: x[0].id)
        ],
        "positions": [
            {
                "id": snap.id,
                "account_id": snap.account_id,
                "instrument_id": snap.instrument_id,
                "instrument_type": itype,
                "market_value_kopecks": snap.market_value_kopecks,
                "include_in_capital": bool(pos_accounts.get(snap.id, True)),
            }
            for snap, _iname, itype in sorted(pos_rows, key=lambda x: x[0].id)
        ],
        "debts": [
            {
                "id": d.id,
                "balance_kopecks": d.current_balance_kopecks,
                "include_in_liquid_capital": d.include_in_liquid_capital,
            }
            for d in sorted(debt_rows, key=lambda x: x.id)
        ],
        "goals": [
            {
                "id": g.id,
                "target_kopecks": g.target_value_kopecks,
                "is_active": g.is_active,
                "goal_type": g.goal_type,
            }
            for g in sorted(capital_goals, key=lambda x: x.id)
        ],
    }
    base_fp = _base_fingerprint(frozen_payload)

    eligible_position_ids = _sorted_ids(
        [p["id"] for p in frozen_payload["positions"] if p["include_in_capital"]]
    )
    eligible_deposit_ids = _sorted_ids(
        [d["id"] for d in frozen_payload["deposits"] if d["include_in_capital"]]
    )
    normalized_target_scope = {
        "selector": "all_eligible",
        "eligible_position_ids": eligible_position_ids,
        "eligible_deposit_ids": eligible_deposit_ids,
    }

    # R5 + R2: row_applicability only for eligible; excluded absent
    row_applicability: dict[str, str] = {}
    base_per_position: dict[str, dict] = {}
    stressed_per_position: dict[str, dict] = {}
    impact_per_position: dict[str, dict] = {}
    stressed_positions: dict[int, int] = {}
    coverage_applied = 0
    coverage_not = 0
    coverage_unknown = 0
    known_scope_delta = 0

    # Need to populate stressed_positions for all eligible only; for base we keep all?
    # But per_position should also only contain eligible (R5)
    for p in frozen_payload["positions"]:
        pid = p["id"]
        incl = bool(p["include_in_capital"])
        base_v = int(p["market_value_kopecks"])
        # For excluded, stressed = base, not in row_applicability/impact/coverage
        if not incl:
            stressed_positions[pid] = base_v
            continue
        appl = classify_applicability(p["instrument_type"])
        row_applicability[str(pid)] = appl.value
        if appl == RowApplicability.APPLIED:
            stressed_v = stressed_market_value_kopecks(base_v, canonical_pct)
            delta = stressed_v - base_v
            coverage_applied += 1
            known_scope_delta += delta
        elif appl == RowApplicability.UNKNOWN:
            stressed_v = base_v
            delta = 0
            coverage_unknown += 1
        else:
            stressed_v = base_v
            delta = 0
            coverage_not += 1
        stressed_positions[pid] = stressed_v
        # R2: per_position keep only market values, no applicability
        base_per_position[str(pid)] = {
            "market_value_kopecks": base_v,
            "market_value": _money_api(base_v),
            "account_id": p["account_id"],
            "instrument_id": p["instrument_id"],
            "instrument_type": p["instrument_type"],
            "include_in_capital": incl,
        }
        stressed_per_position[str(pid)] = {
            "market_value_kopecks": stressed_v,
            "market_value": _money_api(stressed_v),
            "account_id": p["account_id"],
            "instrument_id": p["instrument_id"],
            "instrument_type": p["instrument_type"],
            "include_in_capital": incl,
        }
        impact_per_position[str(pid)] = {
            "delta_kopecks": delta,
            "delta": _money_api(delta) if delta >= 0 else "-" + _money_api(-delta),
            "applicability": appl.value,
        }

    # Also need stressed_positions for non-eligible already set

    coverage = {
        "total_positions": len(eligible_position_ids),
        "eligible_positions": len(eligible_position_ids),
        "applied": coverage_applied,
        "not_applicable": coverage_not,
        "unknown": coverage_unknown,
        "known_scope_impact_kopecks": known_scope_delta,
        "known_scope_impact": _money_api(known_scope_delta)
        if known_scope_delta >= 0
        else "-" + _money_api(-known_scope_delta),
    }

    has_unknown = coverage_unknown > 0

    # BLOCKER B: build liquid capital from frozen_payload only — no DB re-read, no liquid_capital_for_month
    cash_total = sum(c["amount_kopecks"] for c in frozen_payload["cash"] if c["include_in_capital"])
    deposits_total = sum(
        d["balance_kopecks"] for d in frozen_payload["deposits"] if d["include_in_capital"]
    )
    debts_total = sum(
        d["balance_kopecks"] for d in frozen_payload["debts"] if d["include_in_liquid_capital"]
    )
    securities_total_base = sum(
        p["market_value_kopecks"] for p in frozen_payload["positions"] if p["include_in_capital"]
    )
    # Build domain inputs for canonical builder (R1) from frozen
    base_domain_positions = tuple(
        RiskPositionInput(
            position_id=p["id"],
            account_id=p["account_id"],
            instrument_id=p["instrument_id"],
            instrument_type=p["instrument_type"],
            amount_kopecks=int(p["market_value_kopecks"]),
        )
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    stressed_domain_positions = tuple(
        RiskPositionInput(
            position_id=p["id"],
            account_id=p["account_id"],
            instrument_id=p["instrument_id"],
            instrument_type=p["instrument_type"],
            amount_kopecks=stressed_positions[p["id"]],
        )
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    domain_deposits = tuple(
        RiskDepositInput(account_id=d["account_id"], amount_kopecks=int(d["balance_kopecks"]))
        for d in frozen_payload["deposits"]
        if d["include_in_capital"]
    )
    # Per-account deposit/securities tuples for liquid capital — built from frozen only
    _frozen_deposit_accounts = tuple(
        AccountAmount(account_id=d["account_id"], amount=RubleAmount(int(d["balance_kopecks"])))
        for d in frozen_payload["deposits"]
        if d["include_in_capital"]
    )
    _frozen_securities_accounts_base = tuple(
        AccountAmount(
            account_id=p["account_id"], amount=RubleAmount(int(p["market_value_kopecks"]))
        )
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    _frozen_securities_accounts_stressed = tuple(
        AccountAmount(
            account_id=p["account_id"], amount=RubleAmount(int(stressed_positions[p["id"]]))
        )
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    base_liquid_input = LiquidCapitalInput(
        cash=RubleAmount(cash_total),
        deposits=RubleAmount(deposits_total),
        securities=RubleAmount(securities_total_base),
        included_debts=RubleAmount(debts_total),
        other_liquid_assets=RubleAmount(0),
        deposit_accounts=_frozen_deposit_accounts,
        securities_accounts=_frozen_securities_accounts_base,
    )
    base_liquid = calculate_liquid_capital(base_liquid_input)

    # Prepare supports for builder (asset/account)
    # Valuation issues: for eligible positions only? but we keep empty for scenario (no valuation check)
    # Instead we treat has_unknown as asset unknown support
    # Use domain support helpers

    # For scenario, we need to compute support for asset/account from unknown applicability
    # We'll create metric supports via domain logic but map to scenario's metric_support
    # The canonical builder will be called with SUPPORTED or UNKNOWN based on has_unknown
    from hermes_finance.domain.risk_allocation import RiskSupportStatus as DomainRiskStatus

    if has_unknown:
        asset_support_domain = MetricSupport(
            status=DomainRiskStatus.UNKNOWN, reason_codes=("instrument_type_not_authoritative",)
        )
        account_support_domain = MetricSupport(
            status=DomainRiskStatus.SUPPORTED
        )  # account not affected by unknown type
    else:
        asset_support_domain = MetricSupport(status=DomainRiskStatus.SUPPORTED)
        account_support_domain = MetricSupport(status=DomainRiskStatus.SUPPORTED)

    # Include cash_not_account_linked reason if needed
    if cash_total:
        # domain account support would have cash_not_account_linked; we handle separately for scenario metric_support?
        # Keep domain support for builder as above, but scenario metric_support will be derived later
        pass

    stressed_securities = sum(stressed_positions[pid] for pid in eligible_position_ids)
    stressed_liquid_input = LiquidCapitalInput(
        cash=RubleAmount(cash_total),
        deposits=RubleAmount(deposits_total),
        securities=RubleAmount(stressed_securities),
        included_debts=RubleAmount(debts_total),
        other_liquid_assets=RubleAmount(0),
        deposit_accounts=_frozen_deposit_accounts,
        securities_accounts=_frozen_securities_accounts_stressed,
    )
    stressed_liquid = calculate_liquid_capital(stressed_liquid_input)

    # R1: use canonical builder for both base and stressed
    def _allocation_metric_to_dict(metric) -> dict:
        # Convert AllocationMetric to scenario asset_allocation dict with distinct buckets
        buckets = {item.key: item.amount.kopecks for item in metric.items}
        # Ensure all R07-06A buckets present
        result: dict[str, Any] = {
            "cash_kopecks": buckets.get("cash", 0),
            "cash": _money_api(buckets.get("cash", 0)),
            "deposits_kopecks": buckets.get("deposits", 0),
            "deposits": _money_api(buckets.get("deposits", 0)),
            "unknown_asset_class_kopecks": buckets.get("unknown_asset_class", 0),
            "unknown_asset_class": _money_api(buckets.get("unknown_asset_class", 0)),
            "denominator_kopecks": metric.denominator.kopecks,
        }
        for k in ("stock", "bond", "fund", "currency", "gold", "other"):
            val = buckets.get(k, 0)
            result[f"{k}_kopecks"] = val
            result[f"{k}"] = _money_api(val)
            # find share_pct from metric items
            pct = next((item.share_pct for item in metric.items if item.key == k), None)
            # Also need cash/deposits/unknown share
            result[f"{k}_share_pct"] = format(pct, ".2f") if pct is not None else None
        for k in ("cash", "deposits", "unknown_asset_class"):
            pct = next((item.share_pct for item in metric.items if item.key == k), None)
            result[f"{k}_share_pct"] = format(pct, ".2f") if pct is not None else None
        return result

    def _account_metric_to_list(metric) -> list[dict]:
        # Convert account AllocationMetric to scenario list, keep only ids (R4)
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
                # key is account:<id>
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
        # Sort as builder does: (-amount, key)
        result.sort(key=lambda x: (-x["amount_kopecks"], str(x["account_id"])))
        return result

    def _top_metric_to_list(metric) -> list[dict]:
        result = []
        for item in metric.items:
            # R4: keep only ids, no names; keep applicability? we have it in metric? but builder's top items don't have applicability
            result.append(
                {
                    "position_id": item.position_id,
                    "account_id": item.account_id,
                    "instrument_id": item.instrument_id,
                    "instrument_type": item.instrument_type,
                    "amount_kopecks": item.amount.kopecks,
                    "amount": _money_api(item.amount.kopecks),
                    "share_pct": format(item.share_pct, ".2f")
                    if item.share_pct is not None
                    else None,
                    # R4: do NOT include account_name/instrument_name
                    # Keep applicability only if needed? For top_positions we keep it? But R2 says only row_applicability and impact; remove from top?
                    # To satisfy R4/R2 strictly, we remove applicability from top as well.
                    # We'll keep it out of normative, but include for legacy check? Better exclude.
                }
            )
        result.sort(key=lambda x: (-x["amount_kopecks"], x["position_id"]))
        return result

    # Build base metrics via canonical builder
    base_asset_metric = build_asset_allocation(
        cash_kopecks=cash_total,
        deposits=domain_deposits,
        positions=base_domain_positions,
        liquid_assets_kopecks=base_liquid.total_assets.kopecks,
        support=asset_support_domain,
        excluded=(),
    )
    base_account_metric = build_account_allocation(
        cash_kopecks=cash_total,
        deposits=domain_deposits,
        positions=base_domain_positions,
        liquid_assets_kopecks=base_liquid.total_assets.kopecks,
        support=account_support_domain,
        excluded=(),
        account_names=None,  # R4: no names in normative, will be in presentation_metadata
    )
    base_top_metric = build_top_positions(
        positions=base_domain_positions,
        liquid_assets_kopecks=base_liquid.total_assets.kopecks,
        top_n=top_n,
        issues=(),
        account_names=None,
        instrument_names=None,
    )

    stressed_asset_metric = build_asset_allocation(
        cash_kopecks=cash_total,
        deposits=domain_deposits,
        positions=stressed_domain_positions,
        liquid_assets_kopecks=stressed_liquid.total_assets.kopecks,
        support=asset_support_domain,
        excluded=(),
    )
    stressed_account_metric = build_account_allocation(
        cash_kopecks=cash_total,
        deposits=domain_deposits,
        positions=stressed_domain_positions,
        liquid_assets_kopecks=stressed_liquid.total_assets.kopecks,
        support=account_support_domain,
        excluded=(),
        account_names=None,
    )
    stressed_top_metric = build_top_positions(
        positions=stressed_domain_positions,
        liquid_assets_kopecks=stressed_liquid.total_assets.kopecks,
        top_n=top_n,
        issues=(),
        account_names=None,
        instrument_names=None,
    )

    base_asset = _allocation_metric_to_dict(base_asset_metric)
    stressed_asset = _allocation_metric_to_dict(stressed_asset_metric)
    base_account_alloc = _account_metric_to_list(base_account_metric)
    stressed_account_alloc = _account_metric_to_list(stressed_account_metric)
    base_top = _top_metric_to_list(base_top_metric)
    stressed_top = _top_metric_to_list(stressed_top_metric)

    base_goals_list = []
    stressed_goals_list = []
    # BLOCKER B: Goals from frozen_payload only — do not re-read DB
    for g in frozen_payload["goals"]:
        gid = int(g["id"])
        target_kopecks = int(g["target_kopecks"])
        base_calc = calculate_goal_achievement_forecast(
            goal_id=gid,
            reporting_month_id=month.id,
            as_of_date=month.snapshot_date,
            current_value=base_liquid.liquid_capital_net,
            target_value=RubleAmount(target_kopecks),
            source_forecast_version=None,
        )
        stressed_calc = calculate_goal_achievement_forecast(
            goal_id=gid,
            reporting_month_id=month.id,
            as_of_date=month.snapshot_date,
            current_value=stressed_liquid.liquid_capital_net,
            target_value=RubleAmount(target_kopecks),
            source_forecast_version=None,
        )

        def _goal_dict(calc, _target_kopecks=target_kopecks):
            return {
                "goal_id": calc.goal_id,
                "target_kopecks": _target_kopecks,
                "target": _money_api(_target_kopecks),
                "current_kopecks": calc.current_value.kopecks if calc.current_value else None,
                "current": _money_api(calc.current_value.kopecks) if calc.current_value else None,
                "remaining_kopecks": calc.remaining_amount.kopecks
                if calc.remaining_amount
                else None,
                "remaining": _money_api(calc.remaining_amount.kopecks)
                if calc.remaining_amount
                else None,
                "progress_pct": format(calc.progress_pct, ".2f")
                if calc.progress_pct is not None
                else None,
                "status": calc.status,
            }

        base_goals_list.append(_goal_dict(base_calc))
        stressed_goals_list.append(_goal_dict(stressed_calc))

    base_metrics = {
        "liquid_assets_kopecks": base_liquid.total_assets.kopecks,
        "liquid_assets": _money_api(base_liquid.total_assets.kopecks),
        "liquid_capital_net_kopecks": base_liquid.liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(base_liquid.liquid_capital_net.kopecks),
        "debts_included_kopecks": base_liquid.total_debts_included.kopecks,
        "debts_included": _money_api(base_liquid.total_debts_included.kopecks),
        "asset_allocation": base_asset,
        "account_allocation": base_account_alloc,
        "top_positions": base_top,
        "capital_goals": sorted(base_goals_list, key=lambda x: x["goal_id"]),
        "per_position": {
            k: v for k, v in sorted(base_per_position.items(), key=lambda kv: int(kv[0]))
        },
        "passive_income_effect": {
            "status": "unavailable",
            "reason": "no_deterministic_income_relationship",
        },
        "future_cash_flow_rows_unchanged": True,
    }
    stressed_metrics = {
        "liquid_assets_kopecks": stressed_liquid.total_assets.kopecks,
        "liquid_assets": _money_api(stressed_liquid.total_assets.kopecks),
        "liquid_capital_net_kopecks": stressed_liquid.liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(stressed_liquid.liquid_capital_net.kopecks),
        "debts_included_kopecks": stressed_liquid.total_debts_included.kopecks,
        "debts_included": _money_api(stressed_liquid.total_debts_included.kopecks),
        "asset_allocation": stressed_asset,
        "account_allocation": stressed_account_alloc,
        "top_positions": stressed_top,
        "capital_goals": sorted(stressed_goals_list, key=lambda x: x["goal_id"]),
        "per_position": {
            k: v for k, v in sorted(stressed_per_position.items(), key=lambda kv: int(kv[0]))
        },
        "passive_income_effect": {
            "status": "unavailable",
            "reason": "no_deterministic_income_relationship",
        },
        "future_cash_flow_rows_unchanged": True,
    }

    impact = {
        "liquid_assets_delta_kopecks": stressed_liquid.total_assets.kopecks
        - base_liquid.total_assets.kopecks,
        "liquid_assets_delta": _money_api(
            stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks
        )
        if (stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks) >= 0
        else "-"
        + _money_api(-(stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks)),
        "liquid_capital_net_delta_kopecks": stressed_liquid.liquid_capital_net.kopecks
        - base_liquid.liquid_capital_net.kopecks,
        "liquid_capital_net_delta": _money_api(
            stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks
        )
        if (stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks)
        >= 0
        else "-"
        + _money_api(
            -(stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks)
        ),
        "known_scope_impact_kopecks": known_scope_delta,
        "known_scope_impact": _money_api(known_scope_delta)
        if known_scope_delta >= 0
        else "-" + _money_api(-known_scope_delta),
        "per_position": {
            k: v for k, v in sorted(impact_per_position.items(), key=lambda kv: int(kv[0]))
        },
    }

    def _support_for_aggregates() -> MetricSupportStatus:
        if has_unknown:
            return MetricSupportStatus.UNKNOWN
        return MetricSupportStatus.SUPPORTED

    agg_status = _support_for_aggregates().value
    agg_reason = ["instrument_type_not_authoritative"] if has_unknown else []
    metric_support = {
        "liquid_assets": {"status": agg_status, "reason_codes": agg_reason},
        "liquid_capital_net": {"status": agg_status, "reason_codes": agg_reason},
        "asset_allocation": {"status": agg_status, "reason_codes": agg_reason},
        "account_allocation": {"status": agg_status, "reason_codes": agg_reason},
        "top_positions": {"status": agg_status, "reason_codes": agg_reason},
        "capital_goals": {"status": agg_status, "reason_codes": agg_reason},
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

    affected_refs = {
        "reporting_month_id": month.id,
        "position_ids": _sorted_ids([p["id"] for p in frozen_payload["positions"]]),
        "account_ids": _sorted_ids(list(account_names.keys())),
        "instrument_ids": _sorted_ids([p["instrument_id"] for p in frozen_payload["positions"]]),
        "deposit_ids": eligible_deposit_ids,
        "cash_ids": _sorted_ids([c.id for c in cash_rows]),
    }

    reporting_month_dict = {
        "id": month.id,
        "year": month.year,
        "month": month.month,
        "snapshot_date": month.snapshot_date.isoformat(),
        "status": month.status,
    }
    normalized_shock = {
        "shock_type": "equity_drawdown",
        "drawdown_pct": pct_str,
    }

    # Presentation metadata excluded from fingerprint (R4)
    presentation_metadata = {
        "account_names": dict(sorted(account_names.items())),
        "instrument_names": dict(sorted(instrument_names.items())),
    }

    # Fingerprint: strip to normative fields only (no names, no applicability in per_position)
    def _strip_account_alloc(lst: list[dict]) -> list[dict]:
        return [
            {
                "account_id": x["account_id"],
                "amount_kopecks": x["amount_kopecks"],
                "share_pct": x.get("share_pct"),
                "unassigned": x.get("unassigned", False),
            }
            for x in sorted(lst, key=lambda v: (str(v["account_id"]), v["amount_kopecks"]))
        ]

    def _strip_top(lst: list[dict]) -> list[dict]:
        return [
            {
                "position_id": x["position_id"],
                "account_id": x["account_id"],
                "instrument_id": x["instrument_id"],
                "instrument_type": x["instrument_type"],
                "amount_kopecks": x["amount_kopecks"],
                "share_pct": x.get("share_pct"),
            }
            for x in sorted(lst, key=lambda v: v["position_id"])
        ]

    def _strip_goals(lst: list[dict]) -> list[dict]:
        return sorted(
            [
                {
                    "goal_id": g["goal_id"],
                    "target_kopecks": g["target_kopecks"],
                    "current_kopecks": g["current_kopecks"],
                    "remaining_kopecks": g["remaining_kopecks"],
                    "progress_pct": g["progress_pct"],
                    "status": g["status"],
                }
                for g in lst
            ],
            key=lambda v: v["goal_id"],
        )

    fingerprint_input_base = {
        "liquid_assets_kopecks": base_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": base_metrics["liquid_capital_net_kopecks"],
        "debts_included_kopecks": base_metrics["debts_included_kopecks"],
        "asset_allocation": {
            k: v
            for k, v in base_asset.items()
            if k.endswith("_kopecks") or k.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(base_account_alloc),
        "top_positions": _strip_top(base_top),
        "capital_goals": _strip_goals(base_goals_list),
        "per_position": {
            k: {"market_value_kopecks": v["market_value_kopecks"]}
            for k, v in sorted(base_per_position.items(), key=lambda kv: int(kv[0]))
        },
        "passive_income_effect": base_metrics["passive_income_effect"],
    }
    fingerprint_input_stressed = {
        "liquid_assets_kopecks": stressed_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": stressed_metrics["liquid_capital_net_kopecks"],
        "debts_included_kopecks": stressed_metrics["debts_included_kopecks"],
        "asset_allocation": {
            k: v
            for k, v in stressed_asset.items()
            if k.endswith("_kopecks") or k.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(stressed_account_alloc),
        "top_positions": _strip_top(stressed_top),
        "capital_goals": _strip_goals(stressed_goals_list),
        "per_position": {
            k: {"market_value_kopecks": v["market_value_kopecks"]}
            for k, v in sorted(stressed_per_position.items(), key=lambda kv: int(kv[0]))
        },
        "passive_income_effect": stressed_metrics["passive_income_effect"],
    }

    semantic_fp = semantic_fingerprint_payload(
        contract_version=CONTRACT_VERSION,
        calculation_version=CALCULATION_VERSION,
        shock_schema_version=SHOCK_SCHEMA_VERSION,
        reporting_month=reporting_month_dict,
        base_fingerprint=base_fp,
        normalized_shock=normalized_shock,
        normalized_target_scope=normalized_target_scope,
        assumptions=list(assumptions),
        base=fingerprint_input_base,
        stressed=fingerprint_input_stressed,
        impact=impact,
        row_applicability=dict(sorted(row_applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_refs=dict(sorted(affected_refs.items())),
    )

    gen_str = (
        generated_at.astimezone(timezone.utc).isoformat() if generated_at is not None else None
    )

    return ScenarioLabEvaluation(
        contract_version=CONTRACT_VERSION,
        calculation_version=CALCULATION_VERSION,
        shock_schema_version=SHOCK_SCHEMA_VERSION,
        reporting_month=reporting_month_dict,
        base_fingerprint=base_fp,
        semantic_fingerprint=semantic_fp,
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
        generated_at=gen_str,
        warnings=(),
        presentation_metadata=presentation_metadata,
    )
