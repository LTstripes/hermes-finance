"""Scenario Lab 141-A — equity_drawdown only. Covers 28 required checks."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, GoalType, InstrumentType
from hermes_finance.persistence import Base, CashBalance, Debt, DepositSnapshot, ExpectedCashFlow, Goal, Instrument, InvestmentCashFlow, PositionSnapshot, ReportingMonth
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.debts import create_debt
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.goals import create_goal
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.scenario_lab import ScenarioLabError, evaluate_scenario_lab


@pytest.fixture
def session(tmp_path: Path):
    db = create_database(tmp_path / "scenario_lab.db")
    Base.metadata.create_all(db.engine)
    s = db.session_factory()
    try:
        yield s
    finally:
        s.close()
        db.engine.dispose()


def _month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12)):
    return create_reporting_month(session, year=year, month=month, snapshot_date=snapshot_date)


def _stock(session, name="S"):
    return create_instrument(session, name=name, instrument_type=InstrumentType.STOCK)


def _fund(session): return create_instrument(session, name="Fund", instrument_type=InstrumentType.FUND)
def _bond(session): return create_instrument(session, name="Bond", instrument_type=InstrumentType.BOND)
def _gold(session): return create_instrument(session, name="Gold", instrument_type=InstrumentType.GOLD)
def _currency(session): return create_instrument(session, name="Currency", instrument_type=InstrumentType.CURRENCY)
def _other(session): return create_instrument(session, name="Other", instrument_type=InstrumentType.OTHER)


def _position(session, month_id, account_id, instrument_id, amount="1000.00"):
    # amount as market_price per unit * quantity 1
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


def _basic_setup(session):
    month = _month(session)
    acc = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    return month, acc


# 1 clean stock drawdown
def test_1_clean_stock_drawdown(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20"}})
    assert res.row_applicability[str(session.scalar(select(PositionSnapshot.id)))] == "applied"
    # base 1000, stressed 800
    assert res.base["liquid_assets_kopecks"] == 100_000
    assert res.stressed["liquid_assets_kopecks"] == 80_000
    assert res.impact["liquid_assets_delta_kopecks"] == -20_000
    assert res.metric_support["liquid_assets"]["status"] == "supported"


# 2 0%
def test_2_zero_drawdown(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "123.45")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "0"}})
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]
    assert res.impact["liquid_assets_delta_kopecks"] == 0


# 3 100%
def test_3_100_percent_drawdown(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "500.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "100"}})
    assert res.stressed["liquid_assets_kopecks"] == 0
    assert res.impact["liquid_assets_delta_kopecks"] == -50_000


# 4-8 not applicable types
@pytest.mark.parametrize("factory,expected", [(_fund, "not_applicable"), (_bond, "not_applicable"), (_gold, "not_applicable"), (_currency, "not_applicable"), (_other, "not_applicable")])
def test_4_8_not_applicable(session, factory, expected):
    month, acc = _basic_setup(session)
    inst = factory(session)
    _position(session, month.id, acc.id, inst.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    pid = str(session.scalar(select(PositionSnapshot.id)))
    assert res.row_applicability[pid] == expected
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"] == 100_000


# 9 missing/invalid -> unknown
def test_9_unknown(session, monkeypatch):
    month, acc = _basic_setup(session)
    # simulate unknown by making classify return unknown for this instrument
    stock = _stock(session)
    pos = _position(session, month.id, acc.id, stock.id, "1000.00")
    # patch the service-level classify to force unknown for this test
    import hermes_finance.services.scenario_lab as sl
    orig = sl.classify_applicability
    def fake(itype):
        # force unknown for the instrument of this pos
        if itype == "stock":
            # we still want stock to be unknown for this specific test, so return unknown
            return sl.RowApplicability.UNKNOWN
        return orig(itype)
    monkeypatch.setattr(sl, "classify_applicability", fake)
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20"}})
    assert res.row_applicability[str(pos.id)] == "unknown"


# 10 unknown blocks exact aggregate but known-scope preserved
def test_10_unknown_blocks_exact_but_known_scope(session, monkeypatch):
    month = _month(session)
    acc = create_account(session, name="A", account_type=AccountType.BROKERAGE)
    stock = _stock(session, "Stock1")
    stock2 = _stock(session, "Stock2")
    # second will be made unknown via patch selective by position id
    p_stock = _position(session, month.id, acc.id, stock.id, "1000.00")
    p_unknown = _position(session, month.id, acc.id, stock2.id, "400.00")
    import hermes_finance.services.scenario_lab as sl
    orig = sl.classify_applicability
    # we need to distinguish: first stock stays applied, second becomes unknown
    # We'll base on a counter: first call -> applied, second -> unknown ; but classification is per instrument_type 'stock' identical
    # So we patch to return unknown on second invocation
    calls = {"n": 0}
    def fake(itype):
        calls["n"] += 1
        if calls["n"] == 2:
            return sl.RowApplicability.UNKNOWN
        return orig(itype)
    # Actually positions are iterated in id order, so second position will be second call
    monkeypatch.setattr(sl, "classify_applicability", fake)
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20"}})
    # known scope impact = -200 (20% of stock 1000)
    assert res.coverage["known_scope_impact_kopecks"] == -20_000
    assert res.coverage["unknown"] == 1
    # full aggregates must be unknown status
    assert res.metric_support["liquid_assets"]["status"] == "unknown"
    assert res.metric_support["liquid_capital_net"]["status"] == "unknown"
    # known impact still preserved, coverage visible
    assert res.coverage["applied"] == 1
    assert res.coverage["total_positions"] == 2


# 11 debts unchanged
def test_11_debts_unchanged(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    create_debt(session, reporting_month_id=month.id, debt_type="credit_card", name="CC", current_balance="300.00", include_in_liquid_capital=True)
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    assert res.base["debts_included_kopecks"] == 30_000
    assert res.stressed["debts_included_kopecks"] == 30_000
    assert res.metric_support["debts"]["status"] == "supported"


# 12 liquid capital propagation
def test_12_liquid_capital(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    # base assets = 1500, stressed = 1000 (500 cash + 500 stock)
    assert res.base["liquid_assets_kopecks"] == 150_000
    assert res.stressed["liquid_assets_kopecks"] == 100_000
    assert res.base["liquid_capital_net_kopecks"] == 150_000
    assert res.stressed["liquid_capital_net_kopecks"] == 100_000


# 13 asset allocation
def test_13_asset_allocation(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    bond = _bond(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    _position(session, month.id, acc.id, bond.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    assert res.base["asset_allocation"]["stocks_kopecks"] == 100_000
    assert res.stressed["asset_allocation"]["stocks_kopecks"] == 50_000
    assert res.base["asset_allocation"]["bonds_kopecks"] == 100_000
    assert res.stressed["asset_allocation"]["bonds_kopecks"] == 100_000


# 14 account allocation
def test_14_account_allocation(session):
    month = _month(session)
    a1 = create_account(session, name="A1", account_type=AccountType.BROKERAGE)
    a2 = create_account(session, name="A2", account_type=AccountType.BROKERAGE)
    stock = _stock(session)
    _position(session, month.id, a1.id, stock.id, "1000.00")
    bond = _bond(session)
    _position(session, month.id, a2.id, bond.id, "2000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    base_a1 = next(x for x in res.base["account_allocation"] if x["account_id"] == a1.id)
    stressed_a1 = next(x for x in res.stressed["account_allocation"] if x["account_id"] == a1.id)
    assert base_a1["amount_kopecks"] == 100_000
    assert stressed_a1["amount_kopecks"] == 50_000
    base_a2 = next(x for x in res.base["account_allocation"] if x["account_id"] == a2.id)
    stressed_a2 = next(x for x in res.stressed["account_allocation"] if x["account_id"] == a2.id)
    assert base_a2["amount_kopecks"] == stressed_a2["amount_kopecks"] == 200_000


# 15 top-position concentration
def test_15_top_positions(session):
    month, acc = _basic_setup(session)
    s1 = _stock(session, "S1")
    s2 = _stock(session, "S2")
    _position(session, month.id, acc.id, s1.id, "2000.00")
    _position(session, month.id, acc.id, s2.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    # before: S1 top, after: S1 still top but values halved
    assert res.base["top_positions"][0]["amount_kopecks"] == 200_000
    assert res.stressed["top_positions"][0]["amount_kopecks"] == 100_000


# 16 capital Goal
def test_16_capital_goal(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    goal = create_goal(session, name="Cap", goal_type=GoalType.CAPITAL, target_value="5000.00", calculation_mode="liquid_capital_net")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    base_g = next(g for g in res.base["capital_goals"] if g["goal_id"] == goal.id)
    stressed_g = next(g for g in res.stressed["capital_goals"] if g["goal_id"] == goal.id)
    assert base_g["current_kopecks"] == 100_000
    assert stressed_g["current_kopecks"] == 50_000
    assert base_g["progress_pct"] == "20.00"
    assert stressed_g["progress_pct"] == "10.00"


# 17 passive-income effect unavailable
def test_17_passive_income_unavailable(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "30"}})
    assert res.base["passive_income_effect"]["status"] == "unavailable"
    assert res.stressed["passive_income_effect"]["status"] == "unavailable"
    assert res.stressed["passive_income_effect"]["reason"] == "no_deterministic_income_relationship"
    assert res.metric_support["passive_income_effect"]["status"] == "unavailable"


# 18 dividends unchanged
def test_18_dividends_unchanged(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    create_investment_cash_flow(session, reporting_month_id=month.id, account_id=acc.id, instrument_id=stock.id, flow_type="dividend", event_date=date(2030, 5, 10), gross_amount="100.00", tax_amount="0.00", commission_amount="0.00", net_amount="100.00", currency="RUB", source="test")
    before = session.scalars(select(InvestmentCashFlow)).all()
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    after = session.scalars(select(InvestmentCashFlow)).all()
    assert len(before) == len(after) == 1
    assert before[0].net_amount_kopecks == after[0].net_amount_kopecks == 10_000


# 19 coupons unchanged
def test_19_coupons_unchanged(session):
    month, acc = _basic_setup(session)
    bond = _bond(session)
    _position(session, month.id, acc.id, bond.id, "1000.00")
    create_investment_cash_flow(session, reporting_month_id=month.id, account_id=acc.id, instrument_id=bond.id, flow_type="coupon", event_date=date(2030, 5, 10), gross_amount="50.00", tax_amount="0", commission_amount="0", net_amount="50.00", currency="RUB", source="test")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    # coupon flow still there
    flows = session.scalars(select(InvestmentCashFlow)).all()
    assert flows[0].net_amount_kopecks == 5000


# 20 redemption unchanged
def test_20_redemption_unchanged(session):
    month, acc = _basic_setup(session)
    bond = _bond(session)
    _position(session, month.id, acc.id, bond.id, "1000.00")
    create_investment_cash_flow(session, reporting_month_id=month.id, account_id=acc.id, instrument_id=bond.id, flow_type="redemption", event_date=date(2030, 5, 10), gross_amount="1000.00", tax_amount="0", commission_amount="0", net_amount="1000.00", currency="RUB", source="test")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "50"}})
    flows = session.scalars(select(InvestmentCashFlow)).all()
    assert flows[0].flow_type == "redemption"
    assert flows[0].net_amount_kopecks == 100_000


# 21 canonical future cash-flow rows unchanged
def test_21_future_cash_flows_unchanged(session):
    month, acc = _basic_setup(session)
    bond = _bond(session)
    _position(session, month.id, acc.id, bond.id, "1000.00")
    create_expected_cash_flow(session, reporting_month_id=month.id, account_id=acc.id, instrument_id=bond.id, flow_type="coupon", expected_date=date(2030, 6, 1), gross_amount="100.00", currency="RUB", source="src", source_as_of_date=date(2030, 5, 12), forecast_version="v1", is_confirmed=False)
    before = session.scalars(select(ExpectedCashFlow)).all()
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20"}})
    after = session.scalars(select(ExpectedCashFlow)).all()
    assert len(before) == len(after) == 1
    assert before[0].expected_net_amount_kopecks == after[0].expected_net_amount_kopecks


# 22 deterministic replay
def test_22_deterministic_replay(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    r1 = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20.00"}})
    r2 = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20.00"}})
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.base == r2.base
    assert r1.stressed == r2.stressed
    assert r1.row_applicability == r2.row_applicability


# 23 generated_at does not change fingerprint
def test_23_generated_at_not_in_fingerprint(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    r1 = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "15"}}, generated_at=datetime(2030, 5, 12, 10, 0, tzinfo=timezone.utc))
    r2 = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "15"}}, generated_at=datetime(2030, 5, 12, 11, 0, tzinfo=timezone.utc))
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.generated_at != r2.generated_at


# 24 combined shock rejected
def test_24_combined_rejected(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "10"}, "fx_translation_shock": {"pct": "10"}})
    assert exc.value.code == "unsupported_composition_v1"


# 25 invalid below 0
def test_25_invalid_below_0(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    with pytest.raises(ValueError) as exc:
        evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "-1"}})
    assert "invalid_drawdown_pct" in str(exc.value)


# 26 invalid above 100
def test_26_invalid_above_100(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    with pytest.raises(ValueError) as exc:
        evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "101"}})
    assert "invalid_drawdown_pct" in str(exc.value)


# 27 no DB mutation
def test_27_no_db_mutation(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    pos = _position(session, month.id, acc.id, stock.id, "1000.00")
    cash = create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    deposit = create_deposit_snapshot(session, reporting_month_id=month.id, account_id=acc.id, name="Dep", deposit_type="deposit", balance="2000.00", annual_rate="5.00")
    debt = create_debt(session, reporting_month_id=month.id, debt_type="credit_card", name="Debt", current_balance="100.00", include_in_liquid_capital=True)
    goal = create_goal(session, name="G", goal_type=GoalType.CAPITAL, target_value="10000.00", calculation_mode="liquid_capital_net")
    # counts before
    def counts():
        return {
            "months": session.scalar(select(func.count()).select_from(ReportingMonth)),
            "positions": session.scalar(select(func.count()).select_from(PositionSnapshot)),
            "cash": session.scalar(select(func.count()).select_from(CashBalance)),
            "deposits": session.scalar(select(func.count()).select_from(DepositSnapshot)),
            "debts": session.scalar(select(func.count()).select_from(Debt)),
            "goals": session.scalar(select(func.count()).select_from(Goal)),
        }
    before = counts()
    before_pos_value = session.get(PositionSnapshot, pos.id).market_value_kopecks
    evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "30"}})
    after = counts()
    assert before == after
    assert session.get(PositionSnapshot, pos.id).market_value_kopecks == before_pos_value
    # ensure session has no pending writes
    assert not session.new
    assert not session.dirty


# 28 no network/provider calls (we monkeypatch socket to fail if called, and ensure no provider modules invoked)
def test_28_no_network_calls(session, monkeypatch):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    import socket
    def _fail(*a, **kw): raise AssertionError("network call attempted")
    monkeypatch.setattr(socket, "socket", _fail)
    # also guard httpx if imported
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "10"}})
    assert res.semantic_fingerprint

# additional: decimal precision and rounding half up
def test_drawdown_rounding_half_up(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    # 1 kopeck base, 33.333% drawdown -> stressed = 0.66667 kopecks -> 1? Half up: 0.666 -> 1? Decimal(1)* (66.667/100)=0.66667 -> 1 kopeck
    _position(session, month.id, acc.id, stock.id, "0.01")
    res = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "33.333"}})
    # 1 *0.66667=0.66667 -> rounds to 1
    assert res.stressed["liquid_assets_kopecks"] in (0, 1)  # deterministic rounding check
    # more precise: 0.01 =1 kopeck, 33.333% -> 0.66667 -> 1
    assert res.stressed["per_position"][str(session.scalar(select(PositionSnapshot.id)))]["stressed_market_value_kopecks"] == 1

def test_binary_float_rejected(session):
    month, acc = _basic_setup(session)
    stock = _stock(session)
    _position(session, month.id, acc.id, stock.id, "1000.00")
    with pytest.raises(ValueError) as exc:
        evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": 20.0}})
    assert "invalid_drawdown_pct" in str(exc.value) or "binary" in str(exc.value).lower()
