"""Scenario Lab 141-B — deposit_rate_assumption. Covers required acceptance set.

Deposit-rate scenario is a read-only deterministic what-if over the frozen
selected reporting month: only the supported forecast deposit-interest
component (and the approximate ladder deposit-interest component) may change.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, GoalType, InstrumentType
from hermes_finance.persistence import (
    Base,
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
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.debts import create_debt
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.goals import create_goal
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)
from hermes_finance.services.scenario_lab import ScenarioLabError, evaluate_scenario_lab

RATE_ALL = {"assumed_annual_rate_pct": "12"}


@pytest.fixture
def session(tmp_path: Path):
    db = create_database(tmp_path / "scenario_deposit.db")
    Base.metadata.create_all(db.engine)
    s = db.session_factory()
    try:
        yield s
    finally:
        s.close()
        db.engine.dispose()


def _month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12)):
    return create_reporting_month(session, year=year, month=month, snapshot_date=snapshot_date)


def _account(session, *, include_in_capital=True, account_type=AccountType.SAVINGS, name="Bank"):
    return create_account(
        session, name=name, account_type=account_type, include_in_capital=include_in_capital
    )


def _deposit(
    session,
    month_id,
    account_id,
    *,
    balance="120000.00",
    annual_rate="6.00",
    name="Dep",
    deposit_type="deposit",
):
    return create_deposit_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        name=name,
        deposit_type=deposit_type,
        balance=balance,
        annual_rate=annual_rate,
    )


def _stock(session, name="Stock"):
    return create_instrument(session, name=name, instrument_type=InstrumentType.STOCK)


def _bond(session, name="Bond"):
    return create_instrument(session, name=name, instrument_type=InstrumentType.BOND)


def _position(session, month_id, account_id, instrument_id, amount="1000.00"):
    return create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity="1",
        average_cost_per_unit="1.00",
        market_price_per_unit=amount,
        price_date=date(2030, 5, 12),
    )


def _expected_coupon(
    session, month_id, account_id, instrument_id, *, amount="100.00", expected_date=date(2030, 6, 1)
):
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type="coupon",
        expected_date=expected_date,
        gross_amount=amount,
        currency="RUB",
        source="synthetic",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )


# 1. Contract example: 120000 RUB @ 12% -> 1200 RUB/month
def test_1_contract_example_monthly_interest(session):
    month, account = _month(session), _account(session)
    deposit = _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "deposit_ids": [deposit.id]}}
    )
    deposit_id = str(deposit.id)
    assert res.base["per_deposit"][deposit_id]["balance_kopecks"] == 12_000_000
    assert res.stressed["per_deposit"][deposit_id]["balance_kopecks"] == 12_000_000
    # persisted base at 6% -> 600.00; stressed at 12% -> 1200.00
    assert res.base["per_deposit"][deposit_id]["expected_monthly_interest_kopecks"] == 60_000
    assert res.stressed["per_deposit"][deposit_id]["expected_monthly_interest_kopecks"] == 120_000
    assert res.impact["per_deposit"][deposit_id]["delta_kopecks"] == 60_000
    assert res.row_applicability[deposit_id] == "applied"


# 2. 0% rate keeps principal, zero interest
def test_2_zero_rate(session):
    month, account = _month(session), _account(session)
    deposit = _deposit(session, month.id, account.id)
    res = evaluate_scenario_lab(
        session,
        month.id,
        {"deposit_rate_assumption": {"assumed_annual_rate_pct": "0", "deposit_ids": [deposit.id]}},
    )
    deposit_id = str(deposit.id)
    assert res.base["per_deposit"][deposit_id]["balance_kopecks"] == 12_000_000
    assert res.stressed["per_deposit"][deposit_id]["balance_kopecks"] == 12_000_000
    assert res.stressed["per_deposit"][deposit_id]["expected_monthly_interest_kopecks"] == 0
    assert res.impact["per_deposit"][deposit_id]["delta_kopecks"] == -60_000


# 3. explicit one-of-two target: only A changes
def test_3_explicit_one_of_two(session):
    month, account = _month(session), _account(session)
    a = _deposit(session, month.id, account.id, balance="100000.00", annual_rate="6.00", name="A")
    b = _deposit(session, month.id, account.id, balance="50000.00", annual_rate="6.00", name="B")
    res = evaluate_scenario_lab(
        session,
        month.id,
        {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12", "deposit_ids": [a.id]}},
    )
    a_id, b_id = str(a.id), str(b.id)
    assert res.row_applicability[a_id] == "applied"
    assert res.row_applicability[b_id] == "not_applicable"
    # A: 100000 @ 12% -> 1000.00/mo (was 500.00); B stays 250.00
    assert res.stressed["per_deposit"][a_id]["expected_monthly_interest_kopecks"] == 100_000
    assert res.base["per_deposit"][b_id]["expected_monthly_interest_kopecks"] == 25_000
    assert res.stressed["per_deposit"][b_id]["expected_monthly_interest_kopecks"] == 25_000
    # forecast delta only from A: (1000 - 500) * 12 = 6000.00 per year
    assert res.impact["annual_deposit_interest_delta_kopecks"] == 600_000
    assert res.impact["per_deposit"][a_id]["delta_kopecks"] == 50_000
    assert res.impact["per_deposit"][b_id]["delta_kopecks"] == 0


# 4. all_eligible_deposits normalized scope holds exact frozen sorted ids
def test_4_all_eligible_normalized_scope(session):
    month, account = _month(session), _account(session)
    d1 = _deposit(session, month.id, account.id, balance="100.00", annual_rate="6.00", name="B")
    d2 = _deposit(session, month.id, account.id, balance="200.00", annual_rate="6.00", name="A")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    scope = res.normalized_target_scope
    assert scope["selector"] == "all_eligible_deposits"
    assert scope["deposit_ids"] == sorted([d1.id, d2.id])
    # both applied
    assert res.row_applicability[str(d1.id)] == "applied"
    assert res.row_applicability[str(d2.id)] == "applied"


# 5. frozen target set: mid-evaluation DB mutation does not enter the running scenario
def test_5_frozen_target_set(session, monkeypatch):
    from sqlalchemy.orm import Session as SASession

    month, account = _month(session), _account(session)
    d1 = _deposit(session, month.id, account.id, balance="100000.00", annual_rate="6.00", name="A")
    shock = {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    baseline = evaluate_scenario_lab(session, month.id, shock)
    assert baseline.normalized_target_scope["deposit_ids"] == [d1.id]
    scope_before = baseline.normalized_target_scope
    fingerprint_before = baseline.semantic_fingerprint
    base_before = baseline.base

    import hermes_finance.services.scenario_lab as sl

    orig_calc = sl.calculate_liquid_capital
    mutated = {"done": False}

    def patched_calc(inp):
        if not mutated["done"]:
            mutated["done"] = True
            engine = session.get_bind()
            second = SASession(engine)
            try:
                month_row = second.get(ReportingMonth, month.id)
                second.add(
                    DepositSnapshot(
                        reporting_month_id=month_row.id,
                        account_id=account.id,
                        name="Late",
                        deposit_type="deposit",
                        balance_kopecks=5_000_000,
                        annual_rate_basis_points=600,
                        expected_monthly_interest_kopecks=25_000,
                        actual_interest_received_kopecks=0,
                    )
                )
                second.commit()
            finally:
                second.close()
        return orig_calc(inp)

    monkeypatch.setattr(sl, "calculate_liquid_capital", patched_calc)
    running = evaluate_scenario_lab(session, month.id, shock)
    # the running scenario result and target ids remain unchanged
    assert running.normalized_target_scope == scope_before
    assert running.semantic_fingerprint == fingerprint_before
    assert running.base == base_before
    assert running.base["per_deposit"].keys() == {str(d1.id)}


# 6. explicit order determinism
def test_6_explicit_order_determinism(session):
    month, account = _month(session), _account(session)
    d1 = _deposit(session, month.id, account.id, balance="100000.00", annual_rate="6.00", name="A")
    d2 = _deposit(session, month.id, account.id, balance="50000.00", annual_rate="6.00", name="B")
    d3 = _deposit(session, month.id, account.id, balance="25000.00", annual_rate="6.00", name="C")
    ids = [d1.id, d2.id, d3.id]
    r1 = evaluate_scenario_lab(
        session,
        month.id,
        {
            "deposit_rate_assumption": {
                "assumed_annual_rate_pct": "12",
                "deposit_ids": list(reversed(ids)),
            }
        },
    )
    r2 = evaluate_scenario_lab(
        session,
        month.id,
        {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12", "deposit_ids": ids}},
    )
    assert r1.normalized_target_scope["deposit_ids"] == sorted(ids)
    assert r1.normalized_target_scope == r2.normalized_target_scope
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.stressed == r2.stressed


# 7. duplicate ids do not double-apply
def test_7_duplicate_ids_no_double_count(session):
    month, account = _month(session), _account(session)
    deposit = _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    res = evaluate_scenario_lab(
        session,
        month.id,
        {
            "deposit_rate_assumption": {
                "assumed_annual_rate_pct": "12",
                "deposit_ids": [deposit.id, deposit.id, deposit.id],
            }
        },
    )
    assert res.normalized_target_scope["deposit_ids"] == [deposit.id]
    assert res.impact["per_deposit"][str(deposit.id)]["delta_kopecks"] == 60_000
    assert res.impact["monthly_interest_delta_kopecks"] == 60_000


# 8. foreign-month / nonexistent id rejected deterministically
def test_8_foreign_month_or_missing_id(session):
    month, account = _month(session), _account(session)
    other_month = create_reporting_month(
        session, year=2030, month=4, snapshot_date=date(2030, 4, 10)
    )
    foreign = _deposit(session, other_month.id, account.id, balance="100.00", annual_rate="6.00")
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": "12",
                    "deposit_ids": [foreign.id],
                }
            },
        )
    assert exc.value.code == "foreign_month_deposit_id"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12", "deposit_ids": [999999]}},
        )
    assert exc.value.code == "foreign_month_deposit_id"


# 9. basis-point normalization through canonical PercentageRate
def test_9_basis_point_normalization(session):
    month, account = _month(session), _account(session)
    deposit = _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    res = evaluate_scenario_lab(
        session,
        month.id,
        {
            "deposit_rate_assumption": {
                "assumed_annual_rate_pct": "12.345",
                "deposit_ids": [deposit.id],
            }
        },
    )
    assert res.normalized_shock_input["assumed_annual_rate_pct"] == "12.35"
    assert res.normalized_shock_input["annual_rate_basis_points"] == 1235
    assert res.stressed["per_deposit"][str(deposit.id)]["annual_rate_basis_points"] == 1235


# 10. money HALF_UP boundary at whole kopeck
def test_10_money_half_up_boundary(session):
    month, account = _month(session), _account(session)
    # 6 kopecks balance @ assumed 100% -> 6*10000bp/10000/12 = 0.5 -> 1 kopeck (ROUND_HALF_UP)
    deposit = create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="D",
        deposit_type="deposit",
        balance="0.06",
        annual_rate="6.00",
    )
    res = evaluate_scenario_lab(
        session,
        month.id,
        {
            "deposit_rate_assumption": {
                "assumed_annual_rate_pct": "100",
                "deposit_ids": [deposit.id],
            }
        },
    )
    # persisted at 6% -> 6*600/10000/12 = 0.03 -> 0 kopecks
    assert deposit.expected_monthly_interest_kopecks == 0
    assert res.base["per_deposit"][str(deposit.id)]["expected_monthly_interest_kopecks"] == 0
    # stressed at 100% -> 0.5 -> ROUND_HALF_UP -> 1 kopeck
    assert res.stressed["per_deposit"][str(deposit.id)]["expected_monthly_interest_kopecks"] == 1
    assert res.impact["per_deposit"][str(deposit.id)]["delta_kopecks"] == 1


# 11. liquid capital unchanged
def test_11_liquid_capital_unchanged(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="200000.00", annual_rate="6.00")
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]
    assert res.base["liquid_capital_net_kopecks"] == res.stressed["liquid_capital_net_kopecks"]
    assert res.impact["liquid_assets_delta_kopecks"] == 0
    assert res.impact["liquid_capital_net_delta_kopecks"] == 0


# 12. allocation unchanged (asset/account/top)
def test_12_allocation_unchanged(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="200000.00", annual_rate="6.00")
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    assert res.base["asset_allocation"] == res.stressed["asset_allocation"]
    assert res.base["account_allocation"] == res.stressed["account_allocation"]
    assert res.base["top_positions"] == res.stressed["top_positions"]
    assert res.base["asset_allocation"]["deposits_kopecks"] == 20_000_000


# 13. capital Goal unchanged
def test_13_capital_goal_unchanged(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="200000.00", annual_rate="6.00")
    goal = create_goal(
        session,
        name="Cap",
        goal_type=GoalType.CAPITAL,
        target_value="1000000.00",
        calculation_mode="liquid_capital_net",
    )
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    base_goal = next(g for g in res.base["capital_goals"] if g["goal_id"] == goal.id)
    stressed_goal = next(g for g in res.stressed["capital_goals"] if g["goal_id"] == goal.id)
    assert base_goal == stressed_goal
    assert base_goal["current_kopecks"] == 20_000_000


# 14. forecast deposit component changed only
def test_14_forecast_deposit_component_changed(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")  # 600/mo
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    base_dep = res.base["forecast_passive_income"]["breakdown"]["expected_deposit_interest_kopecks"]
    stressed_dep = res.stressed["forecast_passive_income"]["breakdown"][
        "expected_deposit_interest_kopecks"
    ]
    # base 600*12 = 7200.00; stressed 1200*12 = 14400.00
    assert base_dep == 720_000
    assert stressed_dep == 1_440_000
    # annual forecast total changes by the same 7200.00
    delta = (
        res.stressed["forecast_passive_income"]["annual_total_kopecks"]
        - res.base["forecast_passive_income"]["annual_total_kopecks"]
    )
    assert delta == 720_000
    assert res.impact["forecast_annual_total_delta_kopecks"] == 720_000


# 15-18. coupon/dividend/other unchanged; redemption excluded
def test_15_coupon_component_unchanged(session):
    month, account = _month(session), _account(session)
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _expected_coupon(session, month.id, account.id, bond.id, amount="100.00")
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    base = res.base["forecast_passive_income"]["breakdown"]["expected_coupon_net_kopecks"]
    stressed = res.stressed["forecast_passive_income"]["breakdown"]["expected_coupon_net_kopecks"]
    assert base == stressed == 10_000


def test_16_dividend_component_unchanged(session):
    month = _month(session, year=2030, month=5)
    account = _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    # a closed month with actual dividend history
    closed = create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 12))
    stock = _stock(session)
    create_investment_cash_flow(
        session,
        reporting_month_id=closed.id,
        account_id=account.id,
        instrument_id=stock.id,
        flow_type="dividend",
        event_date=date(2030, 4, 10),
        gross_amount="30.00",
        tax_amount="0.00",
        commission_amount="0.00",
        net_amount="30.00",
        currency="RUB",
        source="test",
    )
    close_reporting_month(session, closed.id)
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    base = res.base["forecast_passive_income"]["breakdown"]["expected_dividend_component_kopecks"]
    stressed = res.stressed["forecast_passive_income"]["breakdown"][
        "expected_dividend_component_kopecks"
    ]
    assert base == stressed == 36_000  # 30.00 * 12


def test_17_other_capital_income_unchanged(session):
    month, account = _month(session), _account(session)
    stock = _stock(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    # manual expected 'other' flow in calendar window
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=stock.id,
        flow_type="other",
        expected_date=date(2030, 7, 1),
        gross_amount="40.00",
        currency="RUB",
        source="synthetic",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    base = res.base["forecast_passive_income"]["breakdown"]["other_expected_capital_income_kopecks"]
    stressed = res.stressed["forecast_passive_income"]["breakdown"][
        "other_expected_capital_income_kopecks"
    ]
    assert base == stressed == 4_000


def test_18_redemption_excluded_from_forecast(session):
    month, account = _month(session), _account(session)
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    create_expected_cash_flow(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=bond.id,
        flow_type="redemption",
        expected_date=date(2030, 8, 1),
        gross_amount="10000.00",
        currency="RUB",
        source="synthetic",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    for forecast in (res.base["forecast_passive_income"], res.stressed["forecast_passive_income"]):
        # redemption not part of passive income forecast at all
        assert "redemption" not in forecast["breakdown"]
        # coupon/ladder untouched by redemption rows in forecast totals
        assert forecast["breakdown"]["expected_coupon_net_kopecks"] == 0


# 19. current actual passive-income Goal unchanged (never substituted by forecast)
def test_19_current_actual_pi_goal_unchanged(session):
    month = _month(session, year=2030, month=5)
    account = _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    # actual-based passive income goal with closed-month history
    closed = create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 12))
    stock = _stock(session)
    create_investment_cash_flow(
        session,
        reporting_month_id=closed.id,
        account_id=account.id,
        instrument_id=stock.id,
        flow_type="dividend",
        event_date=date(2030, 4, 10),
        gross_amount="50.00",
        tax_amount="0.00",
        commission_amount="0.00",
        net_amount="50.00",
        currency="RUB",
        source="test",
    )
    close_reporting_month(session, closed.id)
    create_goal(
        session,
        name="PI",
        goal_type=GoalType.PASSIVE_INCOME,
        target_value="10000.00",
        calculation_mode="monthly_net_passive_income",
    )
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    assert res.base["passive_income_goal_effect"] == res.stressed["passive_income_goal_effect"]
    assert res.base["passive_income_goal_effect"]["status"] == "unchanged"
    # Blocker #2 contract state: metric_support reports support state, the
    # financial effect above reports unchanged.
    assert res.metric_support["passive_income_goal"]["status"] == "supported"
    # no forecast value was written into any goal family
    for family in (res.base, res.stressed):
        assert "current_kopecks" not in family.get("passive_income_goal_effect", {})
        # capital_goals remain capital-only (no passive income goal appears there)
        assert all(g["goal_id"] is not None for g in family["capital_goals"])


# 20. cash-flow ladder: 12 months reflect stressed estimate, no fabricated events
def test_20_ladder_stressed_monthly_component(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")  # 600/mo
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _expected_coupon(session, month.id, account.id, bond.id, amount="100.00")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    base_months = res.base["cash_flow_ladder"]["months"]
    stressed_months = res.stressed["cash_flow_ladder"]["months"]
    assert len(stressed_months) == 12
    for base_month, stressed_month in zip(base_months, stressed_months):
        # deposit interest component replaced by 1200.00 monthly
        assert base_month["deposit_interest_kopecks"] == 60_000
        assert stressed_month["deposit_interest_kopecks"] == 120_000
        # coupon unchanged, redemption unchanged
        assert base_month["coupon_kopecks"] == stressed_month["coupon_kopecks"]
        # passive_income and total change only by deposit delta
        assert (
            stressed_month["passive_income_kopecks"] - base_month["passive_income_kopecks"]
            == 60_000
        )
        assert (
            stressed_month["total_cash_flow_kopecks"] - base_month["total_cash_flow_kopecks"]
            == 60_000
        )
        assert stressed_month["is_approximate"] is True
    # ladder rows: coupon event present in its month only
    ladder_events = [
        event
        for window_name in ("upcoming_14_days", "upcoming_30_days")
        for event in res.base["cash_flow_ladder"][window_name]["events"]
    ]
    assert all(event["flow_type"] != "interest" for event in ladder_events)


# 21. upcoming 14/30 windows unchanged
def test_21_upcoming_windows_unchanged(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _expected_coupon(
        session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 5, 13)
    )
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    assert (
        res.base["cash_flow_ladder"]["upcoming_14_days"]
        == res.stressed["cash_flow_ladder"]["upcoming_14_days"]
    )
    assert (
        res.base["cash_flow_ladder"]["upcoming_30_days"]
        == res.stressed["cash_flow_ladder"]["upcoming_30_days"]
    )
    # coupon event present once (base==stressed identical window), deposit never fabricated
    coupon_events = [
        e
        for e in res.base["cash_flow_ladder"]["upcoming_14_days"]["events"]
        if e["component"] == "coupon"
    ]
    assert len(coupon_events) == 1
    interest_events = [
        e
        for e in res.base["cash_flow_ladder"]["upcoming_14_days"]["events"]
        if e["component"] == "deposit_interest"
    ]
    assert interest_events == []


# 22. empty all-eligible set: supported deterministic no-op
def test_22_empty_all_eligible_noop(session):
    month = _month(session)
    account = _account(session)
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    assert res.normalized_target_scope["deposit_ids"] == []
    assert res.coverage["eligible_deposits"] == 0
    assert res.impact["monthly_interest_delta_kopecks"] == 0
    assert res.impact["forecast_annual_total_delta_kopecks"] == 0
    assert res.metric_support["forecast_passive_income"]["status"] == "supported"
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]


# 23-25. invalid rate values rejected
def test_23_negative_rate_rejected(session):
    month = _month(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": "-1",
                    "all_eligible_deposits": True,
                }
            },
        )
    assert exc.value.code == "invalid_assumed_rate_pct"


def test_24_nan_infinity_rejected(session):
    month = _month(session)
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ScenarioLabError) as exc:
            evaluate_scenario_lab(
                session,
                month.id,
                {
                    "deposit_rate_assumption": {
                        "assumed_annual_rate_pct": bad,
                        "all_eligible_deposits": True,
                    }
                },
            )
        assert exc.value.code == "invalid_assumed_rate_pct"


def test_25_binary_float_rejected(session):
    month = _month(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": 12.0,
                    "all_eligible_deposits": True,
                }
            },
        )
    assert exc.value.code == "invalid_assumed_rate_pct"
    # bool is not a valid rate
    with pytest.raises(ScenarioLabError):
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": True,
                    "all_eligible_deposits": True,
                }
            },
        )


# 26. combined shock rejected
def test_26_combined_shock_rejected(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="100.00", annual_rate="6.00")
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "equity_drawdown": {"drawdown_pct": "10"},
                "deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True},
            },
        )
    assert exc.value.code == "unsupported_composition_v1"


# 27. equity regression after refactor (light: full suite lives in the equity module)
def test_27_equity_still_works(session):
    month, account = _month(session), _account(session)
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20"}})
    assert res.stressed["liquid_assets_kopecks"] == 80_000


# 28. deterministic replay
def test_28_deterministic_replay(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    shock = {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    r1 = evaluate_scenario_lab(session, month.id, shock)
    r2 = evaluate_scenario_lab(session, month.id, shock)
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.base == r2.base
    assert r1.stressed == r2.stressed
    assert r1.normalized_target_scope == r2.normalized_target_scope


# 29. generated_at excluded from semantic fingerprint
def test_29_generated_at_excluded(session):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    shock = {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    r1 = evaluate_scenario_lab(
        session, month.id, shock, generated_at=datetime(2030, 5, 12, 10, 0, tzinfo=UTC)
    )
    r2 = evaluate_scenario_lab(
        session, month.id, shock, generated_at=datetime(2030, 5, 12, 11, 0, tzinfo=UTC)
    )
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.generated_at != r2.generated_at


# 30. no DB mutation
def test_30_no_db_mutation(session):
    month, account = _month(session), _account(session)
    deposit = _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    stock = _stock(session)
    pos = _position(session, month.id, account.id, stock.id, "1000.00")
    cash = create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    debt = create_debt(
        session,
        reporting_month_id=month.id,
        debt_type="credit_card",
        name="Debt",
        current_balance="100.00",
        include_in_liquid_capital=True,
    )

    def counts():
        return {
            "months": session.scalar(select(func.count()).select_from(ReportingMonth)),
            "deposits": session.scalar(select(func.count()).select_from(DepositSnapshot)),
            "positions": session.scalar(select(func.count()).select_from(PositionSnapshot)),
            "cash": session.scalar(select(func.count()).select_from(CashBalance)),
            "debts": session.scalar(select(func.count()).select_from(Debt)),
            "goals": session.scalar(select(func.count()).select_from(Goal)),
            "expected": session.scalar(select(func.count()).select_from(ExpectedCashFlow)),
            "flows": session.scalar(select(func.count()).select_from(InvestmentCashFlow)),
        }

    before = counts()
    before_rate = session.get(DepositSnapshot, deposit.id).annual_rate_basis_points
    before_value = session.get(PositionSnapshot, pos.id).market_value_kopecks
    evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    after = counts()
    assert before == after
    assert session.get(DepositSnapshot, deposit.id).annual_rate_basis_points == before_rate
    assert session.get(PositionSnapshot, pos.id).market_value_kopecks == before_value
    assert session.get(CashBalance, cash.id).amount_kopecks == 50_000
    assert session.get(Debt, debt.id).current_balance_kopecks == 10_000
    assert not session.new
    assert not session.dirty


# 31. no network/provider calls
def test_31_no_network_calls(session, monkeypatch):
    month, account = _month(session), _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")

    def _fail(*args, **kwargs):
        raise AssertionError("network call attempted")

    monkeypatch.setattr("socket.socket", _fail)
    res = evaluate_scenario_lab(
        session, month.id, {"deposit_rate_assumption": {**RATE_ALL, "all_eligible_deposits": True}}
    )
    assert res.semantic_fingerprint


# selector validation extras
def test_selector_both_rejected(session):
    month, account = _month(session), _account(session)
    deposit = _deposit(session, month.id, account.id, balance="100.00", annual_rate="6.00")
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": "12",
                    "all_eligible_deposits": True,
                    "deposit_ids": [deposit.id],
                }
            },
        )
    assert exc.value.code == "invalid_target_selector"


def test_selector_neither_rejected(session):
    month = _month(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12"}},
        )
    assert exc.value.code == "invalid_target_selector"


def test_selector_false_rejected(session):
    month = _month(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": "12",
                    "all_eligible_deposits": False,
                }
            },
        )
    assert exc.value.code == "invalid_target_selector"


def test_empty_explicit_ids_rejected(session):
    month = _month(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12", "deposit_ids": []}},
        )
    assert exc.value.code == "invalid_deposit_ids"


def test_malformed_ids_rejected(session):
    month = _month(session)
    for bad in ([1, "2"], ["1"], [1.5], [None]):
        with pytest.raises(ScenarioLabError) as exc:
            evaluate_scenario_lab(
                session,
                month.id,
                {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12", "deposit_ids": bad}},
            )
        assert exc.value.code == "invalid_deposit_ids"


def test_foreign_rate_scenario_does_not_change_deposit_principal_in_capital(session):
    """Deposit excluded from capital: rate shock still applies to its interest
    (capital inclusion is a separate concept), principal untouched in capital."""
    month = _month(session)
    account = _account(session, include_in_capital=False, account_type=AccountType.SAVINGS)
    deposit = _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    res = evaluate_scenario_lab(
        session,
        month.id,
        {"deposit_rate_assumption": {"assumed_annual_rate_pct": "12", "deposit_ids": [deposit.id]}},
    )
    # interest shock still supported for this frozen snapshot row
    assert res.row_applicability[str(deposit.id)] == "applied"
    assert (
        res.stressed["per_deposit"][str(deposit.id)]["expected_monthly_interest_kopecks"] == 120_000
    )
    # but the deposit does not participate in liquid capital at all
    assert res.base["asset_allocation"]["deposits_kopecks"] == 0
    assert res.stressed["asset_allocation"]["deposits_kopecks"] == 0


# ---------------------------------------------------------------------------
# Blocker #1 regressions: context-independent Decimal semantics.
#
# Rate normalization must delegate to the canonical PercentageRate contract
# and the deposit-interest money calculation must not depend on the ambient
# decimal.getcontext() precision. The fixtures below run the same canonical
# inputs under drastically different ambient precisions and require identical
# results in every environment.
# ---------------------------------------------------------------------------


def test_rate_normalization_independent_of_ambient_precision():
    """canonical_assumed_rate_basis_points + normalized_rate_string are stable
    under any ambient decimal context precision."""
    from decimal import localcontext

    from hermes_finance.domain.scenario_lab import (
        canonical_assumed_rate_basis_points,
        normalized_rate_string,
    )

    expected_by_pct = {
        "12": (1200, "12.00"),
        "12.3": (1230, "12.30"),
        "12.345": (1235, "12.35"),  # basis-point HALF_UP boundary
    }
    for ambient_prec in (2, 5, 12, 28, 60):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            for raw, (bp, api) in expected_by_pct.items():
                from hermes_finance.domain.scenario_lab import parse_assumed_annual_rate_pct

                pct = parse_assumed_annual_rate_pct(raw)
                assert canonical_assumed_rate_basis_points(pct) == bp, (ambient_prec, raw)
                assert normalized_rate_string(bp) == api, (ambient_prec, raw)


def test_rate_exact_half_up_boundaries_context_invariant():
    """Exact half-up boundaries with 55-digit tails — no fixed prec truncation.

    0.0049...999 -> 0 bp, 0.0050...001 -> 1 bp, under any ambient prec.
    Regression for the integrator blocker where prec=40 truncated tails.
    """
    from decimal import Decimal, localcontext

    from hermes_finance.domain.scenario_lab import canonical_assumed_rate_basis_points
    from hermes_finance.domain.values import PercentageRate

    low = "0.0049999999999999999999999999999999999999999999999999999"
    high = "0.0050000000000000000000000000000000000000000000000000001"
    for ambient_prec in (2, 5, 10, 28, 60):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            # via canonical contract directly
            assert PercentageRate.from_decimal(Decimal(low)).basis_points == 0, ambient_prec
            assert PercentageRate.from_decimal(Decimal(high)).basis_points == 1, ambient_prec
            # via scenario helper (delegates to same contract)
            assert canonical_assumed_rate_basis_points(Decimal(low)) == 0, ambient_prec
            assert canonical_assumed_rate_basis_points(Decimal(high)) == 1, ambient_prec
            # end-to-end via evaluate_scenario_lab path also uses same semantics
            # (parse -> canonical -> PercentageRate), test through parse
            from hermes_finance.domain.scenario_lab import parse_assumed_annual_rate_pct

            assert canonical_assumed_rate_basis_points(parse_assumed_annual_rate_pct(low)) == 0
            assert canonical_assumed_rate_basis_points(parse_assumed_annual_rate_pct(high)) == 1


def test_ruble_and_rate_exact_boundaries_context_invariant():
    """RubleAmount and deposit-interest also exact under hostile prec."""
    from decimal import Decimal, localcontext

    from hermes_finance.domain.deposits import calculate_deposit_expected_monthly_interest_kopecks
    from hermes_finance.domain.values import RubleAmount

    # RubleAmount: 0.005 -> 1 kop? No, 0.005 *100 =0.5 -> 1 kop half-up
    # exact tails: 0.0049... -> 0, 0.0050... -> 1
    low_amt = "0.0049999999999999999999999999999999999999999999999999999"
    high_amt = "0.0050000000000000000000000000000000000000000000000000001"
    for ambient_prec in (2, 5, 28):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            assert RubleAmount.from_decimal(Decimal(low_amt)).kopecks == 0
            assert RubleAmount.from_decimal(Decimal(high_amt)).kopecks == 1
            # deposit interest: balance 60_000 (600 RUB) at 1bp -> exactly 0.5 kop -> 1
            # deposit calculation is integer rational, context must not affect
            assert calculate_deposit_expected_monthly_interest_kopecks(60_000, 1) == 1
            assert calculate_deposit_expected_monthly_interest_kopecks(12_000_000, 1200) == 120_000


def test_deposit_interest_independent_of_ambient_precision():
    """calculate_deposit_expected_monthly_interest_kopecks ignores ambient
    precision: balance * rate / 12 with whole-kopeck HALF_UP rounding."""
    from decimal import localcontext

    from hermes_finance.domain.deposits import (
        calculate_deposit_expected_monthly_interest_kopecks,
    )

    # (balance_kopecks, rate_bp, expected_monthly_kopecks)
    cases = [
        (12_000_000, 1200, 120_000),  # contract example: 120000 @ 12% -> 1200.00
        (12_000_000, 600, 60_000),  # 120000 @ 6% -> 600.00
        (10_000_000, 1235, 102_917),  # 100000 @ 12.35% -> 1029.1666.. -> 1029.17
        (1, 1, 0),  # 0.000001 @ 0.01% / 12 -> far below half a kopeck -> 0
        (3, 1, 0),  # 3 * 1 / 10000 / 12 = 0.000025 -> 0
        (60_000, 1, 1),  # exact whole-kopeck boundary: 0.5 kop -> HALF_UP -> 1
        (100_000_000, 1, 833),  # 1000000 @ 0.01% / 12 = 833.33.. -> 833
    ]
    for ambient_prec in (2, 5, 12, 28, 60):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            for balance, rate_bp, expected in cases:
                got = calculate_deposit_expected_monthly_interest_kopecks(balance, rate_bp)
                assert got == expected, (ambient_prec, balance, rate_bp, got, expected)


def test_full_scenario_eval_independent_of_ambient_precision(session):
    """End-to-end: same frozen month + same input -> identical evaluation
    (fingerprints included) regardless of ambient decimal precision."""
    month = _month(session)
    account = _account(session)
    _deposit(session, month.id, account.id, balance="120000.00", annual_rate="6.00")
    shock = {**RATE_ALL, "all_eligible_deposits": True}

    from decimal import localcontext

    results = []
    for ambient_prec in (5, 28, 60):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            res = evaluate_scenario_lab(session, month.id, {"deposit_rate_assumption": shock})
            results.append(res)
    first = results[0]
    for other in results[1:]:
        assert other.semantic_fingerprint == first.semantic_fingerprint
        assert other.base_fingerprint == first.base_fingerprint
        assert other.base == first.base
        assert other.stressed == first.stressed
        assert other.impact == first.impact
        assert other.normalized_target_scope == first.normalized_target_scope
        assert other.normalized_shock_input == first.normalized_shock_input


# ---------------------------------------------------------------------------
# Single-capture internal-consistency regressions.
#
# materialize_frozen_base is the ONLY DB read phase. The hooks below mutate
# the database between capture stages (via the canonical read-model
# dependencies the materializer composes) and prove that a running
# evaluation never observes a mixture of DB states: every surface keeps
# describing the single captured snapshot.
# ---------------------------------------------------------------------------


def _capture_stage_mutation(session, month, account, *, stage_probe):
    """Insert a new deposit from a second session at the given capture stage.

    ``stage_probe`` is a monkeypatched canonical read-model function used by
    the materializer; it fires the mutation exactly once, then delegates.
    """
    from sqlalchemy.orm import Session as SASession

    import hermes_finance.services.scenario_frozen_base as sfb

    mutated = {"done": False}

    def patched(session_arg, *args, **kwargs):
        if not mutated["done"]:
            mutated["done"] = True
            engine = session.get_bind()
            second = SASession(engine)
            try:
                second.add(
                    DepositSnapshot(
                        reporting_month_id=month.id,
                        account_id=account.id,
                        name="Late",
                        deposit_type="deposit",
                        balance_kopecks=5_000_000,
                        annual_rate_basis_points=600,
                        expected_monthly_interest_kopecks=25_000,
                        actual_interest_received_kopecks=0,
                    )
                )
                second.commit()
            finally:
                second.close()
        return stage_probe(session_arg, *args, **kwargs)

    return sfb, patched


def test_deposit_frozen_base_consistent_under_mutation_between_capture_stages(
    session, monkeypatch
):
    """A deposit committed while the materializer is mid-capture (between its
    read-model stages) must not leak into the running evaluation: the frozen
    base, target scope, fingerprints and every surface stay one consistent
    pre-mutation snapshot."""
    month, account = _month(session), _account(session)
    d1 = _deposit(session, month.id, account.id, balance="100000.00", annual_rate="6.00", name="A")
    shock_payload = {**RATE_ALL, "all_eligible_deposits": True}
    shock = {"deposit_rate_assumption": shock_payload}

    # pre-mutation reference evaluation
    reference = evaluate_scenario_lab(session, month.id, shock)

    import hermes_finance.services.scenario_frozen_base as sfb

    stage = sfb._capture_stage_build_cash_flow_ladder
    _, patched = _capture_stage_mutation(
        session, month, account, stage_probe=stage
    )
    monkeypatch.setattr(sfb, "_capture_stage_build_cash_flow_ladder", patched)

    running = evaluate_scenario_lab(session, month.id, shock)

    assert running.base_fingerprint == reference.base_fingerprint
    assert running.semantic_fingerprint == reference.semantic_fingerprint
    assert running.normalized_target_scope["deposit_ids"] == [d1.id]
    assert running.normalized_target_scope == reference.normalized_target_scope
    assert running.base == reference.base
    assert running.stressed == reference.stressed
    assert running.impact == reference.impact
    assert running.coverage == reference.coverage
    # the late deposit exists in the DB now but never entered the result
    assert set(running.base["per_deposit"]) == {str(d1.id)}


def test_equity_frozen_base_consistent_under_mutation_between_capture_stages(
    session, monkeypatch
):
    """Same internal-consistency guarantee for the equity shock: positions
    committed mid-capture do not enter the running evaluation."""
    from hermes_finance.domain import InstrumentType

    month, account = _month(session), _account(session)
    stock = create_instrument(session, name="LateStock", instrument_type=InstrumentType.STOCK)
    _position(session, month.id, account.id, stock.id, "1000.00")
    shock = {"equity_drawdown": {"drawdown_pct": "20"}}
    reference = evaluate_scenario_lab(session, month.id, shock)

    from sqlalchemy.orm import Session as SASession

    import hermes_finance.services.scenario_frozen_base as sfb

    engine = session.get_bind()
    orig_merged = sfb._capture_stage_merged_payout_calendar
    mutated = {"done": False}

    def patched_merged(session_arg, *args, **kwargs):
        if not mutated["done"]:
            mutated["done"] = True
            second = SASession(engine)
            try:
                create_instrument(second, name="LateBond", instrument_type=InstrumentType.BOND)
                late_bond = second.scalar(
                    select(Instrument.id).where(Instrument.name == "LateBond")
                )
                create_position_snapshot(
                    second,
                    reporting_month_id=month.id,
                    account_id=account.id,
                    instrument_id=late_bond,
                    quantity="1",
                    average_cost_per_unit="1.00",
                    market_price_per_unit="999999.00",
                    price_date=date(2030, 5, 12),
                )
                second.commit()
            finally:
                second.close()
        return orig_merged(session_arg, *args, **kwargs)

    monkeypatch.setattr(sfb, "_capture_stage_merged_payout_calendar", patched_merged)

    running = evaluate_scenario_lab(session, month.id, shock)

    assert running.base_fingerprint == reference.base_fingerprint
    assert running.semantic_fingerprint == reference.semantic_fingerprint
    assert running.base == reference.base
    assert running.stressed == reference.stressed
    assert running.impact == reference.impact
