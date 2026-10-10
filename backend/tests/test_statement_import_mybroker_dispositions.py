"""Synthetic acceptance of the frozen document-scoped archived-instrument contract."""

import copy
import json
import sqlite3
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from test_statement_import_mybroker import (
    FILENAME,
    ISIN,
    apply,
    fixture,
    include_source_account,
    preview,
)
from test_statement_import_mybroker import database as database

from hermes_finance.domain import PerformanceScope
from hermes_finance.domain.historical_endpoints import EndpointIntent
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    BrokerIdentityMapping,
    ClassNoCrossingCoverage,
    ExecutedTrade,
    Instrument,
    InvestmentCashFlow,
    MyBrokerDispositionApply,
    MyBrokerDispositionChange,
    MyBrokerDispositionRevision,
    MyBrokerDispositionSet,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import confirm_mapping
from hermes_finance.services.class_endpoint_eligibility import _facts
from hermes_finance.services.executed_trades import apply_executed_trades, preview_executed_trades
from hermes_finance.services.historical_endpoints import preview_historical_endpoint
from hermes_finance.services.mybroker_dispositions import (
    REASON,
    apply_lifecycle,
    impact,
    lifecycle_preview,
)
from hermes_finance.services.mybroker_import import (
    apply_mybroker,
    preview_mybroker,
    read_mybroker_import,
)
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.portfolio_xirr import xirr_for_interval
from hermes_finance.services.source_cash_coverage import inventory
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError

SKIP = "RU000A000001"
A, B = date(2030, 1, 1), date(2030, 1, 31)


def mixed_xml(*, trades=True, unsupported=False):
    root = ET.fromstring(fixture(unsupported=unsupported))
    row = root.find(".//{MyBroker}Details[@ISIN1]")
    second = copy.deepcopy(row)
    second.set("ISIN1", SKIP)
    for parent in root.iter():
        if row in list(parent):
            parent.append(second)
            break
    trade = root.find(".//{MyBroker}Details[@isin_reg]")
    if trades:
        second = copy.deepcopy(trade)
        second.set("isin_reg", SKIP)
        second.set("trade_no", "10000000002\r\n2000000002")
        for parent in root.iter():
            if trade in list(parent):
                parent.append(second)
                break
        money = root.find(".//{MyBroker}rn")
        second = copy.deepcopy(money)
        second.find(".//{MyBroker}comment").set("comment", "Расчеты по сделке 10000000002")
        for parent in root.iter():
            if money in list(parent):
                parent.append(second)
                break
    else:
        for parent in root.iter():
            for child in list(parent):
                if child.tag == "{MyBroker}Details" and "isin_reg" in child.attrib:
                    parent.remove(child)
                if child.tag == "{MyBroker}rn":
                    parent.remove(child)
    return ET.tostring(root, encoding="utf-8")


def inspect(session, xml, filename=FILENAME):
    return preview_mybroker(
        session, document=xml, filename=filename, skipped_isins=(SKIP,), owner_reviewed=True
    )


def accept(session, xml, reviewed=None, request="synthetic-source", filename=FILENAME):
    reviewed = reviewed or inspect(session, xml, filename)
    return apply_mybroker(
        session,
        document=xml,
        filename=filename,
        confirmation_digest=reviewed["confirmation_digest"],
        confirmed_range=(reviewed["document"]["covered_from"], reviewed["document"]["covered_to"]),
        confirmed_mappings=reviewed["mappings"],
        skipped_isins=(SKIP,),
        owner_reviewed=True,
        request_id=request,
    )


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_explicit_skip_preserves_whole_evidence_without_catalogue_or_financial_writes(database):
    xml = mixed_xml(unsupported=True)
    with database.session_factory() as session:
        assert not preview(session, xml)["can_apply"]
        with pytest.raises(MyBrokerError, match="skip_owner_review_required"):
            preview_mybroker(session, document=xml, filename=FILENAME, skipped_isins=(SKIP,))
        reviewed = inspect(session, xml)
        assert reviewed["can_apply"] and reviewed["counts"] == {
            "mapped": 1,
            "skipped": 1,
            "unsupported": 1,
        }
        before = (count(session, Instrument), count(session, BrokerIdentityMapping))
        saved = accept(session, xml, reviewed)
        fetched = read_mybroker_import(session, saved["import_id"])
        assert fetched == {k: v for k, v in saved.items() if k != "duplicate"}
        assert fetched["document"] == reviewed["document"]
        assert fetched["document"]["document_sha256"] == digest_bytes(xml)
        assert (
            len(fetched["document"]["positions"])
            == len(fetched["document"]["trades"])
            == len(fetched["document"]["money"])
            == 2
        )
        assert fetched["document"]["parser"] == "mybroker-s1-v2"
        assert fetched["mappings"] == reviewed["mappings"]
        assert fetched["instrument_choices"] == reviewed["instrument_choices"]
        assert fetched["counts"] == reviewed["counts"]
        disposition = fetched["instrument_dispositions"][0]
        assert (
            disposition["effective_state"] == "accepted" and disposition["owner_reviewed"] is True
        )
        assert len(disposition["occurrences"]) == 3
        assert before == (count(session, Instrument), count(session, BrokerIdentityMapping))
        for model in (ExecutedTrade, InvestmentCashFlow, PositionSnapshot, ReportingMonth):
            assert count(session, model) == 0
        source = session.get(MyBrokerImport, saved["import_id"])
        assert "<" not in source.normalized_json and "Synthetic name" not in source.normalized_json


@pytest.mark.parametrize("repo_skipped", [False, True])
def test_combined_b_repo_and_archived_skip_preserve_both_financial_guards(database, repo_skipped):
    from test_statement_import_historical_owner_flows import attest
    from test_statement_import_mybroker import repo_fixture

    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.services.historical_owner_flows import preview_historical_owner_flow

    root = ET.fromstring(mixed_xml())
    # Select the trade collection explicitly; position collections use the same tag.
    collection = root.find(
        "{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/{MyBroker}Details_Collection"
    )
    for row in ET.fromstring(repo_fixture(pair=True, duplicate=True)).findall(
        ".//{MyBroker}Details[@trade_no]"
    ):
        if repo_skipped:
            row.set("isin_reg", SKIP)
        collection.append(row)
    raw = ET.tostring(root, encoding="utf-8")
    with database.session_factory() as session:
        reviewed = inspect(session, raw)
        assert reviewed["can_apply"]
        assert {"repo_semantics_unsupported", "trade_ids_incomplete"} <= set(reviewed["blockers"])
        saved = accept(session, raw, reviewed)
        fetched = read_mybroker_import(session, saved["import_id"])
        assert fetched["document"] == reviewed["document"]
        assert fetched["document"]["document_sha256"] == digest_bytes(raw)
        repo = [t for t in fetched["document"]["trades"] if t["repo_observed"]]
        assert len(repo) == 3
        assert all(t["identity"] is None and t["cash_legs"] == [] for t in repo)
        assert fetched["instrument_dispositions"][0]["effective_state"] == "accepted"
        assert accept(session, raw, request="synthetic-reimport")["duplicate"]
        account_id = next(m["hermes_id"] for m in fetched["mappings"] if m["kind"] == "account")
        intent = attest(
            session,
            OwnerFlowIntent(
                account_id=account_id, seed={"import_id": saved["import_id"], "ordinal": 0}
            ),
        )
        owner_flow = preview_historical_owner_flow(session, intent)
        assert not owner_flow["can_apply"]
        assert {REASON, "repo_semantics_unsupported", "trade_ids_incomplete"} <= set(
            owner_flow["blockers"]
        )
        for model in (ExecutedTrade, InvestmentCashFlow, PositionSnapshot, ReportingMonth):
            assert count(session, model) == 0


def digest_bytes(raw):
    from hashlib import sha256

    return sha256(raw).hexdigest()


def test_undecided_account_and_invalid_decisions_remain_blocked(database):
    with database.session_factory() as session:
        root = ET.fromstring(mixed_xml())
        root.find(".//{MyBroker}Details[@ISIN1]").set("acc_code", "7654321-000")
        p = inspect(session, ET.tostring(root, encoding="utf-8"))
        assert (
            not p["can_apply"]
            and {"kind": "account", "identity": "7654321-000"} in p["missing_mappings"]
        )
        for skips in ((SKIP, SKIP), ("RU000A999999",)):
            with pytest.raises(MyBrokerError, match="instrument_decision_invalid"):
                preview_mybroker(
                    session,
                    document=mixed_xml(),
                    filename=FILENAME,
                    skipped_isins=skips,
                    owner_reviewed=True,
                )


