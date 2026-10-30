"""Synthetic Owner gold source commands and financial evidence boundaries."""

import sqlite3
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, select

from hermes_finance.api.owner_manual_gold_history import GoldHistoryNoStoreMiddleware, router
from hermes_finance.api.settings import session_for_request
from hermes_finance.database import create_database
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
    ClassNoCrossingCoverage,
    Instrument,
    OwnerManualGoldHistory,
    OwnerManualGoldHistoryApply,
    OwnerManualGoldHistoryRevision,
    PositionSnapshot,
)
from hermes_finance.services import owner_manual_gold_history as gold
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)


@pytest.fixture
def source(tmp_path):
    database = create_database(tmp_path / "synthetic-gold.db")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as session:
        account = create_account(session, name="Synthetic vault", account_type="other")
        instrument = create_instrument(session, name="Synthetic gold", instrument_type="gold")
        month = create_reporting_month(session, year=2033, month=3, snapshot_date=date(2033, 3, 31))
        position = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity="9",
            average_cost_per_unit="3000.00",
            market_price_per_unit="3500.00",
            price_date=date(2033, 3, 29),
        )
        close_reporting_month(session, month.id)
        yield database, session, account.id, instrument.id, position.id
    database.engine.dispose()


def intent(source, **changes):
    result = dict(
        account_id=source[2],
        instrument_id=source[3],
        expected_revision=0,
        covered_from="2033-02-01",
        covered_to="2033-03-31",
        complete=True,
        zero_start=True,
        current_quantity="9",
        current_quantity_date="2033-03-31",
        provenance_reference="synthetic-owner-declaration",
        events=[
            dict(
                event_id="purchase-one",
                event_date="2033-02-03",
                side="BUY",
                grams="12",
                amount_basis="actual",
                amount_rub="32000.00",
                fee_state="known",
                fee_rub="60.00",
            ),
            dict(
                event_id="sale-one",
                event_date="2033-03-05",
                side="SELL",
                grams="3",
                amount_basis="actual",
                amount_rub="10000.00",
                fee_state="known",
                fee_rub="15.00",
            ),
        ],
    )
    result.update(changes)
    return result


def confirm(session, payload, key="synthetic-request"):
    preview = gold.preview_gold_history(session, payload)
    request = dict(payload, confirmation_digest=preview["confirmation_digest"], request_id=key)
    return gold.apply_gold_history(session, request), request


def economic_rows(database):
    with sqlite3.connect(database.database_path) as connection:
        return {
            name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if not name.startswith("owner_manual_gold") and name != "class_no_crossing_coverages"
        }


def test_preview_apply_readback_exact_bridge_and_closed_months_unchanged(source):
    database, session, *_ = source
    before = economic_rows(database)
    preview = gold.preview_gold_history(session, intent(source))
    assert preview["action"] == "create" and preview["can_apply"]
    assert list(session.scalars(select(OwnerManualGoldHistory))) == []
    assert economic_rows(database) == before
    response, _ = confirm(session, intent(source))
    row = gold.read_gold_history(session, response["history"]["history_id"])
    assert response["accepted_revision"] == 1 and not response["duplicate"]
    assert row == response["history"] == gold.read_gold_histories(session)[0]
    assert row["authority"] == "owner_attestation" and row["currentness"] == "current"
    result = row["result"]
    assert result["total_result_kopecks"] == "942500"
    assert result["realized_result_kopecks"] == "197000"
    assert result["unrealized_result_kopecks"] == "745500"
    assert result["separate_fees_kopecks"] == "7500"
    assert result["tax_treatment"] == "not_provided"
    assert row["valuation"]["price_date"] == "2033-03-29"
    assert row["valuation"]["date"] == "2033-03-29"
    assert row["valuation"]["snapshot_date"] == "2033-03-31"
    assert row["result"]["valuation_date"] == "2033-03-29"
    assert economic_rows(database) == before


