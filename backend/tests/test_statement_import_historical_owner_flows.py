"""Synthetic-only H2-A1 financial, identity, concurrency and lifecycle matrix."""

import copy
from datetime import date, datetime
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select, text
from test_statement_import_mybroker import apply, fixture, preview
from test_statement_import_mybroker import database as database

from hermes_finance.domain.historical_owner_flows import CLAIMS, OwnerFlowIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBalance,
    CashBoundaryCoverage,
    ExternalFlow,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowApply,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    InvestmentCashFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.historical_owner_flows import (
    apply_historical_owner_flow,
    preview_historical_owner_flow,
    read_historical_owner_flow,
)
from hermes_finance.statement_import.mybroker import MyBrokerError

DAY = date(2030, 1, 17)


def xml(
    *,
    amount="12.34",
    currency="RUB",
    stamp="10",
    duplicate=False,
    linked=False,
    opaque=False,
    money=True,
    cash_day="2030-01-17",
    pending=False,
    extra_amounts=(),
):
    root = ET.fromstring(fixture(unsupported=opaque, pending=False))
    for report in root.findall("{MyBroker}Trades/{MyBroker}Report"):
        for child in list(report):
            report.remove(child)
    group = root.find(".//{MyBroker}settlement_date")
    group.set("settlement_date", cash_day + "T00:00:00")
    rn = root.find(".//{MyBroker}rn")
    rn.set("last_update", "2030-01-17T10:00:" + stamp)
    root.find(".//{MyBroker}comment").set(
        "comment", "Расчеты по сделке 10000000001" if linked else "Synthetic opaque semantics"
    )
    volume = root.find(".//{MyBroker}p_code[@volume]")
    volume.set("volume", amount)
    volume.set("p_code", currency)
    if duplicate:
        root.find(".//{MyBroker}rn_Collection").append(copy.deepcopy(rn))
    for extra_amount in extra_amounts:
        extra = copy.deepcopy(rn)
        extra.find(".//{MyBroker}p_code[@volume]").set("volume", extra_amount)
        root.find(".//{MyBroker}rn_Collection").append(extra)
    if not money:
        for report in root.findall("{MyBroker}Trades2/{MyBroker}Report"):
            for child in list(report):
                report.remove(child)
    if pending:
        pending_root = ET.fromstring(fixture(pending=True))
        report = root.find("{MyBroker}Trades/{MyBroker}Report")
        report.append(copy.deepcopy(pending_root.find(".//{MyBroker}Tablix3")))
    return ET.tostring(root, encoding="utf-8")


def source(session, **kwargs):
    raw = xml(**kwargs)
    result = apply(session, raw, preview(session, raw))
    account = next(b["hermes_id"] for b in result["mappings"] if b["kind"] == "account")
    return OwnerFlowIntent(
        account_id=account, seed={"import_id": result["import_id"], "ordinal": 0}
    )


def attest(session, intent):
    plan = preview_historical_owner_flow(session, intent)
    return OwnerFlowIntent.model_validate(
        {
            **intent.model_dump(mode="json"),
            "claims": {
                "provenance_kind": "owner_attested_source_row",
                "reference": "synthetic-review",
                "direction": plan["evidence"]["core"]["direction"]
                if plan["evidence"]["core"]
                else "contribution",
                "source_set_fingerprint": plan["source_set_fingerprint"] or "a" * 64,
                "review_context_digest": plan["review_context_digest"] or "b" * 64,
                **dict.fromkeys(CLAIMS, True),
            },
        }
    )


def accept(session, intent, request_id="synthetic-apply"):
    plan = preview_historical_owner_flow(session, intent)
    assert plan["can_apply"], plan["blockers"]
    return apply_historical_owner_flow(
        session, intent, confirmation_digest=plan["confirmation_digest"], request_id=request_id
    )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def target(intent, readback, operation="reaffirm"):
    return intent.model_copy(
        update={
            "operation": operation,
            "flow_id": readback["flow_id"],
            "expected_revision": readback["revision"],
            "claims": None,
        }
    )


