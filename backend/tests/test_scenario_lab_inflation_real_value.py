"""Scenario Lab 141-C — inflation_real_value. Covers the contract acceptance set.

Inflation is a secondary real-value presentation shock (contract section 9
and the section 11 semantic matrix): nominal financial facts never change
and only month-known future cash flows of the frozen R07-05 ladder are
re-expressed in base-period purchasing power using the explicit v1 monthly
convention ``real_value = nominal / (1 + annual/12) ^ months_ahead`` with a
single ROUND_HALF_UP rounding at the whole-kopeck money boundary.

Future-capital purchasing power and inflation-adjusted Goal coverage stay
``unavailable`` (no future capital trajectory / no Goal price-basis
contract). The evaluation is read-only, deterministic, context-independent
in Decimal precision and never reads the database after the single frozen
base capture.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
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
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.scenario_lab import ScenarioLabError, evaluate_scenario_lab

INFLATION_12 = {"annual_inflation_pct": "12"}

# Base reporting month 2030-05; ladder months 2030-05 .. 2031-04 (offsets 0..11).
LADDER_MONTH_KEYS = [
    "2030-05",
    "2030-06",
    "2030-07",
    "2030-08",
    "2030-09",
    "2030-10",
    "2030-11",
    "2030-12",
    "2031-01",
    "2031-02",
    "2031-03",
    "2031-04",
]


@pytest.fixture
def session(tmp_path: Path):
    db = create_database(tmp_path / "scenario_inflation.db")
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


def _fund(session, name="Fund"):
    return create_instrument(session, name=name, instrument_type=InstrumentType.FUND)


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


def _expected_flow(
    session,
    month_id,
    account_id,
    instrument_id,
    *,
    flow_type,
    amount,
    expected_date,
):
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        expected_date=expected_date,
        gross_amount=amount,
        currency="RUB",
        source="synthetic",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )


def _coupon(session, month_id, account_id, instrument_id, *, amount="100.00", expected_date):
    return _expected_flow(
        session,
        month_id,
        account_id,
        instrument_id,
        flow_type="coupon",
        amount=amount,
        expected_date=expected_date,
    )


def _redemption(session, month_id, account_id, instrument_id, *, amount, expected_date):
    return _expected_flow(
        session,
        month_id,
        account_id,
        instrument_id,
        flow_type="redemption",
        amount=amount,
        expected_date=expected_date,
    )


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


# ---------------------------------------------------------------------------
# Fixture A — full ladder: deposit 600.00/mo, coupons 100.00 at months +1/+6,
# redemption 10000.00 at month +11, bond position 1000.00.
# ---------------------------------------------------------------------------


def _full_setup(session):
    month = _month(session)
    account = _account(session)
    _deposit(session, month.id, account.id)  # 60000 kop/mo ladder deposit interest
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _coupon(session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 6, 1))
    _coupon(
        session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 11, 15)
    )
    _redemption(
        session,
        month.id,
        account.id,
        bond.id,
        amount="10000.00",
        expected_date=date(2031, 4, 1),
    )
    return month, account


def _income_row(res, key):
    return res.stressed["cash_flow_real_value"][key]


# 1. Contract example G: known payment 6 calendar months ahead, annual 12% ->
#    monthly 1% -> real = N / 1.01^6. Nominal stays untouched.
def test_1_contract_example_g_six_month_coupon(session):
    month, account = _month(session), _account(session)
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _coupon(
        session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 11, 15)
    )
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    row = _income_row(res, "2030-11")
    # 100.00 RUB = 10000 kopecks nominal, 6 months ahead
    assert row["nominal_income_kopecks"] == 10_000
    assert row["nominal_income"] == "100.00"
    assert row["months_ahead"] == 6
    # 10000 / 1.01^6 = 9420.45... -> ROUND_HALF_UP -> 9420 kopecks = 94.20 RUB
    assert row["real_income_kopecks"] == 9420
    assert row["real_income"] == "94.20"
    assert row["income_delta_kopecks"] == -580
    assert row["income_delta"] == "-5.80"
    # nominal surface untouched everywhere
    ladder = res.stressed["cash_flow_ladder"]["months"]
    nov = next(m for m in ladder if m["year"] == 2030 and m["month"] == 11)
    assert nov["coupon_kopecks"] == 10_000
    # no redemption anywhere in this fixture
    assert row["nominal_redemption_kopecks"] == 0
    assert row["real_redemption_kopecks"] == 0


# 2. Addition 2: months_ahead == 0 -> real_value == nominal_value
def test_2_same_month_real_equals_nominal(session):
    month, account = _month(session), _account(session)
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    # coupon inside the base month itself (day after snapshot date)
    _coupon(
        session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 5, 13)
    )
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    row = res.stressed["cash_flow_real_value"]["2030-05"]
    assert row["months_ahead"] == 0
    assert row["nominal_income_kopecks"] == 10_000
    assert row["real_income_kopecks"] == 10_000
    assert row["income_delta_kopecks"] == 0
    # base and stressed presentation rows are identical for months_ahead == 0
    assert res.base["cash_flow_real_value"]["2030-05"] == row


# 3. 0% inflation: real value equals nominal for every month
def test_3_zero_inflation_all_rows_unchanged(session):
    month, account = _full_setup(session)
    res = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "0"}}
    )
    assert res.normalized_shock_input["annual_inflation_pct"] == "0"
    assert res.base["cash_flow_real_value"] == res.stressed["cash_flow_real_value"]
    assert res.impact["future_income_real_value_delta_kopecks"] == 0
    assert res.impact["future_redemption_real_value_delta_kopecks"] == 0
    assert res.impact["future_total_cash_flow_real_value_delta_kopecks"] == 0
    assert res.impact["future_income_real_value_delta"] == "0.00"
    assert res.impact["per_month"]["2031-04"]["redemption_delta_kopecks"] == 0


# 4. Full fixture: real-value rows, months_ahead grid, aggregates, coverage
def test_4_full_fixture_real_value_rows_and_aggregates(session):
    month, account = _full_setup(session)
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    rows = res.stressed["cash_flow_real_value"]
    assert list(rows.keys()) == LADDER_MONTH_KEYS
    # months_ahead == calendar distance 0..11
    assert [row["months_ahead"] for row in rows.values()] == list(range(12))
    # every ladder month carries the 600.00/mo deposit estimate plus coupons
    assert rows["2030-05"]["nominal_income_kopecks"] == 60_000
    assert rows["2030-05"]["real_income_kopecks"] == 60_000
    # coupon month +1: 70000 -> 69307 (-6.93)
    assert rows["2030-06"]["nominal_income_kopecks"] == 70_000
    assert rows["2030-06"]["real_income_kopecks"] == 69_307
    assert rows["2030-06"]["income_delta_kopecks"] == -693
    # coupon month +6: 70000 -> 65943 (-40.57)
    assert rows["2030-11"]["nominal_income_kopecks"] == 70_000
    assert rows["2030-11"]["real_income_kopecks"] == 65_943
    assert rows["2030-11"]["income_delta_kopecks"] == -4_057
    # month +11 income: 60000 -> 53779; redemption 1000000 -> 896324
    apr = rows["2031-04"]
    assert apr["nominal_income_kopecks"] == 60_000
    assert apr["real_income_kopecks"] == 53_779
    assert apr["nominal_redemption_kopecks"] == 1_000_000
    assert apr["real_redemption_kopecks"] == 896_324
    assert apr["redemption_delta_kopecks"] == -103_676
    assert apr["nominal_total_cash_flow_kopecks"] == 1_060_000
    assert apr["real_total_cash_flow_kopecks"] == 950_103
    assert apr["total_cash_flow_delta_kopecks"] == -109_897
    # aggregates equal the per-month sums per family
    assert res.impact["future_income_real_value_delta_kopecks"] == -38_622
    assert res.impact["future_redemption_real_value_delta_kopecks"] == -103_676
    assert res.impact["future_total_cash_flow_real_value_delta_kopecks"] == -142_298
    assert res.impact["future_income_real_value_delta"] == "-386.22"
    assert res.impact["future_redemption_real_value_delta"] == "-1036.76"
    assert res.impact["future_total_cash_flow_real_value_delta"] == "-1422.98"
    # per_month impact rows mirror stressed rows
    assert res.impact["per_month"]["2030-06"]["income_delta_kopecks"] == -693
    assert res.impact["per_month"]["2030-06"]["months_ahead"] == 1
    assert sum(row["income_delta_kopecks"] for row in res.impact["per_month"].values()) == -38_622
    assert (
        sum(row["redemption_delta_kopecks"] for row in res.impact["per_month"].values()) == -103_676
    )
    # coverage: all 12 month rows applied, none unknown
    assert res.coverage["total_months"] == 12
    assert res.coverage["eligible_months"] == 12
    assert res.coverage["applied"] == 12
    assert res.coverage["not_applicable"] == 0
    assert res.coverage["unknown"] == 0
    assert res.coverage["known_scope_income_real_value_delta_kopecks"] == -38_622
    assert res.coverage["known_scope_redemption_real_value_delta_kopecks"] == -103_676
    assert res.coverage["known_scope_total_cash_flow_real_value_delta_kopecks"] == -142_298
    assert res.row_applicability == {key: "applied" for key in LADDER_MONTH_KEYS}
    # income and redemption are separate categories in every row
    for key, row in rows.items():
        assert "income_delta_kopecks" in row and "redemption_delta_kopecks" in row


# 5. Nominal families never change: liquid capital, allocation, goals,
#    forecast and the nominal ladder are identical under base and stressed.
def test_5_nominal_families_unchanged(session):
    month, account = _full_setup(session)
    create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    goal = create_goal(
        session,
        name="Cap",
        goal_type=GoalType.CAPITAL,
        target_value="1000000.00",
        calculation_mode="liquid_capital_net",
    )
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    for family in ("liquid_assets_kopecks", "liquid_capital_net_kopecks", "debts_included_kopecks"):
        assert res.base[family] == res.stressed[family], family
    for family in ("asset_allocation", "account_allocation", "top_positions"):
        assert res.base[family] == res.stressed[family], family
    assert res.base["capital_goals"] == res.stressed["capital_goals"]
    base_goal = next(g for g in res.base["capital_goals"] if g["goal_id"] == goal.id)
    assert base_goal["current_kopecks"] == 12_150_000  # cash 500 + deposit 120000 + bond 1000
    # nominal forecast identical (single shared nominal projection)
    assert res.base["forecast_passive_income"] == res.stressed["forecast_passive_income"]
    assert res.base["forecast_passive_income"]["breakdown"][
        "expected_deposit_interest_kopecks"
    ] == (720_000)
    # nominal ladder identical and intact (coupon 100.00 present at +6)
    assert res.base["cash_flow_ladder"] == res.stressed["cash_flow_ladder"]
    ladder_months = res.stressed["cash_flow_ladder"]["months"]
    assert len(ladder_months) == 12
    nov = next(m for m in ladder_months if m["year"] == 2030 and m["month"] == 11)
    assert nov["coupon_kopecks"] == 10_000
    assert res.impact["liquid_assets_delta_kopecks"] == 0
    assert res.impact["liquid_capital_net_delta_kopecks"] == 0


# 6. Metric support: nominal metrics supported/unchanged, real-value metrics
#    supported, future-capital and goal adjustments honestly unavailable.
def test_6_metric_support_and_effect_blocks(session):
    month, account = _full_setup(session)
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    for key in (
        "liquid_assets",
        "liquid_capital_net",
        "asset_allocation",
        "account_allocation",
        "top_positions",
        "capital_goals",
        "forecast_passive_income",
        "cash_flow_ladder",
        "deposit_interest",
        "coupons",
        "dividends",
        "other_capital_income",
        "redemption",
        "historical_actual_passive_income",
        "debts",
        "current_capital_real_value",
        "future_income_real_value",
        "future_redemption_real_value",
        "future_total_cash_flow_real_value",
    ):
        assert res.metric_support[key]["status"] == "supported", key
    assert res.metric_support["future_capital_purchasing_power"]["status"] == "unavailable"
    assert res.metric_support["future_capital_purchasing_power"]["reason_codes"] == [
        "no_future_capital_trajectory"
    ]
    assert res.metric_support["inflation_adjusted_goal_coverage"]["status"] == "unavailable"
    assert res.metric_support["inflation_adjusted_goal_coverage"]["reason_codes"] == [
        "goal_price_basis_not_defined"
    ]
    # effect blocks appear identically in base and stressed
    for family in (res.base, res.stressed):
        assert family["current_capital_real_value_effect"] == {
            "status": "unchanged",
            "basis": "base_period_purchasing_power",
            "affected": False,
        }
        assert family["future_capital_purchasing_power_effect"] == {
            "status": "unavailable",
            "reason": "no_future_capital_trajectory",
        }
        assert family["inflation_adjusted_goal_effect"] == {
            "status": "unavailable",
            "reason": "goal_price_basis_not_defined",
        }
    # explicit v1 convention is declared
    assert "v1_monthly_inflation_convention" in res.assumptions


# 7. Normalized shock canonicalization and target scope
def test_7_normalized_shock_canonical_and_scope(session):
    month, account = _full_setup(session)
    r12 = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    r12b = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "12.00"}}
    )
    r12c = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "12.0"}}
    )
    r13 = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "13"}}
    )
    assert r12.normalized_shock_input == {
        "shock_type": "inflation_real_value",
        "annual_inflation_pct": "12",
    }
    assert r12.semantic_fingerprint == r12b.semantic_fingerprint == r12c.semantic_fingerprint
    assert r12.semantic_fingerprint != r13.semantic_fingerprint
    assert r12.normalized_target_scope == {
        "selector": "cash_flow_ladder_months",
        "ladder_months": LADDER_MONTH_KEYS,
    }
    # equivalent inputs produce identical stressed presentation
    assert r12.stressed == r12b.stressed == r12c.stressed
    assert r12.stressed != r13.stressed


# 8. Annual 6% -> monthly 0.5%: 10000 / 1.005^6 = 9705
def test_8_annual_6_percent(session):
    month, account = _month(session), _account(session)
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _coupon(
        session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 11, 15)
    )
    res = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "6"}}
    )
    row = _income_row(res, "2030-11")
    assert row["months_ahead"] == 6
    assert row["real_income_kopecks"] == 9_705
    assert row["income_delta_kopecks"] == -295


# 9. Repeating monthly rate (annual 100% -> 8.333..% monthly) stays exact and
#    deterministic at the kopeck boundary
def test_9_repeating_monthly_rate(session):
    month, account = _month(session), _account(session)
    bond = _bond(session)
    _position(session, month.id, account.id, bond.id, "1000.00")
    _coupon(
        session, month.id, account.id, bond.id, amount="100.00", expected_date=date(2030, 11, 15)
    )
    res = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "100"}}
    )
    row = _income_row(res, "2030-11")
    assert row["real_income_kopecks"] == 6_186
    assert row["income_delta_kopecks"] == -3_814
    # 12.5% -> 1.041666..% monthly also deterministic
    res2 = evaluate_scenario_lab(
        session, month.id, {"inflation_real_value": {"annual_inflation_pct": "12.5"}}
    )
    assert _income_row(res2, "2030-11")["real_income_kopecks"] == 9_397


# 10-13. Invalid inputs rejected with machine-readable codes
def test_10_negative_inflation_rejected(session):
    month, account = _full_setup(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session, month.id, {"inflation_real_value": {"annual_inflation_pct": "-1"}}
        )
    assert exc.value.code == "invalid_inflation_pct"


def test_11_nan_infinity_rejected(session):
    month, account = _full_setup(session)
    for bad in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ScenarioLabError) as exc:
            evaluate_scenario_lab(
                session, month.id, {"inflation_real_value": {"annual_inflation_pct": bad}}
            )
        assert exc.value.code == "invalid_inflation_pct"


def test_12_binary_float_and_bool_rejected(session):
    month, account = _full_setup(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session, month.id, {"inflation_real_value": {"annual_inflation_pct": 12.0}}
        )
    assert exc.value.code == "invalid_inflation_pct"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session, month.id, {"inflation_real_value": {"annual_inflation_pct": True}}
        )
    assert exc.value.code == "invalid_inflation_pct"


def test_13_missing_or_extra_fields_rejected(session):
    month, account = _full_setup(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(session, month.id, {"inflation_real_value": {}})
    assert exc.value.code == "invalid_inflation_pct"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {"inflation_real_value": {"annual_inflation_pct": "12", "extra": 1}},
        )
    assert exc.value.code == "invalid_shock_input"


# 14. Composition and unknown shock types fail closed
def test_14_combined_shock_rejected(session):
    month, account = _full_setup(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "equity_drawdown": {"drawdown_pct": "10"},
                "inflation_real_value": INFLATION_12,
            },
        )
    assert exc.value.code == "unsupported_composition_v1"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "deposit_rate_assumption": {
                    "assumed_annual_rate_pct": "12",
                    "all_eligible_deposits": True,
                },
                "inflation_real_value": INFLATION_12,
            },
        )
    assert exc.value.code == "unsupported_composition_v1"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session, month.id, {"gold_price_shock": {"gold_price_change_pct": "10"}}
        )
    assert exc.value.code == "unsupported_shock_type_v1"


# 15. top_n validated on the inflation path
def test_15_top_n_validated(session):
    month, account = _full_setup(session)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12}, top_n=0)
    assert exc.value.code == "invalid_top_n"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12}, top_n=True)
    assert exc.value.code == "invalid_top_n"


# 16. Inflation never consults instrument-type applicability: non-stock and
#     fund positions neither block nor leak into the real-value rows.
def test_16_instrument_types_irrelevant_for_real_value(session):
    month, account = _full_setup(session)
    fund = _fund(session)
    _position(session, month.id, account.id, fund.id, "9999.00")
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "7777.00")
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    # row_applicability contains only the month grid; no instrument rows at all
    assert set(res.row_applicability) == set(LADDER_MONTH_KEYS)
    assert res.coverage["unknown"] == 0
    assert res.metric_support["liquid_assets"]["status"] == "supported"
    assert res.metric_support["future_income_real_value"]["status"] == "supported"
    # capital is present but untouched
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]


# 17. Month with no cash flows at all: deterministic supported no-op
def test_17_empty_month_noop(session):
    month, account = _month(session), _account(session)
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    assert list(res.stressed["cash_flow_real_value"].keys()) == LADDER_MONTH_KEYS
    assert res.impact["future_income_real_value_delta_kopecks"] == 0
    assert res.impact["future_total_cash_flow_real_value_delta_kopecks"] == 0
    assert res.metric_support["future_income_real_value"]["status"] == "supported"
    assert res.coverage["applied"] == 12
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]


# 18. Deterministic replay
def test_18_deterministic_replay(session):
    month, account = _full_setup(session)
    shock = {"inflation_real_value": INFLATION_12}
    r1 = evaluate_scenario_lab(session, month.id, shock)
    r2 = evaluate_scenario_lab(session, month.id, shock)
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.base_fingerprint == r2.base_fingerprint
    assert r1.base == r2.base
    assert r1.stressed == r2.stressed
    assert r1.impact == r2.impact
    assert r1.normalized_target_scope == r2.normalized_target_scope
    assert r1.normalized_shock_input == r2.normalized_shock_input


# 19. generated_at excluded from the semantic fingerprint
def test_19_generated_at_excluded(session):
    month, account = _full_setup(session)
    shock = {"inflation_real_value": INFLATION_12}
    r1 = evaluate_scenario_lab(
        session, month.id, shock, generated_at=datetime(2030, 5, 12, 10, 0, tzinfo=UTC)
    )
    r2 = evaluate_scenario_lab(
        session, month.id, shock, generated_at=datetime(2030, 5, 12, 11, 0, tzinfo=UTC)
    )
    assert r1.semantic_fingerprint == r2.semantic_fingerprint
    assert r1.generated_at != r2.generated_at


# 20. No DB mutation
def test_20_no_db_mutation(session):
    month, account = _full_setup(session)
    cash = create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    debt = create_debt(
        session,
        reporting_month_id=month.id,
        debt_type="credit_card",
        name="Debt",
        current_balance="100.00",
        include_in_liquid_capital=True,
    )
    goal = create_goal(
        session,
        name="Cap",
        goal_type=GoalType.CAPITAL,
        target_value="1000000.00",
        calculation_mode="liquid_capital_net",
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
    evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    after = counts()
    assert before == after
    assert session.get(CashBalance, cash.id).amount_kopecks == 50_000
    assert session.get(Debt, debt.id).current_balance_kopecks == 10_000
    assert session.get(Goal, goal.id).target_value_kopecks == 100_000_000
    assert not session.new
    assert not session.dirty


# 21. No network/provider calls
def test_21_no_network_calls(session, monkeypatch):
    month, account = _full_setup(session)

    def _fail(*args, **kwargs):
        raise AssertionError("network call attempted")

    monkeypatch.setattr("socket.socket", _fail)
    res = evaluate_scenario_lab(session, month.id, {"inflation_real_value": INFLATION_12})
    assert res.semantic_fingerprint


# 22. Equity and deposit-rate regressions survive the dispatch change
def test_22_equity_and_deposit_still_work(session):
    month, account = _full_setup(session)
    stock = _stock(session)
    _position(session, month.id, account.id, stock.id, "1000.00")
    eq = evaluate_scenario_lab(session, month.id, {"equity_drawdown": {"drawdown_pct": "20"}})
    assert eq.stressed["liquid_assets_kopecks"] < eq.base["liquid_assets_kopecks"]
    dep = evaluate_scenario_lab(
        session,
        month.id,
        {
            "deposit_rate_assumption": {
                "assumed_annual_rate_pct": "12",
                "all_eligible_deposits": True,
            }
        },
    )
    assert (
        dep.stressed["forecast_passive_income"]["breakdown"]["expected_deposit_interest_kopecks"]
        == 1_440_000
    )


# 23. Domain helper is context-independent and exact at kopeck boundaries
def test_23_real_value_helper_context_invariance():
    from hermes_finance.domain.scenario_lab import parse_annual_inflation_pct, real_value_kopecks

    # (nominal_kopecks, annual_pct, months_ahead, expected_kopecks)
    cases = [
        (10_000, "12", 0, 10_000),  # Addition 2
        (10_000, "12", 1, 9_901),
        (60_000, "12", 2, 58_818),
        (60_000, "12", 11, 53_779),
        (10_000, "12", 6, 9_420),  # contract example G
        (1_000_000, "12", 11, 896_324),
        (10_000, "6", 6, 9_705),
        (60_000, "6", 11, 56_797),
        (10_000, "100", 6, 6_186),  # repeating monthly rate
        (10_000, "12.5", 6, 9_397),  # repeating monthly rate
        (10_000, "0", 11, 10_000),  # zero inflation
        (0, "12", 11, 0),
        (1, "12", 11, 1),  # sub-kopeck stays at its boundary
        (101, "12", 1, 100),  # exact division
        (102, "12", 1, 101),  # 100.990.. -> HALF_UP up
    ]
    for ambient_prec in (2, 5, 12, 28, 60):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            for nominal, annual, months_ahead, expected in cases:
                pct = parse_annual_inflation_pct(annual)
                got = real_value_kopecks(nominal, pct, months_ahead)
                assert got == expected, (ambient_prec, nominal, annual, months_ahead, got, expected)


# 24. Parse validation of the inflation rate itself
def test_24_inflation_parse_validation():
    from hermes_finance.domain.scenario_lab import parse_annual_inflation_pct

    assert parse_annual_inflation_pct("12") == Decimal("12")
    assert parse_annual_inflation_pct("12.00") == Decimal("12")
    assert parse_annual_inflation_pct(12) == Decimal("12")
    assert parse_annual_inflation_pct("0") == Decimal("0")
    for bad in (-1, "-1", 12.0, "NaN", "Infinity", "-Infinity", "", True, None):
        with pytest.raises(ValueError) as exc:
            parse_annual_inflation_pct(bad)
        assert "invalid_inflation_pct" in str(exc.value)


# 25. Full evaluation independent of the ambient decimal precision
def test_25_full_scenario_eval_independent_of_ambient_precision(session):
    month, account = _full_setup(session)
    shock = {"inflation_real_value": INFLATION_12}
    results = []
    for ambient_prec in (5, 28, 60):
        with localcontext() as ctx:
            ctx.prec = ambient_prec
            results.append(evaluate_scenario_lab(session, month.id, shock))
    first = results[0]
    for other in results[1:]:
        assert other.semantic_fingerprint == first.semantic_fingerprint
        assert other.base_fingerprint == first.base_fingerprint
        assert other.base == first.base
        assert other.stressed == first.stressed
        assert other.impact == first.impact
        assert other.coverage == first.coverage
        assert other.normalized_shock_input == first.normalized_shock_input
        assert other.normalized_target_scope == first.normalized_target_scope


# ---------------------------------------------------------------------------
# Single-capture internal-consistency regression: a deposit committed while
# the materializer is mid-capture (between read-model stages) must never leak
# into the running inflation evaluation — same frozen base, fingerprints and
# surfaces as the pre-mutation reference.
# ---------------------------------------------------------------------------


def _capture_stage_late_deposit(session, month, account, *, stage_probe):
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


def test_26_frozen_base_consistent_under_mutation_between_capture_stages(session, monkeypatch):
    month, account = _full_setup(session)
    shock = {"inflation_real_value": INFLATION_12}

    # pre-mutation reference evaluation
    reference = evaluate_scenario_lab(session, month.id, shock)

    import hermes_finance.services.scenario_frozen_base as sfb

    stage = sfb._capture_stage_build_cash_flow_ladder
    _, patched = _capture_stage_late_deposit(session, month, account, stage_probe=stage)
    monkeypatch.setattr(sfb, "_capture_stage_build_cash_flow_ladder", patched)

    running = evaluate_scenario_lab(session, month.id, shock)

    assert running.base_fingerprint == reference.base_fingerprint
    assert running.semantic_fingerprint == reference.semantic_fingerprint
    assert running.base == reference.base
    assert running.stressed == reference.stressed
    assert running.impact == reference.impact
    assert running.coverage == reference.coverage
    assert running.row_applicability == reference.row_applicability
    assert running.normalized_target_scope == reference.normalized_target_scope
    # the late deposit exists in the DB now but never entered any surface:
    # the ladder deposit component stays the captured 600.00/mo estimate
    assert running.stressed["cash_flow_real_value"]["2030-06"]["nominal_income_kopecks"] == 70_000
    assert running.stressed["cash_flow_real_value"]["2031-04"]["nominal_income_kopecks"] == 60_000
    # and no extra deposit row exists anywhere in the frozen result
    assert (
        session.scalar(
            select(func.count()).select_from(DepositSnapshot).where(DepositSnapshot.name == "Late")
        )
        == 1
    )
