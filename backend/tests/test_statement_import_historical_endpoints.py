"""Synthetic H1-A acceptance, source exactness and durable lifecycle regressions."""

import copy
import json
import sqlite3
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from test_statement_import_mybroker import apply, fixture, preview
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import endpoint_xml, positions_only

from hermes_finance.domain.historical_endpoints import EndpointIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBalance,
    DepositSnapshot,
    HistoricalEndpointApply,
    HistoricalEndpointRevision,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.historical_endpoints import (
    apply_historical_endpoint,
    preview_historical_endpoint,
    read_historical_endpoint,
)
from hermes_finance.services.reporting_months import close_reporting_month, reopen_reporting_month
from hermes_finance.statement_import.mybroker import MyBrokerError

DAY = date(2030, 1, 31)


def setup_source(
    session, *, xml=None, quantity="3", value="100.01", cash="0", keep_trades=False, forward=None
):
    source_xml = xml or endpoint_xml(rub_amounts=(None, cash))
    root = ET.fromstring(source_xml if keep_trades else positions_only(source_xml))
    security = root.find(".//{MyBroker}Details[@ISIN1]")
    security.set("real_rest", quantity)
    security.set("forward_rest", forward if forward is not None else quantity)
    security.set("real_volume", value)
    raw = ET.tostring(root, encoding="utf-8")
    source = apply(session, raw, preview(session, raw))
    bindings = source["mappings"]
    account_id = next(b["hermes_id"] for b in bindings if b["kind"] == "account")
    instrument_id = next(b["hermes_id"] for b in bindings if b["kind"] == "instrument")
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account_id,
            effective_from=date(2030, 1, 1),
            effective_to=DAY,
            include_in_returns=True,
        )
    )
    session.commit()
    intent = EndpointIntent(
        account_id=account_id, valuation_date=DAY, source_import_id=source["import_id"]
    )
    return intent, instrument_id


def attest(session, intent):
    observed = preview_historical_endpoint(session, intent)
    claims = {
        "provenance_kind": "owner_attestation",
        "reference": "synthetic-review",
        "account_id": intent.account_id,
        "valuation_date": intent.valuation_date.isoformat(),
        "source_side": "ending",
        "source_set_fingerprint": observed["source_set_fingerprint"],
        "inventory_complete": True,
        "other_components_absent": True,
        "rub_cash_complete_and_reconciled": True,
        "rub_stock_basis_confirmed": [
            p["row_fingerprint"] for p in observed["evidence"]["positions"]
        ],
    }
    return EndpointIntent.model_validate({**intent.model_dump(mode="json"), "claims": claims})


def accept(session, intent, key="synthetic-apply"):
    plan = preview_historical_endpoint(session, intent)
    assert plan["can_apply"], plan["blockers"]
    return apply_historical_endpoint(
        session, intent, confirmation_digest=plan["confirmation_digest"], request_id=key
    )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def matching_month(session, intent, instrument_id):
    month = ReportingMonth(
        year=2030, month=1, period_start=date(2030, 1, 1), period_end=DAY, snapshot_date=DAY
    )
    session.add(month)
    session.flush()
    session.add(
        PositionSnapshot(
            reporting_month_id=month.id,
            account_id=intent.account_id,
            instrument_id=instrument_id,
            quantity=Decimal("3"),
            market_value_kopecks=10001,
            average_cost_per_unit_kopecks=0,
            market_price_per_unit_kopecks=0,
            cost_basis_kopecks=0,
            unrealized_result_kopecks=0,
            price_date=DAY,
        )
    )
    session.add(
        CashBalance(
            reporting_month_id=month.id,
            account_id=intent.account_id,
            name="Synthetic cash",
            amount_kopecks=0,
            currency="RUB",
        )
    )
    session.commit()
    return month.id