def test_idempotency_revision_noop_and_original_receipt_replay(source):
    _, session, *_ = source
    initial, request = confirm(session, intent(source))
    replay = gold.apply_gold_history(session, request)
    assert replay["duplicate"] and replay["accepted_revision"] == 1
    with pytest.raises(gold.GoldHistoryError, match="idempotency_conflict"):
        gold.apply_gold_history(session, dict(request, current_quantity="8"))
    unchanged, _ = confirm(session, intent(source, expected_revision=1), "fresh-noop")
    assert unchanged["accepted_revision"] == 1
    correction = intent(source, expected_revision=1, change_reason="Correct actual sale amount")
    correction["events"][1]["amount_rub"] = "9900.00"
    revised, _ = confirm(session, correction, "corrected")
    assert revised["accepted_revision"] == 2
    assert revised["history"]["result"]["total_result_kopecks"] == "932500"
    assert (
        revised["history"]["revisions"][0]["declaration"]["events"][1]["amount_kopecks"]
        == "1000000"
    )
    old_replay = gold.apply_gold_history(session, request)
    assert old_replay["accepted_revision"] == 1 and old_replay["history"]["revision"] == 2
    assert len(list(session.scalars(select(OwnerManualGoldHistoryRevision)))) == 2
    assert initial["history"]["history_id"] == revised["history"]["history_id"]
    with pytest.raises(gold.GoldHistoryError, match="gold_revision_conflict"):
        gold.preview_gold_history(session, intent(source))


@pytest.mark.parametrize("dependency", ["catalogue", "snapshot", "scope"])
def test_stale_preview_rejects_without_source_effects(source, dependency):
    database, session, _, instrument_id, position_id = source
    payload = intent(source)
    preview = gold.preview_gold_history(session, payload)
    if dependency == "catalogue":
        session.get(Instrument, instrument_id).name = "Changed synthetic name"
        session.commit()
    elif dependency == "snapshot":
        # Deliberate synthetic competing state: no production/CLOSED operation.
        session.get(PositionSnapshot, position_id).notes = "Changed synthetic dependency"
        session.commit()
    else:
        payload["current_quantity"] = "8"
    before = economic_rows(database)
    with pytest.raises(gold.GoldHistoryError, match="gold_preview_stale"):
        gold.apply_gold_history(
            session,
            dict(payload, request_id="stale", confirmation_digest=preview["confirmation_digest"]),
        )
    assert gold.read_gold_histories(session) == []
    assert economic_rows(database) == before


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"complete": False}, "gold_trade_history_incomplete"),
        ({"zero_start": False}, "gold_zero_start_unproven"),
        ({"current_quantity": "8"}, "gold_quantity_mismatch"),
    ],
)
def test_incomplete_and_unproved_quantity_never_become_zero_result(source, change, reason):
    response, _ = confirm(source[1], intent(source, **change))
    assert response["history"]["result"]["total_result_kopecks"] is None
    assert reason in response["history"]["reason_codes"]


def test_unknown_fees_stay_unknown_and_known_zero_is_explicit(source):
    payload = intent(source)
    payload["events"][0].update(fee_state="unknown", fee_rub=None)
    response, _ = confirm(source[1], payload)
    assert response["history"]["result"]["separate_fees_kopecks"] is None
    assert response["history"]["result"]["net_sales_kopecks"] == "998500"
    assert response["history"]["result"]["total_result_kopecks"] is None
    assert "gold_separate_fees_unknown" in response["history"]["reason_codes"]
    payload["expected_revision"] = 1
    payload["change_reason"] = "Owner confirmed no purchase fee"
    payload["events"][0].update(fee_state="known_zero", fee_rub=None)
    response, _ = confirm(source[1], payload, "known-zero")
    assert response["history"]["result"]["separate_fees_kopecks"] == "1500"
    assert response["history"]["result"]["total_result_kopecks"] == "948500"


def test_derived_price_is_labeled_and_rounds_once(source):
    payload = intent(source)
    payload["events"][0].update(
        amount_basis="derived_unit_price", amount_rub=None, unit_price_rub="2666.67"
    )
    response, _ = confirm(source[1], payload)
    assert response["history"]["events"][0]["amount_kopecks"] == "3200004"
    assert response["history"]["result"]["amount_basis"] == "derived"
    assert response["history"]["result"]["total_result_kopecks"] == "942496"