def test_exact_receipt_duplicate_changed_range_choices_and_plain_s1_corrections(database):
    xml = mixed_xml()
    with database.session_factory() as session:
        p = inspect(session, xml)
        saved = accept(session, xml, p)
        assert accept(session, xml, p)["duplicate"]
        # A fresh panel starts without local decisions, then reviews the exact
        # persisted choices via GET and binds them to a new Preview/request.
        fresh = preview(session, xml)
        assert fresh["already_imported"] == saved["import_id"] and not fresh["can_apply"]
        recorded = read_mybroker_import(session, fresh["already_imported"])
        skips = tuple(i["isin"] for i in recorded["instrument_choices"] if i["choice"] == "skip")
        replay = preview_mybroker(
            session, document=xml, filename=FILENAME, skipped_isins=skips, owner_reviewed=True
        )
        assert replay["can_apply"] and replay["document"] == recorded["document"]
        repeated = accept(session, xml, replay, request="synthetic-fresh")
        assert repeated["duplicate"] and repeated["import_id"] == saved["import_id"]
        assert read_mybroker_import(session, repeated["import_id"]) == recorded
        assert (
            count(session, MyBrokerImport) == 1 and count(session, MyBrokerDispositionRevision) == 1
        )
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            accept(session, xml, p, filename="Брокерский 1234567 (01.01.30-28.02.30).xml")
        changed = preview(session, xml)
        assert "instrument_disposition_reconciliation_required" in changed["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, changed)
        raw = fixture()
        apply(session, raw, preview(session, raw))
        retrospective = preview_mybroker(
            session, document=raw, filename=FILENAME, skipped_isins=(ISIN,), owner_reviewed=True
        )
        assert "instrument_disposition_reconciliation_required" in retrospective["conflicts"]


def test_skipped_trade_cannot_gain_authority_from_overlapping_mapped_occurrence(database):
    xml = mixed_xml()
    with database.session_factory() as session:
        saved = accept(session, xml)
        mapped_identity = next(
            t["identity"] for t in saved["document"]["trades"] if t["core"]["isin"] == ISIN
        )
        skipped_identity = next(
            t["identity"] for t in saved["document"]["trades"] if t["core"]["isin"] == SKIP
        )
        mapped = preview_executed_trades(session, [mapped_identity])
        assert mapped["can_apply"]
        apply_executed_trades(
            session,
            identities=[mapped_identity],
            confirmation_digest=mapped["confirmation_digest"],
            request_id="synthetic-mapped-trade",
        )
        assert (
            REASON
            in preview_executed_trades(session, [skipped_identity])["candidates"][0]["conflicts"]
        )
        from hermes_finance.services.instruments import create_instrument

        instrument = create_instrument(
            session, name="Synthetic archived mapping review", instrument_type="stock", isin=SKIP
        )
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="instrument",
            provider_identity=SKIP,
            hermes_target_id=instrument.id,
            observed_isin=SKIP,
        )
        raw = xml.replace(b"Synthetic name never retained", b"Synthetic changed ignored name")
        changed = preview(session, raw)
        assert "instrument_disposition_reconciliation_required" in changed["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, raw, changed)
        assert count(session, MyBrokerImport) == 1
        # Defensive readers also reject mixed evidence imported by an older or
        # unsupported writer. This is a fabricated persistence corruption probe.
        original = session.get(MyBrokerImport, saved["import_id"])
        session.add(
            MyBrokerImport(
                document_sha256=changed["document"]["document_sha256"],
                covered_from=original.covered_from,
                covered_to=original.covered_to,
                parser_version=original.parser_version,
                confirmation_digest=changed["confirmation_digest"],
                normalized_json=json.dumps(changed["document"]),
                mappings_json=json.dumps(changed["mappings"]),
                accepted_at=datetime.now(UTC),
            )
        )
        session.commit()
        candidate = preview_executed_trades(session, [skipped_identity])
        assert not candidate["can_apply"] and REASON in candidate["candidates"][0]["conflicts"]
        assert count(session, ExecutedTrade) == 1
        account = next(b["hermes_id"] for b in saved["mappings"] if b["kind"] == "account")
        cash = inventory(session, account, A, B)
        skipped_cash = next(
            m for m in cash["money_dispositions"] if m["row"].get("primary_id") == "10000000002"
        )
        assert skipped_cash["disposition"] == "unresolved"
        assert REASON in cash["blockers"]


def test_settled_position_carry_forward_blocks_all_same_account_dates_but_not_other_account(
    database,
):
    xml = mixed_xml(trades=False)
    with database.session_factory() as session:
        account = include_source_account(session)
        saved = accept(session, xml)
        for start, end in [
            (A, B),
            (date(2029, 1, 1), date(2029, 2, 1)),
            (date(2035, 1, 1), date(2035, 2, 1)),
        ]:
            facts = _facts(session, "stock", start, end)
            assert REASON in facts["reason_codes"]
            for reader in (xirr_for_interval, twrr_for_interval):
                result = reader(
                    session,
                    scope=PerformanceScope.ACCOUNT,
                    account_id=account,
                    start_date=start,
                    end_date=end,
                )
                assert REASON in result.reason_codes and not result.is_available
        other = create_account(session, name="Synthetic disjoint", account_type="brokerage")
        assert impact(session, (other.id,)) == []
        result = xirr_for_interval(
            session, scope=PerformanceScope.ACCOUNT, account_id=other.id, start_date=A, end_date=B
        )
        assert REASON not in result.reason_codes
        endpoint = preview_historical_endpoint(
            session,
            EndpointIntent(
                account_id=account, valuation_date=B, source_import_id=saved["import_id"]
            ),
        )
        assert REASON in endpoint["blockers"] and not endpoint["can_apply"]
        assert all(p["instrument_id"] is not None for p in endpoint["evidence"]["positions"])
        assert len(endpoint["evidence"]["positions"]) == 1
        source = read_mybroker_import(session, saved["import_id"])
        assert source["instrument_dispositions"][0]["effective_state"] == "accepted"


def test_preexisting_complete_class_coverage_refuses_skip_even_outside_report_interval(database):
    with database.session_factory() as session:
        include_source_account(session)
        session.add(
            ClassNoCrossingCoverage(
                asset_class="stock",
                covered_from=date(2035, 1, 1),
                covered_to=date(2035, 2, 1),
                coverage_state="complete",
                revision=1,
                material_signature="a" * 64,
                provenance_kind="owner_attestation",
            )
        )
        session.commit()
        reviewed = inspect(session, mixed_xml(trades=False))
        assert (
            not reviewed["can_apply"]
            and "accepted_class_coverage_requires_reconciliation" in reviewed["conflicts"]
        )
        assert count(session, MyBrokerImport) == 0


def test_revoke_reaffirm_aba_and_exact_receipt_keep_permanent_exclusions(database):
    with database.session_factory() as session:
        saved = accept(session, mixed_xml())
        import_id = saved["import_id"]
        intent = dict(import_id=import_id, isin=SKIP, operation="revoke", expected_revision=1)
        view = lifecycle_preview(session, **intent)
        receipt = apply_lifecycle(
            session,
            **intent,
            confirmation_digest=view["confirmation_digest"],
            request_id="synthetic-revoke",
        )
        assert receipt["dispositions"][0]["effective_state"] == "revoked"
        assert impact(session, [saved["mappings"][0]["hermes_id"]])
        intent2 = dict(import_id=import_id, isin=SKIP, operation="reaffirm", expected_revision=2)
        view = lifecycle_preview(session, **intent2)
        applied = apply_lifecycle(
            session,
            **intent2,
            confirmation_digest=view["confirmation_digest"],
            request_id="synthetic-reaffirm",
        )
        assert applied["dispositions"][0]["effective_state"] == "accepted"
        mapping_id = next(b["mapping_id"] for b in saved["mappings"] if b["kind"] == "account")
        session.execute(
            text(
                "UPDATE broker_identity_mappings SET status='revoked', revoked_at=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": mapping_id},
        )
        session.execute(
            text(
                "UPDATE broker_identity_mappings SET status='effective', revoked_at=NULL WHERE id=:id"
            ),
            {"id": mapping_id},
        )
        session.commit()
        current = read_mybroker_import(session, import_id)["instrument_dispositions"][0]
        assert current["effective_state"] == "retired" and current["revision"] == 4
        replay = apply_lifecycle(
            session,
            **intent,
            confirmation_digest=receipt_confirmation(session, "synthetic-revoke"),
            request_id="synthetic-revoke",
        )
        assert replay["committed_revision_ids"] == receipt["committed_revision_ids"]
        assert replay["dispositions"][0]["effective_state"] == "retired"
        assert count(session, MyBrokerDispositionChange) == 4
        stale = lifecycle_preview(session, **intent2)
        assert not stale["can_apply"]


def receipt_confirmation(session, key):
    return session.get(MyBrokerDispositionApply, key).confirmation_digest


def test_atomic_failure_rolls_back_source_dispositions_and_receipt(database, monkeypatch):
    from hermes_finance.services import mybroker_import

    with database.session_factory() as session:
        xml = mixed_xml()
        p = inspect(session, xml)

        def fail(*args, **kwargs):
            raise RuntimeError("synthetic injected failure")

        monkeypatch.setattr(mybroker_import, "initial_accept", fail)
        with pytest.raises(RuntimeError, match="synthetic injected"):
            accept(session, xml, p)
        for model in (
            MyBrokerImport,
            MyBrokerDispositionSet,
            MyBrokerDispositionRevision,
            MyBrokerDispositionApply,
        ):
            assert count(session, model) == 0


def test_stale_mapping_preview_fails_atomically_and_history_is_append_only(database):
    with database.session_factory() as session:
        xml = mixed_xml()
        p = inspect(session, xml)
        mapping = session.get(BrokerIdentityMapping, p["mappings"][0]["mapping_id"])
        mapping.status = "revoked"
        mapping.revoked_at = datetime.now(UTC)
        session.commit()
        with pytest.raises(MyBrokerError, match="preview_stale"):
            accept(session, xml, p)
        mapping.status = "effective"
        mapping.revoked_at = None
        session.commit()
        saved = accept(session, xml)
        for table in (
            "mybroker_disposition_sets",
            "mybroker_disposition_revisions",
            "mybroker_disposition_applies",
            "mybroker_disposition_changes",
        ):
            if table.endswith("changes"):
                mapping.status = "revoked"
                mapping.revoked_at = datetime.now(UTC)
                session.commit()
            with pytest.raises(IntegrityError, match="append-only"):
                session.execute(text(f"DELETE FROM {table}"))
            session.rollback()
        assert (
            read_mybroker_import(session, saved["import_id"])["instrument_dispositions"][0][
                "effective_state"
            ]
            == "retired"
        )


def test_http_review_apply_independent_get_and_strict_lifecycle(database):
    with TestClient(create_app(database=database)) as client:
        files = {"file": (FILENAME, mixed_xml(), "application/xml")}
        decisions = {"skipped_isins": [SKIP], "owner_reviewed": True}
        p = client.post(
            "/api/mybroker-import/preview", files=files, data={"decisions": json.dumps(decisions)}
        )
        assert p.status_code == 200, p.text
        p = p.json()
        confirmation = {
            **decisions,
            "confirmation_digest": p["confirmation_digest"],
            "covered_from": p["document"]["covered_from"],
            "covered_to": p["document"]["covered_to"],
            "mappings": p["mappings"],
            "request_id": "synthetic-http",
        }
        saved = client.post(
            "/api/mybroker-import/apply",
            files=files,
            data={"confirmation": json.dumps(confirmation)},
        )
        assert saved.status_code == 200, saved.text
        fetched = client.get(f"/api/mybroker-import/{saved.json()['import_id']}").json()
        assert fetched["document"] == p["document"] and fetched["counts"] == p["counts"]
        intent = {
            "import_id": fetched["import_id"],
            "isin": SKIP,
            "operation": "revoke",
            "expected_revision": 1,
        }
        p = client.post("/api/mybroker-import/dispositions/preview", json=intent).json()
        result = client.post(
            "/api/mybroker-import/dispositions/apply",
            json={
                **intent,
                "confirmation_digest": p["confirmation_digest"],
                "request_id": "synthetic-http-revoke",
            },
        )
        assert (
            result.status_code == 200
            and result.json()["dispositions"][0]["effective_state"] == "revoked"
        )
        assert (
            client.post(
                "/api/mybroker-import/dispositions/preview", json={**intent, "operation": "map"}
            ).status_code
            == 422
        )
        bad = client.post(
            "/api/mybroker-import/preview",
            files=files,
            data={"decisions": json.dumps({**decisions, "raw_xml": "forbidden"})},
        )
        assert bad.status_code == 422


def test_empty_migration_append_only_and_populated_downgrade_refusal(tmp_path):
    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-skip-migration.db"
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        for table in (
            "mybroker_disposition_sets",
            "mybroker_disposition_revisions",
            "mybroker_disposition_applies",
            "mybroker_disposition_changes",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'skip_change_%'"
            ).fetchone()[0]
            == 9
        )
    result = run_alembic(path, "downgrade", "0053_historical_portfolio_flows")
    assert result.returncode == 0, result.stderr
    assert run_alembic(path, "upgrade", "head").returncode == 0
    from hermes_finance.database import create_database

    db = create_database(path)
    from hermes_finance.services.instruments import create_instrument

    with db.session_factory() as session:
        account = create_account(session, name="Synthetic migrated", account_type="brokerage")
        instrument = create_instrument(
            session, name="Synthetic mapped", instrument_type="stock", isin=ISIN
        )
        for alias in ("1234567", "1234567-000"):
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=account.id,
            )
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="instrument",
            provider_identity=ISIN,
            hermes_target_id=instrument.id,
            observed_isin=ISIN,
        )
        saved = accept(session, mixed_xml())
        assert saved["instrument_dispositions"][0]["effective_state"] == "accepted"
        with pytest.raises(IntegrityError, match="append-only"):
            session.execute(text("DELETE FROM mybroker_disposition_revisions"))
        session.rollback()
    db.engine.dispose()
    result = run_alembic(path, "downgrade", "0053_historical_portfolio_flows")
    assert result.returncode != 0 and "cannot discard reviewed source exclusions" in result.stderr