@pytest.mark.parametrize(
    "amount,direction,minor",
    [
        ("12.34", "contribution", 1234),
        ("-12.34", "withdrawal", 1234),
        ("92233720368547758.07", "contribution", 2**63 - 1),
    ],
)
def test_exact_source_core_no_month_or_coverage_materialization(database, amount, direction, minor):
    with database.session_factory() as session:
        intent = attest(session, source(session, amount=amount))
        result = accept(session, intent)
        readback = read_historical_owner_flow(session, result["readback"]["flow_id"])
        assert readback == result["readback"]
        assert readback["core"] == {
            "account_id": intent.account_id,
            "event_date": DAY.isoformat(),
            "currency": "RUB",
            "signed_source_amount": amount,
            "direction": direction,
            "boundary_amount_kopecks": minor,
        }
        assert readback["account_scope"]["status"] == "authoritative"
        assert readback["portfolio_scope"]["status"] == readback["cash_coverage"] == "unknown"
        assert readback["boundary_amount_kopecks"] == minor
        for model in (
            ReportingMonth,
            CashBoundaryCoverage,
            ExternalFlow,
            CashBalance,
            PositionSnapshot,
            InvestmentCashFlow,
        ):
            assert count(session, model) == 0
        assert count(session, HistoricalOwnerFlow) == 1
        assert count(session, HistoricalOwnerFlowOccurrence) == 1


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"amount": "0"}, "amount_out_of_bounds"),
        ({"amount": "-0"}, "amount_out_of_bounds"),
        ({"amount": "12.341"}, "fractional_kopeck"),
        ({"amount": "12.340000000000000000000000000000001"}, "fractional_kopeck"),
        ({"amount": "92233720368547758.08"}, "amount_out_of_bounds"),
        ({"currency": "USD"}, "source_currency_unsupported"),
        ({"cash_day": "2030-02-01"}, "source_date_out_of_range"),
        ({"linked": True}, "source_trade_linkage_unsupported"),
        ({"opaque": True}, "4_Transfers_unsupported"),
        ({"duplicate": True}, "same_report_multiplicity"),
    ],
)
def test_incompatible_source_blocks_atomic_acceptance(database, kwargs, reason):
    with database.session_factory() as session:
        intent = attest(session, source(session, **kwargs))
        plan = preview_historical_owner_flow(session, intent)
        assert reason in plan["blockers"], plan["blockers"]
        with pytest.raises(MyBrokerError, match=reason):
            apply_historical_owner_flow(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="blocked",
            )
        for model in (
            HistoricalOwnerFlow,
            HistoricalOwnerFlowOccurrence,
            HistoricalOwnerFlowRevision,
            HistoricalOwnerFlowApply,
        ):
            assert count(session, model) == 0


@pytest.mark.parametrize("name", CLAIMS)
def test_every_semantic_claim_is_explicit_and_unconfirmed_by_default(database, name):
    with database.session_factory() as session:
        raw = source(session)
        assert (
            "owner_cash_claims_missing" in preview_historical_owner_flow(session, raw)["blockers"]
        )
        intent = attest(session, raw)
        data = intent.model_dump(mode="json")
        data["claims"].pop(name)
        rejected = OwnerFlowIntent.model_validate(data)
        assert name + "_unconfirmed" in preview_historical_owner_flow(session, rejected)["blockers"]


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("direction", "withdrawal", "attested_direction_mismatch"),
        ("source_set_fingerprint", "c" * 64, "claim_binding_mismatch"),
        ("review_context_digest", "d" * 64, "claim_binding_mismatch"),
    ],
)
def test_claim_binding_cannot_override_source(database, field, value, reason):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        data = intent.model_dump(mode="json")
        data["claims"][field] = value
        assert (
            reason
            in preview_historical_owner_flow(session, OwnerFlowIntent.model_validate(data))[
                "blockers"
            ]
        )