def test_multiple_purchases_allow_total_but_not_unproved_cost_allocation(source):
    payload = intent(source)
    payload["events"][0].update(grams="6", amount_rub="16000.00", fee_rub="30.00")
    second = dict(payload["events"][0], event_id="purchase-two", event_date="2033-02-06")
    payload["events"].append(second)
    response, _ = confirm(source[1], payload)
    result = response["history"]["result"]
    assert result["total_result_kopecks"] == "942500"
    assert result["realized_result_kopecks"] is None
    assert result["unrealized_result_kopecks"] is None
    assert result["decomposition_reason_codes"] == ["gold_cost_allocation_unproven"]


def test_fully_exited_gold_without_snapshot_uses_affirmative_zero_grams(source):
    payload = intent(
        source, current_quantity="0", covered_to="2033-02-28", current_quantity_date="2033-02-28"
    )
    payload["events"][1].update(event_date="2033-02-10", grams="12", amount_rub="40000.00")
    response, _ = confirm(source[1], payload)
    row = response["history"]
    assert row["valuation"] is None
    assert row["result"]["valuation_kopecks"] == "0"
    assert row["result"]["total_result_kopecks"] == "792500"
    assert row["result"]["unrealized_result_kopecks"] == "0"


def test_catalogue_reclassification_withholds_without_mutating_history(source):
    _, session, _, instrument_id, _ = source
    response, _ = confirm(session, intent(source))
    session.get(Instrument, instrument_id).instrument_type = "other"
    session.commit()
    row = gold.read_gold_history(session, response["history"]["history_id"])
    assert row["currentness"] == "dependency_changed"
    assert row["result"]["total_result_kopecks"] is None
    assert row["revision"] == 1


def test_append_failure_rolls_back_source_and_coverage_retirement(source):
    _, session, *_ = source
    coverage = ClassNoCrossingCoverage(
        asset_class="gold",
        covered_from=date(2033, 2, 1),
        covered_to=date(2033, 3, 31),
        coverage_state="complete",
        provenance_kind="owner_attestation",
        material_signature="1" * 64,
        revision=1,
    )
    session.add(coverage)
    session.commit()
    preview = gold.preview_gold_history(session, intent(source))

    def fail(_mapper, _connection, _target):
        raise RuntimeError("synthetic receipt failure")

    event.listen(OwnerManualGoldHistoryApply, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="synthetic receipt failure"):
            gold.apply_gold_history(
                session,
                dict(
                    intent(source),
                    request_id="failed",
                    confirmation_digest=preview["confirmation_digest"],
                ),
            )
    finally:
        event.remove(OwnerManualGoldHistoryApply, "before_insert", fail)
    assert gold.read_gold_histories(session) == []
    session.refresh(coverage)
    assert coverage.coverage_state == "complete" and coverage.revision == 1


def test_crossing_retirement_retains_removed_facts_and_disjoint_gold_claim(source):
    _, session, account_id, *_ = source
    common = dict(
        asset_class="gold",
        coverage_state="complete",
        provenance_kind="owner_attestation",
        material_signature="2" * 64,
        revision=1,
    )
    affected = ClassNoCrossingCoverage(
        **common, covered_from=date(2033, 2, 1), covered_to=date(2033, 3, 31)
    )
    disjoint = ClassNoCrossingCoverage(
        **common, covered_from=date(2034, 1, 1), covered_to=date(2034, 12, 31)
    )
    session.add_all([affected, disjoint])
    session.commit()
    confirm(session, intent(source))
    session.refresh(affected)
    session.refresh(disjoint)
    assert (affected.coverage_state, affected.revision) == ("unknown", 2)
    assert (disjoint.coverage_state, disjoint.revision) == ("complete", 1)
    correction = intent(
        source,
        expected_revision=1,
        current_quantity="12",
        change_reason="Owner removed erroneous sale",
    )
    correction["events"].pop()
    confirm(session, correction, "removed-sale")
    material = gold.gold_crossing_evidence(
        session, (account_id,), date(2033, 3, 1), date(2033, 3, 31)
    )
    assert len(material["material"]) == 2
    assert material["crossings"] == []
    assert gold.gold_crossing_evidence(
        session, (account_id + 100,), date(2033, 1, 1), date(2033, 12, 31)
    ) == {"material": [], "crossings": []}