def test_mapped_to_skip_and_adjacent_position_support_require_reconciliation(database):
    from test_statement_import_mybroker_endpoints import endpoint_xml, positions_only

    with database.session_factory() as session:
        raw = fixture()
        apply(session, raw, preview(session, raw))
        changed = raw.replace(b"Synthetic name never retained", b"Synthetic new ignored name")
        p = preview_mybroker(
            session, document=changed, filename=FILENAME, skipped_isins=(ISIN,), owner_reviewed=True
        )
        assert (
            not p["can_apply"]
            and "instrument_disposition_reconciliation_required" in p["conflicts"]
        )
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply_mybroker(
                session,
                document=changed,
                filename=FILENAME,
                confirmation_digest=p["confirmation_digest"],
                confirmed_range=(p["document"]["covered_from"], p["document"]["covered_to"]),
                confirmed_mappings=p["mappings"],
                skipped_isins=(ISIN,),
                owner_reviewed=True,
                request_id="synthetic-refused",
            )
        raw = positions_only(endpoint_xml())
        apply(session, raw, preview(session, raw))
        filename = "Брокерский 1234567 (01.02.30-28.02.30).xml"
        p = preview_mybroker(
            session,
            document=raw.replace(b"1000.00", b"1100.00"),
            filename=filename,
            skipped_isins=(ISIN,),
            owner_reviewed=True,
        )
        assert "instrument_disposition_reconciliation_required" in p["conflicts"]
        assert count(session, MyBrokerDispositionRevision) == 0


def test_concurrent_skip_apply_keeps_one_source_revision_and_exact_receipt(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    xml = mixed_xml()
    with database.session_factory() as session:
        p = inspect(session, xml)
    barrier = Barrier(2)

    def attempt(_):
        with database.session_factory() as session:
            barrier.wait(timeout=10)
            return accept(session, xml, p)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, range(2)))
    assert {r["import_id"] for r in results} == {1}
    assert sorted(r["duplicate"] for r in results) == [False, True]
    with database.session_factory() as session:
        assert (
            count(session, MyBrokerImport)
            == count(session, MyBrokerDispositionRevision)
            == count(session, MyBrokerDispositionApply)
            == 1
        )