def test_new_report_requires_full_set_review_then_corroborates_same_identity(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        initial_plan = preview_historical_owner_flow(session, intent)
        first = accept(session, intent)
        flow_id = first["readback"]["flow_id"]
        source(session, stamp="11")
        retired = read_historical_owner_flow(session, flow_id)
        assert retired["effective_state"] == "retired"
        assert retired["boundary_amount_kopecks"] is None
        review = attest(session, target(intent, retired, "corroborate"))
        assert len(preview_historical_owner_flow(session, review)["evidence"]["occurrences"]) == 2
        renewed = accept(session, review, "corroborate")["readback"]
        assert renewed["flow_id"] == flow_id and renewed["boundary_amount_kopecks"] == 1234
        assert count(session, HistoricalOwnerFlow) == 1
        assert count(session, HistoricalOwnerFlowOccurrence) == 2
        replay = apply_historical_owner_flow(
            session,
            intent,
            confirmation_digest=initial_plan["confirmation_digest"],
            request_id="synthetic-apply",
        )
        assert replay["committed_revision_id"] == first["committed_revision_id"]
        assert replay["readback"] == renewed
        again = attest(session, target(review, renewed, "accept"))
        assert accept(session, again, "fresh-noop")["result_action"] == "noop"
        assert count(session, HistoricalOwnerFlowRevision) == 3


def test_multiple_reports_are_not_equivalence_without_bound_owner_claim(database):
    with database.session_factory() as session:
        intent = source(session)
        source(session, stamp="11")
        intent = attest(session, intent)
        intent.claims.complete_occurrence_set_is_one_event = False
        assert (
            "complete_occurrence_set_is_one_event_unconfirmed"
            in preview_historical_owner_flow(session, intent)["blockers"]
        )


@pytest.mark.parametrize("other", [{"amount": "12.35"}, {"money": False}, {"duplicate": True}])
def test_changed_missing_or_ambiguous_overlapping_source_blocks(database, other):
    with database.session_factory() as session:
        intent = source(session)
        source(session, stamp="11", **other)
        plan = preview_historical_owner_flow(session, attest(session, intent))
        assert not plan["can_apply"]
        assert any(
            b in plan["blockers"]
            for b in ("overlapping_source_event_missing", "same_report_multiplicity")
        )


def test_revoke_broken_mapping_and_retained_ownership_no_replay_resurrection(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        plan = preview_historical_owner_flow(session, intent)
        first = accept(session, intent)
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        original = mapping.source_as_of
        mapping.source_as_of = datetime(2030, 1, 1)
        session.commit()
        mapping.source_as_of = original
        session.commit()
        retired = read_historical_owner_flow(session, first["readback"]["flow_id"])
        assert retired["effective_state"] == "retired"
        assert retired["revision"] == 2
        revoke = OwnerFlowIntent(
            operation="revoke",
            flow_id=retired["flow_id"],
            expected_revision=2,
            reason_code="attestation_withdrawn",
        )
        revoked = accept(session, revoke, "revoke")["readback"]
        assert revoked["effective_state"] == "revoked"
        assert count(session, HistoricalOwnerFlowOccurrence) == 1
        replay = apply_historical_owner_flow(
            session,
            intent,
            confirmation_digest=plan["confirmation_digest"],
            request_id="synthetic-apply",
        )
        assert replay["committed_revision_id"] == first["committed_revision_id"]
        assert replay["readback"]["effective_state"] == "revoked"
        assert (
            "occurrence_already_owned" in preview_historical_owner_flow(session, intent)["blockers"]
        )
        renewed = attest(session, target(intent, revoked))
        assert accept(session, renewed, "reaffirm")["readback"]["effective_state"] == "accepted"


def test_membership_change_retirement_does_not_promote_portfolio_scope(database):
    with database.session_factory() as session:
        intent = source(session)
        membership = AccountPerformanceScopeMembership(
            account_id=intent.account_id, effective_from=date(2030, 1, 1), include_in_returns=False
        )
        session.add(membership)
        session.commit()
        first = accept(session, attest(session, intent))["readback"]
        assert first["account_scope"]["status"] == "authoritative"
        assert first["portfolio_scope"]["status"] == "unknown"
        membership.include_in_returns = True
        session.commit()
        membership.include_in_returns = False
        session.commit()
        assert read_historical_owner_flow(session, first["flow_id"])["effective_state"] == "retired"


def test_stale_competing_acceptance_and_request_id_conflict(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        plan = preview_historical_owner_flow(session, intent)
        accept(session, intent)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_historical_owner_flow(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="competing",
            )
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            apply_historical_owner_flow(
                session, intent, confirmation_digest="e" * 64, request_id="synthetic-apply"
            )
        assert count(session, HistoricalOwnerFlowApply) == 1


def test_receipt_failure_rolls_back_core_ownership_and_revision(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        plan = preview_historical_owner_flow(session, intent)

        def fail(*_args):
            raise RuntimeError("synthetic-write-failure")

        event.listen(HistoricalOwnerFlowApply, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="synthetic-write-failure"):
                apply_historical_owner_flow(
                    session,
                    intent,
                    confirmation_digest=plan["confirmation_digest"],
                    request_id="failure",
                )
        finally:
            event.remove(HistoricalOwnerFlowApply, "before_insert", fail)
        for model in (
            HistoricalOwnerFlow,
            HistoricalOwnerFlowOccurrence,
            HistoricalOwnerFlowRevision,
            HistoricalOwnerFlowApply,
        ):
            assert count(session, model) == 0


def test_legacy_and_complete_coverage_disclosed_and_blocked(database):
    with database.session_factory() as session:
        intent = source(session)
        month = ReportingMonth(
            year=2030,
            month=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
            snapshot_date=date(2030, 1, 31),
        )
        session.add(month)
        session.flush()
        session.add(
            ExternalFlow(
                reporting_month_id=month.id,
                account_id=intent.account_id,
                event_date=DAY,
                boundary_amount_kopecks=1234,
                direction="contribution",
                kind="external_contribution",
                source="manual",
            )
        )
        session.add(
            CashBoundaryCoverage(
                account_id=intent.account_id,
                covered_from=DAY,
                covered_to=DAY,
                coverage_state="complete",
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        plan = preview_historical_owner_flow(session, attest(session, intent))
        assert "legacy_flow_or_transfer_overlap" in plan["blockers"]
        assert "legacy_complete_coverage_not_source_reconciled" in plan["blockers"]
        assert len(plan["evidence"]["dependencies"]["legacy_flows"]) == 1


def test_calendar_only_closed_month_and_unrelated_reopen_do_not_change_authority(database):
    with database.session_factory() as session:
        intent = source(session)
        month = ReportingMonth(
            year=2030,
            month=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
            snapshot_date=date(2030, 1, 31),
            status="closed",
        )
        session.add(month)
        session.commit()
        first = accept(session, attest(session, intent))["readback"]
        month.status = "draft"
        session.commit()
        assert (
            read_historical_owner_flow(session, first["flow_id"])["effective_state"] == "accepted"
        )


def test_api_independent_get_strict_financial_inputs_and_read_only(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
    client = TestClient(create_app(database=database))
    body = intent.model_dump(mode="json")
    plan = client.post("/api/historical-owner-flows/preview", json=body)
    assert plan.status_code == 200
    result = client.post(
        "/api/historical-owner-flows/apply",
        json={
            **body,
            "request_id": "api-apply",
            "confirmation_digest": plan.json()["confirmation_digest"],
        },
    )
    assert result.status_code == 200, result.text
    readback = result.json()["readback"]
    assert client.get("/api/historical-owner-flows/" + readback["flow_id"]).json() == readback
    for extra in ({"amount": "1"}, {"reporting_month_id": 1}, {"normalized_row": {}}):
        assert (
            client.post("/api/historical-owner-flows/preview", json={**body, **extra}).status_code
            == 422
        )
    with database.session_factory() as session:
        assert count(session, HistoricalOwnerFlowRevision) == 1
        session.scalar(select(HistoricalOwnerFlow)).boundary_amount_kopecks = 1
        with pytest.raises(ValueError, match="append-only"):
            session.flush()
        session.rollback()


def test_source_dependency_read_fails_closed_without_repair_on_direct_sql(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        first = accept(session, intent)["readback"]
        session.execute(
            text(
                "UPDATE broker_identity_mappings SET source_as_of = '2030-01-01' WHERE subject_kind = 'account'"
            )
        )
        session.commit()
        invalid = read_historical_owner_flow(session, first["flow_id"])
        assert invalid["effective_state"] == "invalidated"
        assert invalid["boundary_amount_kopecks"] is None
        assert count(session, HistoricalOwnerFlowRevision) == 1
        revoke = OwnerFlowIntent(
            operation="revoke",
            flow_id=first["flow_id"],
            expected_revision=1,
            reason_code="evidence_disputed",
        )
        assert accept(session, revoke, "broken-revoke")["readback"]["effective_state"] == "revoked"


@pytest.mark.parametrize(
    "data",
    [
        {"operation": "revoke", "flow_id": "synthetic"},
        {"operation": "corroborate", "account_id": 1, "seed": {"import_id": 1, "ordinal": 0}},
        {"account_id": 1, "seed": {"import_id": 1, "section": "transfers", "ordinal": 0}},
        {"account_id": 1, "seed": {"import_id": 1, "ordinal": 0}, "direction": "income"},
    ],
)
def test_request_shape_rejects_category_and_replacement_expansion(data):
    with pytest.raises(ValidationError):
        OwnerFlowIntent.model_validate(data)


def test_simultaneous_competing_writers_one_identity_and_atomic_loser(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    with database.session_factory() as session:
        intent = attest(session, source(session))
        plan = preview_historical_owner_flow(session, intent)
    barrier = Barrier(2)

    def worker(key):
        with database.session_factory() as session:
            barrier.wait(timeout=5)
            try:
                return apply_historical_owner_flow(
                    session,
                    intent,
                    confirmation_digest=plan["confirmation_digest"],
                    request_id=key,
                )
            except MyBrokerError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ("writer-a", "writer-b")))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert "preview_stale" in results
    with database.session_factory() as session:
        assert count(session, HistoricalOwnerFlow) == 1
        assert count(session, HistoricalOwnerFlowOccurrence) == 1
        assert count(session, HistoricalOwnerFlowRevision) == 1
        assert count(session, HistoricalOwnerFlowApply) == 1


def test_writer_reservation_precedes_authoritative_reads(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        plan = preview_historical_owner_flow(session, intent)
        statements = []

        def record(_connection, _cursor, statement, *_args):
            statements.append(statement)

        event.listen(database.engine, "before_cursor_execute", record)
        try:
            apply_historical_owner_flow(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="reservation",
            )
        finally:
            event.remove(database.engine, "before_cursor_execute", record)
        assert statements[0].startswith("UPDATE historical_owner_flow_revisions")
        assert any(s.startswith("SELECT") for s in statements[1:])


def test_changed_core_target_and_conflicting_source_are_refused(database):
    with database.session_factory() as session:
        intent = attest(session, source(session))
        first = accept(session, intent)["readback"]
        changed = source(session, amount="12.35", stamp="11")
        replacement = attest(session, target(changed, first))
        assert (
            "changed_core_unsupported"
            in preview_historical_owner_flow(session, replacement)["blockers"]
        )
        fresh = attest(session, changed)
        assert (
            "overlapping_source_event_missing"
            in preview_historical_owner_flow(session, fresh)["blockers"]
        )
        assert count(session, HistoricalOwnerFlow) == 1


def test_new_legacy_then_remove_remains_retired_and_rollback_is_atomic(database):
    with database.session_factory() as session:
        intent = source(session)
        first = accept(session, attest(session, intent))["readback"]
        month = ReportingMonth(
            year=2030,
            month=1,
            period_start=date(2030, 1, 1),
            period_end=date(2030, 1, 31),
            snapshot_date=date(2030, 1, 31),
        )
        session.add(month)
        session.commit()
        legacy = ExternalFlow(
            reporting_month_id=month.id,
            account_id=intent.account_id,
            event_date=DAY,
            boundary_amount_kopecks=1,
            direction="contribution",
            kind="external_contribution",
            source="manual",
        )
        session.add(legacy)
        session.flush()
        session.rollback()
        assert read_historical_owner_flow(session, first["flow_id"])["revision"] == 1
        session.add(legacy)
        session.commit()
        invalid = read_historical_owner_flow(session, first["flow_id"])
        assert invalid["effective_state"] == "retired"
        assert "legacy_flow_or_transfer_overlap" in invalid["blockers"]
        session.delete(legacy)
        session.commit()
        assert read_historical_owner_flow(session, first["flow_id"])["effective_state"] == "retired"


def test_unrelated_interval_source_and_account_flags_do_not_retire(database):
    from test_statement_import_mybroker import FILENAME

    from hermes_finance.persistence import Account

    with database.session_factory() as session:
        intent = source(session)
        first = accept(session, attest(session, intent))["readback"]
        raw = xml(stamp="11", cash_day="2030-02-17")
        filename = FILENAME.replace("01.01.30-31.01.30", "01.02.30-28.02.30")
        apply(session, raw, preview(session, raw, filename), filename)
        account = session.get(Account, intent.account_id)
        account.include_in_returns = False
        session.commit()
        assert (
            read_historical_owner_flow(session, first["flow_id"])["effective_state"] == "accepted"
        )


def test_migration_empty_unique_permanent_ownership_append_only_and_loss_guard(tmp_path):
    import sqlite3

    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-owner-flow-migration.db"
    assert run_alembic(path, "upgrade", "0050_historical_endpoints").returncode == 0
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    tables = (
        "historical_owner_flows",
        "historical_owner_flow_occurrences",
        "historical_owner_flow_revisions",
        "historical_owner_flow_applies",
    )
    with sqlite3.connect(path) as connection:
        for table in (*tables, "reporting_months", "external_flows"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    assert run_alembic(path, "downgrade", "0050_historical_endpoints").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO accounts(id,name,account_type) VALUES(1,'Synthetic','brokerage')"
        )
        connection.execute(
            "INSERT INTO mybroker_imports(id,document_sha256,covered_from,covered_to,parser_version,confirmation_digest,normalized_json,mappings_json,accepted_at) VALUES(1,?,'2030-01-01','2030-01-31','mybroker-s1-v2',?,'{}','[]','2030-02-01')",
            ("a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO historical_owner_flows VALUES('synthetic',1,'2030-01-17','RUB','12.34','contribution',1234)"
        )
        connection.execute(
            "INSERT INTO historical_owner_flow_occurrences VALUES(1,'synthetic',1,'money',0,?)",
            ("c" * 64,),
        )
        connection.execute(
            "INSERT INTO historical_owner_flow_revisions VALUES(1,'synthetic',1,NULL,'accept','accepted','{}',?,NULL,'2030-02-01')",
            ("d" * 64,),
        )
        connection.execute(
            "INSERT INTO historical_owner_flow_applies VALUES(1,'synthetic',?,?,'synthetic',1,'created','2030-02-01')",
            ("e" * 64, "f" * 64),
        )
        for table in tables:
            for operation in (f"UPDATE {table} SET " + ("id=id"), f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                    connection.execute(operation)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute(
                "INSERT INTO historical_owner_flow_occurrences VALUES(2,'synthetic',1,'money',0,?)",
                ("c" * 64,),
            )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    result = run_alembic(path, "downgrade", "0050_historical_endpoints")
    assert result.returncode != 0
    assert "cannot discard historical owner flow acceptance" in result.stderr


def test_backup_restore_preserves_core_occurrences_retirement_and_receipt(database):
    from hermes_finance.services.backups import create_backup, restore_backup

    with database.session_factory() as session:
        intent = attest(session, source(session))
        plan = preview_historical_owner_flow(session, intent)
        first = accept(session, intent)["readback"]
        membership = AccountPerformanceScopeMembership(
            account_id=intent.account_id, effective_from=date(2030, 1, 1), include_in_returns=True
        )
        session.add(membership)
        session.commit()
        retired = read_historical_owner_flow(session, first["flow_id"])
        assert retired["effective_state"] == "retired"
    backup = create_backup(database)
    with database.session_factory() as session:
        accept(session, attest(session, target(intent, retired)), "renew")
    restore_backup(database, backup.id)
    with database.session_factory() as session:
        recovered = read_historical_owner_flow(session, first["flow_id"])
        assert recovered["revision"] == 2 and recovered["effective_state"] == "retired"
        assert count(session, HistoricalOwnerFlowOccurrence) == 1
        replay = apply_historical_owner_flow(
            session,
            intent,
            confirmation_digest=plan["confirmation_digest"],
            request_id="synthetic-apply",
        )
        assert replay["readback"] == recovered


@pytest.mark.parametrize("change", ["mapping", "source", "legacy"])
def test_retired_revoke_binds_current_dependencies_without_requiring_valid_support(
    database, change
):
    from hermes_finance.services.broker_identity_mappings import confirm_mapping, revoke_mapping

    with database.session_factory() as session:
        intent = attest(session, source(session))
        first = accept(session, intent)["readback"]
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        alias = mapping.provider_identity
        # Material source support is now broken; withdrawal must remain possible.
        revoke_mapping(session, mapping.id)
        retired = read_historical_owner_flow(session, first["flow_id"])
        revoke = OwnerFlowIntent(
            operation="revoke",
            flow_id=first["flow_id"],
            expected_revision=retired["revision"],
            reason_code="evidence_disputed",
        )
        old = preview_historical_owner_flow(session, revoke)
        assert old["can_apply"]
        if change == "mapping":
            confirm_mapping(
                session,
                provider="alfa_mybroker",
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=intent.account_id,
            )
        elif change == "source":
            # Incoming immutable support while retired does not append another retirement.
            confirm_mapping(
                session,
                provider="alfa_mybroker",
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=intent.account_id,
            )
            source(session, stamp="11")
        else:
            month = ReportingMonth(
                year=2030,
                month=1,
                period_start=date(2030, 1, 1),
                period_end=date(2030, 1, 31),
                snapshot_date=date(2030, 1, 31),
            )
            session.add(month)
            session.flush()
            session.add(
                ExternalFlow(
                    reporting_month_id=month.id,
                    account_id=intent.account_id,
                    event_date=DAY,
                    boundary_amount_kopecks=1,
                    direction="contribution",
                    kind="external_contribution",
                    source="manual",
                )
            )
            session.commit()
        assert (
            read_historical_owner_flow(session, first["flow_id"])["revision"] == retired["revision"]
        )
        new = preview_historical_owner_flow(session, revoke)
        assert new["confirmation_digest"] != old["confirmation_digest"]
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_historical_owner_flow(
                session,
                revoke,
                confirmation_digest=old["confirmation_digest"],
                request_id="stale-revoke",
            )
        assert count(session, HistoricalOwnerFlowApply) == 1
        assert accept(session, revoke, "fresh-revoke")["readback"]["effective_state"] == "revoked"


@pytest.mark.parametrize("amount", [0.25, 12, True, "NaN", "Infinity", "1e0", "01.00"])
def test_noncanonical_corrupt_source_payload_never_commits_financial_history(database, amount):
    import json

    from hermes_finance.persistence import MyBrokerImport

    with database.session_factory() as session:
        intent = source(session, amount="0.25")
        row = session.get(MyBrokerImport, intent.seed.import_id)
        document = json.loads(row.normalized_json)
        document["money"][0]["amount"] = amount
        row.normalized_json = json.dumps(document)
        session.commit()
        intent = attest(session, intent)
        plan = preview_historical_owner_flow(session, intent)
        assert "source_money_invalid" in plan["blockers"]
        with pytest.raises(MyBrokerError, match="source_money_invalid"):
            apply_historical_owner_flow(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="corrupt-source",
            )
        assert count(session, HistoricalOwnerFlow) == 0
        assert count(session, HistoricalOwnerFlowOccurrence) == 0
        assert count(session, HistoricalOwnerFlowRevision) == 0
        assert count(session, HistoricalOwnerFlowApply) == 0


@pytest.mark.parametrize(
    "second_amount,direction,minor",
    [
        ("56.78", "contribution", 5678),
        ("-56.78", "withdrawal", 5678),
        ("-12.34", "withdrawal", 1234),
    ],
)
def test_distinct_same_day_signatures_are_independently_accepted(
    database, second_amount, direction, minor
):
    with database.session_factory() as session:
        first_intent = source(session, extra_amounts=(second_amount,))
        first = accept(session, attest(session, first_intent))["readback"]
        second_intent = first_intent.model_copy(
            update={
                "seed": first_intent.seed.model_copy(update={"ordinal": 1}),
            }
        )
        # A second eligible row cannot replace the frozen economics of the first.
        replacement = attest(session, target(second_intent, first))
        blocked = preview_historical_owner_flow(session, replacement)
        assert "changed_core_unsupported" in blocked["blockers"]
        with pytest.raises(MyBrokerError, match="changed_core_unsupported"):
            apply_historical_owner_flow(
                session,
                replacement,
                confirmation_digest=blocked["confirmation_digest"],
                request_id="replacement",
            )
        assert count(session, HistoricalOwnerFlowApply) == 1
        second_intent = attest(session, second_intent)
        second = accept(session, second_intent, "second-event")["readback"]
        assert first["flow_id"] != second["flow_id"]
        assert second["core"]["account_id"] == first["core"]["account_id"]
        assert second["core"]["event_date"] == first["core"]["event_date"] == DAY.isoformat()
        assert second["core"]["signed_source_amount"] == second_amount
        assert second["core"]["direction"] == direction
        assert second["boundary_amount_kopecks"] == minor
        assert second["revision"] == first["revision"] == 1
        assert read_historical_owner_flow(session, first["flow_id"]) == first
        assert read_historical_owner_flow(session, second["flow_id"]) == second
        assert first["owned_occurrences"][0]["ordinal"] == "0"
        assert second["owned_occurrences"][0]["ordinal"] == "1"
        for flow in (first, second):
            assert flow["account_scope"]["status"] == "authoritative"
            assert flow["portfolio_scope"]["status"] == flow["cash_coverage"] == "unknown"
        for model in (
            HistoricalOwnerFlow,
            HistoricalOwnerFlowOccurrence,
            HistoricalOwnerFlowRevision,
            HistoricalOwnerFlowApply,
        ):
            assert count(session, model) == 2
        assert (
            count(session, ReportingMonth)
            == count(session, ExternalFlow)
            == count(session, CashBoundaryCoverage)
            == 0
        )


@pytest.mark.parametrize("ordinal", [0, 1])
def test_same_signature_row_cohort_is_still_ambiguous_and_cannot_create_money(database, ordinal):
    with database.session_factory() as session:
        intent = source(session, extra_amounts=("12.34",))
        intent = intent.model_copy(
            update={"seed": intent.seed.model_copy(update={"ordinal": ordinal})}
        )
        intent = attest(session, intent)
        plan = preview_historical_owner_flow(session, intent)
        assert "same_report_multiplicity" in plan["blockers"]
        assert len(plan["evidence"]["occurrences"]) == 2
        with pytest.raises(MyBrokerError, match="same_report_multiplicity"):
            apply_historical_owner_flow(
                session,
                intent,
                confirmation_digest=plan["confirmation_digest"],
                request_id="ambiguous",
            )
        for model in (
            HistoricalOwnerFlow,
            HistoricalOwnerFlowOccurrence,
            HistoricalOwnerFlowRevision,
            HistoricalOwnerFlowApply,
        ):
            assert count(session, model) == 0


@pytest.mark.parametrize("revoke", [False, True])
def test_same_signature_existing_owner_blocks_fresh_create_even_after_revoke(database, revoke):
    with database.session_factory() as session:
        intent = source(session)
        first = accept(session, attest(session, intent))["readback"]
        if revoke:
            withdrawal = OwnerFlowIntent(
                operation="revoke",
                flow_id=first["flow_id"],
                expected_revision=first["revision"],
                reason_code="attestation_withdrawn",
            )
            first = accept(session, withdrawal, "revoke")["readback"]
        fresh = attest(session, intent)
        plan = preview_historical_owner_flow(session, fresh)
        assert "existing_event_reconciliation_required" in plan["blockers"]
        assert "occurrence_already_owned" in plan["blockers"]
        with pytest.raises(MyBrokerError, match="occurrence_already_owned"):
            apply_historical_owner_flow(
                session,
                fresh,
                confirmation_digest=plan["confirmation_digest"],
                request_id="competing-owner",
            )
        assert read_historical_owner_flow(session, first["flow_id"]) == first
        assert (
            count(session, HistoricalOwnerFlow)
            == count(session, HistoricalOwnerFlowOccurrence)
            == 1
        )
        assert (
            count(session, HistoricalOwnerFlowApply)
            == count(session, HistoricalOwnerFlowRevision)
            == (2 if revoke else 1)
        )