@pytest.mark.parametrize(
    "change",
    [
        {"account_id": True},
        {"current_quantity": "NaN"},
        {"zero_start": "yes"},
        {"current_quantity_date": "2033-03-30"},
        {"events": []},
    ],
)
def test_strict_bounded_inputs(source, change):
    with pytest.raises(ValidationError):
        gold.GoldHistoryIntent.model_validate(intent(source, **change))


def test_api_exact_scope_preview_apply_get_and_error_contract(source):
    database, _, account_id, instrument_id, _ = source
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(GoldHistoryNoStoreMiddleware)

    def session_override():
        with database.session_factory() as session:
            yield session

    app.dependency_overrides[session_for_request] = session_override
    with TestClient(app) as client:
        path = "/api/owner-manual-gold-history"
        empty = client.get(path)
        assert empty.headers["cache-control"] == "no-store"
        assert empty.json()["histories"] == []
        payload = intent(source)
        preview = client.post(path + "/preview", json=payload)
        assert preview.status_code == 200
        request = dict(
            payload,
            request_id="api-request",
            confirmation_digest=preview.json()["confirmation_digest"],
        )
        applied = client.post(path + "/apply", json=request)
        assert applied.status_code == 200
        history_id = applied.json()["history"]["history_id"]
        assert client.get(path + f"/{history_id}").json() == applied.json()["history"]
        receipt = client.get(path + "/receipts/api-request").json()
        assert receipt["accepted_revision"] == 1
        assert receipt["history"] == applied.json()["history"]
        assert client.get(path + "/receipts/unknown").status_code == 404
        assert (
            len(
                client.get(
                    path, params=dict(account_id=account_id, instrument_id=instrument_id)
                ).json()["histories"]
            )
            == 1
        )
        assert client.get(path, params=dict(account_id=account_id + 100)).json()["histories"] == []
        assert client.post(path + "/apply", json=dict(request, complete=False)).status_code == 409
        assert client.post(path + "/preview", json=dict(payload, events=[])).status_code == 422
        assert client.get(path + "/9999").status_code == 404
        for response in (
            client.get(path + "?account_id=1&account_id=2"),
            client.get(path + "?unknown=true"),
            client.post(path + "/preview", json={}),
        ):
            assert response.status_code == 422
            assert response.headers["cache-control"] == "no-store"
        assert client.delete(path).headers["cache-control"] == "no-store"