def test_supported_backup_recovery_preserves_retirement_receipts_and_full_source(database):
    from hermes_finance.services.backups import create_backup, restore_backup

    with database.session_factory() as session:
        saved = accept(session, mixed_xml())
        mapping = session.get(BrokerIdentityMapping, saved["mappings"][0]["mapping_id"])
        mapping.status, mapping.revoked_at = "revoked", datetime.now(UTC)
        session.commit()
        mapping.status, mapping.revoked_at = "effective", None
        session.commit()
        retired = read_mybroker_import(session, saved["import_id"])
        assert retired["instrument_dispositions"][0]["effective_state"] == "retired"
    backup = create_backup(database)
    with database.session_factory() as session:
        intent = dict(
            import_id=saved["import_id"], isin=SKIP, operation="reaffirm", expected_revision=2
        )
        p = lifecycle_preview(session, **intent)
        renewed = apply_lifecycle(
            session,
            **intent,
            confirmation_digest=p["confirmation_digest"],
            request_id="synthetic-after-backup",
        )
        assert renewed["dispositions"][0]["revision"] == 3
    restore_backup(database, backup.id)
    with database.session_factory() as session:
        assert read_mybroker_import(session, saved["import_id"]) == retired
        assert count(session, MyBrokerDispositionApply) == 1
        replay = accept(
            session,
            mixed_xml(),
            request="synthetic-source",
            reviewed={
                "confirmation_digest": saved["confirmation_digest"],
                "document": saved["document"],
                "mappings": saved["mappings"],
            },
        )
        assert replay["instrument_dispositions"][0]["effective_state"] == "retired"
        assert replay["committed_revision_ids"] == [
            saved["instrument_dispositions"][0]["revision_id"]
        ]


def test_independently_evidenced_disjoint_account_xirr_stays_available(database):
    from test_historical_source_xirr import accept_inputs, prepare, result

    with database.session_factory() as session:
        prepared = prepare(session, other=True)
        accept_inputs(session, prepared)
        before = result(session, prepared[0])
        assert before.is_available
        accept(session, mixed_xml(trades=False))
        after = result(session, prepared[0])
        assert after == before and after.is_available
        assert impact(session, (prepared[0],)) == []


@pytest.mark.parametrize("membership", ["missing", "included", "gap", "excluded"])
@pytest.mark.parametrize("h1", [False, True])
def test_exclusion_diagnostic_survives_missing_membership_h1_h2_through_public_reads(
    database, membership, h1
):
    from test_historical_source_xirr import A as start
    from test_historical_source_xirr import B as end
    from test_historical_source_xirr import accept_inputs, prepare

    from hermes_finance.persistence import Account, AccountPerformanceScopeMembership

    with database.session_factory() as session:
        account_id = session.scalar(select(Account.id))
        if h1:
            prepared = prepare(session)
            # H1 identities select the historical path, with no H2 cash authority.
            accept_inputs(session, prepared, coverage=False)
        rows = list(session.scalars(select(AccountPerformanceScopeMembership)))
        for row in rows:
            session.delete(row)
        if membership != "missing":
            session.add(
                AccountPerformanceScopeMembership(
                    account_id=account_id,
                    effective_from=start if membership != "gap" else end,
                    effective_to=end,
                    include_in_returns=membership != "excluded",
                )
            )
        session.commit()
        accept(session, mixed_xml(trades=False))
        other = create_account(session, name="Synthetic unrelated", account_type="brokerage")
        other_id = other.id

    with TestClient(create_app(database=database)) as client:
        for scope, identity in (
            ("account", account_id),
            ("portfolio", None),
            ("account", other_id),
        ):
            params = {"start_date": start.isoformat(), "end_date": end.isoformat(), "scope": scope}
            if identity is not None:
                params["account_id"] = identity
            affected = identity == account_id or (scope == "portfolio" and membership != "excluded")
            for endpoint in ("availability", "xirr", "twrr", "readiness"):
                response = client.get(f"/api/performance/{endpoint}", params=params)
                assert response.status_code == 200, response.text
                body = response.json()
                metrics = (
                    [body["xirr"], body["twrr"]]
                    if endpoint in ("availability", "readiness")
                    else [body]
                )
                for metric in metrics:
                    assert metric["availability"] == "not_computable"
                    assert (REASON in metric["reason_codes"]) is affected
                    assert len(metric["reason_codes"]) == len(set(metric["reason_codes"]))
                    if endpoint != "availability":
                        assert metric["value"] is None and metric["quality"] == "unavailable"
                if endpoint == "readiness":
                    diagnostic = [d for d in body["diagnostics"] if d["key"] == "excluded_source"]
                    assert bool(diagnostic) is affected
                    if affected:
                        assert diagnostic[0]["affected_metrics"] == ["xirr", "twrr"]
                        assert diagnostic[0]["action"]["capability"] == "source_required"
                        assert len(body["diagnostics"]) > 1
                    assert SKIP not in response.text and '"import_id"' not in response.text


def test_skip_preserves_closed_facts_and_reopen_does_not_remove_blockers(database):
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        create_reporting_month,
        reopen_reporting_month,
    )

    with database.session_factory() as session:
        account = include_source_account(session)
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=B)
        instrument = session.scalar(select(Instrument))
        position = PositionSnapshot(
            reporting_month_id=month.id,
            account_id=account,
            instrument_id=instrument.id,
            quantity=10,
            historical_instrument_type="stock",
            market_value_kopecks=100000,
            average_cost_per_unit_kopecks=10000,
            market_price_per_unit_kopecks=10000,
            accrued_interest_kopecks=0,
            cost_basis_kopecks=100000,
            unrealized_result_kopecks=0,
            price_date=B,
        )
        session.add(position)
        session.commit()
        close_reporting_month(session, month.id)
        before = (
            month.status,
            position.quantity,
            position.market_value_kopecks,
            position.historical_instrument_type,
        )
        saved = accept(session, mixed_xml(trades=False))
        session.refresh(month)
        session.refresh(position)
        assert (
            month.status,
            position.quantity,
            position.market_value_kopecks,
            position.historical_instrument_type,
        ) == before
        assert (
            REASON
            in xirr_for_interval(
                session,
                scope=PerformanceScope.ACCOUNT,
                account_id=account,
                start_date=A,
                end_date=B,
            ).reason_codes
        )
        reopen_reporting_month(session, month.id)
        assert month.status == "draft" and position.market_value_kopecks == 100000
        assert (
            read_mybroker_import(session, saved["import_id"])["instrument_dispositions"][0][
                "effective_state"
            ]
            == "accepted"
        )
        assert (
            REASON
            in xirr_for_interval(
                session,
                scope=PerformanceScope.ACCOUNT,
                account_id=account,
                start_date=A,
                end_date=B,
            ).reason_codes
        )


def test_mapping_private_comment_is_never_copied_into_skip_ledger_or_readback(database):
    from hermes_finance.services.broker_identity_mappings import revoke_mapping

    with database.session_factory() as session:
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "account")
        )
        alias, target = mapping.provider_identity, mapping.hermes_target_id
        private_comment = "SYNTHETIC PRIVATE REVOKE COMMENT NOT SOURCE EVIDENCE"
        revoke_mapping(session, mapping.id, reason=private_comment)
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="account",
            provider_identity=alias,
            hermes_target_id=target,
        )
        saved = accept(session, mixed_xml())
        assert private_comment not in json.dumps(saved)
        assert all(
            private_comment not in r.evidence_json
            for r in session.scalars(select(MyBrokerDispositionRevision))
        )


def test_new_skip_invalidates_existing_h1_h2_h3_and_h0_discloses_only_structure(database):
    from test_historical_source_xirr import A as start
    from test_historical_source_xirr import B as end
    from test_historical_source_xirr import accept_inputs, portfolio_authority, prepare, result

    from hermes_finance.persistence import CashBoundaryCoverage, HistoricalEndpointRevision
    from hermes_finance.services.historical_endpoints import read_historical_endpoint
    from hermes_finance.services.historical_owner_flows import read_historical_owner_flow
    from hermes_finance.services.historical_portfolio_flows import read_historical_portfolio_flow
    from hermes_finance.services.historical_reconstruction import preview_historical_reconstruction
    from hermes_finance.services.source_cash_coverage import read_source_cash_coverage

    with database.session_factory() as session:
        prepared = prepare(session, amounts=("10.00",))
        flows = accept_inputs(session, prepared)
        portfolio_authority(session, flows)
        assert result(session, prepared[0]).is_available
        endpoint_keys = list(session.scalars(select(HistoricalEndpointRevision.endpoint_key)))
        coverage_id = session.scalar(select(CashBoundaryCoverage.id))
        saved = accept(session, mixed_xml(trades=False))
        for key in endpoint_keys:
            endpoint = read_historical_endpoint(session, key)
            assert endpoint["effective_state"] != "accepted" and REASON in endpoint["blockers"]
            assert endpoint["total_value_kopecks"] is None
        for reader in (read_historical_owner_flow, read_historical_portfolio_flow):
            flow = reader(session, flows[0]["flow_id"])
            assert flow["effective_state"] != "accepted" and REASON in flow["blockers"]
        coverage = read_source_cash_coverage(session, coverage_id)
        assert coverage["coverage_state"] == "unknown" and REASON in coverage["blockers"]
        actual = result(session, prepared[0])
        assert not actual.is_available and REASON in actual.reason_codes
        h0 = preview_historical_reconstruction(
            session, account_ids=[prepared[0]], requested_from=start, requested_to=end
        )
        encoded = json.dumps(h0)
        assert REASON in encoded and SKIP not in encoded and "10000000002" not in encoded
        assert read_mybroker_import(session, saved["import_id"])["document"]["positions"]


