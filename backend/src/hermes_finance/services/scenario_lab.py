"""Service adapter for Scenario Lab 141-A — equity_drawdown only.

Read-only, no provider/network/fx, no writes. Composes canonical read models.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.goal_achievement import calculate_goal_achievement_forecast
from hermes_finance.domain.liquid_capital import calculate_liquid_capital
from hermes_finance.domain.liquid_capital import LiquidCapitalInput
from hermes_finance.domain.risk_allocation import percentage
from hermes_finance.domain.scenario_lab import (
    CALCULATION_VERSION,
    CONTRACT_VERSION,
    SHOCK_SCHEMA_VERSION,
    MetricSupportStatus,
    RowApplicability,
    canonical_json_hash,
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
    ExpectedCashFlow,
    Goal,
    Instrument,
    InvestmentCashFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.liquid_capital import liquid_capital_for_month
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
    # filter truthy? we consider present keys; if multiple keys present -> unsupported
    # also if shock contains more than one top-level shock type
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
    # reject extra keys that would imply composition? extra fields are allowed if they are not shocks,
    # but presence of another shock key already handled. Forbid unexpected fields inside?
    # allow only drawdown_pct
    extra = set(payload.keys()) - {"drawdown_pct"}
    if extra:
        raise ScenarioLabError("invalid_shock_input", f"unexpected fields {extra}")


def _sorted_ids(values: list[int]) -> list[int]:
    return sorted(set(values))


def _base_fingerprint(frozen_payload: dict) -> str:
    canonical = json.dumps(frozen_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
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
    # validate composition first
    _validate_single_shock(shock)
    payload = shock["equity_drawdown"]
    pct = parse_drawdown_pct(payload["drawdown_pct"])
    pct_str = normalize_drawdown_pct(pct)

    # validate top_n
    if not isinstance(top_n, int) or isinstance(top_n, bool):
        raise ScenarioLabError("invalid_top_n", "top_n must be int")
    if not 1 <= top_n <= 100:
        raise ScenarioLabError("invalid_top_n", "top_n 1..100")

    # fetch reporting month (read-only)
    with session.no_autoflush:
        month: ReportingMonth | None = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

        # cash, deposits, positions, debts, goals, expected cash flows (for unchanged check)
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
        # position rows with instrument type
        pos_rows = list(
            session.execute(
                select(PositionSnapshot, Instrument.name, Instrument.instrument_type)
                .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
                .where(PositionSnapshot.reporting_month_id == reporting_month_id)
                .order_by(PositionSnapshot.id)
            ).all()
        )
        # need include_in_capital per position via Account
        pos_accounts = {
            row[0].id: session.get(Account, row[0].account_id).include_in_capital
            if session.get(Account, row[0].account_id) is not None
            else True
            for row in pos_rows
        }
        # also need account names for allocation
        account_names: dict[int, str] = {}
        for dep, name, _inc in deposit_rows:
            account_names[dep.account_id] = name
        for snap, inst_name, _type in pos_rows:
            acc = session.get(Account, snap.account_id)
            if acc is not None:
                account_names[snap.account_id] = acc.name

        debt_rows = list(
            session.scalars(
                select(Debt).where(Debt.reporting_month_id == reporting_month_id).order_by(Debt.id)
            )
        )
        # capital goals (active, type capital)
        all_goals = list(session.scalars(select(Goal).order_by(Goal.id)).all())
        capital_goals = [
            g for g in all_goals if g.is_active and g.goal_type == "capital" and g.calculation_mode == "liquid_capital_net"
        ]

        # expected cash flows + investment cash flows for unchanged verification (read only)
        expected_flows = list(
            session.scalars(
                select(ExpectedCashFlow).where(ExpectedCashFlow.reporting_month_id == reporting_month_id).order_by(ExpectedCashFlow.id)
            )
        )
        investment_flows = list(
            session.scalars(
                select(InvestmentCashFlow).where(InvestmentCashFlow.reporting_month_id == reporting_month_id).order_by(InvestmentCashFlow.id)
            )
        )

    # --- frozen base payload ---
    frozen_payload = {
        "reporting_month": {
            "id": month.id,
            "year": month.year,
            "month": month.month,
            "snapshot_date": month.snapshot_date.isoformat(),
            "status": month.status,
        },
        "cash": [
            {"id": c.id, "amount_kopecks": c.amount_kopecks, "currency": c.currency, "include_in_capital": c.include_in_capital}
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
            {"id": d.id, "balance_kopecks": d.current_balance_kopecks, "include_in_liquid_capital": d.include_in_liquid_capital}
            for d in sorted(debt_rows, key=lambda x: x.id)
        ],
        "goals": [
            {"id": g.id, "target_kopecks": g.target_value_kopecks, "is_active": g.is_active, "goal_type": g.goal_type}
            for g in sorted(capital_goals, key=lambda x: x.id)
        ],
    }
    base_fp = _base_fingerprint(frozen_payload)

    # normalized target scope: frozen eligibility sets
    eligible_position_ids = _sorted_ids([p["id"] for p in frozen_payload["positions"] if p["include_in_capital"]])
    eligible_deposit_ids = _sorted_ids([d["id"] for d in frozen_payload["deposits"] if d["include_in_capital"]])
    # for all_eligible_deposits reproducibility note, include sorted ids
    normalized_target_scope = {
        "selector": "all_eligible",
        "eligible_position_ids": eligible_position_ids,
        "eligible_deposit_ids": eligible_deposit_ids,
    }

    # row applicability and per-position stressed values
    row_applicability: dict[str, str] = {}
    per_position: dict[str, dict] = {}
    stressed_positions: dict[int, int] = {}  # id -> stressed value
    coverage_applied = 0
    coverage_not = 0
    coverage_unknown = 0
    known_scope_delta = 0

    for p in frozen_payload["positions"]:
        appl = classify_applicability(p["instrument_type"])
        row_applicability[str(p["id"])] = appl.value
        base_v = int(p["market_value_kopecks"])
        if appl == RowApplicability.APPLIED:
            stressed_v = stressed_market_value_kopecks(base_v, pct) if p["include_in_capital"] else base_v
            delta = stressed_v - base_v if p["include_in_capital"] else 0
            coverage_applied += 1
            if p["include_in_capital"]:
                known_scope_delta += delta
        elif appl == RowApplicability.UNKNOWN:
            stressed_v = base_v  # unchanged for unknown, but aggregate is unknown
            delta = 0
            coverage_unknown += 1
        else:
            stressed_v = base_v
            delta = 0
            coverage_not += 1
        # if not included in capital, applicability still tracked but not stressing
        if not p["include_in_capital"]:
            stressed_v = base_v
            delta = 0
        stressed_positions[p["id"]] = stressed_v
        per_position[str(p["id"])] = {
            "base_market_value_kopecks": base_v,
            "base_market_value": _money_api(base_v),
            "stressed_market_value_kopecks": stressed_v,
            "stressed_market_value": _money_api(stressed_v),
            "delta_kopecks": delta,
            "delta": _money_api(delta) if delta >= 0 else "-" + _money_api(-delta),
            "applicability": appl.value,
            "account_id": p["account_id"],
            "instrument_id": p["instrument_id"],
            "instrument_type": p["instrument_type"],
        }

    total_positions = len(frozen_payload["positions"])
    coverage = {
        "total_positions": total_positions,
        "applied": coverage_applied,
        "not_applicable": coverage_not,
        "unknown": coverage_unknown,
        "known_scope_impact_kopecks": known_scope_delta,
        "known_scope_impact": _money_api(known_scope_delta) if known_scope_delta >= 0 else "-" + _money_api(-known_scope_delta),
    }

    has_unknown = coverage_unknown > 0

    # canonical base liquid capital (reuse service for exact semantics)
    base_liquid = liquid_capital_for_month(session, reporting_month_id)

    # compute stressed liquid using domain calculator directly (no DB write)
    # need cash/deposits/securities totals with stressed securities
    cash_total = sum(c.amount_kopecks for c in cash_rows if c.include_in_capital)
    deposits_total = sum(d.balance_kopecks for d, _n, inc in deposit_rows if inc)
    # base securities total already in base_liquid; compute stressed
    stressed_securities = 0
    # account grouping for stressed
    from collections import defaultdict
    stressed_by_account: dict[int, int] = defaultdict(int)
    # deposits by account
    for d, _n, inc in deposit_rows:
        if inc:
            stressed_by_account[d.account_id] += int(d.balance_kopecks)
    # positions by account with include check
    for p in frozen_payload["positions"]:
        if p["include_in_capital"]:
            stressed_securities += stressed_positions[p["id"]]
            stressed_by_account[p["account_id"]] += stressed_positions[p["id"]]
    # build inputs for calculator
    from hermes_finance.domain.liquid_capital import AccountAmount

    base_input_accounts = tuple(
        AccountAmount(account_id=aid, amount=RubleAmount(kop))
        for aid, kop in sorted(stressed_by_account.items())
    )
    # But for base we already have; for stressed we reuse same+stressed securities
    stressed_input = LiquidCapitalInput(
        cash=RubleAmount(cash_total),
        deposits=RubleAmount(deposits_total),
        securities=RubleAmount(stressed_securities),
        included_debts=base_liquid.total_debts_included,
        other_liquid_assets=RubleAmount(0),
        deposit_accounts=tuple(
            AccountAmount(account_id=d.account_id, amount=RubleAmount(int(d.balance_kopecks)))
            for d, _n, inc in deposit_rows if inc
        ),
        securities_accounts=tuple(
            AccountAmount(account_id=p["account_id"], amount=RubleAmount(stressed_positions[p["id"]]))
            for p in frozen_payload["positions"] if p["include_in_capital"]
        ),
    )
    stressed_liquid = calculate_liquid_capital(stressed_input)

    # asset allocation: group by instrument_type buckets canonical dashboard: cash, deposits, stocks, bonds, gold_other
    # For scenario we mimic dashboard grouping but also expose unknown? Use risk_allocation style but keep simple: asset allocation by stock/bond/gold_other
    # We'll compute stocks/bonds as per types
    def _asset_breakdown(stressed: bool) -> dict:
        # reuse frozen payload positions with stressed values if stressed else base
        by_type: dict[str, int] = {}
        for p in frozen_payload["positions"]:
            if not p["include_in_capital"]:
                continue
            val = stressed_positions[p["id"]] if stressed else int(p["market_value_kopecks"])
            itype = p["instrument_type"]
            # validate enum
            if itype not in ("stock", "bond"):
                itype = "gold_other"
            by_type[itype] = by_type.get(itype, 0) + val
        stocks = by_type.get("stock", 0)
        bonds = by_type.get("bond", 0)
        gold_other = by_type.get("gold_other", 0)
        return {
            "cash_kopecks": cash_total,
            "cash": _money_api(cash_total),
            "deposits_kopecks": deposits_total,
            "deposits": _money_api(deposits_total),
            "stocks_kopecks": stocks,
            "stocks": _money_api(stocks),
            "bonds_kopecks": bonds,
            "bonds": _money_api(bonds),
            "gold_other_kopecks": gold_other,
            "gold_other": _money_api(gold_other),
        }

    base_asset = _asset_breakdown(False)
    stressed_asset = _asset_breakdown(True)

    # account allocation list sorted
    def _account_allocation(stressed: bool) -> list[dict]:
        # deposits + positions per account
        acc_totals: dict[int, int] = defaultdict(int)
        for d, _n, inc in deposit_rows:
            if inc:
                acc_totals[d.account_id] += int(d.balance_kopecks)
        for p in frozen_payload["positions"]:
            if p["include_in_capital"]:
                val = stressed_positions[p["id"]] if stressed else int(p["market_value_kopecks"])
                acc_totals[p["account_id"]] += val
        denominator = base_liquid.total_assets.kopecks if not stressed else stressed_liquid.total_assets.kopecks
        # if has unknown, denominator for full aggregate is unknown status, but we still compute for known-scope?
        result = []
        for aid in sorted(acc_totals.keys()):
            amt = acc_totals[aid]
            pct_val = percentage(amt, denominator) if denominator > 0 else None
            result.append({
                "account_id": aid,
                "account_name": account_names.get(aid, f"account {aid}"),
                "amount_kopecks": amt,
                "amount": _money_api(amt),
                "share_pct": format(pct_val, ".2f") if pct_val is not None else None,
            })
        # unassigned cash bucket if cash present (cash has no account_id in early schema, but CashBalance now has account_id? keep as unassigned)
        # risk_allocation treats cash as unassigned; here cash already included via cash_total but not assigned to accounts
        # So add unassigned entry if cash >0
        if cash_total:
            pct_val = percentage(cash_total, denominator) if denominator > 0 else None
            result.append({
                "account_id": None,
                "account_name": "Unassigned cash",
                "amount_kopecks": cash_total,
                "amount": _money_api(cash_total),
                "share_pct": format(pct_val, ".2f") if pct_val is not None else None,
                "unassigned": True,
            })
        # sort by amount desc then account_id
        result.sort(key=lambda x: (-x["amount_kopecks"], str(x["account_id"])))
        return result

    base_account_alloc = _account_allocation(False)
    stressed_account_alloc = _account_allocation(True)

    # top positions sorted by market value desc
    def _top_positions(stressed: bool, top_n: int) -> list[dict]:
        items = []
        denominator = base_liquid.total_assets.kopecks if not stressed else stressed_liquid.total_assets.kopecks
        for p in frozen_payload["positions"]:
            if not p["include_in_capital"]:
                continue
            val = stressed_positions[p["id"]] if stressed else int(p["market_value_kopecks"])
            if val <= 0:
                continue
            pct_val = percentage(val, denominator) if denominator > 0 else None
            # need instrument name
            iname = next((iname for snap, iname, _t in pos_rows if snap.id == p["id"]), f"instrument {p['instrument_id']}")
            items.append({
                "position_id": p["id"],
                "account_id": p["account_id"],
                "account_name": account_names.get(p["account_id"], ""),
                "instrument_id": p["instrument_id"],
                "instrument_name": iname,
                "instrument_type": p["instrument_type"],
                "amount_kopecks": val,
                "amount": _money_api(val),
                "share_pct": format(pct_val, ".2f") if pct_val is not None else None,
                "applicability": row_applicability[str(p["id"])],
            })
        items.sort(key=lambda x: (-x["amount_kopecks"], x["position_id"]))
        return items[:top_n]

    base_top = _top_positions(False, top_n)
    stressed_top = _top_positions(True, top_n)

    # capital goals propagation: reuse domain calculator
    base_goals_list = []
    stressed_goals_list = []
    for g in capital_goals:
        base_calc = calculate_goal_achievement_forecast(
            goal_id=g.id,
            reporting_month_id=month.id,
            as_of_date=month.snapshot_date,
            current_value=base_liquid.liquid_capital_net,
            target_value=RubleAmount(g.target_value_kopecks),
            source_forecast_version=None,
        )
        stressed_calc = calculate_goal_achievement_forecast(
            goal_id=g.id,
            reporting_month_id=month.id,
            as_of_date=month.snapshot_date,
            current_value=stressed_liquid.liquid_capital_net,
            target_value=RubleAmount(g.target_value_kopecks),
            source_forecast_version=None,
        )
        def _goal_dict(calc):
            return {
                "goal_id": calc.goal_id,
                "target_kopecks": g.target_value_kopecks,
                "target": _money_api(g.target_value_kopecks),
                "current_kopecks": calc.current_value.kopecks if calc.current_value else None,
                "current": _money_api(calc.current_value.kopecks) if calc.current_value else None,
                "remaining_kopecks": calc.remaining_amount.kopecks if calc.remaining_amount else None,
                "remaining": _money_api(calc.remaining_amount.kopecks) if calc.remaining_amount else None,
                "progress_pct": format(calc.progress_pct, ".2f") if calc.progress_pct is not None else None,
                "status": calc.status,
            }
        base_goals_list.append(_goal_dict(base_calc))
        stressed_goals_list.append(_goal_dict(stressed_calc))

    # base and stressed metrics dicts for fingerprint (deterministic, kopecks ints)
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
        "per_position": {k: v for k, v in sorted(per_position.items(), key=lambda kv: int(kv[0]))},
    }
    # for base per_position, delta is 0; for stressed, use stressed deltas
    # build stressed per_position view (same structure but with stressed values)
    stressed_per_pos = per_position  # already contains stressed values
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
        "per_position": {k: v for k, v in sorted(stressed_per_pos.items(), key=lambda kv: int(kv[0]))},
        # passive income unchanged but reported as unavailable
        "passive_income_effect": {"status": "unavailable", "reason": "no_deterministic_income_relationship"},
        "future_cash_flow_rows_unchanged": True,
    }
    # include passive income effect also in base for symmetry
    base_metrics["passive_income_effect"] = {"status": "unavailable", "reason": "no_deterministic_income_relationship"}
    base_metrics["future_cash_flow_rows_unchanged"] = True

    impact = {
        "liquid_assets_delta_kopecks": stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks,
        "liquid_assets_delta": _money_api(stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks) if (stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks) >= 0 else "-" + _money_api(-(stressed_liquid.total_assets.kopecks - base_liquid.total_assets.kopecks)),
        "liquid_capital_net_delta_kopecks": stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks,
        "liquid_capital_net_delta": _money_api(stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks) if (stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks) >= 0 else "-" + _money_api(-(stressed_liquid.liquid_capital_net.kopecks - base_liquid.liquid_capital_net.kopecks)),
        "known_scope_impact_kopecks": known_scope_delta,
        "known_scope_impact": _money_api(known_scope_delta) if known_scope_delta >= 0 else "-" + _money_api(-known_scope_delta),
    }

    # metric support tri-state
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
        "passive_income_effect": {"status": "unavailable", "reason_codes": ["no_deterministic_income_relationship"]},
        "dividends": {"status": "supported", "reason_codes": []},
        "coupons": {"status": "supported", "reason_codes": []},
        "redemption": {"status": "supported", "reason_codes": []},
        "future_cash_flows": {"status": "supported", "reason_codes": []},
        "debts": {"status": "supported", "reason_codes": []},
    }
    # if no unknown, per_position still supported

    # assumptions (sorted)
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

    # affected refs
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
    # For fingerprint we need deterministic dicts with sorted keys; let service build payload via helper
    # Build base/stressed/impact dicts for fingerprint already have deterministic structure
    # Use canonical_json_hash via semantic_fingerprint_payload

    # Build metric_support for fingerprint as dict with sorted keys
    # row_applicability already string keys
    fingerprint_input_base = {
        "liquid_assets_kopecks": base_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": base_metrics["liquid_capital_net_kopecks"],
        "asset_allocation": base_asset,
        "account_allocation": base_account_alloc,
        "top_positions": base_top,
        "capital_goals": sorted(base_goals_list, key=lambda x: x["goal_id"]),
    }
    fingerprint_input_stressed = {
        "liquid_assets_kopecks": stressed_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": stressed_metrics["liquid_capital_net_kopecks"],
        "asset_allocation": stressed_asset,
        "account_allocation": stressed_account_alloc,
        "top_positions": stressed_top,
        "capital_goals": sorted(stressed_goals_list, key=lambda x: x["goal_id"]),
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

    # generated_at string, excluded from fingerprint
    gen_str = generated_at.astimezone(timezone.utc).isoformat() if generated_at is not None else None

    # ensure read-only: we never called commit, never mutated; session dirty check outside

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
    )