def test_migration_empty_upgrade_append_only_and_populated_downgrade_refusal(tmp_path):
    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-gold-migration.db"
    previous = "0067_investment_report_proofs"
    upgraded = run_alembic(path, "upgrade", previous)
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(path) as connection:
        before = {
            name: connection.execute(f'SELECT * FROM "{name}"').fetchall()
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                " AND name <> 'alembic_version'"
            )
        }
    upgraded = run_alembic(path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(path) as connection:
        assert all(
            connection.execute(f'SELECT * FROM "{name}"').fetchall() == rows
            for name, rows in before.items()
        )
        assert connection.execute(
            "SELECT count(*) FROM owner_manual_gold_histories"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert run_alembic(path, "downgrade", previous).returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    database = create_database(path)
    with database.session_factory() as session:
        account = create_account(session, name="Migration synthetic", account_type="other")
        instrument = create_instrument(session, name="Migration gold", instrument_type="gold")
        payload = dict(
            account_id=account.id,
            instrument_id=instrument.id,
            expected_revision=0,
            covered_from="2034-01-01",
            covered_to="2034-01-31",
            complete=True,
            zero_start=True,
            current_quantity="1",
            current_quantity_date="2034-01-31",
            provenance_reference="synthetic",
            events=[
                dict(
                    event_id="migration-event",
                    event_date="2034-01-03",
                    side="BUY",
                    grams="1",
                    amount_basis="actual",
                    amount_rub="100.00",
                    fee_state="known_zero",
                )
            ],
        )
        confirm(session, payload)
    database.engine.dispose()
    with sqlite3.connect(path) as connection:
        for table in (
            "owner_manual_gold_histories",
            "owner_manual_gold_history_revisions",
            "owner_manual_gold_history_applies",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="append_only"):
                connection.execute(f"DELETE FROM {table}")
            connection.rollback()
    refused = run_alembic(path, "downgrade", previous)
    assert refused.returncode != 0 and "cannot discard Owner gold evidence" in refused.stderr


def test_class_reattestation_reads_retained_gold_crossing(monkeypatch, source):
    from hermes_finance.services import class_endpoint_eligibility as eligibility

    # Use the real gold evidence reader in _facts, even when other independent
    # prerequisites are missing. A new COMPLETE assertion must still see it.
    confirm(source[1], intent(source))
    monkeypatch.setattr(
        eligibility,
        "_scope_membership_coverage",
        lambda *a, **k: (
            type("Membership", (), {"reason_codes": (), "account_ids": (source[2],)})(),
            {source[2]: []},
        ),
    )
    monkeypatch.setattr(eligibility, "_membership_at", lambda *a, **k: True)
    facts = eligibility._facts(source[1], "gold", date(2033, 2, 1), date(2033, 3, 31))
    assert "owner_gold_known_crossing" in facts["reason_codes"]
    other = eligibility._facts(source[1], "stock", date(2033, 2, 1), date(2033, 3, 31))
    assert "owner_gold_known_crossing" not in other["reason_codes"]


def test_mistaken_date_correction_retires_old_claim_and_allows_fresh_reattestation(tmp_path):
    from hermes_finance.services.class_endpoint_eligibility import (
        class_endpoint_eligibility,
        save_no_crossing_coverage,
    )

    database = create_database(tmp_path / "synthetic-gold-correction.db")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as session:
        account = create_account(session, name="Correction synthetic", account_type="other")
        instrument = create_instrument(session, name="Correction gold", instrument_type="gold")
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account.id, effective_from=date(2036, 1, 1), include_in_returns=True
            )
        )
        session.commit()
        start, end = date(2037, 2, 28), date(2037, 4, 30)
        months = []
        for day in (start, end):
            month = create_reporting_month(
                session, year=day.year, month=day.month, snapshot_date=day
            )
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity="1",
                average_cost_per_unit="1000.00",
                market_price_per_unit="1200.00",
                price_date=day,
            )
            months.append(month)
        claim = save_no_crossing_coverage(
            session,
            asset_class="gold",
            covered_from=start,
            covered_to=end,
            coverage_state="complete",
            opening_inventory_complete=True,
            closing_inventory_complete=True,
        )
        original_signature = claim.material_signature
        for month in months:
            close_reporting_month(session, month.id)
        payload = dict(
            account_id=account.id,
            instrument_id=instrument.id,
            expected_revision=0,
            covered_from="2037-01-01",
            covered_to="2037-04-30",
            complete=True,
            zero_start=True,
            current_quantity="1",
            current_quantity_date="2037-04-30",
            provenance_reference="synthetic",
            events=[
                dict(
                    event_id="stable-purchase",
                    event_date="2037-03-15",
                    side="BUY",
                    grams="1",
                    amount_basis="actual",
                    amount_rub="1000.00",
                    fee_state="known_zero",
                )
            ],
        )
        confirm(session, payload)
        blocked = class_endpoint_eligibility(
            session, asset_class="gold", start_date=start, end_date=end
        )
        assert "owner_gold_known_crossing" in blocked["reason_codes"]
        payload["expected_revision"] = 1
        payload["change_reason"] = "Correct mistaken purchase date from retained original"
        payload["events"][0]["event_date"] = "2037-01-15"
        confirm(session, payload, "date-correction")
        corrected = class_endpoint_eligibility(
            session, asset_class="gold", start_date=start, end_date=end
        )
        assert "owner_gold_known_crossing" not in corrected["reason_codes"]
        assert corrected["status"] == "unavailable"  # Retired claim does not revive.
        session.refresh(claim)
        assert claim.coverage_state == "unknown" and claim.material_signature is None
        for month in months:
            reopen_reporting_month(session, month.id)
        fresh = save_no_crossing_coverage(
            session,
            asset_class="gold",
            covered_from=start,
            covered_to=end,
            coverage_state="complete",
            opening_inventory_complete=True,
            closing_inventory_complete=True,
            coverage_id=claim.id,
            expected_revision=claim.revision,
        )
        assert fresh.material_signature != original_signature
        for month in months:
            close_reporting_month(session, month.id)
        eligible = class_endpoint_eligibility(
            session, asset_class="gold", start_date=start, end_date=end
        )
        assert eligible["status"] == "eligible"
        assert gold.read_gold_histories(session)[0]["revision"] == 2
    database.engine.dispose()