def test_consistent_overlap_and_later_quiet_report_never_expire_excluded_impact(database):
    with database.session_factory() as session:
        account = include_source_account(session)
        xml = mixed_xml()
        first = accept(session, xml)
        other = xml.replace(
            b"Synthetic name never retained", b"Synthetic corroborating ignored name"
        )
        second = accept(session, other, request="synthetic-overlap")
        assert first["import_id"] != second["import_id"]
        quiet = fixture(quiet=True)
        filename = "Брокерский 1234567 (01.02.30-28.02.30).xml"
        apply(session, quiet, preview(session, quiet, filename), filename)
        future = xirr_for_interval(
            session,
            scope=PerformanceScope.ACCOUNT,
            account_id=account,
            start_date=date(2035, 1, 1),
            end_date=date(2035, 2, 1),
        )
        assert not future.is_available and REASON in future.reason_codes
        assert len(impact(session, (account,))) == 2
        assert count(session, ExecutedTrade) == count(session, InvestmentCashFlow) == 0


def test_source_mutation_requires_reconciliation_and_source_aba_cannot_revive(database):
    with database.session_factory() as session:
        saved = accept(session, mixed_xml())
        source = session.get(MyBrokerImport, saved["import_id"])
        original = source.normalized_json
        changed = json.loads(original)
        changed["positions"][1]["actual_quantity"] = "999"
        session.execute(
            text("UPDATE mybroker_imports SET normalized_json=:document WHERE id=:id"),
            {"id": source.id, "document": json.dumps(changed)},
        )
        session.commit()
        invalid = read_mybroker_import(session, source.id)["instrument_dispositions"][0]
        assert invalid["effective_state"] == "invalid"
        p = lifecycle_preview(
            session, import_id=source.id, isin=SKIP, operation="reaffirm", expected_revision=2
        )
        assert (
            not p["can_apply"] and "instrument_disposition_reconciliation_required" in p["blockers"]
        )
        session.execute(
            text("UPDATE mybroker_imports SET normalized_json=:document WHERE id=:id"),
            {"id": source.id, "document": original},
        )
        session.commit()
        restored = read_mybroker_import(session, source.id)["instrument_dispositions"][0]
        assert restored["effective_state"] == "retired" and restored["revision"] == 2
        assert (
            restored["trade_identities"] == saved["instrument_dispositions"][0]["trade_identities"]
        )


def test_preparation_readback_exposes_current_exclusions_and_rejects_stale_coverage_token(database):
    from hermes_finance.services.cash_boundary_coverage import create_cash_boundary_coverage
    from hermes_finance.services.in_kind_boundary_coverage import create_in_kind_boundary_coverage

    with database.session_factory() as session:
        account = include_source_account(session)
        cash = create_cash_boundary_coverage(
            session, account_id=account, covered_from=A, covered_to=B
        )
        create_in_kind_boundary_coverage(session, account_id=account, covered_from=A, covered_to=B)
        cash_id = cash.id
    with TestClient(create_app(database=database)) as client:
        params = {"account_id": account, "start_date": A.isoformat(), "end_date": B.isoformat()}
        original = client.get("/api/performance/preparation", params=params)
        assert original.status_code == 200
        before = original.json()
        assert (
            before["cash_coverages"][0]["coverage_state"]
            == before["in_kind_coverages"][0]["coverage_state"]
            == "complete"
        )
        with database.session_factory() as session:
            accept(session, mixed_xml(trades=False))
        response = client.get("/api/performance/preparation", params=params)
        assert response.status_code == 200
        after = response.json()
        assert after["evidence_token"] != before["evidence_token"]
        for key in ("cash_coverages", "in_kind_coverages"):
            row = after[key][0]
            assert (
                row["coverage_state"] == "unknown" and row["recorded_coverage_state"] == "complete"
            )
            assert row["exclusion_blockers"] == [REASON]
        stale = client.patch(
            f"/api/cash-boundary-coverages/{cash_id}",
            json={"coverage_state": "unknown"},
            headers={"X-Performance-Evidence": before["evidence_token"]},
        )
        assert stale.status_code == 409


def test_skip_cannot_hide_quantity_conflict_with_closed_snapshot(database):
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        create_reporting_month,
    )

    with database.session_factory() as session:
        account = include_source_account(session)
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=B)
        instrument = session.scalar(select(Instrument))
        position = PositionSnapshot(
            reporting_month_id=month.id,
            account_id=account,
            instrument_id=instrument.id,
            quantity=9,
            average_cost_per_unit_kopecks=0,
            market_price_per_unit_kopecks=0,
            market_value_kopecks=0,
            cost_basis_kopecks=0,
            unrealized_result_kopecks=0,
            price_date=B,
        )
        session.add(position)
        session.commit()
        close_reporting_month(session, month.id)
        raw = fixture()
        p = preview_mybroker(
            session, document=raw, filename=FILENAME, skipped_isins=(ISIN,), owner_reviewed=True
        )
        assert "accepted_endpoint_quantity_conflict" in p["conflicts"] and not p["can_apply"]
        assert all(b["kind"] == "account" for b in p["mappings"])
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply_mybroker(
                session,
                document=raw,
                filename=FILENAME,
                confirmation_digest=p["confirmation_digest"],
                confirmed_range=(p["document"]["covered_from"], p["document"]["covered_to"]),
                confirmed_mappings=p["mappings"],
                skipped_isins=(ISIN,),
                owner_reviewed=True,
                request_id="synthetic-closed-conflict",
            )
        session.refresh(month)
        session.refresh(position)
        assert month.status == "closed" and position.quantity == 9
        assert count(session, MyBrokerImport) == count(session, MyBrokerDispositionRevision) == 0


# Skip-to-Map uses only fabricated accepted-source evidence and isolated databases.
def correction_targets(session, isins, *, fund=None):
    from hermes_finance.services.instruments import create_instrument

    for isin in isins:
        instrument = create_instrument(
            session,
            name="Synthetic correction target",
            isin=isin,
            instrument_type="fund" if isin == fund else "stock",
        )
        confirm_mapping(
            session,
            provider=PROVIDER,
            subject_kind="instrument",
            provider_identity=isin,
            hermes_target_id=instrument.id,
            observed_isin=isin,
        )


def correction_decisions(session, import_ids):
    from hermes_finance.persistence import MyBrokerCorrectionRevision
    from hermes_finance.services.mybroker_dispositions import original_dispositions

    result = []
    for import_id in import_ids:
        source = session.get(MyBrokerImport, import_id)
        for item in original_dispositions(session, source):
            mapping = session.scalar(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.provider == PROVIDER,
                    BrokerIdentityMapping.subject_kind == "instrument",
                    BrokerIdentityMapping.provider_identity == item["isin"],
                    BrokerIdentityMapping.status == "effective",
                )
            )
            current = session.scalar(
                select(MyBrokerCorrectionRevision)
                .where(
                    MyBrokerCorrectionRevision.import_id == import_id,
                    MyBrokerCorrectionRevision.isin == item["isin"],
                )
                .order_by(MyBrokerCorrectionRevision.revision.desc())
                .limit(1)
            )
            result.append(
                dict(
                    import_id=import_id,
                    document_sha256=source.document_sha256,
                    isin=item["isin"],
                    original_revision_id=item["history"][0]["revision_id"],
                    expected_revision=item["revision"],
                    expected_correction_revision=current.revision if current else 0,
                    mapping_id=mapping.id,
                    hermes_id=mapping.hermes_target_id,
                    reviewed_instrument_type=session.get(
                        Instrument, mapping.hermes_target_id
                    ).instrument_type,
                )
            )
    return result


