"""Synthetic C2/C3 whole-class evidence, corrections and exact endpoints."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text

from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Account,
    Base,
    ClassNoCrossingCoverage,
    Instrument,
    InvestmentCashFlow,
    PositionSnapshot,
)
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership as Membership,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.class_endpoint_eligibility import (
    class_endpoint_eligibility,
    save_no_crossing_coverage,
)
from hermes_finance.services.in_kind_boundary_coverage import create_in_kind_movement
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)

START, MID, END = date(2030, 1, 31), date(2030, 2, 15), date(2030, 2, 28)


@pytest.fixture
def env(tmp_path):
    database = create_database(tmp_path / "synthetic-class.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    months = [
        create_reporting_month(session, year=2030, month=n, snapshot_date=day)
        for n, day in ((1, START), (2, END))
    ]
    account = create_account(session, name="Synthetic class account", account_type="brokerage")
    session.add(
        Membership(account_id=account.id, effective_from=date(2029, 1, 1), include_in_returns=True)
    )
    session.commit()
    instrument = create_instrument(session, name="Synthetic stock", instrument_type="stock")
    for month, price in zip(months, ("100.00", "110.00")):
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=2,
            average_cost_per_unit="100.00",
            market_price_per_unit=price,
            price_date=month.snapshot_date,
        )
    yield session, database, months, account.id, instrument.id
    session.close()
    database.engine.dispose()


def attest(env, asset_class="stock", **kwargs):
    return save_no_crossing_coverage(
        env[0],
        asset_class=asset_class,
        covered_from=START,
        covered_to=END,
        coverage_state="complete",
        **kwargs,
    )


def close(env):
    for month in env[2]:
        close_reporting_month(env[0], month.id)


def read(env, asset_class="stock", start=START, end=END):
    return class_endpoint_eligibility(
        env[0], asset_class=asset_class, start_date=start, end_date=end
    )


def positions(env):
    return list(env[0].scalars(select(PositionSnapshot).order_by(PositionSnapshot.id)))


def flow(env, kind, *, instrument=True):
    row = InvestmentCashFlow(
        reporting_month_id=env[2][1].id,
        account_id=env[3],
        instrument_id=env[4] if instrument else None,
        flow_type=kind,
        event_date=MID,
        gross_amount_kopecks=100,
        tax_amount_kopecks=0,
        commission_amount_kopecks=0,
        net_amount_kopecks=100,
        currency="RUB",
        source="synthetic",
    )
    env[0].add(row)
    env[0].commit()


def test_stable_exact_endpoints_catalogue_and_account_edits_do_not_rewrite(env):
    attest(env)
    close(env)
    before = read(env)
    assert before["status"] == "eligible"
    assert (before["opening_value_kopecks"], before["closing_value_kopecks"]) == (20000, 22000)
    assert before["historical_account_ids"] == (env[3],)
    assert before["coverage_provenance"][0]["provenance_kind"] == "owner_attestation"
    env[0].get(Instrument, env[4]).instrument_type = "bond"
    account = env[0].get(Account, env[3])
    account.include_in_capital = account.include_in_returns = False
    env[0].commit()
    assert read(env) == before


def test_no_empty_query_attestation_or_nearest_date(env):
    close(env)
    result = read(env)
    assert result["status"] == "unavailable"
    assert "no_crossing_coverage_missing_or_ambiguous" in result["reason_codes"]
    assert result["opening_value_kopecks"] is None
    result = read(env, start=date(2030, 1, 30))
    assert result["actual_opening_date"] is None
    assert "exact_endpoint_missing_or_ambiguous" in result["reason_codes"]


@pytest.mark.parametrize(
    "mutation, reason",
    [
        ("unknown", "historical_class_unknown"),
        ("quantity", "position_quantity_changed"),
        ("disappear", "position_set_changed"),
        ("appear", "position_set_changed"),
        ("reclassify", "historical_class_reclassified"),
        ("foreign", "unsupported_currency"),
    ],
)
def test_bad_whole_class_material_rejects_attestation_and_blocks_read(env, mutation, reason):
    session = env[0]
    row = positions(env)[1]
    if mutation == "unknown":
        row.historical_instrument_type = None
    elif mutation == "quantity":
        row.quantity = Decimal(3)
    elif mutation == "disappear":
        session.delete(row)
    elif mutation == "appear":
        extra = create_instrument(
            session, name="Synthetic additional stock", instrument_type="stock"
        )
        create_position_snapshot(
            session,
            reporting_month_id=env[2][1].id,
            account_id=env[3],
            instrument_id=extra.id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=END,
        )
    elif mutation == "reclassify":
        row.historical_instrument_type = "bond"
    else:
        session.get(Instrument, env[4]).currency = "USD"
    session.commit()
    with pytest.raises(ValueError, match=reason):
        attest(env)
    close(env)
    result = read(env)
    assert reason in result["reason_codes"]
    assert result["opening_value_kopecks"] is None


@pytest.mark.parametrize(
    "kind",
    [
        "dividend",
        "coupon",
        "redemption",
        "commission",
        "tax",
        "realized_profit",
        "realized_loss",
        "other",
    ],
)
def test_known_cash_crossings_and_net_zero_are_not_no_crossing(env, kind):
    flow(env, kind)
    flow(env, "tax")
    with pytest.raises(ValueError, match="known_cash_crossing"):
        attest(env)
    close(env)
    assert "known_cash_crossing" in read(env)["reason_codes"]


def test_unallocated_cost_blocks_but_settlement_cash_is_outside_class(env):
    flow(env, "deposit", instrument=False)
    attest(env)
    flow(env, "commission", instrument=False)
    close(env)
    assert "cash_flow_class_unknown" in read(env)["reason_codes"]


def test_external_in_kind_defeats_assertion(env):
    create_in_kind_movement(
        env[0],
        reporting_month_id=env[2][1].id,
        event_date=MID,
        movement_kind="external_in",
        destination_account_id=env[3],
        instrument_id=env[4],
        quantity=1,
    )
    with pytest.raises(ValueError, match="external_in_kind_crossing"):
        attest(env)
    close(env)
    assert "external_in_kind_crossing" in read(env)["reason_codes"]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_internal_same_class_transfer_requires_exact_reconciliation(env, ambiguous):
    session = env[0]
    destination = create_account(session, name="Synthetic destination", account_type="brokerage")
    session.add(
        Membership(
            account_id=destination.id, effective_from=date(2029, 1, 1), include_in_returns=True
        )
    )
    session.commit()
    closing = positions(env)[1]
    session.delete(closing)
    session.commit()
    # Both accounts have a persisted position inventory at both endpoints;
    # missing class rows are explained only by the explicit transfer below.
    ancillary = create_instrument(session, name="Synthetic transfer gold", instrument_type="gold")
    for account_id in (env[3], destination.id):
        for month in env[2]:
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account_id,
                instrument_id=ancillary.id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=month.snapshot_date,
            )
    create_position_snapshot(
        session,
        reporting_month_id=env[2][1].id,
        account_id=destination.id,
        instrument_id=env[4],
        quantity=2,
        average_cost_per_unit="100.00",
        market_price_per_unit="110.00",
        price_date=END,
    )
    create_in_kind_movement(
        session,
        reporting_month_id=env[2][1].id,
        event_date=MID,
        movement_kind="internal_transfer",
        source_account_id=env[3],
        destination_account_id=destination.id,
        instrument_id=env[4],
        quantity=None if ambiguous else 2,
    )
    if ambiguous:
        with pytest.raises(ValueError, match="internal_transfer_ambiguous"):
            attest(env)
    else:
        attest(env)
    close(env)
    result = read(env)
    assert result["status"] == ("unavailable" if ambiguous else "eligible")
    if not ambiguous:
        assert (result["opening_value_kopecks"], result["closing_value_kopecks"]) == (20000, 22000)


@pytest.mark.parametrize("mode", ["gap", "changed", "overlap", "new_account"])
def test_membership_must_be_complete_and_constant(env, mode):
    session = env[0]
    member = session.scalar(select(Membership))
    if mode == "new_account":
        create_account(session, name="Synthetic unknown scope", account_type="brokerage")
    elif mode == "overlap":
        session.add(Membership(account_id=env[3], effective_from=MID, include_in_returns=True))
    else:
        member.effective_to = date(2030, 2, 14)
        session.add(
            Membership(
                account_id=env[3],
                effective_from=END if mode == "gap" else MID,
                include_in_returns=mode == "gap",
            )
        )
    session.commit()
    with pytest.raises(ValueError, match="membership_incomplete_or_changed"):
        attest(env)
    close(env)
    assert "membership_incomplete_or_changed" in read(env)["reason_codes"]


def test_reopen_revoke_correction_and_reaffirm_lifecycle(env):
    coverage = attest(env)
    coverage_id = coverage.id
    close(env)
    assert read(env)["status"] == "eligible"
    with pytest.raises(ClosedReportingMonthError):
        save_no_crossing_coverage(
            env[0],
            coverage_id=coverage_id,
            expected_revision=1,
            asset_class="stock",
            covered_from=START,
            covered_to=END,
            coverage_state="revoked",
        )
    for month in env[2]:
        reopen_reporting_month(env[0], month.id)
    assert read(env)["coverage_state"] == "unknown"
    close(env)
    assert read(env)["status"] == "unavailable"
    for month in env[2]:
        reopen_reporting_month(env[0], month.id)
    row = positions(env)[1]
    update_position_snapshot(env[0], row.id, market_price_per_unit="120.00")
    revision = env[0].get(ClassNoCrossingCoverage, coverage_id).revision
    coverage = attest(env, coverage_id=coverage_id, expected_revision=revision)
    close(env)
    assert read(env)["closing_value_kopecks"] == 24000
    for month in env[2]:
        reopen_reporting_month(env[0], month.id)
    save_no_crossing_coverage(
        env[0],
        coverage_id=coverage_id,
        expected_revision=env[0].get(ClassNoCrossingCoverage, coverage_id).revision,
        asset_class="stock",
        covered_from=START,
        covered_to=END,
        coverage_state="revoked",
    )
    close(env)
    assert read(env)["coverage_state"] == "revoked"
    assert read(env)["status"] == "unavailable"


def test_reused_session_observes_contradictory_committed_material(env):
    attest(env)
    close(env)
    assert read(env)["status"] == "eligible"
    # Synthetic persistence corruption/correction from another session.
    with env[1].session_factory() as writer:
        writer.execute(
            text("UPDATE position_snapshots SET quantity = 3 WHERE id = :id"),
            {"id": positions(env)[1].id},
        )
        writer.commit()
    result = read(env)
    assert "no_crossing_material_changed" in result["reason_codes"]
    assert "position_quantity_changed" in result["reason_codes"]
    assert result["opening_value_kopecks"] is None


def test_classes_are_independent_and_bond_value_is_persisted_once(env):
    session = env[0]
    for kind in ("bond", "gold"):
        instrument = create_instrument(session, name="Synthetic " + kind, instrument_type=kind)
        for month in env[2]:
            p = create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=env[3],
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="20.00",
                accrued_interest="1.00",
                price_date=month.snapshot_date,
            )
            # Stored non-round-tripping total is authoritative, not price * quantity.
            p.market_value_kopecks = 2001
            session.commit()
    for kind in ("stock", "bond", "gold"):
        attest(env, kind)
    flow(env, "dividend")
    close(env)
    assert read(env)["status"] == "unavailable"
    for kind in ("bond", "gold"):
        result = read(env, kind)
        assert result["status"] == "eligible"
        assert result["opening_value_kopecks"] == result["closing_value_kopecks"] == 2001


@pytest.mark.parametrize("kind", ["fund", "currency", "gold_other", "deposit", "savings"])
def test_unsupported_classes(env, kind):
    assert read(env, kind)["reason_codes"] == ["unsupported_class"]


def test_api_create_revision_correction_and_endpoint_contract(env):
    body = dict(
        asset_class="stock",
        covered_from=str(START),
        covered_to=str(END),
        coverage_state="complete",
        provenance_kind="owner_attestation",
        provenance_reference="synthetic-owner-reference",
    )
    with TestClient(create_app(database=env[1])) as client:
        response = client.post("/api/class-evidence/coverages", json=body)
        assert response.status_code == 201, response.text
        row = response.json()
        path = f"/api/class-evidence/coverages/{row['id']}"
        assert client.put(path, json=body).status_code == 428
        body["coverage_state"] = "revoked"
        assert client.put(path, json=body, headers={"If-Match": "1"}).status_code == 200
        assert client.put(path, json=body, headers={"If-Match": "1"}).status_code == 409
        assert client.put(path, json=body, headers={"If-Match": "１".encode()}).status_code == 400
        assert client.get("/api/class-evidence/coverages").json()[0]["revision"] == 2
        close(env)
        response = client.get(
            "/api/class-evidence/endpoints",
            params={
                "asset_class": "stock",
                "start_date": str(START),
                "end_date": str(END),
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "unavailable"
        assert response.json()["coverage_state"] == "revoked"
        assert client.put(path, json=body, headers={"If-Match": "2"}).status_code == 409


def test_explicit_c1_correction_then_undo_does_not_revive_assertion(env):
    coverage = attest(env)
    row = positions(env)[1]
    update_position_snapshot(env[0], row.id, historical_instrument_type="bond")
    update_position_snapshot(env[0], row.id, historical_instrument_type="stock")
    close(env)
    assert read(env)["coverage_state"] == "unknown"
    assert read(env)["status"] == "unavailable"
    assert env[0].get(ClassNoCrossingCoverage, coverage.id).revision == 2


def test_crossing_on_opening_date_is_not_silently_excluded(env):
    flow(env, "coupon")
    row = env[0].scalar(select(InvestmentCashFlow))
    row.event_date = START
    env[0].commit()
    with pytest.raises(ValueError, match="known_cash_crossing"):
        attest(env)


def test_composite_read_pins_one_committed_snapshot_during_correction(env):
    attest(env)
    close(env)
    position_id = positions(env)[1].id
    with env[1].engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar() == "wal"
    changed = False

    def concurrent_correction(connection, cursor, statement, parameters, context, executemany):
        nonlocal changed
        if not changed and "FROM class_no_crossing_coverages" in statement:
            changed = True
            with env[1].session_factory() as writer:
                writer.execute(
                    text("UPDATE position_snapshots SET quantity = 3 WHERE id = :id"),
                    {"id": position_id},
                )
                writer.commit()

    event.listen(env[1].engine, "before_cursor_execute", concurrent_correction)
    try:
        assert read(env)["status"] == "eligible"
        assert changed
    finally:
        event.remove(env[1].engine, "before_cursor_execute", concurrent_correction)
    assert read(env)["status"] == "unavailable"


def test_clean_subset_cannot_hide_an_included_account_without_endpoint_positions(env):
    account = create_account(env[0], name="Synthetic missing inventory", account_type="brokerage")
    env[0].add(
        Membership(account_id=account.id, effective_from=date(2029, 1, 1), include_in_returns=True)
    )
    env[0].commit()
    with pytest.raises(ValueError, match="endpoint_account_positions_missing"):
        attest(env)
    close(env)
    result = read(env)
    assert "endpoint_account_positions_missing" in result["reason_codes"]
    assert result["opening_value_kopecks"] is None