@pytest.mark.parametrize("quantity", ["3", "3.123456789012345678901234567890123456"])
def test_exact_source_endpoint_and_no_other_financial_writes(database, quantity):
    with database.session_factory() as session:
        intent, _ = setup_source(session, quantity=quantity)
        intent = attest(session, intent)
        result = accept(session, intent)
        readback = read_historical_endpoint(session, result["readback"]["endpoint_key"])
        assert result["readback"] == readback
        assert readback["total_value_kopecks"] == 10001
        position = readback["evidence"]["positions"][0]
        assert position["quantity"] == quantity
        assert position["value"] == "100.01"
        assert position["value_kopecks"] == 10001
        assert readback["evidence"]["rub_cash"]["amount_kopecks"] == 0
        assert readback["evidence"]["endpoint_c1"] is None
        for model in (
            ReportingMonth,
            PositionSnapshot,
            CashBalance,
            DepositSnapshot,
            InvestmentCashFlow,
        ):
            assert count(session, model) == 0
        assert count(session, HistoricalEndpointRevision) == 1


@pytest.mark.parametrize(
    "value,reason",
    [
        ("100.001", "fractional_kopeck"),
        ("92233720368547758.08", "amount_out_of_bounds"),
        ("-1", "amount_out_of_bounds"),
        ("100.0000000000000000000000000000000001", "fractional_kopeck"),
    ],
)
def test_amount_exactness_refuses_rounding(database, value, reason):
    with database.session_factory() as session:
        intent, _ = setup_source(session, value=value)
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)
        assert reason in plan["blockers"]
        assert plan["evidence"]["positions"][0]["value"] == value
        with pytest.raises(MyBrokerError, match=reason):
            apply_historical_endpoint(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="blocked",
            )
        assert count(session, HistoricalEndpointApply) == 0


@pytest.mark.parametrize(
    "xml,reason",
    [
        (endpoint_xml(rub=False), "rub_cash_missing_or_ambiguous"),
        (endpoint_xml(unclassified=True), "position_row_unclassified"),
        (endpoint_xml(rub_amounts=(None, None)), "ending_amount_missing"),
    ],
    ids=["missing-cash", "unclassified", "missing-ending-cash"],
)
def test_incomplete_source_never_authoritative(database, xml, reason):
    with database.session_factory() as session:
        intent, _ = setup_source(session, xml=xml)
        plan = preview_historical_endpoint(session, attest(session, intent))
        assert reason in plan["blockers"]
        assert plan["total_value_kopecks"] is None


def test_claims_are_exact_row_bound_and_catalogue_is_not_c1(database):
    with database.session_factory() as session:
        intent, instrument_id = setup_source(session)
        unclaimed = preview_historical_endpoint(session, intent)
        assert "endpoint_claims_missing" in unclaimed["blockers"]
        intent = attest(session, intent)
        invalid = intent.model_copy(
            update={"claims": intent.claims.model_copy(update={"source_set_fingerprint": "a" * 64})}
        )
        assert "claim_binding_mismatch" in preview_historical_endpoint(session, invalid)["blockers"]
        invalid = intent.model_copy(
            update={"claims": intent.claims.model_copy(update={"rub_stock_basis_confirmed": []})}
        )
        assert (
            "rub_stock_basis_unconfirmed"
            in preview_historical_endpoint(session, invalid)["blockers"]
        )
        session.get(Instrument, instrument_id).instrument_type = "bond"
        session.commit()
        result = accept(session, intent)
        assert result["readback"]["evidence"]["endpoint_c1"] is None


def test_replay_noop_receipt_and_conflicting_reuse(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)
        first = accept(session, intent)
        replay = apply_historical_endpoint(
            session,
            intent,
            confirmation_digest=plan["confirmation_digest"],
            request_id="synthetic-apply",
        )
        assert replay["replayed"] and replay["readback"] == first["readback"]
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            apply_historical_endpoint(
                session, intent, confirmation_digest="b" * 64, request_id="synthetic-apply"
            )
        noop = intent.model_copy(update={"expected_revision": 1})
        assert accept(session, noop, "fresh-noop")["result_action"] == "noop"
        assert count(session, HistoricalEndpointRevision) == 1
        assert count(session, HistoricalEndpointApply) == 2