def correction_accept(session, decisions, request="synthetic-correction"):
    from hermes_finance.services.mybroker_corrections import apply_corrections, preview_corrections

    reviewed = preview_corrections(session, decisions=decisions, owner_reviewed=True)
    assert reviewed["can_apply"], reviewed["blockers"]
    return apply_corrections(
        session,
        decisions=decisions,
        owner_reviewed=True,
        request_id=request,
        confirmation_digest=reviewed["confirmation_digest"],
    )


def correction_xml(isins):
    root = ET.fromstring(fixture())
    position = root.find(".//{MyBroker}Details[@ISIN1]")
    trade = root.find(".//{MyBroker}Details[@isin_reg]")
    money = root.find(".//{MyBroker}rn")
    for n, isin in enumerate(isins, 1):
        for row, attributes in (
            (position, {"ISIN1": isin}),
            (trade, {"isin_reg": isin, "trade_no": f"{10000000001 + n}\n{2000000001 + n}"}),
            (money, {}),
        ):
            extra = copy.deepcopy(row)
            extra.attrib.update(attributes)
            if row is money:
                extra.find(".//{MyBroker}comment").set(
                    "comment", f"Расчеты по сделке {10000000001 + n}"
                )
            for parent in root.iter():
                if row in list(parent):
                    parent.append(extra)
                    break
    return ET.tostring(root, encoding="utf-8")


def correction_source(session, isins, *, raw=None, request="synthetic-source-batch"):
    raw = raw or correction_xml(isins)
    p = preview_mybroker(
        session, document=raw, filename=FILENAME, skipped_isins=tuple(isins), owner_reviewed=True
    )
    assert p["can_apply"], p["conflicts"]
    return apply_mybroker(
        session,
        document=raw,
        filename=FILENAME,
        skipped_isins=tuple(isins),
        owner_reviewed=True,
        request_id=request,
        confirmation_digest=p["confirmation_digest"],
        confirmed_mappings=p["mappings"],
        confirmed_range=(p["document"]["covered_from"], p["document"]["covered_to"]),
    )


def test_correction_full_19_decisions_18_isins_overlap_and_independent_consumers(database):
    from hermes_finance.persistence import MyBrokerCorrectionRevision
    from hermes_finance.services.historical_reconstruction import preview_historical_reconstruction
    from hermes_finance.services.mybroker_corrections import read_correction_batch

    isins = [f"RU000A{i:06d}" for i in range(11, 29)]
    with database.session_factory() as session:
        account = include_source_account(session)
        first = correction_source(session, isins)
        second = correction_source(session, [isins[0]], request="synthetic-second")
        ids = [first["import_id"], second["import_id"]]
        original = [
            (s.normalized_json, s.mappings_json, s.document_sha256)
            for s in session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id))
        ]
        correction_targets(session, isins, fund=isins[-1])
        decisions = correction_decisions(session, ids)
        assert len(decisions) == 19 and len({d["isin"] for d in decisions}) == 18
        saved = correction_accept(session, decisions)
        assert len(saved["receipt"]["committed_revision_ids"]) == 19
        assert all(c["effective_state"] == "mapped" for c in saved["current_corrections"])
        assert read_correction_batch(session, "synthetic-correction") == saved
        assert original == [
            (s.normalized_json, s.mappings_json, s.document_sha256)
            for s in session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id))
        ]
        assert count(session, MyBrokerCorrectionRevision) == 19
        assert count(session, ExecutedTrade) == count(session, InvestmentCashFlow) == 0
        assert impact(session, [account]) == []
        reread = read_mybroker_import(session, first["import_id"])
        assert reread["document"] == first["document"] and reread["mappings"] == first["mappings"]
        assert (
            reread["counts"]["skipped"] == 0
            and len(reread["effective_mappings"]) == len(first["mappings"]) + 18
        )
        identity = next(
            t["identity"] for t in first["document"]["trades"] if t["core"]["isin"] == isins[0]
        )
        p = preview_executed_trades(session, [identity])
        assert p["can_apply"], p
        candidate = p["candidates"][0]
        assert len(candidate["evidence"]["cash_legs"]) == 1
        assert len(candidate["evidence"]["cash_legs"][0]["occurrences"]) == 2
        apply_executed_trades(
            session,
            identities=[identity],
            request_id="synthetic-promote",
            confirmation_digest=p["confirmation_digest"],
        )
        assert count(session, ExecutedTrade) == 1 and count(session, InvestmentCashFlow) == 0
        h0 = preview_historical_reconstruction(
            session, account_ids=[account], requested_from=A, requested_to=B
        )
        assert REASON not in str(h0) and h0["financial_apply_available"] is False
        h1 = preview_historical_endpoint(
            session,
            EndpointIntent(
                account_id=account, valuation_date=B, source_import_id=first["import_id"]
            ),
        )
        assert REASON not in h1["blockers"] and not h1["can_apply"]
        assert len(h1["evidence"]["positions"]) == 19
        h2 = inventory(session, account, A, B)
        assert REASON not in h2["blockers"] and h2["blockers"]
        for reader in (xirr_for_interval, twrr_for_interval):
            performance = reader(
                session,
                scope=PerformanceScope.ACCOUNT,
                account_id=account,
                start_date=A,
                end_date=B,
            )
            assert not performance.is_available and REASON not in performance.reason_codes
        # New exact reviewed intent is a revision no-op, including after S2 writes.
        again = correction_accept(session, correction_decisions(session, ids), "synthetic-noop")
        assert (
            again["receipt"]["committed_revision_ids"] == saved["receipt"]["committed_revision_ids"]
        )
        assert count(session, MyBrokerCorrectionRevision) == 19


def test_correction_overlap_partial_and_incompatible_fund_refuse_entire_batch(database):
    from hermes_finance.persistence import MyBrokerCorrectionApply, MyBrokerCorrectionRevision
    from hermes_finance.services.mybroker_corrections import apply_corrections, preview_corrections

    isins = ["RU000A000011", "RU000A000012"]
    with database.session_factory() as session:
        first = correction_source(session, isins)
        second = correction_source(session, [isins[0]], request="synthetic-second")
        correction_targets(session, isins, fund=isins[-1])
        decisions = correction_decisions(session, [first["import_id"], second["import_id"]])
        partial = preview_corrections(session, decisions=decisions[:-1], owner_reviewed=True)
        assert not partial["can_apply"] and "correction_overlap_incomplete" in partial["blockers"]
        decisions[1]["reviewed_instrument_type"] = "stock"
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        assert not p["can_apply"] and "correction_target_incompatible" in p["blockers"]
        with pytest.raises(MyBrokerError, match="correction_batch_blocked"):
            apply_corrections(
                session,
                decisions=decisions,
                owner_reviewed=True,
                request_id="synthetic-blocked",
                confirmation_digest=p["confirmation_digest"],
            )
        assert (
            count(session, MyBrokerCorrectionApply)
            == count(session, MyBrokerCorrectionRevision)
            == 0
        )


def test_correction_replay_aba_current_state_and_new_revision_never_revive_old_s2(database):
    from hermes_finance.persistence import MyBrokerCorrectionRevision
    from hermes_finance.services.executed_trades import read_executed_trades
    from hermes_finance.services.mybroker_corrections import (
        apply_corrections,
        preview_corrections,
        read_correction_batch,
    )

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        decisions = correction_decisions(session, [source["import_id"]])
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        args = dict(
            decisions=decisions,
            owner_reviewed=True,
            request_id="synthetic-replay",
            confirmation_digest=p["confirmation_digest"],
        )
        saved = apply_corrections(session, **args)
        identity = next(
            t["identity"] for t in source["document"]["trades"] if t["core"]["isin"] == SKIP
        )
        p2 = preview_executed_trades(session, [identity])
        apply_executed_trades(
            session,
            identities=[identity],
            request_id="synthetic-s2",
            confirmation_digest=p2["confirmation_digest"],
        )
        mapping_id = decisions[0]["mapping_id"]
        # Same-transaction SQL A->B->A still leaves a monotonic change history.
        session.execute(
            text(
                "UPDATE broker_identity_mappings SET status='revoked', revoked_at=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": mapping_id},
        )
        session.execute(
            text(
                "UPDATE broker_identity_mappings SET status='effective', revoked_at=NULL WHERE id=:id"
            ),
            {"id": mapping_id},
        )
        session.commit()
        stale = apply_corrections(session, **args)
        assert stale["receipt"] == saved["receipt"]
        assert stale["current_corrections"][0]["effective_state"] == "retired"
        assert count(session, MyBrokerCorrectionRevision) == 1
        assert read_correction_batch(session, "synthetic-replay") == stale
        assert REASON in read_executed_trades(session)["trades"][0]["conflicts"]
        with pytest.raises(MyBrokerError, match="idempotency_conflict"):
            apply_corrections(session, **{**args, "confirmation_digest": "0" * 64})
        fresh = correction_accept(
            session, correction_decisions(session, [source["import_id"]]), "synthetic-fresh-map"
        )
        assert fresh["current_corrections"][0]["revision"] == 2
        assert count(session, ExecutedTrade) == 1
        assert (
            "source_enrichment_not_accepted"
            in read_executed_trades(session)["trades"][0]["conflicts"]
        )
        # Original receipt remains immutable even after a later reviewed revision.
        assert read_correction_batch(session, "synthetic-replay")["receipt"] == saved["receipt"]


