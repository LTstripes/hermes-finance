"""Scenario Lab 141-B — fx_translation_shock baseline semantics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, getcontext
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session as SASession

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, GoalType, InstrumentType
from hermes_finance.domain.scenario_lab import (
    FX_TRANSLATION_BASIS_UNAVAILABLE,
    MISSING_CURRENCY,
    RowApplicability,
    canonical_reporting_value_change_pct,
    classify_fx_applicability,
    normalize_reporting_value_change_pct,
    parse_reporting_value_change_pct,
    parse_target_currency,
)
from hermes_finance.persistence import (
    Base,
    CashBalance,
    Debt,
    DepositSnapshot,
    Goal,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.debts import create_debt
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.goals import create_goal
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.scenario_lab import ScenarioLabError, evaluate_scenario_lab

_FX_SENSITIVE = (
    "liquid_assets",
    "liquid_capital_net",
    "asset_allocation",
    "account_allocation",
    "top_positions",
    "capital_goals",
    "per_position",
)


@pytest.fixture
def session(tmp_path: Path):
    db = create_database(tmp_path / "scenario_lab_fx.db")
    Base.metadata.create_all(db.engine)
    s = db.session_factory()
    try:
        yield s
    finally:
        s.close()
        db.engine.dispose()


def _month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12)):
    return create_reporting_month(session, year=year, month=month, snapshot_date=snapshot_date)


def _instrument(session, name="S", currency="RUB", instrument_type=InstrumentType.STOCK):
    return create_instrument(session, name=name, instrument_type=instrument_type, currency=currency)


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


def _basic_setup(session):
    month = _month(session)
    acc = create_account(session, name="Broker", account_type=AccountType.BROKERAGE)
    return month, acc


def _fx(target="USD", pct="10"):
    return {
        "fx_translation_shock": {
            "target_currency": target,
            "reporting_value_change_pct": pct,
        }
    }


def _set_currency(session, instrument: Instrument, currency: str) -> None:
    instrument.currency = currency
    session.commit()
    session.refresh(instrument)


def _assert_fx_sensitive_status(res, status: str, *reasons: str) -> None:
    for key in _FX_SENSITIVE:
        support = res.metric_support[key]
        assert support["status"] == status, key
        for reason in reasons:
            assert reason in support["reason_codes"], key


# ---- domain input exactness ----


def test_target_currency_trim_uppercase_canonical():
    assert parse_target_currency(" usd ") == "USD"
    assert parse_target_currency("Usd") == "USD"
    assert parse_target_currency("USD") == "USD"


@pytest.mark.parametrize("raw", ["", "  ", "US", "USDT", "US1", "12A", True, 1, None, 1.0])
def test_target_currency_invalid_fail_closed(raw):
    with pytest.raises(ValueError) as exc:
        parse_target_currency(raw)
    assert "invalid_target_currency" in str(exc.value)


def test_signed_pct_canonical_and_range():
    assert normalize_reporting_value_change_pct(parse_reporting_value_change_pct("10")) == "10"
    assert normalize_reporting_value_change_pct(parse_reporting_value_change_pct("10.00")) == "10"
    assert normalize_reporting_value_change_pct(parse_reporting_value_change_pct("+10")) == "10"
    assert normalize_reporting_value_change_pct(parse_reporting_value_change_pct("-10")) == "-10"
    assert normalize_reporting_value_change_pct(parse_reporting_value_change_pct("-100")) == "-100"
    assert normalize_reporting_value_change_pct(parse_reporting_value_change_pct("1000")) == "1000"
    assert canonical_reporting_value_change_pct(
        parse_reporting_value_change_pct("10.00")
    ) == Decimal("10")
    with pytest.raises(ValueError) as exc:
        parse_reporting_value_change_pct("-100.01")
    assert "invalid_reporting_value_change_pct" in str(exc.value)
    with pytest.raises(ValueError):
        parse_reporting_value_change_pct("-101")
    with pytest.raises(ValueError) as exc:
        parse_reporting_value_change_pct(10.0)
    assert "binary float" in str(exc.value)
    with pytest.raises(ValueError):
        parse_reporting_value_change_pct(True)
    with pytest.raises(ValueError):
        parse_reporting_value_change_pct(False)


def test_classify_fx_reporting_currency_not_applicable():
    assert (
        classify_fx_applicability("RUB", target_currency="RUB", reporting_currency="RUB")
        == RowApplicability.NOT_APPLICABLE
    )
    assert (
        classify_fx_applicability("USD", target_currency="USD", reporting_currency="RUB")
        == RowApplicability.APPLIED
    )
    assert (
        classify_fx_applicability("EUR", target_currency="USD", reporting_currency="RUB")
        == RowApplicability.NOT_APPLICABLE
    )
    assert (
        classify_fx_applicability("  ", target_currency="USD", reporting_currency="RUB")
        == RowApplicability.UNKNOWN
    )
    assert (
        classify_fx_applicability("US", target_currency="USD", reporting_currency="RUB")
        == RowApplicability.UNKNOWN
    )


# ---- service acceptance ----


def test_input_canonicalization_and_fingerprint_stability(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    _position(session, month.id, acc.id, usd.id, "1000.00")
    r1 = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    r2 = evaluate_scenario_lab(session, month.id, _fx("USD", "10.00"))
    r3 = evaluate_scenario_lab(session, month.id, _fx(" usd ", "+10"))
    assert r1.semantic_fingerprint == r2.semantic_fingerprint == r3.semantic_fingerprint
    assert r1.normalized_shock_input["target_currency"] == "USD"
    assert r1.normalized_shock_input["reporting_value_change_pct"] == "10"
    r_distinct = evaluate_scenario_lab(session, month.id, _fx("USD", "10.001"))
    assert r_distinct.semantic_fingerprint != r1.semantic_fingerprint
    assert r_distinct.normalized_shock_input["reporting_value_change_pct"] == "10.001"


def test_lowercase_whitespace_target_currency_canonicalizes(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "U", currency="USD")
    _position(session, month.id, acc.id, usd.id)
    a = evaluate_scenario_lab(session, month.id, _fx("usd", "10"))
    b = evaluate_scenario_lab(session, month.id, _fx(" USD ", "10"))
    assert a.normalized_shock_input == b.normalized_shock_input
    assert a.semantic_fingerprint == b.semantic_fingerprint


def test_signed_decimal_and_rejects(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "U", currency="USD")
    _position(session, month.id, acc.id, usd.id)
    neg = evaluate_scenario_lab(session, month.id, _fx("USD", "-10"))
    pos = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert neg.normalized_shock_input["reporting_value_change_pct"] == "-10"
    assert pos.normalized_shock_input["reporting_value_change_pct"] == "10"
    assert neg.semantic_fingerprint != pos.semantic_fingerprint
    evaluate_scenario_lab(session, month.id, _fx("USD", "-100"))
    evaluate_scenario_lab(session, month.id, _fx("USD", "1000"))
    with pytest.raises(ValueError) as exc:
        evaluate_scenario_lab(session, month.id, _fx("USD", 10.0))
    assert "invalid_reporting_value_change_pct" in str(exc.value)
    with pytest.raises(ValueError):
        evaluate_scenario_lab(session, month.id, _fx("USD", True))
    with pytest.raises(ValueError) as exc:
        evaluate_scenario_lab(session, month.id, _fx("USD", "-100.01"))
    assert "below -100" in str(exc.value)
    with pytest.raises(ValueError):
        evaluate_scenario_lab(session, month.id, _fx("US", "10"))


def test_matching_usd_not_naively_multiplied(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    pos = _position(session, month.id, acc.id, usd.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    pid = str(pos.id)
    assert res.base["per_position"][pid]["market_value_kopecks"] == 100_000
    assert res.stressed["per_position"][pid]["market_value_kopecks"] == 100_000
    assert res.stressed["liquid_assets_kopecks"] == 100_000
    assert res.stressed["liquid_assets_kopecks"] != 110_000
    assert res.impact["liquid_assets_delta_kopecks"] == 0
    assert res.impact["per_position"][pid]["delta_kopecks"] == 0
    assert res.row_applicability[pid] == "applied"
    assert FX_TRANSLATION_BASIS_UNAVAILABLE in res.impact["per_position"][pid]["reason_codes"]
    _assert_fx_sensitive_status(res, "unavailable", FX_TRANSLATION_BASIS_UNAVAILABLE)


def test_different_currency_not_applicable(session):
    month, acc = _basic_setup(session)
    eur = _instrument(session, "EUR-stock", currency="EUR")
    pos = _position(session, month.id, acc.id, eur.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    pid = str(pos.id)
    assert res.row_applicability[pid] == "not_applicable"
    assert res.impact["per_position"][pid]["reason_codes"] == []
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"] == 100_000
    _assert_fx_sensitive_status(res, "supported")


def test_missing_invalid_currency_unknown_never_not_applicable(session):
    month, acc = _basic_setup(session)
    blank = _instrument(session, "Blank", currency="USD")
    invalid = _instrument(session, "Bad", currency="USD")
    _set_currency(session, blank, "   ")
    _set_currency(session, invalid, "US")
    p_blank = _position(session, month.id, acc.id, blank.id, "400.00")
    p_invalid = _position(session, month.id, acc.id, invalid.id, "500.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.row_applicability[str(p_blank.id)] == "unknown"
    assert res.row_applicability[str(p_invalid.id)] == "unknown"
    assert res.row_applicability[str(p_blank.id)] != "not_applicable"
    assert MISSING_CURRENCY in res.impact["per_position"][str(p_blank.id)]["reason_codes"]
    assert MISSING_CURRENCY in res.impact["per_position"][str(p_invalid.id)]["reason_codes"]
    _assert_fx_sensitive_status(res, "unknown", MISSING_CURRENCY)


def test_empty_target_scope_supported_unchanged(session):
    month, acc = _basic_setup(session)
    rub = _instrument(session, "RUB-stock", currency="RUB")
    pos = _position(session, month.id, acc.id, rub.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.row_applicability[str(pos.id)] == "not_applicable"
    assert res.coverage["applied"] == 0
    assert res.coverage["unknown"] == 0
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]
    assert res.impact["liquid_assets_delta_kopecks"] == 0
    _assert_fx_sensitive_status(res, "supported")


def test_unknown_only_aggregate_unknown(session):
    month, acc = _basic_setup(session)
    inst = _instrument(session, "Mystery", currency="USD")
    _set_currency(session, inst, "")
    pos = _position(session, month.id, acc.id, inst.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.row_applicability[str(pos.id)] == "unknown"
    assert res.coverage["applied"] == 0
    assert res.coverage["unknown"] == 1
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"] == 100_000
    _assert_fx_sensitive_status(res, "unknown", MISSING_CURRENCY)
    assert res.metric_support["liquid_assets"]["status"] != "supported"


def test_matching_scope_aggregate_unavailable_numeric_base_known(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    _position(session, month.id, acc.id, usd.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.coverage["applied"] == 1
    assert res.coverage["unknown"] == 0
    assert res.base["liquid_assets_kopecks"] == 100_000
    assert res.stressed["liquid_assets_kopecks"] == 100_000
    _assert_fx_sensitive_status(res, "unavailable", FX_TRANSLATION_BASIS_UNAVAILABLE)
    assert res.metric_support["liquid_assets"]["status"] != "supported"


def test_mixed_matching_and_unknown_coverage(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    mystery = _instrument(session, "Mystery", currency="USD")
    _set_currency(session, mystery, "US")
    p_usd = _position(session, month.id, acc.id, usd.id, "1000.00")
    p_unk = _position(session, month.id, acc.id, mystery.id, "400.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.row_applicability[str(p_usd.id)] == "applied"
    assert res.row_applicability[str(p_unk.id)] == "unknown"
    assert res.coverage["applied"] == 1
    assert res.coverage["unknown"] == 1
    _assert_fx_sensitive_status(
        res, "unavailable", FX_TRANSLATION_BASIS_UNAVAILABLE, MISSING_CURRENCY
    )
    assert res.metric_support["liquid_assets"]["reason_codes"] == [
        FX_TRANSLATION_BASIS_UNAVAILABLE,
        MISSING_CURRENCY,
    ]


def test_excluded_capital_rows_do_not_contaminate(session):
    month = _month(session)
    acc_inc = create_account(session, name="Inc", account_type=AccountType.BROKERAGE)
    acc_ex = create_account(
        session, name="Ex", account_type=AccountType.BROKERAGE, include_in_capital=False
    )
    usd = _instrument(session, "USD-stock", currency="USD")
    rub = _instrument(session, "RUB-stock", currency="RUB")
    mystery = _instrument(session, "Mystery", currency="USD")
    _set_currency(session, mystery, "  ")
    p_rub = _position(session, month.id, acc_inc.id, rub.id, "1000.00")
    p_ex_usd = _position(session, month.id, acc_ex.id, usd.id, "5000.00")
    p_ex_unk = _position(session, month.id, acc_ex.id, mystery.id, "400.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert str(p_ex_usd.id) not in res.row_applicability
    assert str(p_ex_unk.id) not in res.row_applicability
    assert str(p_ex_usd.id) not in res.impact["per_position"]
    assert str(p_rub.id) in res.row_applicability
    assert res.row_applicability[str(p_rub.id)] == "not_applicable"
    assert res.coverage["applied"] == 0
    assert res.coverage["unknown"] == 0
    assert res.coverage["eligible_positions"] == 1
    _assert_fx_sensitive_status(res, "supported")
    assert res.base["liquid_assets_kopecks"] == 100_000


def test_no_db_mutation(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    pos = _position(session, month.id, acc.id, usd.id, "1000.00")
    create_cash_balance(session, reporting_month_id=month.id, name="Cash", amount="500.00")
    create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=acc.id,
        name="Dep",
        deposit_type="deposit",
        balance="2000.00",
        annual_rate="5.00",
    )
    create_debt(
        session,
        reporting_month_id=month.id,
        debt_type="credit_card",
        name="Debt",
        current_balance="100.00",
        include_in_liquid_capital=True,
    )
    create_goal(
        session,
        name="G",
        goal_type=GoalType.CAPITAL,
        target_value="10000.00",
        calculation_mode="liquid_capital_net",
    )

    def counts():
        return {
            "months": session.scalar(select(func.count()).select_from(ReportingMonth)),
            "positions": session.scalar(select(func.count()).select_from(PositionSnapshot)),
            "cash": session.scalar(select(func.count()).select_from(CashBalance)),
            "deposits": session.scalar(select(func.count()).select_from(DepositSnapshot)),
            "debts": session.scalar(select(func.count()).select_from(Debt)),
            "goals": session.scalar(select(func.count()).select_from(Goal)),
            "instruments": session.scalar(select(func.count()).select_from(Instrument)),
        }

    before = counts()
    before_pos = session.get(PositionSnapshot, pos.id).market_value_kopecks
    before_ccy = session.get(Instrument, usd.id).currency
    evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert counts() == before
    assert session.get(PositionSnapshot, pos.id).market_value_kopecks == before_pos
    assert session.get(Instrument, usd.id).currency == before_ccy
    assert not session.new
    assert not session.dirty


def test_frozen_payload_concurrent_writer(session, monkeypatch):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    pos = _position(session, month.id, acc.id, usd.id, "10.00")
    baseline = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert baseline.base["liquid_assets_kopecks"] == 1000
    assert baseline.stressed["liquid_assets_kopecks"] == 1000
    assert baseline.metric_support["liquid_assets"]["status"] == "unavailable"

    import hermes_finance.services.scenario_lab as sl

    orig_calc = sl.calculate_liquid_capital
    mutated = {"done": False}

    def patched_calc(inp):
        if not mutated["done"]:
            mutated["done"] = True
            engine = session.get_bind()
            second = SASession(engine)
            try:
                ps = second.get(PositionSnapshot, pos.id)
                inst = second.get(Instrument, usd.id)
                assert ps is not None and inst is not None
                ps.market_value_kopecks = 2000
                inst.currency = "RUB"
                second.commit()
            finally:
                second.close()
        return orig_calc(inp)

    monkeypatch.setattr(sl, "calculate_liquid_capital", patched_calc)
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.base["liquid_assets_kopecks"] == 1000
    assert res.stressed["liquid_assets_kopecks"] == 1000
    assert res.stressed["liquid_assets_kopecks"] != 1100
    assert res.stressed["liquid_assets_kopecks"] != 2000
    assert res.metric_support["liquid_assets"]["status"] == "unavailable"
    assert res.row_applicability[str(pos.id)] == "applied"
    monkeypatch.setattr(sl, "calculate_liquid_capital", orig_calc)


def test_ambient_decimal_context_does_not_change_semantics(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "USD-stock", currency="USD")
    _position(session, month.id, acc.id, usd.id, "1000.00")
    long_pct = "10.12345678901234567890123456789"
    getcontext().prec = 5
    r_low = evaluate_scenario_lab(session, month.id, _fx("USD", long_pct))
    getcontext().prec = 50
    r_high = evaluate_scenario_lab(session, month.id, _fx("USD", long_pct))
    getcontext().prec = 28
    assert r_low.semantic_fingerprint == r_high.semantic_fingerprint
    assert r_low.normalized_shock_input == r_high.normalized_shock_input
    assert r_low.stressed["liquid_assets_kopecks"] == r_high.stressed["liquid_assets_kopecks"]
    assert r_low.metric_support["liquid_assets"]["status"] == "unavailable"


def test_no_ticker_name_inference(session):
    month, acc = _basic_setup(session)
    named = _instrument(session, name="Apple USD NYSE", currency="RUB")
    named.ticker = "AAPL"
    session.commit()
    pos = _position(session, month.id, acc.id, named.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.row_applicability[str(pos.id)] == "not_applicable"
    _assert_fx_sensitive_status(res, "supported")
    assert "no_live_fx_lookup" in res.assumptions
    assert "no_inferred_fx_exposure" in res.assumptions
    assert "no_hedge_inference" in res.assumptions
    assert "no_ticker_name_issuer_domicile_inference" in res.assumptions


def test_reporting_currency_target_is_not_fx(session):
    month, acc = _basic_setup(session)
    rub = _instrument(session, "RUB-stock", currency="RUB")
    pos = _position(session, month.id, acc.id, rub.id, "1000.00")
    res = evaluate_scenario_lab(session, month.id, _fx("RUB", "10"))
    assert res.row_applicability[str(pos.id)] == "not_applicable"
    _assert_fx_sensitive_status(res, "supported")
    assert res.base["liquid_assets_kopecks"] == res.stressed["liquid_assets_kopecks"]


def test_composition_and_unsupported_still_rejected(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "U", currency="USD")
    _position(session, month.id, acc.id, usd.id)
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {
                "equity_drawdown": {"drawdown_pct": "10"},
                "fx_translation_shock": {
                    "target_currency": "USD",
                    "reporting_value_change_pct": "10",
                },
            },
        )
    assert exc.value.code == "unsupported_composition_v1"
    with pytest.raises(ScenarioLabError) as exc:
        evaluate_scenario_lab(
            session,
            month.id,
            {"issuer_impairment": {"issuer_id": "x", "haircut_pct": "10"}},
        )
    assert exc.value.code == "unsupported_shock_type_v1"


def test_no_network_calls(session, monkeypatch):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "U", currency="USD")
    _position(session, month.id, acc.id, usd.id)
    import socket

    def _fail(*a, **kw):
        raise AssertionError("network call attempted")

    monkeypatch.setattr(socket, "socket", _fail)
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    assert res.semantic_fingerprint


def test_capital_goal_support_unavailable_when_matching(session):
    month, acc = _basic_setup(session)
    usd = _instrument(session, "U", currency="USD")
    _position(session, month.id, acc.id, usd.id, "1000.00")
    goal = create_goal(
        session,
        name="Cap",
        goal_type=GoalType.CAPITAL,
        target_value="5000.00",
        calculation_mode="liquid_capital_net",
    )
    res = evaluate_scenario_lab(session, month.id, _fx("USD", "10"))
    base_g = next(g for g in res.base["capital_goals"] if g["goal_id"] == goal.id)
    stressed_g = next(g for g in res.stressed["capital_goals"] if g["goal_id"] == goal.id)
    assert base_g["current_kopecks"] == stressed_g["current_kopecks"] == 100_000
    assert res.metric_support["capital_goals"]["status"] == "unavailable"
    assert FX_TRANSLATION_BASIS_UNAVAILABLE in res.metric_support["capital_goals"]["reason_codes"]
