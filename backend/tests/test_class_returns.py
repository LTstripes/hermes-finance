"""Synthetic no-crossing class service/API vectors; no Owner or provider data."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hermes_finance.database import create_database
from hermes_finance.domain.twrr import calculate_twrr
from hermes_finance.domain.xirr import (
    XirrAvailabilityStatus,
    XirrCashFlow,
    XirrQuality,
    XirrResult,
    calculate_xirr,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    APP_SETTINGS_ID,
    AccountPerformanceScopeMembership,
    AppSettings,
    Base,
    Instrument,
    InvestmentCashFlow,
    PositionSnapshot,
)
from hermes_finance.services import class_returns as service
from hermes_finance.services.accounts import create_account
from hermes_finance.services.class_endpoint_eligibility import (
    class_endpoint_eligibility,
    save_no_crossing_coverage,
)
from hermes_finance.services.in_kind_boundary_coverage import create_in_kind_movement
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)

START, END = date(2030, 1, 31), date(2031, 1, 31)


@pytest.fixture
def history(tmp_path):
    database = create_database(tmp_path / "synthetic-class-returns.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()

    def make(*, opening="1000.00", closing="1100.00", end=END, asset_class="stock"):
        months = [
            create_reporting_month(session, year=day.year, month=day.month, snapshot_date=day)
            for day in (START, end)
        ]
        account = create_account(session, name="Synthetic account", account_type="brokerage")
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.commit()
        instrument = create_instrument(
            session, name="Synthetic instrument", instrument_type=asset_class
        )
        for month, price in zip(months, (opening, closing)):
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="1000.00",
                market_price_per_unit=price,
                price_date=month.snapshot_date,
            )
        return session, database, months, account.id, instrument.id, end, asset_class

    yield make
    session.close()
    database.engine.dispose()


def attest(env, **claims):
    return save_no_crossing_coverage(
        env[0],
        asset_class=env[6],
        covered_from=START,
        covered_to=env[5],
        coverage_state="complete",
        opening_inventory_complete=claims.get("opening", True),
        closing_inventory_complete=claims.get("closing", True),
    )


def close(env):
    for month in env[2]:
        close_reporting_month(env[0], month.id)


def read(env):
    return service.class_returns_for_interval(
        env[0], asset_class=env[6], start_date=START, end_date=env[5]
    )


def positions(env):
    return list(env[0].scalars(select(PositionSnapshot).order_by(PositionSnapshot.id)))


def no_solvers(monkeypatch):
    xirr, twrr = (
        Mock(side_effect=AssertionError("evidence must gate XIRR")),
        Mock(side_effect=AssertionError("evidence must gate TWRR")),
    )
    monkeypatch.setattr(service, "calculate_xirr", xirr)
    monkeypatch.setattr(service, "calculate_twrr", twrr)
    return xirr, twrr


def assert_evidence_blocked(env, spies, reason, *, unsupported=False):
    evidence = class_endpoint_eligibility(
        env[0], asset_class=env[6], start_date=START, end_date=env[5]
    )
    result = read(env)
    assert result["eligibility_status"] == ("unsupported" if unsupported else "unavailable")
    assert result["evidence_reason_codes"] == evidence["reason_codes"]
    assert reason in result["evidence_reason_codes"]
    for name in ("xirr", "twrr"):
        assert result[name]["value"] is None
        assert result[name]["availability"] == "not_computable"
        assert result[name]["quality"] == "unavailable"
        assert result[name]["reason_codes"] == evidence["reason_codes"]
        assert result[name]["reason_source"] == "evidence"
    for spy in spies:
        spy.assert_not_called()


@pytest.mark.parametrize("asset_class", ["stock", "bond", "gold"])
@pytest.mark.parametrize(
    "closing, expected", [("1100.00", "10"), ("1000.00", "0"), ("900.00", "-10")]
)
def test_exact_year_positive_flat_loss_and_only_endpoint_construction(
    history, monkeypatch, asset_class, closing, expected
):
    env = history(closing=closing, asset_class=asset_class)
    attest(env)
    close(env)
    xirr, twrr = Mock(wraps=calculate_xirr), Mock(wraps=calculate_twrr)
    monkeypatch.setattr(service, "calculate_xirr", xirr)
    monkeypatch.setattr(service, "calculate_twrr", twrr)
    result = read(env)
    xirr.assert_called_once_with(
        (XirrCashFlow(START, -100000), XirrCashFlow(END, int(Decimal(closing) * 100)))
    )
    twrr.assert_called_once_with(100000, int(Decimal(closing) * 100), boundaries=())
    assert result["eligibility_status"] == "eligible"
    assert result["evidence_reason_codes"] == []
    for name in ("xirr", "twrr"):
        assert result[name]["availability"] == "available"
        assert result[name]["quality"] == "exact"
        assert abs(result[name]["value"] - Decimal(expected)) < Decimal("1e-20")
        assert result[name]["reason_source"] is None


def test_short_interval_annualized_xirr_differs_from_period_twrr(history):
    env = history(end=date(2030, 7, 31))
    attest(env)
    close(env)
    result = read(env)
    assert result["xirr"]["annualized"] is True
    assert result["twrr"]["annualized"] is False
    assert Decimal("20") < result["xirr"]["value"] < Decimal("22")
    assert result["twrr"]["value"] == Decimal("10")


@pytest.mark.parametrize(
    "opening, closing", [("0.00", "1100.00"), ("1000.00", "0.00"), ("0.00", "0.00")]
)
def test_zero_endpoints_keep_each_solver_domain_without_fallback(history, opening, closing):
    env = history(opening=opening, closing=closing)
    attest(env)
    close(env)
    result = read(env)
    assert result["eligibility_status"] == "eligible"
    assert result["evidence_reason_codes"] == []
    assert result["xirr"]["reason_codes"] == ("not_computable_xirr_no_valid_root",)
    assert result["xirr"]["value"] is None
    assert result["xirr"]["reason_source"] == "solver"
    if opening == "0.00":
        assert result["twrr"]["value"] is None
        assert result["twrr"]["reason_codes"] == (
            "not_computable_twrr_zero_or_negative_denominator",
        )
        assert result["twrr"]["reason_source"] == "solver"
    else:
        assert result["twrr"]["availability"] == "available"
        assert result["twrr"]["value"] == Decimal("-100")


def test_missing_no_crossing_does_not_invoke_solvers(history, monkeypatch):
    env = history()
    close(env)
    assert_evidence_blocked(
        env, no_solvers(monkeypatch), "no_crossing_coverage_missing_or_ambiguous"
    )


@pytest.mark.parametrize("claim", ["opening", "closing"])
def test_inventory_claim_missing_cannot_be_repaired_by_other_class_rows(
    history, monkeypatch, claim
):
    env = history()
    other_account = create_account(env[0], name="Synthetic other account", account_type="brokerage")
    env[0].add(
        AccountPerformanceScopeMembership(
            account_id=other_account.id, effective_from=date(2029, 1, 1), include_in_returns=True
        )
    )
    env[0].commit()
    bond = create_instrument(env[0], name="Synthetic bond", instrument_type="bond")
    for month in env[2]:
        create_position_snapshot(
            env[0],
            reporting_month_id=month.id,
            account_id=other_account.id,
            instrument_id=bond.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=month.snapshot_date,
        )
    attest(env, **{claim: False})
    close(env)
    assert_evidence_blocked(env, no_solvers(monkeypatch), f"{claim}_class_inventory_not_complete")


@pytest.mark.parametrize(
    "identity, reason",
    [(None, "historical_class_unknown"), ("bond", "historical_class_reclassified")],
)
def test_c1_unknown_or_ambiguous_does_not_invoke_solvers(history, monkeypatch, identity, reason):
    env = history()
    positions(env)[1].historical_instrument_type = identity
    env[0].commit()
    close(env)
    assert_evidence_blocked(env, no_solvers(monkeypatch), reason)


@pytest.mark.parametrize("mode", ["material", "reopen", "correction"])
def test_no_stale_results_after_material_or_lifecycle_change(history, monkeypatch, mode):
    env = history()
    attest(env)
    close(env)
    assert read(env)["xirr"]["availability"] == "available"
    if mode == "material":
        # Synthetic committed drift bypasses normal guards solely to exercise invalidation.
        positions(env)[1].market_value_kopecks += 100
        env[0].commit()
        reason = "no_crossing_material_changed"
    else:
        reopen_reporting_month(env[0], env[2][1].id)
        if mode == "correction":
            row = positions(env)[1]
            update_position_snapshot(env[0], row.id, historical_instrument_type="bond")
            update_position_snapshot(env[0], row.id, historical_instrument_type="stock")
        close_reporting_month(env[0], env[2][1].id)
        reason = "no_crossing_coverage_not_complete"
    assert_evidence_blocked(env, no_solvers(monkeypatch), reason)


def test_current_catalogue_type_and_currency_cannot_rewrite_returns(history):
    env = history()
    attest(env)
    close(env)
    before = read(env)
    instrument = env[0].get(Instrument, env[4])
    instrument.instrument_type = "bond"
    instrument.currency = "USD"
    env[0].commit()
    assert read(env) == before


def test_non_rub_base_currency_is_unsupported_and_gates_solvers(history, monkeypatch):
    env = history()
    attest(env)
    close(env)
    settings = env[0].get(AppSettings, APP_SETTINGS_ID)
    if settings is None:
        env[0].add(AppSettings(id=APP_SETTINGS_ID, base_currency="USD"))
    else:
        settings.base_currency = "USD"
    env[0].commit()
    assert_evidence_blocked(env, no_solvers(monkeypatch), "unsupported_currency", unsupported=True)


@pytest.mark.parametrize("kind", ["dividend", "coupon", "redemption"])
def test_known_distribution_contradiction_gates_solvers(history, monkeypatch, kind):
    env = history()
    attest(env)
    env[0].add(
        InvestmentCashFlow(
            reporting_month_id=env[2][1].id,
            account_id=env[3],
            instrument_id=env[4],
            flow_type=kind,
            event_date=date(2030, 7, 31),
            gross_amount_kopecks=100,
            tax_amount_kopecks=0,
            commission_amount_kopecks=0,
            net_amount_kopecks=100,
            currency="RUB",
            source="synthetic",
        )
    )
    env[0].commit()
    close(env)
    assert_evidence_blocked(env, no_solvers(monkeypatch), "known_cash_crossing")


def test_exact_same_class_transfer_keeps_only_aggregate_endpoints(history, monkeypatch):
    env = history()
    session = env[0]
    destination = create_account(session, name="Synthetic destination", account_type="brokerage")
    session.add(
        AccountPerformanceScopeMembership(
            account_id=destination.id, effective_from=date(2029, 1, 1), include_in_returns=True
        )
    )
    session.commit()
    session.delete(positions(env)[1])
    session.commit()
    create_position_snapshot(
        session,
        reporting_month_id=env[2][1].id,
        account_id=destination.id,
        instrument_id=env[4],
        quantity=1,
        average_cost_per_unit="1000.00",
        market_price_per_unit="1100.00",
        price_date=END,
    )
    create_in_kind_movement(
        session,
        reporting_month_id=env[2][1].id,
        event_date=date(2031, 1, 15),
        movement_kind="internal_transfer",
        source_account_id=env[3],
        destination_account_id=destination.id,
        instrument_id=env[4],
        quantity=1,
    )
    attest(env)
    close(env)
    xirr, twrr = Mock(wraps=calculate_xirr), Mock(wraps=calculate_twrr)
    monkeypatch.setattr(service, "calculate_xirr", xirr)
    monkeypatch.setattr(service, "calculate_twrr", twrr)
    result = read(env)
    assert result["historical_account_ids"] == (env[3], destination.id)
    assert result["twrr"]["value"] == Decimal("10")
    xirr.assert_called_once_with((XirrCashFlow(START, -100000), XirrCashFlow(END, 110000)))
    twrr.assert_called_once_with(100000, 110000, boundaries=())


def api_read(client, env, asset_class=None):
    return client.get(
        "/api/performance/class-returns",
        params=dict(asset_class=asset_class or env[6], start_date=str(START), end_date=str(env[5])),
    )


def test_api_dates_units_safe_provenance_and_read_only(history):
    env = history()
    attest(env)
    close(env)
    with TestClient(create_app(database=env[1])) as client:
        before = env[1].engine.raw_connection()
        try:
            before_state = tuple(before.iterdump())
            response = api_read(client, env)
            assert response.status_code == 200, response.text
            assert tuple(before.iterdump()) == before_state
        finally:
            before.close()
        body = response.json()
        assert body["asset_class"] == "stock"
        assert (
            body["requested_period"]
            == body["actual_covered_period"]
            == {"start_date": str(START), "end_date": str(END)}
        )
        assert body["historical_account_ids"] == [env[3]]
        assert body["performance_currency"] == "RUB"
        assert body["valuation_basis"] == "persisted_rub_market_value_kopecks"
        assert body["coverage_state"] == "complete"
        assert body["coverage_provenance"][0]["opening_inventory_complete"] is True
        assert body["coverage_provenance"][0]["closing_inventory_complete"] is True
        assert body["coverage_provenance"][0]["provenance_kind"] == "owner_attestation"
        assert "signature" not in response.text
        for name in ("xirr", "twrr"):
            assert isinstance(body[name]["value"], str)
            assert abs(Decimal(body[name]["value"]) - 10) < Decimal("1e-20")
            assert body[name]["value_unit"] == "percentage_points"
        assert body["xirr"]["annualized"] is True
        assert body["twrr"]["annualized"] is False
        for path in ("xirr", "twrr"):
            assert (
                client.get(
                    f"/api/performance/{path}",
                    params=dict(start_date=str(START), end_date=str(END), scope="asset_class"),
                ).status_code
                == 422
            )


@pytest.mark.parametrize(
    "asset_class", ["fund", "currency", "deposit", "savings", "gold_other", "other"]
)
def test_unsupported_class_api_preserves_capability_reason_and_gates_solvers(
    history, monkeypatch, asset_class
):
    env = history()
    spies = no_solvers(monkeypatch)
    with TestClient(create_app(database=env[1])) as client:
        response = api_read(client, env, asset_class)
    assert response.status_code == 200
    body = response.json()
    assert body["asset_class"] == asset_class
    assert body["eligibility_status"] == "unsupported"
    assert body["evidence_reason_codes"] == ["unsupported_class"]
    assert body["actual_covered_period"] == {"start_date": None, "end_date": None}
    for name in ("xirr", "twrr"):
        assert body[name]["value"] is None
        assert body[name]["reason_source"] == "evidence"
        assert body[name]["reason_codes"] == ["unsupported_class"]
    for spy in spies:
        spy.assert_not_called()


@pytest.mark.parametrize(
    "reason", ["not_computable_xirr_root_ambiguity", "future_solver_limitation"]
)
def test_generic_solver_reason_propagation_never_becomes_missing_evidence(
    history, monkeypatch, reason
):
    env = history()
    attest(env)
    close(env)
    solver = Mock(
        return_value=XirrResult(
            availability=XirrAvailabilityStatus.NOT_COMPUTABLE,
            quality=XirrQuality.UNAVAILABLE,
            annualized_rate=None,
            reason_codes=(reason,),
        )
    )
    monkeypatch.setattr(service, "calculate_xirr", solver)
    with TestClient(create_app(database=env[1])) as client:
        body = api_read(client, env).json()
    assert body["eligibility_status"] == "eligible"
    assert body["evidence_reason_codes"] == []
    assert body["xirr"]["reason_codes"] == [reason]
    assert body["xirr"]["reason_source"] == "solver"
    assert body["xirr"]["value"] is None
    assert body["twrr"]["availability"] == "available"
    assert body["twrr"]["value"] == "10"
    solver.assert_called_once_with((XirrCashFlow(START, -100000), XirrCashFlow(END, 110000)))


def test_api_rejects_invalid_interval_and_missing_date(history):
    env = history()
    with TestClient(create_app(database=env[1])) as client:
        assert (
            client.get(
                "/api/performance/class-returns", params={"asset_class": "stock"}
            ).status_code
            == 422
        )
        for end in (START, date(2029, 1, 31)):
            response = client.get(
                "/api/performance/class-returns",
                params=dict(asset_class="stock", start_date=str(START), end_date=str(end)),
            )
            assert response.status_code == 422