@pytest.mark.parametrize("operation", ["revoke", "reaffirm"])
def test_correction_predecessor_and_stale_revision_gates(database, operation):
    from hermes_finance.services.mybroker_corrections import preview_corrections

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        item = read_mybroker_import(session, source["import_id"])["instrument_dispositions"][0]
        intent = dict(
            import_id=source["import_id"],
            isin=SKIP,
            operation=operation,
            expected_revision=item["revision"],
        )
        p = lifecycle_preview(session, **intent)
        apply_lifecycle(
            session,
            **intent,
            request_id="synthetic-lifecycle",
            confirmation_digest=p["confirmation_digest"],
        )
        decisions = correction_decisions(session, [source["import_id"]])
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        assert not p["can_apply"] and "correction_predecessor_not_retired" in p["blockers"]
        decisions[0]["expected_revision"] -= 1
        assert (
            "disposition_revision_stale"
            in preview_corrections(session, decisions=decisions, owner_reviewed=True)["blockers"]
        )


def test_correction_stale_preview_and_atomic_rollback(database):
    from sqlalchemy import event

    from hermes_finance.persistence import MyBrokerCorrectionApply, MyBrokerCorrectionRevision
    from hermes_finance.services.mybroker_corrections import apply_corrections, preview_corrections

    with database.session_factory() as session:
        source = correction_source(session, [SKIP, "RU000A000012"])
        correction_targets(session, [SKIP, "RU000A000012"])
        decisions = correction_decisions(session, [source["import_id"]])
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        args = dict(
            decisions=decisions,
            owner_reviewed=True,
            request_id="synthetic-atomic",
            confirmation_digest=p["confirmation_digest"],
        )
        session.execute(
            text("UPDATE instruments SET is_active=0 WHERE id=:id"),
            {"id": decisions[0]["hermes_id"]},
        )
        session.commit()
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_corrections(session, **args)
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        seen = []

        def fail_second(_mapper, _connection, _row):
            seen.append(1)
            if len(seen) == 2:
                raise RuntimeError("synthetic second insert failure")

        event.listen(MyBrokerCorrectionRevision, "before_insert", fail_second)
        try:
            with pytest.raises(RuntimeError, match="second insert"):
                apply_corrections(
                    session, **{**args, "confirmation_digest": p["confirmation_digest"]}
                )
        finally:
            event.remove(MyBrokerCorrectionRevision, "before_insert", fail_second)
        assert (
            count(session, MyBrokerCorrectionApply)
            == count(session, MyBrokerCorrectionRevision)
            == 0
        )
        assert correction_accept(session, decisions)["receipt"]["committed_revision_ids"]


def test_correction_http_readback_and_sql_history_guards(database):
    from hermes_finance.services.mybroker_corrections import HISTORY

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        decisions = correction_decisions(session, [source["import_id"]])
    client = TestClient(create_app(database=database))
    intent = dict(decisions=decisions, owner_reviewed=True)
    p = client.post("/api/mybroker-import/corrections/preview", json=intent)
    assert p.status_code == 200 and p.json()["can_apply"]
    saved = client.post(
        "/api/mybroker-import/corrections/apply",
        json={
            **intent,
            "request_id": "synthetic-http",
            "confirmation_digest": p.json()["confirmation_digest"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert client.get("/api/mybroker-import/corrections/synthetic-http").json() == saved.json()
    assert (
        client.post(
            "/api/mybroker-import/corrections/preview", json={**intent, "owner_reviewed": False}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/mybroker-import/corrections/preview",
            json={**intent, "decisions": decisions + decisions},
        ).status_code
        == 409
    )
    with database.session_factory() as session:
        for model in HISTORY:
            for operation in (
                f"UPDATE {model.__tablename__} SET "
                + (
                    "id=id"
                    if model.__tablename__ != "mybroker_correction_applies"
                    else "request_id=request_id"
                ),
                f"DELETE FROM {model.__tablename__}",
            ):
                with pytest.raises(IntegrityError, match="append-only"):
                    session.execute(text(operation))
                session.rollback()


def test_correction_closed_refusal_and_reopen_preserve_financial_facts(database):
    from hermes_finance.services.mybroker_corrections import apply_corrections, preview_corrections
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        create_reporting_month,
        reopen_reporting_month,
    )

    with database.session_factory() as session:
        account = include_source_account(session)
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        decisions = correction_decisions(session, [source["import_id"]])
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=B)
        position = PositionSnapshot(
            reporting_month_id=month.id,
            account_id=account,
            instrument_id=decisions[0]["hermes_id"],
            quantity=9,
            average_cost_per_unit_kopecks=0,
            market_price_per_unit_kopecks=0,
            market_value_kopecks=0,
            cost_basis_kopecks=0,
            unrealized_result_kopecks=0,
            price_date=B,
        )
        session.add(position)
        session.commit()
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        close_reporting_month(session, month.id)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply_corrections(
                session,
                decisions=decisions,
                owner_reviewed=True,
                request_id="synthetic-closed",
                confirmation_digest=p["confirmation_digest"],
            )
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        assert "closed_reporting_month_requires_reopen" in p["blockers"]
        with pytest.raises(MyBrokerError, match="correction_batch_blocked"):
            apply_corrections(
                session,
                decisions=decisions,
                owner_reviewed=True,
                request_id="synthetic-closed",
                confirmation_digest=p["confirmation_digest"],
            )
        session.refresh(month)
        session.refresh(position)
        assert month.status == "closed" and position.quantity == 9
        reopen_reporting_month(session, month.id)
        correction_accept(session, decisions)
        session.refresh(position)
        assert position.quantity == 9


def test_correction_money_multiplicity_is_not_cross_file_dedup(database):
    from hermes_finance.services.mybroker_corrections import preview_corrections

    root = ET.fromstring(correction_xml([SKIP]))
    money = root.findall(".//{MyBroker}rn")[-1]
    for parent in root.iter():
        if money in list(parent):
            parent.append(copy.deepcopy(money))
            break
    with database.session_factory() as session:
        source = correction_source(session, [SKIP], raw=ET.tostring(root, encoding="utf-8"))
        correction_targets(session, [SKIP])
        p = preview_corrections(
            session,
            decisions=correction_decisions(session, [source["import_id"]]),
            owner_reviewed=True,
        )
        assert not p["can_apply"] and "correction_money_duplicate" in p["blockers"]


def test_correction_migration_parity_empty_and_populated_downgrade(tmp_path):
    from _migration_helpers import run_alembic

    from hermes_finance.database import create_database

    path = tmp_path / "synthetic-correction-migration.db"
    result = run_alembic(path, "upgrade", "head")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(path) as connection:
        for table in (
            "mybroker_correction_applies",
            "mybroker_correction_revisions",
            "mybroker_correction_changes",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        migration_sql = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND (name LIKE 'correction_change_%' OR name LIKE 'mybroker_correction_%') ORDER BY name"
        ).fetchall()
    assert len(migration_sql) == 18
    assert run_alembic(path, "downgrade", "0054_mybroker_dispositions").returncode == 0
    assert run_alembic(path, "upgrade", "head").returncode == 0
    db = create_database(path)
    try:
        with db.session_factory() as session:
            account = create_account(
                session, name="Synthetic migrated correction", account_type="brokerage"
            )
            from hermes_finance.services.instruments import create_instrument

            target = create_instrument(
                session, name="Synthetic original", instrument_type="stock", isin=ISIN
            )
            for alias in ("1234567", "1234567-000"):
                confirm_mapping(
                    session,
                    provider=PROVIDER,
                    subject_kind="account",
                    provider_identity=alias,
                    hermes_target_id=account.id,
                )
            confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="instrument",
                provider_identity=ISIN,
                hermes_target_id=target.id,
                observed_isin=ISIN,
            )
            source = correction_source(session, [SKIP])
            correction_targets(session, [SKIP])
            assert (
                correction_accept(session, correction_decisions(session, [source["import_id"]]))[
                    "current_corrections"
                ][0]["effective_state"]
                == "mapped"
            )
        from hermes_finance.persistence import Base

        metadata_path = tmp_path / "synthetic-correction-metadata.db"
        metadata_db = create_database(metadata_path)
        try:
            Base.metadata.create_all(metadata_db.engine)
            with sqlite3.connect(metadata_path) as connection:
                metadata_sql = connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND (name LIKE 'correction_change_%' OR name LIKE 'mybroker_correction_%') ORDER BY name"
                ).fetchall()
            assert metadata_sql == migration_sql
        finally:
            metadata_db.engine.dispose()
    finally:
        db.engine.dispose()
    result = run_alembic(path, "downgrade", "0054_mybroker_dispositions")
    assert result.returncode != 0 and "cannot discard reviewed source corrections" in result.stderr