def test_later_trade_cash_never_combines_with_earlier_saved_valuation(source):
    payload = intent(source, covered_to="2033-04-30", current_quantity_date="2033-04-30")
    payload["events"][1]["event_date"] = "2033-04-05"
    response, _ = confirm(source[1], payload)
    row = response["history"]
    assert row["valuation"]["date"] == "2033-03-29"
    assert row["valuation"]["snapshot_date"] == "2033-03-31"
    assert row["valuation"]["price_date"] == "2033-03-29"
    assert row["result"]["total_result_kopecks"] is None
    assert "gold_snapshot_quantity_mismatch" in row["reason_codes"]
    assert row["result"]["realized_result_kopecks"] == "0"
    assert row["result"]["realized_reason_codes"] == []


def test_complete_later_history_supports_exact_earlier_prefix_excluding_later_unknown_fee(source):
    payload = intent(
        source, covered_to="2033-04-30", current_quantity_date="2033-04-30", current_quantity="10"
    )
    payload["events"].append(
        dict(
            event_id="later-purchase",
            event_date="2033-04-02",
            side="BUY",
            grams="1",
            amount_basis="actual",
            amount_rub="4000.00",
            fee_state="unknown",
        )
    )
    response, _ = confirm(source[1], payload)
    row = response["history"]
    assert row["result"]["total_result_kopecks"] == "942500"
    assert row["result"]["calculated_quantity"] == "9"
    assert row["result"]["declared_calculated_quantity"] == "10"
    assert row["result"]["separate_fees_kopecks"] == "7500"
    assert row["result"]["period"] == {"covered_from": "2033-02-01", "covered_to": "2033-03-29"}
    summary = gold.read_gold_histories(source[1], include_events=False)[0]
    assert summary["result"] == row["result"]
    assert summary["events"] == summary["declaration"]["events"] == summary["revisions"] == []
    assert not summary["events_loaded"] and row["events_loaded"]


def test_realized_economics_survive_missing_quote_with_explicit_declaration_period(source):
    payload = intent(source, covered_to="2033-03-20", current_quantity_date="2033-03-20")
    response, _ = confirm(source[1], payload)
    result = response["history"]["result"]
    assert response["history"]["valuation"] is None
    assert result["period"]["covered_to"] == result["as_of_date"] == "2033-03-20"
    assert result["valuation_date"] is None and result["valuation_basis"] is None
    assert result["total_result_kopecks"] is None
    assert result["realized_result_kopecks"] == "197000"
    assert result["remaining_cost_kopecks"] == "2404500"
    assert result["unrealized_result_kopecks"] is None
    assert result["realized_reason_codes"] == []
    assert result["unrealized_reason_codes"] == ["gold_saved_valuation_unavailable"]


def test_draft_month_quote_uses_actual_date_with_future_snapshot_placeholder(source):
    database, session, account_id, instrument_id, _ = source
    month = create_reporting_month(session, year=2033, month=4, snapshot_date=date(2033, 4, 30))
    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity="9",
        average_cost_per_unit="3000.00",
        market_price_per_unit="3600.00",
        price_date=date(2033, 4, 10),
    )
    before = economic_rows(database)
    payload = intent(source, covered_to="2033-04-12", current_quantity_date="2033-04-12")
    response, _ = confirm(session, payload)
    row = response["history"]
    assert row["valuation"]["date"] == row["result"]["valuation_date"] == "2033-04-10"
    assert row["valuation"]["snapshot_date"] == "2033-04-30"
    assert row["valuation"]["month_status"] == "draft" and row["valuation"]["provisional"]
    assert row["result"]["valuation_provisional"]
    assert row["result"]["total_result_kopecks"] == "1032500"
    assert economic_rows(database) == before