def test_exact_overlap_and_dependency_driven_reopen_no_revival(database):
    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        intent = attest(session, intent)
        accepted = accept(session, intent)["readback"]
        close_reporting_month(session, month_id)
        assert (
            read_historical_endpoint(session, accepted["endpoint_key"])["effective_state"]
            == "accepted"
        )
        reopen_reporting_month(session, month_id)
        retired = read_historical_endpoint(session, accepted["endpoint_key"])
        assert retired["history"][-1]["operation"] == "retire"
        assert retired["total_value_kopecks"] is None
        close_reporting_month(session, month_id)
        assert (
            read_historical_endpoint(session, accepted["endpoint_key"])["effective_state"]
            == "retired"
        )
        reopen_reporting_month(session, month_id)
        renewed = attest(
            session, intent.model_copy(update={"operation": "reaffirm", "expected_revision": 2})
        )
        assert accept(session, renewed, "reaffirm")["readback"]["revision"] == 3


def test_month_without_frozen_dependency_does_not_retire_endpoint(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        accepted = accept(session, attest(session, intent))["readback"]
        month = ReportingMonth(
            year=2030, month=1, period_start=date(2030, 1, 1), period_end=DAY, snapshot_date=DAY
        )
        session.add(month)
        session.commit()
        close_reporting_month(session, month.id)
        reopen_reporting_month(session, month.id)
        assert read_historical_endpoint(session, accepted["endpoint_key"])["revision"] == 1


@pytest.mark.parametrize("mutation", ["value", "cash", "c1", "cash-inclusion"])
def test_composition_conflicts_and_durable_correction_retirement(database, mutation):
    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        matching_month(session, intent, instrument)
        accepted = accept(session, attest(session, intent))["readback"]
        position = session.scalar(select(PositionSnapshot))
        cash = session.scalar(select(CashBalance))
        if mutation == "value":
            position.market_value_kopecks -= 1
            cash.amount_kopecks += 1  # Same grand total cannot conceal composition.
        elif mutation == "cash":
            cash.amount_kopecks = 1
        elif mutation == "cash-inclusion":
            cash.include_in_capital = False
        else:
            position.historical_instrument_type = "bond"
        session.commit()
        assert (
            read_historical_endpoint(session, accepted["endpoint_key"])["effective_state"]
            == "retired"
        )
        if mutation != "cash-inclusion":
            assert (
                "reconciliation_required"
                in preview_historical_endpoint(session, attest(session, intent))["blockers"]
            )
        position.market_value_kopecks = 10001
        position.historical_instrument_type = None
        cash.amount_kopecks = 0
        cash.include_in_capital = True
        session.commit()
        assert (
            read_historical_endpoint(session, accepted["endpoint_key"])["effective_state"]
            == "retired"
        )


@pytest.mark.parametrize("change", ["membership", "mapping", "month_close"])
def test_stale_preview_rolls_back_without_receipt(database, change):
    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)
        if change == "membership":
            session.scalar(select(AccountPerformanceScopeMembership)).include_in_returns = False
        elif change == "mapping":
            mapping = session.scalar(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.subject_kind == "instrument"
                )
            )
            mapping.observed_isin = None
        else:
            session.get(ReportingMonth, month_id).status = "closed"
        session.commit()
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_historical_endpoint(
                session, intent, confirmation_digest=plan["confirmation_digest"], request_id="stale"
            )
        assert (
            count(session, HistoricalEndpointRevision)
            == count(session, HistoricalEndpointApply)
            == 0
        )


def test_receipt_write_failure_rolls_back_revision(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)

        def fail(_mapper, _connection, _target):
            raise RuntimeError("synthetic-write-failure")

        event.listen(HistoricalEndpointApply, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="synthetic-write-failure"):
                apply_historical_endpoint(
                    session,
                    intent,
                    confirmation_digest=plan["confirmation_digest"],
                    request_id="failure",
                )
        finally:
            event.remove(HistoricalEndpointApply, "before_insert", fail)
        assert (
            count(session, HistoricalEndpointRevision)
            == count(session, HistoricalEndpointApply)
            == 0
        )