def test_correction_concurrent_writer_rechecks_predecessor_under_reservation(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from hermes_finance.persistence import MyBrokerCorrectionApply, MyBrokerCorrectionRevision
    from hermes_finance.services.mybroker_corrections import apply_corrections, preview_corrections

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        decisions = correction_decisions(session, [source["import_id"]])
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
    barrier = Barrier(2)

    def writer(n):
        with database.session_factory() as session:
            barrier.wait(timeout=20)
            try:
                apply_corrections(
                    session,
                    decisions=decisions,
                    owner_reviewed=True,
                    request_id=f"synthetic-concurrent-{n}",
                    confirmation_digest=p["confirmation_digest"],
                )
                return "committed"
            except MyBrokerError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, [1, 2]))
    assert sorted(results) == ["committed", "preview_stale"]
    with database.session_factory() as session:
        assert (
            count(session, MyBrokerCorrectionApply)
            == count(session, MyBrokerCorrectionRevision)
            == 1
        )


@pytest.mark.parametrize("damage", ["source-range", "target-identity", "target-currency"])
def test_correction_invalid_source_or_target_never_lifts_exclusion(database, damage):
    from hermes_finance.services.mybroker_corrections import preview_corrections

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP], fund=SKIP)
        decisions = correction_decisions(session, [source["import_id"]])
        if damage == "source-range":
            session.execute(
                text("UPDATE mybroker_imports SET covered_to='2030-02-28' WHERE id=:id"),
                {"id": source["import_id"]},
            )
        elif damage == "target-identity":
            session.execute(
                text("UPDATE instruments SET isin='RU000A000099' WHERE id=:id"),
                {"id": decisions[0]["hermes_id"]},
            )
        else:
            session.execute(
                text("UPDATE instruments SET currency='USD' WHERE id=:id"),
                {"id": decisions[0]["hermes_id"]},
            )
        session.commit()
        p = preview_corrections(session, decisions=decisions, owner_reviewed=True)
        assert not p["can_apply"]
        assert (
            "source_integrity_or_version"
            if damage == "source-range"
            else "correction_target_incompatible"
        ) in p["blockers"]
        assert all(
            i["effective_state"] != "mapped"
            for i in read_mybroker_import(session, source["import_id"])["instrument_dispositions"]
        )


def test_correction_money_only_overlapping_support_conflict_refuses_batch(database):
    from hermes_finance.services.mybroker_corrections import preview_corrections

    with database.session_factory() as session:
        source = correction_source(session, [SKIP])
        root = ET.fromstring(correction_xml([SKIP]))
        for parent in root.iter():
            for child in list(parent):
                if child.tag == "{MyBroker}Details":
                    parent.remove(child)
        money = root.findall(".//{MyBroker}rn")
        for parent in root.iter():
            if money[0] in list(parent):
                parent.remove(money[0])
        money[-1].find(".//{MyBroker}p_code[@volume]").set("volume", "-999.00")
        correction_source(
            session, [], raw=ET.tostring(root, encoding="utf-8"), request="synthetic-money-only"
        )
        correction_targets(session, [SKIP])
        p = preview_corrections(
            session,
            decisions=correction_decisions(session, [source["import_id"]]),
            owner_reviewed=True,
        )
        assert not p["can_apply"] and "trade_material_conflict" in p["blockers"]


def test_correction_closed_non_cash_boundary_also_requires_reopen(database):
    from hermes_finance.persistence import InKindMovement
    from hermes_finance.services.mybroker_corrections import preview_corrections
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        create_reporting_month,
    )

    with database.session_factory() as session:
        account = include_source_account(session)
        source = correction_source(session, [SKIP])
        correction_targets(session, [SKIP])
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=B)
        movement = InKindMovement(
            reporting_month_id=month.id,
            event_date=B,
            destination_account_id=account,
            movement_kind="external_in",
            provenance_kind="synthetic",
        )
        session.add(movement)
        session.commit()
        close_reporting_month(session, month.id)
        p = preview_corrections(
            session,
            decisions=correction_decisions(session, [source["import_id"]]),
            owner_reviewed=True,
        )
        assert not p["can_apply"] and "closed_reporting_month_requires_reopen" in p["blockers"]
        assert count(session, PositionSnapshot) == 0 and count(session, InKindMovement) == 1


def test_correction_money_only_old_account_binding_cannot_follow_remapped_trade(database):
    from hermes_finance.persistence import MyBrokerCorrectionRevision
    from hermes_finance.services.broker_identity_mappings import remap_mapping
    from hermes_finance.services.mybroker_corrections import apply_corrections, preview_corrections

    root = ET.fromstring(correction_xml([SKIP]))
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "{MyBroker}Details":
                parent.remove(child)
    money = root.findall(".//{MyBroker}rn")
    for parent in root.iter():
        if money[0] in list(parent):
            parent.remove(money[0])
    with database.session_factory() as session:
        money_source = correction_source(session, [], raw=ET.tostring(root, encoding="utf-8"))
        second = create_account(
            session, name="Synthetic remapped account", account_type="brokerage"
        )
        old_accounts = list(
            session.scalars(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.subject_kind == "account",
                    BrokerIdentityMapping.status == "effective",
                )
            )
        )
        for mapping in old_accounts:
            remap_mapping(session, mapping.id, hermes_target_id=second.id)
        trade_source = correction_source(session, [SKIP], request="synthetic-remapped-trade")
        assert money_source["mappings"][0]["hermes_id"] != trade_source["mappings"][0]["hermes_id"]
        correction_targets(session, [SKIP])
        p = preview_corrections(
            session,
            decisions=correction_decisions(session, [trade_source["import_id"]]),
            owner_reviewed=True,
        )
        assert not p["can_apply"] and "accepted_mapping_conflict" in p["blockers"]
        with pytest.raises(MyBrokerError, match="correction_batch_blocked"):
            apply_corrections(
                session,
                decisions=p["intent"]["decisions"],
                owner_reviewed=True,
                request_id="synthetic-stale-money",
                confirmation_digest=p["confirmation_digest"],
            )
        assert count(session, MyBrokerCorrectionRevision) == 0


def test_s2_money_only_accepted_account_cannot_follow_remapped_execution(database):
    from hermes_finance.services.broker_identity_mappings import remap_mapping

    root = ET.fromstring(fixture())
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "{MyBroker}Details":
                parent.remove(child)
    with database.session_factory() as session:
        correction_source(session, [], raw=ET.tostring(root, encoding="utf-8"))
        second = create_account(
            session, name="Synthetic second S2 account", account_type="brokerage"
        )
        old_accounts = list(
            session.scalars(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.subject_kind == "account",
                    BrokerIdentityMapping.status == "effective",
                )
            )
        )
        for mapping in old_accounts:
            remap_mapping(session, mapping.id, hermes_target_id=second.id)
        source = apply(session, fixture(), preview(session, fixture()))
        identity = source["document"]["trades"][0]["identity"]
        p = preview_executed_trades(session, [identity])
        assert not p["can_apply"] and "accepted_mapping_conflict" in p["candidates"][0]["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply_executed_trades(
                session,
                identities=[identity],
                request_id="synthetic-invalid-money",
                confirmation_digest=p["confirmation_digest"],
            )
        assert count(session, ExecutedTrade) == 0
