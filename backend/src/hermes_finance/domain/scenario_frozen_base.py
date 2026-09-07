"""Pure frozen Scenario base DTOs (Scenario Lab v1).

Once ``FrozenScenarioBase`` has been materialized from the database, no
semantic Scenario calculation may perform a new DB read: base, stressed,
impact, support, normalized target scope, fingerprints, Goal calculations,
passive-income forecast and cash-flow projection all operate on this
immutable capture only.

Presentation-only labels stay out of semantic fingerprints; they travel in
separate presentation metadata.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class FrozenCash:
    id: int
    account_id: int | None
    name: str
    amount_kopecks: int
    currency: str
    include_in_capital: bool


@dataclass(frozen=True, slots=True)
class FrozenDeposit:
    """Frozen canonical DepositSnapshot facts for the selected month.

    ``include_in_capital`` is the frozen account-level capital-inclusion flag.
    Scenario deposit-interest eligibility is NOT equal to this flag: forecast
    semantics use every canonical DepositSnapshot row of the month.
    """

    id: int
    account_id: int
    name: str
    deposit_type: str
    balance_kopecks: int
    annual_rate_basis_points: int
    expected_monthly_interest_kopecks: int
    include_in_capital: bool


@dataclass(frozen=True, slots=True)
class FrozenPosition:
    id: int
    account_id: int
    instrument_id: int
    instrument_type: str | None
    market_value_kopecks: int
    include_in_capital: bool
    currency: str | None = None


@dataclass(frozen=True, slots=True)
class FrozenDebt:
    id: int
    balance_kopecks: int
    include_in_liquid_capital: bool


@dataclass(frozen=True, slots=True)
class FrozenGoal:
    id: int
    target_kopecks: int
    is_active: bool
    goal_type: str
    calculation_mode: str


@dataclass(frozen=True, slots=True)
class FrozenExpectedFlow:
    """Canonical forecast expected-flow row (12-month calendar window)."""

    flow_type: str
    net_amount_kopecks: int
    is_approximate: bool


@dataclass(frozen=True, slots=True)
class FrozenDividendMonth:
    year: int
    month: int
    amount_kopecks: int


@dataclass(frozen=True, slots=True)
class FrozenForecastInputs:
    """Frozen canonical inputs for ``calculate_forecast_passive_income``."""

    expected_flows: tuple[FrozenExpectedFlow, ...]
    dividend_months: tuple[FrozenDividendMonth, ...]
    history_start_month: tuple[int, int] | None
    # None => the selected month has no deposit snapshots; zero => snapshots
    # exist but their persisted monthly estimates sum to zero.
    deposit_snapshot_monthly_interest_kopecks: int | None


@dataclass(frozen=True, slots=True)
class FrozenLadderMonth:
    """Frozen R07-05 ladder month components (integer kopecks)."""

    year: int
    month: int
    coupon_kopecks: int
    dividend_kopecks: int
    deposit_interest_kopecks: int
    other_capital_income_kopecks: int
    redemption_principal_kopecks: int
    passive_income_kopecks: int
    total_cash_flow_kopecks: int
    is_approximate: bool


@dataclass(frozen=True, slots=True)
class FrozenWindowEvent:
    """Frozen dated ladder event in the 14/30-day upcoming windows.

    Only canonical, dated calendar events appear here. Undated approximate
    deposit estimates never become window events.
    """

    expected_date: date
    flow_type: str
    component: str
    account_id: int | None
    instrument_id: int | None
    expected_net_amount_kopecks: int
    is_approximate: bool
    source_kind: str
    source_id: int


@dataclass(frozen=True, slots=True)
class FrozenUpcomingWindow:
    days: int
    from_date: date
    to_date: date
    passive_income_kopecks: int
    redemption_principal_kopecks: int
    total_cash_flow_kopecks: int
    events: tuple[FrozenWindowEvent, ...]


@dataclass(frozen=True, slots=True)
class FrozenLadder:
    as_of_date: date
    forecast_version: str
    months: tuple[FrozenLadderMonth, ...]
    upcoming_14_days: FrozenUpcomingWindow
    upcoming_30_days: FrozenUpcomingWindow


@dataclass(frozen=True, slots=True)
class FrozenScenarioBase:
    """Immutable frozen financial payload for all Scenario Lab v1 shocks."""

    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    status: str
    reporting_currency: str
    cash: tuple[FrozenCash, ...]
    deposits: tuple[FrozenDeposit, ...]
    positions: tuple[FrozenPosition, ...]
    debts: tuple[FrozenDebt, ...]
    capital_goals: tuple[FrozenGoal, ...]
    account_names: tuple[tuple[int, str], ...]
    instrument_names: tuple[tuple[int, str], ...]
    forecast: FrozenForecastInputs
    ladder: FrozenLadder
    base_fingerprint: str

    def deposit_by_id(self, deposit_id: int) -> FrozenDeposit | None:
        for deposit in self.deposits:
            if deposit.id == deposit_id:
                return deposit
        return None


def canonical_json_hash(obj: Any) -> str:
    canonical = json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_frozen_base_fingerprint(
    *,
    reporting_month: dict[str, Any],
    reporting_currency: str,
    cash: list[dict[str, Any]],
    deposits: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    debts: list[dict[str, Any]],
    goals: list[dict[str, Any]],
    forecast: dict[str, Any],
    ladder_months: list[dict[str, Any]],
) -> str:
    """Deterministic semantic fingerprint of the frozen base.

    Names/labels are intentionally excluded; only normative financial facts
    participate. ``reporting_currency`` and per-position ``currency`` tags
    are normative base facts (the FX baseline must never silently treat a
    currency-tagged row as reporting-currency exposure).
    """
    payload = {
        "reporting_currency": reporting_currency,
        "reporting_month": reporting_month,
        "cash": sorted(cash, key=lambda item: item["id"]),
        "deposits": sorted(deposits, key=lambda item: item["id"]),
        "positions": sorted(positions, key=lambda item: item["id"]),
        "debts": sorted(debts, key=lambda item: item["id"]),
        "goals": sorted(goals, key=lambda item: item["id"]),
        "forecast": forecast,
        "ladder_months": ladder_months,
    }
    return canonical_json_hash(payload)