def test_revoke_is_explicit_and_replay_returns_current_retired_status(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)
        accepted = accept(session, intent)
        membership = session.scalar(select(AccountPerformanceScopeMembership))
        membership.include_in_returns = False
        session.commit()
        replay = apply_historical_endpoint(
            session,
            intent,
            confirmation_digest=plan["confirmation_digest"],
            request_id="synthetic-apply",
        )
        assert replay["committed_revision_id"] == accepted["committed_revision_id"]
        assert replay["readback"]["effective_state"] == "retired"
        revoke = EndpointIntent(
            operation="revoke",
            account_id=intent.account_id,
            valuation_date=DAY,
            expected_revision=2,
            reason_code="owner_withdrawal",
        )
        revoked = accept(session, revoke, "revoke")["readback"]
        assert revoked["history"][-1]["operation"] == "revoke"
        assert revoked["effective_state"] == "revoked"
        assert revoked["total_value_kopecks"] is None


def test_api_independent_get_and_no_browser_supplied_amounts(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        intent = attest(session, intent)
    client = TestClient(create_app(database=database))
    body = intent.model_dump(mode="json")
    plan = client.post("/api/historical-endpoints/preview", json=body)
    assert plan.status_code == 200
    response = client.post(
        "/api/historical-endpoints/apply",
        json={
            **body,
            "request_id": "api-apply",
            "confirmation_digest": plan.json()["confirmation_digest"],
        },
    )
    assert response.status_code == 200, response.text
    readback = response.json()["readback"]
    assert client.get("/api/historical-endpoints/" + readback["endpoint_key"]).json() == readback
    assert (
        client.post(
            "/api/historical-endpoints/preview", json={**body, "total_value_kopecks": 1}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("kind", ["duplicate", "zero", "zero-with-value", "forward", "opaque"])
def test_source_structural_blockers_cannot_be_attested_away(database, kind):
    root = ET.fromstring(endpoint_xml())
    collection = root.find(".//{MyBroker}Details_Collection")
    security = collection.find("{MyBroker}Details")
    if kind == "duplicate":
        collection.append(copy.deepcopy(security))
    if kind == "opaque":
        ET.SubElement(root.find("{MyBroker}Trades3/{MyBroker}Report"), "{MyBroker}Tablix1")
    quantity, value = (
        ("0", "0")
        if kind == "zero"
        else (("0", "1") if kind == "zero-with-value" else ("3", "100.01"))
    )
    with database.session_factory() as session:
        intent, _ = setup_source(
            session,
            xml=ET.tostring(root),
            quantity=quantity,
            value=value,
            keep_trades=True,
            forward="4" if kind == "forward" else None,
        )
        plan = preview_historical_endpoint(session, attest(session, intent))
        reason = {
            "duplicate": "duplicate_position",
            "zero": "positive_stock_required",
            "zero-with-value": "quantity_value_incompatible",
            "forward": "endpoint_unsettled",
            "opaque": "4_Transfers_unsupported",
        }[kind]
        assert reason in plan["blockers"]
        assert not plan["can_apply"]


def test_pending_opposite_trades_with_equal_actual_forward_still_block(database):
    root = ET.fromstring(endpoint_xml())
    pending_root = ET.fromstring(fixture(pending=True))
    trades = root.find("{MyBroker}Trades/{MyBroker}Report")
    trades.clear()
    trades.set("Name", "2_Trades")
    pending_table = pending_root.find("{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix3")
    opposite = copy.deepcopy(pending_table.find(".//{MyBroker}Details2"))
    opposite.set("trade_no1", "10000000002\r\n2000000002")
    opposite.set("qty2", "-10")
    pending_table.find("{MyBroker}Details2_Collection").append(opposite)
    trades.append(pending_table)
    root.find("{MyBroker}Trades2/{MyBroker}Report").clear()
    root.find("{MyBroker}Trades2/{MyBroker}Report").set("Name", "3_BrokerMoneyMove")
    with database.session_factory() as session:
        intent, _ = setup_source(session, xml=ET.tostring(root), keep_trades=True)
        assert (
            "unresolved_cutoff_trade"
            in preview_historical_endpoint(session, attest(session, intent))["blockers"]
        )


def test_canonical_pending_cannot_be_relaxed_by_unapplied_source_settlement(database):
    from hermes_finance.persistence import ExecutedTradeRevision
    from hermes_finance.services.executed_trades import (
        apply_executed_trades,
        preview_executed_trades,
    )
    from hermes_finance.services.mybroker_import import read_mybroker_lineage

    with database.session_factory() as session:
        pending = fixture(pending=True)
        earlier = "Брокерский 1234567 (01.01.30-16.01.30).xml"
        apply(session, pending, preview(session, pending, earlier), earlier)
        identity = read_mybroker_lineage(session)["trades"][0]["identity"]
        reviewed = preview_executed_trades(session, [identity])
        apply_executed_trades(
            session,
            identities=[identity],
            confirmation_digest=reviewed["confirmation_digest"],
            request_id="pending",
        )
        assert session.scalar(select(ExecutedTradeRevision)).lifecycle == "pending"
        intent, _ = setup_source(session, keep_trades=True)
        plan = preview_historical_endpoint(session, attest(session, intent))
        assert "unresolved_cutoff_trade" in plan["blockers"]


def test_generic_interval_fee_limit_does_not_block_supported_ending(database):
    root = ET.fromstring(endpoint_xml())
    root.find(".//{MyBroker}Details[@trade_no]").set("bank_tax", "1")
    with database.session_factory() as session:
        intent, _ = setup_source(session, xml=ET.tostring(root), keep_trades=True)
        plan = preview_historical_endpoint(session, attest(session, intent))
        assert plan["can_apply"], plan["blockers"]
        assert "commission_basis_unresolved" in plan["return_limitations"]


@pytest.mark.parametrize("membership", ["missing", "ambiguous", "excluded"])
def test_membership_never_inferred_or_promoted(database, membership):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        existing = session.scalar(select(AccountPerformanceScopeMembership))
        if membership == "missing":
            session.delete(existing)
        elif membership == "ambiguous":
            session.add(
                AccountPerformanceScopeMembership(
                    account_id=intent.account_id,
                    effective_from=date(2030, 1, 2),
                    effective_to=DAY,
                    include_in_returns=True,
                )
            )
        else:
            existing.include_in_returns = False
        session.commit()
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)
        if membership == "excluded":
            result = accept(session, intent)["readback"]
            assert result["evidence"]["membership"][0]["include_in_returns"] == "False"
        else:
            assert "membership_missing_or_ambiguous" in plan["blockers"]


def test_beginning_apply_is_unsupported_and_actual_previous_day_is_exact(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        intent = intent.model_copy(update={"source_side": "beginning"})
        plan = preview_historical_endpoint(session, intent)
        assert "beginning_apply_unsupported" in plan["blockers"]
        assert plan["actual_valuation_date"] == "2029-12-31"
        assert plan["evidence"]["source"]["basis"] == "previous_day_eod"


def test_new_accepted_source_conflict_invalidates_reads_even_closed(database):
    from hermes_finance.statement_import.mybroker import canonical

    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        accepted = accept(session, attest(session, intent))["readback"]
        close_reporting_month(session, month_id)
        # Accepted source-only support from another report is distinct from a
        # rejected endpoint Preview. Simulate a contradictory accepted observation.
        original = session.get(MyBrokerImport, intent.source_import_id)
        document = json.loads(original.normalized_json)
        document["document_sha256"] = "c" * 64
        document["positions"][0]["ending_value"] = "100.02"
        session.add(
            MyBrokerImport(
                document_sha256="c" * 64,
                covered_from=original.covered_from,
                covered_to=DAY,
                parser_version=original.parser_version,
                confirmation_digest="d" * 64,
                normalized_json=canonical(document),
                mappings_json=original.mappings_json,
                accepted_at=original.accepted_at,
            )
        )
        session.commit()
        readback = read_historical_endpoint(session, accepted["endpoint_key"])
        assert readback["effective_state"] == "invalidated"
        assert readback["total_value_kopecks"] is None
        assert readback["revision"] == 1  # Effective invalidation never rewrites CLOSED history.


def test_cached_draft_does_not_allow_closed_dependency_retirement(database):
    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        accepted = accept(session, attest(session, intent))["readback"]
        cached = session.get(ReportingMonth, month_id)
        with database.session_factory() as competing:
            close_reporting_month(competing, month_id)
        assert cached.status == "draft"
        session.scalar(select(AccountPerformanceScopeMembership)).include_in_returns = False
        with pytest.raises(MyBrokerError, match="reopen_required"):
            session.commit()
        session.rollback()
        assert read_historical_endpoint(session, accepted["endpoint_key"])["revision"] == 1


def test_supported_backup_restore_preserves_retirement_and_receipts(database):
    from hermes_finance.services.backups import create_backup, restore_backup

    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        intent = attest(session, intent)
        key = accept(session, intent)["readback"]["endpoint_key"]
        close_reporting_month(session, month_id)
        reopen_reporting_month(session, month_id)
    backup = create_backup(database)
    with database.session_factory() as session:
        renewed = attest(
            session, intent.model_copy(update={"operation": "reaffirm", "expected_revision": 2})
        )
        assert accept(session, renewed, "renew")["readback"]["revision"] == 3
    restore_backup(database, backup.id)
    with database.session_factory() as session:
        recovered = read_historical_endpoint(session, key)
        assert recovered["effective_state"] == "retired"
        assert recovered["revision"] == 2
        assert count(session, HistoricalEndpointApply) == 1


def test_endpoint_migration_empty_append_only_and_populated_downgrade_refusal(tmp_path):
    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-endpoint-migration.db"
    assert run_alembic(path, "upgrade", "0049_executed_trade_truth").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        for table in (
            "historical_endpoint_revisions",
            "historical_endpoint_applies",
            "reporting_months",
            "position_snapshots",
        ):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    assert run_alembic(path, "downgrade", "0049_executed_trade_truth").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        # Purely synthetic persistence identity; no source/private payload.
        connection.execute(
            "INSERT INTO historical_endpoint_revisions "
            "(endpoint_key,account_id,valuation_date,basis,currency,revision,operation,acceptance_state,"
            "evidence_json,material_signature,recorded_at) VALUES (?,1,'2030-01-31','eod','RUB',1,'accept','accepted','{}',?,'2030-02-01')",
            ("a" * 64, "b" * 64),
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM historical_endpoint_revisions")
    result = run_alembic(path, "downgrade", "0049_executed_trade_truth")
    assert result.returncode != 0
    assert "cannot discard historical endpoint acceptance" in result.stderr


@pytest.mark.parametrize("operation", ["date-change", "delete"])
def test_month_lifecycle_retires_exact_dependency(database, operation):
    from hermes_finance.services.reporting_months import (
        delete_reporting_month,
        update_reporting_month,
    )

    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        key = accept(session, attest(session, intent))["readback"]["endpoint_key"]
        if operation == "delete":
            delete_reporting_month(session, month_id)
        else:
            update_reporting_month(session, month_id, snapshot_date=date(2030, 2, 1))
        result = read_historical_endpoint(session, key)
        assert result["effective_state"] == "retired"
        assert result["total_value_kopecks"] is None
        assert result["evidence"]["dependencies"]["overlap"][0]["month_id"] == month_id


def test_new_identical_source_corroborates_without_additional_value(database):
    from hermes_finance.statement_import.mybroker import canonical

    with database.session_factory() as session:
        intent, _ = setup_source(session)
        key = accept(session, attest(session, intent))["readback"]["endpoint_key"]
        original = session.get(MyBrokerImport, intent.source_import_id)
        document = json.loads(original.normalized_json)
        document["document_sha256"] = "c" * 64
        session.add(
            MyBrokerImport(
                document_sha256="c" * 64,
                covered_from=original.covered_from,
                covered_to=DAY,
                parser_version=original.parser_version,
                confirmation_digest="d" * 64,
                normalized_json=canonical(document),
                mappings_json=original.mappings_json,
                accepted_at=original.accepted_at,
            )
        )
        session.commit()
        result = read_historical_endpoint(session, key)
        assert result["effective_state"] == "accepted"
        assert result["total_value_kopecks"] == 10001
        assert result["revision"] == 1


def test_missing_source_invalidates_without_hiding_frozen_observations(database):
    with database.session_factory() as session:
        intent, _ = setup_source(session)
        key = accept(session, attest(session, intent))["readback"]["endpoint_key"]
        session.delete(session.get(MyBrokerImport, intent.source_import_id))
        session.commit()
        result = read_historical_endpoint(session, key)
        assert result["effective_state"] == "invalidated"
        assert result["total_value_kopecks"] is None
        assert result["evidence"]["positions"][0]["value"] == "100.01"


def test_writer_reservation_serializes_close_through_commit(database, monkeypatch):
    from threading import Event, Thread

    from hermes_finance.services import historical_endpoints as service

    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        intent = attest(session, intent)
        plan = preview_historical_endpoint(session, intent)
        started, finished = Event(), Event()
        errors = []

        def close():
            try:
                with database.session_factory() as competing:
                    started.set()
                    close_reporting_month(competing, month_id)
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()

        worker = Thread(target=close)
        original = service._plan

        def after_reservation(write_session, selected):
            worker.start()
            assert started.wait(2)
            assert not finished.wait(0.1)
            return original(write_session, selected)

        monkeypatch.setattr(service, "_plan", after_reservation)
        try:
            result = apply_historical_endpoint(
                session, intent, confirmation_digest=plan["confirmation_digest"], request_id="race"
            )
        finally:
            worker.join(5)
        assert finished.is_set() and not errors
        assert result["readback"]["total_value_kopecks"] == 10001


def test_incomplete_trade_identity_cannot_hide_pending_exposure(database):
    root = ET.fromstring(endpoint_xml())
    pending_root = ET.fromstring(fixture(pending=True, missing_id=True))
    root.find("{MyBroker}Trades/{MyBroker}Report").append(
        pending_root.find("{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix3")
    )
    # Remove the unrelated completed trade and money leg; only incomplete-ID pending remains.
    trades = root.find("{MyBroker}Trades/{MyBroker}Report")
    trades.remove(trades.find("{MyBroker}Tablix2"))
    money = root.find("{MyBroker}Trades2/{MyBroker}Report")
    money.clear()
    money.set("Name", "3_BrokerMoneyMove")
    with database.session_factory() as session:
        intent, _ = setup_source(session, xml=ET.tostring(root), keep_trades=True)
        assert (
            "unresolved_cutoff_identity"
            in preview_historical_endpoint(session, attest(session, intent))["blockers"]
        )


def test_proven_unrelated_account_opaque_source_does_not_contaminate(database):
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import confirm_mapping
    from hermes_finance.statement_import.mybroker import PROVIDER

    with database.session_factory() as session:
        intent, _ = setup_source(session)
        other = create_account(session, name="Synthetic other account", account_type="brokerage")
        for alias in ("7654321", "7654321-000"):
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=other.id,
            )
        root = ET.fromstring(fixture(pending=True, unsupported=True))
        for row in root.iter():
            for field in ("acc_code", "acc_code2"):
                if field in row.attrib:
                    row.set(field, "7654321-000")
        filename = "Брокерский 7654321 (01.01.30-31.01.30).xml"
        raw = ET.tostring(root)
        apply(session, raw, preview(session, raw, filename), filename)
        assert accept(session, attest(session, intent))["readback"]["total_value_kopecks"] == 10001


def test_overlap_envelope_contains_no_unrelated_narratives_or_costs(database):
    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        matching_month(session, intent, instrument)
        cash = session.scalar(select(CashBalance))
        cash.notes = "Synthetic narrative"
        session.commit()
        result = accept(session, attest(session, intent))["readback"]
        encoded = json.dumps(result["evidence"])
        assert "Synthetic narrative" not in encoded
        assert "cost_basis" not in encoded
        assert "market_price_per_unit" not in encoded
        assert "unrealized_result" not in encoded


@pytest.mark.parametrize("component", ["position", "cash", "unowned-cash", "deposit"])
def test_component_add_remove_cannot_silently_restore_authority(database, component):
    from hermes_finance.services.instruments import create_instrument

    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        key = accept(session, attest(session, intent))["readback"]["endpoint_key"]
        if component == "position":
            other = create_instrument(
                session, name="Synthetic extra security", instrument_type="stock"
            )
            extra = PositionSnapshot(
                reporting_month_id=month_id,
                account_id=intent.account_id,
                instrument_id=other.id,
                quantity=Decimal("1"),
                market_value_kopecks=1,
                average_cost_per_unit_kopecks=0,
                market_price_per_unit_kopecks=0,
                cost_basis_kopecks=0,
                unrealized_result_kopecks=0,
                price_date=DAY,
            )
        elif component == "deposit":
            extra = DepositSnapshot(
                reporting_month_id=month_id,
                account_id=intent.account_id,
                name="Synthetic deposit",
                deposit_type="deposit",
                balance_kopecks=1,
                annual_rate_basis_points=0,
                expected_monthly_interest_kopecks=0,
            )
        else:
            extra = CashBalance(
                reporting_month_id=month_id,
                account_id=None if component == "unowned-cash" else intent.account_id,
                name="Synthetic extra cash",
                amount_kopecks=1,
                currency="RUB",
            )
        session.add(extra)
        session.commit()
        assert read_historical_endpoint(session, key)["effective_state"] == "retired"
        session.delete(extra)
        session.commit()
        result = read_historical_endpoint(session, key)
        assert result["effective_state"] == "retired" and result["revision"] == 2
        assert result["total_value_kopecks"] is None
        renewed = attest(
            session, intent.model_copy(update={"operation": "reaffirm", "expected_revision": 2})
        )
        assert (
            accept(session, renewed, "explicit-renew")["readback"]["total_value_kopecks"] == 10001
        )


@pytest.mark.parametrize(
    "period,blocked", [("2030-01", True), ("2029-12", True), ("2030-02", False)]
)
def test_archive_quote_date_never_substitutes_for_snapshot_date(database, period, blocked):
    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        session.add(
            PositionSnapshot(
                reporting_month_id=None,
                archived_from_period=period,
                account_id=intent.account_id,
                instrument_id=instrument,
                quantity=Decimal("4"),
                market_value_kopecks=10002,
                average_cost_per_unit_kopecks=0,
                market_price_per_unit_kopecks=0,
                cost_basis_kopecks=0,
                unrealized_result_kopecks=0,
                price_date=date(2029, 12, 1),
            )
        )
        session.commit()
        plan = preview_historical_endpoint(session, attest(session, intent))
        assert ("overlap_ambiguous_or_archived" in plan["blockers"]) == blocked


def test_earlier_forward_disagreement_survives_later_clean_report(database):
    with database.session_factory() as session:
        old_raw = positions_only(endpoint_xml(forward="20"))
        earlier = "Брокерский 1234567 (01.01.30-16.01.30).xml"
        apply(session, old_raw, preview(session, old_raw, earlier), earlier)
        intent, _ = setup_source(session)
        plan = preview_historical_endpoint(session, attest(session, intent))
        assert "unresolved_source_forward_exposure" in plan["blockers"]
        assert not plan["can_apply"]


def test_component_addition_for_other_account_does_not_retire_frozen_overlap(database):
    from hermes_finance.services.accounts import create_account

    with database.session_factory() as session:
        intent, instrument = setup_source(session)
        month_id = matching_month(session, intent, instrument)
        key = accept(session, attest(session, intent))["readback"]["endpoint_key"]
        other = create_account(
            session, name="Synthetic unrelated account", account_type="brokerage"
        )
        session.add(
            DepositSnapshot(
                reporting_month_id=month_id,
                account_id=other.id,
                name="Synthetic unrelated deposit",
                deposit_type="deposit",
                balance_kopecks=1,
                annual_rate_basis_points=0,
                expected_monthly_interest_kopecks=0,
            )
        )
        session.commit()
        result = read_historical_endpoint(session, key)
        assert result["effective_state"] == "accepted" and result["revision"] == 1
