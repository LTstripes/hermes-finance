"""Service adapter for Scenario Lab v1 (141-A equity + 141-B deposit rate).

Read-only, no provider/network/fx, no writes. Composes canonical read models.
Uses pure canonical Risk projection builder from domain/risk_allocation for
both base and stressed allocations (R1), implements R2-R5 fixes.

141-B deposit_rate_assumption shock is added on top of the same read model:
the canonical PercentageRate contract stays the single source of rate
semantics, and ``calculate_deposit_expected_monthly_interest_kopecks`` is
the only deposit-interest calculator.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.deposits import (
    calculate_deposit_expected_monthly_interest_kopecks,
)
from hermes_finance.domain.forecast_passive_income import (
    ExpectedFlow,
    ForecastPassiveIncomeInput,
    calculate_forecast_passive_income,
)
from hermes_finance.domain.goal_achievement import calculate_goal_achievement_forecast
from hermes_finance.domain.liquid_capital import (
    AccountAmount,
    LiquidCapitalInput,
    calculate_liquid_capital,
)
from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome
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
    canonical_assumed_rate_basis_points,
    canonical_drawdown_pct,
    canonical_json_hash,
    classify_applicability,
    normalize_drawdown_pct,
    normalized_rate_string,
    parse_assumed_annual_rate_pct,
    parse_drawdown_pct,
    semantic_fingerprint_payload,
    stressed_market_value_kopecks,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    Account,
    AppSettings,
    CashBalance,
    Debt,
    DepositSnapshot,
    Goal,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.cash_flow_ladder import build_cash_flow_ladder
from hermes_finance.services.passive_income import passive_income_for_months
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError
from hermes_finance.services.settings import parse_passive_income_history_start_month

# ---- errors with machine-readable codes ----


class ScenarioLabError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ---- helpers ----


def _validate_single_shock(shock: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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
    Exactly one of ``all_eligible_deposits`` and ``deposit_ids`` must be
    supplied.
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
        basis_points = canonical_assumed_rate_basis_points(rate_pct)
    except (TypeError, ValueError) as error:
        raise ScenarioLabError("invalid_assumed_rate_pct", str(error)) from error

    has_all = "all_eligible_deposits" in payload and payload["all_eligible_deposits"] is not None
    has_ids = "deposit_ids" in payload and payload["deposit_ids"] is not None

    if has_all and has_ids:
        raise ScenarioLabError(
            "invalid_target_selector",
            "supply exactly one of all_eligible_deposits or deposit_ids",
        )
    if not has_all and not has_ids:
        raise ScenarioLabError(
            "invalid_target_selector",
            "exactly one target selector must be supplied",
        )

    if has_all:
        if payload["all_eligible_deposits"] is not True:
            raise ScenarioLabError(
                "invalid_target_selector",
                "all_eligible_deposits must be true when supplied",
            )
        return basis_points, normalized_rate_string(basis_points), (), True

    raw_ids = payload["deposit_ids"]
    if not isinstance(raw_ids, list):
        raise ScenarioLabError("invalid_deposit_ids", "deposit_ids must be a list of integers")
    deposit_ids: list[int] = []
    for item in raw_ids:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ScenarioLabError(
                "invalid_deposit_ids",
                f"deposit_ids must contain integers, got {item!r}",
            )
        deposit_ids.append(int(item))
    if not deposit_ids:
        raise ScenarioLabError("invalid_deposit_ids", "deposit_ids must not be empty")
    unique = sorted(set(deposit_ids))
    return basis_points, normalized_rate_string(basis_points), tuple(unique), False


def _money_signed(kopecks: int) -> str:
    if kopecks >= 0:
        return _money_api(kopecks)
    return "-" + _money_api(-kopecks)


def _sorted_ids(values: list[int]) -> list[int]:
    return sorted(set(values))


def _base_fingerprint(frozen_payload: dict) -> str:
    canonical = json.dumps(
        frozen_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _money_api(kopecks: int) -> str:
    """Canonical money serialization via the RubleAmount contract."""
    return RubleAmount(kopecks).to_api()


def _allocation_metric_to_dict(metric: Any) -> dict[str, Any]:
    """Convert an asset AllocationMetric to the scenario asset_allocation dict."""
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
    for k in ("stock", "bond", "fund", "currency", "gold", "other"):
        val = buckets.get(k, 0)
        result[f"{k}_kopecks"] = val
        result[f"{k}"] = _money_api(val)
        pct = next((item.share_pct for item in metric.items if item.key == k), None)
        result[f"{k}_share_pct"] = format(pct, ".2f") if pct is not None else None
    for k in ("cash", "deposits", "unknown_asset_class"):
        pct = next((item.share_pct for item in metric.items if item.key == k), None)
        result[f"{k}_share_pct"] = format(pct, ".2f") if pct is not None else None
    return result


def _account_metric_to_list(metric: Any) -> list[dict[str, Any]]:
    """Convert an account AllocationMetric to the scenario list (ids only, R4)."""
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


def _top_metric_to_list(metric: Any) -> list[dict[str, Any]]:
    """Convert a top-positions metric to the scenario list (ids only, R4)."""
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
                "share_pct": format(item.share_pct, ".2f")
                if item.share_pct is not None
                else None,
            }
        )
    result.sort(key=lambda x: (-x["amount_kopecks"], x["position_id"]))
    return result


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


def _capture_frozen_scenario_base(
    session: Session, reporting_month_id: int
) -> tuple[ReportingMonth, dict[str, Any], dict[int, str], dict[int, str], list[CashBalance]]:
    """Single frozen-base capture phase shared by all Scenario shocks.

    One ``no_autoflush`` block reads ReportingMonth identity, cash/deposit/
    position/debt facts, account inclusion flags, instrument classification
    and relevant capital Goal inputs. The returned payload dict is the
    immutable semantic base for every later calculation; no semantic
    calculation re-reads the DB after this phase. Presentation name maps
    travel separately and stay outside semantic fingerprints.
    """
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
    return month, frozen_payload, account_names, instrument_names, cash_rows


def _frozen_capital_metrics(
    frozen_payload: dict[str, Any],
    month: ReportingMonth,
    stressed_positions: dict[int, int],
    *,
    top_n: int,
    has_unknown: bool,
) -> dict[str, Any]:
    """Canonical capital read-model surfaces from the frozen payload only.

    Liquid capital, asset/account allocations, top positions and capital
    Goal achievement for base and stressed position values — no DB access.
    Shocks that do not move positions (deposit rate) pass base values as
    ``stressed_positions`` and the two families are identical by
    construction. Deposit principal enters liquid capital unchanged: the
    deposit-rate shock re-prices forecast interest, never principal.
    """
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
    frozen_deposit_accounts = tuple(
        AccountAmount(account_id=d["account_id"], amount=RubleAmount(int(d["balance_kopecks"])))
        for d in frozen_payload["deposits"]
        if d["include_in_capital"]
    )
    frozen_securities_accounts_base = tuple(
        AccountAmount(
            account_id=p["account_id"], amount=RubleAmount(int(p["market_value_kopecks"]))
        )
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    frozen_securities_accounts_stressed = tuple(
        AccountAmount(
            account_id=p["account_id"], amount=RubleAmount(int(stressed_positions[p["id"]]))
        )
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    base_liquid = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(cash_total),
            deposits=RubleAmount(deposits_total),
            securities=RubleAmount(securities_total_base),
            included_debts=RubleAmount(debts_total),
            other_liquid_assets=RubleAmount(0),
            deposit_accounts=frozen_deposit_accounts,
            securities_accounts=frozen_securities_accounts_base,
        )
    )

    from hermes_finance.domain.risk_allocation import RiskSupportStatus as DomainRiskStatus

    if has_unknown:
        asset_support_domain = MetricSupport(
            status=DomainRiskStatus.UNKNOWN, reason_codes=("instrument_type_not_authoritative",)
        )
        account_support_domain = MetricSupport(status=DomainRiskStatus.SUPPORTED)
    else:
        asset_support_domain = MetricSupport(status=DomainRiskStatus.SUPPORTED)
        account_support_domain = MetricSupport(status=DomainRiskStatus.SUPPORTED)

    stressed_securities = sum(
        stressed_positions[p["id"]]
        for p in frozen_payload["positions"]
        if p["include_in_capital"]
    )
    stressed_liquid = calculate_liquid_capital(
        LiquidCapitalInput(
            cash=RubleAmount(cash_total),
            deposits=RubleAmount(deposits_total),
            securities=RubleAmount(stressed_securities),
            included_debts=RubleAmount(debts_total),
            other_liquid_assets=RubleAmount(0),
            deposit_accounts=frozen_deposit_accounts,
            securities_accounts=frozen_securities_accounts_stressed,
        )
    )

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

    base_goals_list: list[dict[str, Any]] = []
    stressed_goals_list: list[dict[str, Any]] = []
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

        def _goal_dict(calc: Any, _target_kopecks: int = target_kopecks) -> dict[str, Any]:
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

    return {
        "cash_total": cash_total,
        "deposits_total": deposits_total,
        "debts_total": debts_total,
        "base_liquid": base_liquid,
        "stressed_liquid": stressed_liquid,
        "base_asset": base_asset,
        "stressed_asset": stressed_asset,
        "base_account_alloc": base_account_alloc,
        "stressed_account_alloc": stressed_account_alloc,
        "base_top": base_top,
        "stressed_top": stressed_top,
        "base_goals": base_goals_list,
        "stressed_goals": stressed_goals_list,
    }


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
    """Evaluate deterministic single-shock Scenario Lab v1 evaluation.

    Currently supported shocks:
    - ``equity_drawdown`` (141-A)
    - ``deposit_rate_assumption`` (141-B)

    Combined shocks raise ``ScenarioLabError(code=unsupported_composition_v1)``.
    Invalid input is rejected with a deterministic machine-readable code.
    Read-only: no commit, no network, no provider access.
    """
    shock_type, payload = _validate_single_shock(shock)
    if shock_type == "deposit_rate_assumption":
        return _evaluate_deposit_rate_assumption(
            session, reporting_month_id, payload, top_n=top_n, generated_at=generated_at
        )
    # --- equity_drawdown path (141-A, unchanged) ---
    _validate_equity_payload(payload)
    payload = shock["equity_drawdown"]
    raw_pct = parse_drawdown_pct(payload["drawdown_pct"])
    # R3: lossless canonical via string manipulation
    canonical_pct = canonical_drawdown_pct(raw_pct)
    pct_str = normalize_drawdown_pct(canonical_pct)

    if not isinstance(top_n, int) or isinstance(top_n, bool):
        raise ScenarioLabError("invalid_top_n", "top_n must be int")
    if not 1 <= top_n <= 100:
        raise ScenarioLabError("invalid_top_n", "top_n 1..100")

    month, frozen_payload, account_names, instrument_names, cash_rows = (
        _capture_frozen_scenario_base(session, reporting_month_id)
    )

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

    cap = _frozen_capital_metrics(
        frozen_payload,
        month,
        stressed_positions,
        top_n=top_n,
        has_unknown=has_unknown,
    )

    base_metrics = {
        "liquid_assets_kopecks": cap["base_liquid"].total_assets.kopecks,
        "liquid_assets": _money_api(cap["base_liquid"].total_assets.kopecks),
        "liquid_capital_net_kopecks": cap["base_liquid"].liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(cap["base_liquid"].liquid_capital_net.kopecks),
        "debts_included_kopecks": cap["base_liquid"].total_debts_included.kopecks,
        "debts_included": _money_api(cap["base_liquid"].total_debts_included.kopecks),
        "asset_allocation": cap["base_asset"],
        "account_allocation": cap["base_account_alloc"],
        "top_positions": cap["base_top"],
        "capital_goals": sorted(cap["base_goals"], key=lambda x: x["goal_id"]),
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
        "liquid_assets_kopecks": cap["stressed_liquid"].total_assets.kopecks,
        "liquid_assets": _money_api(cap["stressed_liquid"].total_assets.kopecks),
        "liquid_capital_net_kopecks": cap["stressed_liquid"].liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(cap["stressed_liquid"].liquid_capital_net.kopecks),
        "debts_included_kopecks": cap["stressed_liquid"].total_debts_included.kopecks,
        "debts_included": _money_api(cap["stressed_liquid"].total_debts_included.kopecks),
        "asset_allocation": cap["stressed_asset"],
        "account_allocation": cap["stressed_account_alloc"],
        "top_positions": cap["stressed_top"],
        "capital_goals": sorted(cap["stressed_goals"], key=lambda x: x["goal_id"]),
        "per_position": {
            k: v for k, v in sorted(stressed_per_position.items(), key=lambda kv: int(kv[0]))
        },
        "passive_income_effect": {
            "status": "unavailable",
            "reason": "no_deterministic_income_relationship",
        },
        "future_cash_flow_rows_unchanged": True,
    }

    liquid_assets_delta = (
        cap["stressed_liquid"].total_assets.kopecks - cap["base_liquid"].total_assets.kopecks
    )
    liquid_capital_net_delta = (
        cap["stressed_liquid"].liquid_capital_net.kopecks
        - cap["base_liquid"].liquid_capital_net.kopecks
    )
    impact = {
        "liquid_assets_delta_kopecks": liquid_assets_delta,
        "liquid_assets_delta": _money_api(liquid_assets_delta)
        if liquid_assets_delta >= 0
        else "-" + _money_api(-liquid_assets_delta),
        "liquid_capital_net_delta_kopecks": liquid_capital_net_delta,
        "liquid_capital_net_delta": _money_api(liquid_capital_net_delta)
        if liquid_capital_net_delta >= 0
        else "-" + _money_api(-liquid_capital_net_delta),
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

    fingerprint_input_base = {
        "liquid_assets_kopecks": base_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": base_metrics["liquid_capital_net_kopecks"],
        "debts_included_kopecks": base_metrics["debts_included_kopecks"],
        "asset_allocation": {
            k: v
            for k, v in cap["base_asset"].items()
            if k.endswith("_kopecks") or k.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(cap["base_account_alloc"]),
        "top_positions": _strip_top(cap["base_top"]),
        "capital_goals": _strip_goals(cap["base_goals"]),
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
            for k, v in cap["stressed_asset"].items()
            if k.endswith("_kopecks") or k.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(cap["stressed_account_alloc"]),
        "top_positions": _strip_top(cap["stressed_top"]),
        "capital_goals": _strip_goals(cap["stressed_goals"]),
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

# ----------------------------------------------------------------------------
# 141-B deposit_rate_assumption
# ----------------------------------------------------------------------------
#
# Lives next to the 141-A code without changing it. The shock only re-prices
# the supported deposit-interest component of the existing canonical
# forecast/ladder calculators; principal, cash, positions, debts, liquid
# capital, allocation, concentration and capital Goals are unchanged. The
# only DB read happens once at the top of this function; everything else
# operates on the captured tuple and the canonical pure calculators.


def _load_frozen_deposit_rows(
    session: Session,
    reporting_month_id: int,
) -> list[DepositSnapshot]:
    """Frozen canonical DepositSnapshot rows for the selected month.

    Called once during the shared materialization phase; the returned rows
    are the only deposit facts any Scenario calculation may use afterwards.
    Eligibility for deposit-interest semantics covers every snapshot row of
    the month (capital inclusion is a separate concept).
    """
    with session.no_autoflush:
        deposit_snapshots = list(
            session.scalars(
                select(DepositSnapshot)
                .where(DepositSnapshot.reporting_month_id == reporting_month_id)
                .order_by(DepositSnapshot.id)
            )
        )
    return deposit_snapshots


def _load_frozen_forecast_inputs(
    session: Session,
    reporting_month_id: int,
) -> ForecastPassiveIncomeInput:
    """Frozen canonical forecast input for the deposit-rate shock."""
    with session.no_autoflush:
        merged_months = merged_payout_calendar(
            session, reporting_month_id=reporting_month_id, forecast_version="v1"
        )
        expected_flows: list[ExpectedFlow] = []
        for calendar_month in merged_months:
            for flow in calendar_month.items:
                if flow.flow_type == "redemption":
                    continue
                expected_flows.append(
                    ExpectedFlow(
                        flow_type=flow.flow_type,
                        net_amount_kopecks=flow.expected_net_amount.kopecks,
                        is_approximate=bool(flow.is_approximate),
                    )
                )
        deposit_monthly = session.scalars(
            select(DepositSnapshot.expected_monthly_interest_kopecks).where(
                DepositSnapshot.reporting_month_id == reporting_month_id
            )
        ).all()
        deposit_monthly_sum = sum(deposit_monthly) if deposit_monthly else None

        from hermes_finance.domain.reporting import ReportingMonthStatus

        closed_months = session.execute(
            select(ReportingMonth.id, ReportingMonth.year, ReportingMonth.month)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED.value)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        ).all()
        results_by_month = passive_income_for_months(
            session, [month_id for month_id, _, _ in closed_months]
        )
        dividend_months: list[MonthlyPassiveIncome] = []
        for month_id, year, month_number in closed_months:
            dividend_months.append(
                MonthlyPassiveIncome(
                    year=year,
                    month=month_number,
                    amount=results_by_month[month_id].breakdown.dividends,
                )
            )
        settings = session.scalar(
            select(AppSettings).where(AppSettings.id == APP_SETTINGS_ID)
        )
        history_start = parse_passive_income_history_start_month(
            settings.passive_income_history_start_month if settings is not None else None
        )
    return ForecastPassiveIncomeInput(
        expected_flows=tuple(expected_flows),
        dividend_months=tuple(dividend_months),
        history_start_month=history_start,
        deposit_snapshot_monthly_interest_kopecks=deposit_monthly_sum,
    )


def _project_forecast(
    base_inputs: ForecastPassiveIncomeInput,
    *,
    deposit_monthly: int | None,
) -> dict:
    """Run the canonical passive-income forecast on the frozen inputs.

    ``deposit_monthly`` replaces only the selected-month deposit-snapshot
    monthly-interest sum; everything else is frozen canonical input.
    """
    stressed_inputs = ForecastPassiveIncomeInput(
        expected_flows=base_inputs.expected_flows,
        dividend_months=base_inputs.dividend_months,
        history_start_month=base_inputs.history_start_month,
        deposit_snapshot_monthly_interest_kopecks=deposit_monthly,
    )
    result = calculate_forecast_passive_income(stressed_inputs)
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


def _project_ladder(ladder: Any, *, deposit_monthly: int | None) -> list[dict]:
    months: list[dict] = []
    for month in ladder.months:
        coupon = month.coupon.kopecks
        dividend = month.dividend.kopecks
        other = month.other_capital_income.kopecks
        redemption = month.redemption_principal.kopecks
        if deposit_monthly is None:
            deposit_kopecks = month.deposit_interest.kopecks
        else:
            deposit_kopecks = deposit_monthly
        passive = coupon + dividend + deposit_kopecks + other
        total = passive + redemption
        months.append(
            {
                "year": month.year,
                "month": month.month,
                "coupon_kopecks": coupon,
                "coupon": _money_api(coupon),
                "dividend_kopecks": dividend,
                "dividend": _money_api(dividend),
                "deposit_interest_kopecks": deposit_kopecks,
                "deposit_interest": _money_api(deposit_kopecks),
                "other_capital_income_kopecks": other,
                "other_capital_income": _money_api(other),
                "redemption_principal_kopecks": redemption,
                "redemption_principal": _money_api(redemption),
                "passive_income_kopecks": passive,
                "passive_income": _money_api(passive),
                "total_cash_flow_kopecks": total,
                "total_cash_flow": _money_api(total),
                "is_approximate": bool(month.is_approximate),
            }
        )
    return months


def _ladder_window_dict(window: Any) -> dict:
    return {
        "days": window.days,
        "from_date": window.from_date.isoformat(),
        "to_date": window.to_date.isoformat(),
        "passive_income_kopecks": window.passive_income.kopecks,
        "passive_income": _money_api(window.passive_income.kopecks),
        "redemption_principal_kopecks": window.redemption_principal.kopecks,
        "redemption_principal": _money_api(window.redemption_principal.kopecks),
        "total_cash_flow_kopecks": window.total_cash_flow.kopecks,
        "total_cash_flow": _money_api(window.total_cash_flow.kopecks),
        "events": [
            {
                "expected_date": event.expected_date.isoformat(),
                "flow_type": event.flow_type,
                "component": event.component,
                "account_id": event.account_id,
                "instrument_id": event.instrument_id,
                "expected_net_amount_kopecks": event.expected_net_amount.kopecks,
                "is_approximate": bool(event.is_approximate),
                "source_kind": str(event.source_kind.value),
                "source_id": int(event.source_id),
            }
            for event in window.items
        ],
    }


def _ladder_dict(ladder: Any, deposit_monthly: int | None) -> dict:
    return {
        "as_of_date": ladder.as_of_date.isoformat(),
        "forecast_version": ladder.forecast_version,
        "months": _project_ladder(ladder, deposit_monthly=deposit_monthly),
        "upcoming_14_days": _ladder_window_dict(ladder.upcoming_14_days),
        "upcoming_30_days": _ladder_window_dict(ladder.upcoming_30_days),
    }


def _project_deposit_rows(
    deposit_snapshots: list[DepositSnapshot],
    *,
    target_set: set[int],
    rate_basis_points: int,
) -> tuple[dict, dict, dict, dict, int]:
    base_rows: dict[str, dict] = {}
    stressed_rows: dict[str, dict] = {}
    impact_rows: dict[str, dict] = {}
    applicability: dict[str, str] = {}
    base_total = 0
    stressed_total = 0
    for deposit in sorted(deposit_snapshots, key=lambda d: d.id):
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


def _frozen_base_fingerprint_for_deposit_rate(
    *,
    reporting_month: ReportingMonth,
    deposit_snapshots: list[DepositSnapshot],
    forecast_inputs: ForecastPassiveIncomeInput,
    ladder: Any,
) -> str:
    payload = {
        "reporting_month": {
            "id": reporting_month.id,
            "year": reporting_month.year,
            "month": reporting_month.month,
            "snapshot_date": reporting_month.snapshot_date.isoformat(),
            "status": reporting_month.status,
        },
        "deposits": sorted(
            [
                {
                    "id": deposit.id,
                    "account_id": deposit.account_id,
                    "deposit_type": deposit.deposit_type,
                    "balance_kopecks": deposit.balance_kopecks,
                    "annual_rate_basis_points": deposit.annual_rate_basis_points,
                    "expected_monthly_interest_kopecks": deposit.expected_monthly_interest_kopecks,
                }
                for deposit in deposit_snapshots
            ],
            key=lambda item: item["id"],
        ),
        "forecast": {
            "expected_flows": [
                {
                    "flow_type": flow.flow_type,
                    "net_amount_kopecks": flow.net_amount_kopecks,
                    "is_approximate": flow.is_approximate,
                }
                for flow in forecast_inputs.expected_flows
            ],
            "dividend_months": [
                {
                    "year": dividend.year,
                    "month": dividend.month,
                    "amount_kopecks": dividend.amount.kopecks,
                }
                for dividend in forecast_inputs.dividend_months
            ],
            "history_start_month": (
                f"{forecast_inputs.history_start_month[0]:04d}-{forecast_inputs.history_start_month[1]:02d}"
                if forecast_inputs.history_start_month is not None
                else None
            ),
            "deposit_snapshot_monthly_interest_kopecks": (
                forecast_inputs.deposit_snapshot_monthly_interest_kopecks
            ),
        },
        "ladder_months": [
            {
                "year": month.year,
                "month": month.month,
                "coupon_kopecks": month.coupon.kopecks,
                "dividend_kopecks": month.dividend.kopecks,
                "deposit_interest_kopecks": month.deposit_interest.kopecks,
                "other_capital_income_kopecks": month.other_capital_income.kopecks,
                "redemption_principal_kopecks": month.redemption_principal.kopecks,
                "passive_income_kopecks": month.passive_income.kopecks,
                "total_cash_flow_kopecks": month.total_cash_flow.kopecks,
                "is_approximate": bool(month.is_approximate),
            }
            for month in ladder.months
        ],
    }
    return canonical_json_hash(payload)


def _strip_deposit_rows_for_fingerprint(rows: dict[str, dict]) -> dict:
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


def _ladder_fingerprint_dict(ladder_dict: dict) -> dict:
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
        "upcoming_14_days": ladder_dict["upcoming_14_days"],
        "upcoming_30_days": ladder_dict["upcoming_30_days"],
    }


def _evaluate_deposit_rate_assumption(
    session: Session,
    reporting_month_id: int,
    payload: dict[str, Any],
    *,
    top_n: int,
    generated_at: datetime | None,
) -> ScenarioLabEvaluation:
    rate_basis_points, rate_string, requested_ids, all_eligible = _parse_deposit_rate_input(payload)

    # Materialization phase: shared frozen base + deposit ORM rows.
    # Every semantic calculation below operates on these captures only.
    month, frozen_payload, account_names, instrument_names, _cash_rows = (
        _capture_frozen_scenario_base(session, reporting_month_id)
    )
    deposit_snapshots = _load_frozen_deposit_rows(session, reporting_month_id)
    deposit_by_id = {deposit.id: deposit for deposit in deposit_snapshots}

    if all_eligible:
        target_ids = sorted(deposit_by_id)
    else:
        missing = [d_id for d_id in requested_ids if d_id not in deposit_by_id]
        if missing:
            raise ScenarioLabError(
                "foreign_month_deposit_id",
                f"deposit_ids do not belong to the selected frozen reporting month: {missing}",
            )
        target_ids = sorted(requested_ids)
    target_set = set(target_ids)

    base_forecast_inputs = _load_frozen_forecast_inputs(session, reporting_month_id)
    ladder = build_cash_flow_ladder(session, reporting_month_id=reporting_month_id)

    base_rows, stressed_rows, impact_rows, applicability, total_delta = _project_deposit_rows(
        deposit_snapshots,
        target_set=target_set,
        rate_basis_points=rate_basis_points,
    )

    if deposit_snapshots:
        base_deposit_monthly = sum(
            deposit.expected_monthly_interest_kopecks for deposit in deposit_snapshots
        )
        stressed_deposit_monthly = sum(
            stressed_rows[str(deposit.id)]["expected_monthly_interest_kopecks"]
            for deposit in deposit_snapshots
        )
    else:
        base_deposit_monthly = None
        stressed_deposit_monthly = None

    base_forecast = _project_forecast(
        base_forecast_inputs, deposit_monthly=base_deposit_monthly
    )
    stressed_forecast = _project_forecast(
        base_forecast_inputs, deposit_monthly=stressed_deposit_monthly
    )
    base_ladder_dict = _ladder_dict(ladder, deposit_monthly=base_deposit_monthly)
    stressed_ladder_dict = _ladder_dict(ladder, deposit_monthly=stressed_deposit_monthly)

    # Capital surfaces: deposit-rate shock never moves principal, cash,
    # positions or debts — stressed position values equal base by design.
    stressed_positions = {p["id"]: p["market_value_kopecks"] for p in frozen_payload["positions"]}
    cap = _frozen_capital_metrics(
        frozen_payload,
        month,
        stressed_positions,
        top_n=top_n,
        has_unknown=False,
    )

    base_fp = _frozen_base_fingerprint_for_deposit_rate(
        reporting_month=month,
        deposit_snapshots=deposit_snapshots,
        forecast_inputs=base_forecast_inputs,
        ladder=ladder,
    )

    if all_eligible:
        selector = "all_eligible_deposits"
    else:
        selector = "deposit_ids"
    normalized_target_scope = {
        "selector": selector,
        "deposit_ids": list(target_ids),
        "eligible_deposit_ids": sorted(deposit_by_id),
    }

    applied_count = sum(1 for value in applicability.values() if value == "applied")
    not_applicable_count = sum(
        1 for value in applicability.values() if value == "not_applicable"
    )
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
            key: value
            for key, value in sorted(impact_rows.items(), key=lambda kv: int(kv[0]))
        },
    }
    coverage = {
        "total_deposits": len(deposit_snapshots),
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
        "passive_income_goal": {"status": "supported", "reason_codes": []},
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

    affected_refs = {
        "reporting_month_id": reporting_month_id,
        "deposit_ids": _sorted_ids([deposit.id for deposit in deposit_snapshots]),
        "account_ids": _sorted_ids([deposit.account_id for deposit in deposit_snapshots]),
        "position_ids": [],
        "instrument_ids": [],
        "cash_ids": [],
    }

    reporting_month_dict = {
        "id": month.id,
        "year": month.year,
        "month": month.month,
        "snapshot_date": month.snapshot_date.isoformat(),
        "status": month.status,
    }
    normalized_shock = {
        "shock_type": "deposit_rate_assumption",
        "assumed_annual_rate_pct": rate_string,
        "annual_rate_basis_points": rate_basis_points,
    }

    passive_income_goal_effect = {
        "status": "unchanged",
        "basis": "historical_actual_rolling_average",
        "affected": False,
    }

    base_metrics = {
        "liquid_assets_kopecks": cap["base_liquid"].total_assets.kopecks,
        "liquid_assets": _money_api(cap["base_liquid"].total_assets.kopecks),
        "liquid_capital_net_kopecks": cap["base_liquid"].liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(cap["base_liquid"].liquid_capital_net.kopecks),
        "debts_included_kopecks": cap["base_liquid"].total_debts_included.kopecks,
        "debts_included": _money_api(cap["base_liquid"].total_debts_included.kopecks),
        "asset_allocation": cap["base_asset"],
        "account_allocation": cap["base_account_alloc"],
        "top_positions": cap["base_top"],
        "capital_goals": sorted(cap["base_goals"], key=lambda x: x["goal_id"]),
        "per_deposit": {
            key: value
            for key, value in sorted(base_rows.items(), key=lambda kv: int(kv[0]))
        },
        "forecast_passive_income": base_forecast,
        "cash_flow_ladder": base_ladder_dict,
        "passive_income_goal_effect": passive_income_goal_effect,
        "future_cash_flow_rows_unchanged": True,
    }
    stressed_metrics = {
        "liquid_assets_kopecks": cap["stressed_liquid"].total_assets.kopecks,
        "liquid_assets": _money_api(cap["stressed_liquid"].total_assets.kopecks),
        "liquid_capital_net_kopecks": cap["stressed_liquid"].liquid_capital_net.kopecks,
        "liquid_capital_net": _money_api(cap["stressed_liquid"].liquid_capital_net.kopecks),
        "debts_included_kopecks": cap["stressed_liquid"].total_debts_included.kopecks,
        "debts_included": _money_api(cap["stressed_liquid"].total_debts_included.kopecks),
        "asset_allocation": cap["stressed_asset"],
        "account_allocation": cap["stressed_account_alloc"],
        "top_positions": cap["stressed_top"],
        "capital_goals": sorted(cap["stressed_goals"], key=lambda x: x["goal_id"]),
        "per_deposit": {
            key: value
            for key, value in sorted(stressed_rows.items(), key=lambda kv: int(kv[0]))
        },
        "forecast_passive_income": stressed_forecast,
        "cash_flow_ladder": stressed_ladder_dict,
        "passive_income_goal_effect": passive_income_goal_effect,
        "future_cash_flow_rows_unchanged": True,
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

    fingerprint_input_base = {
        "liquid_assets_kopecks": base_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": base_metrics["liquid_capital_net_kopecks"],
        "debts_included_kopecks": base_metrics["debts_included_kopecks"],
        "asset_allocation": {
            k: v
            for k, v in cap["base_asset"].items()
            if k.endswith("_kopecks") or k.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(cap["base_account_alloc"]),
        "top_positions": _strip_top(cap["base_top"]),
        "capital_goals": _strip_goals(cap["base_goals"]),
        "per_deposit": _strip_deposit_rows_for_fingerprint(base_rows),
        "forecast_passive_income": forecast_fingerprint_base,
        "cash_flow_ladder": _ladder_fingerprint_dict(base_ladder_dict),
    }
    fingerprint_input_stressed = {
        "liquid_assets_kopecks": stressed_metrics["liquid_assets_kopecks"],
        "liquid_capital_net_kopecks": stressed_metrics["liquid_capital_net_kopecks"],
        "debts_included_kopecks": stressed_metrics["debts_included_kopecks"],
        "asset_allocation": {
            k: v
            for k, v in cap["stressed_asset"].items()
            if k.endswith("_kopecks") or k.endswith("_share_pct")
        },
        "account_allocation": _strip_account_alloc(cap["stressed_account_alloc"]),
        "top_positions": _strip_top(cap["stressed_top"]),
        "capital_goals": _strip_goals(cap["stressed_goals"]),
        "per_deposit": _strip_deposit_rows_for_fingerprint(stressed_rows),
        "forecast_passive_income": forecast_fingerprint_stressed,
        "cash_flow_ladder": _ladder_fingerprint_dict(stressed_ladder_dict),
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
        row_applicability=dict(sorted(applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_refs=dict(sorted(affected_refs.items())),
    )

    gen_str = (
        generated_at.astimezone(timezone.utc).isoformat() if generated_at is not None else None
    )
    presentation_metadata = {
        "account_names": dict(sorted(account_names.items())),
        "deposit_names": {
            deposit.id: deposit.name
            for deposit in sorted(deposit_snapshots, key=lambda d: d.id)
        },
    }
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
        row_applicability=dict(sorted(applicability.items(), key=lambda kv: int(kv[0]))),
        metric_support=dict(sorted(metric_support.items())),
        coverage=coverage,
        affected_canonical_refs=dict(sorted(affected_refs.items())),
        generated_at=gen_str,
        warnings=(),
        presentation_metadata=presentation_metadata,
    )
