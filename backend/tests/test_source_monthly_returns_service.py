"""Synthetic monthly source-account estimates; no Owner sources or finance writes."""

import calendar
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from astra_hunt_runner import CASES as ASTRA_CASES
from astra_hunt_runner import ROOT as ASTRA_ROOT
from astra_hunt_runner import replay as astra_replay
from test_statement_import_broker_statement_provisional import (
    _finite_tables,
    provisional_xml,
)
from test_statement_import_mybroker import ACCOUNT

from hermes_finance.domain.broker_statement_provisional import (
    ProvisionalAssumptions,
    ProvisionalChoice,
)
from hermes_finance.persistence import Base
from hermes_finance.services import source_intake
from hermes_finance.services.source_monthly_returns import read_monthly_returns


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    database = source_returns_database_factory(tmp_path)
    yield database
    database.engine.dispose()


def save_month(
    db,
    month=4,
    *,
    beginning="9000",
    closing="10211",
    extra=(),
    candidate_count=1,
    marker=None,
    missing_closing=False,
    money_currency=None,
    filename=None,
):
    xml = provisional_xml(
        beginning=beginning,
        closing=closing,
        extra_money=extra,
        candidate_count=candidate_count,
        missing_closing=missing_closing,
    )
    xml = (
        xml.decode()
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(".04.2030", f".{month:02d}.2030")
        .encode()
    )
    if marker or money_currency:
        root = ET.fromstring(xml)
        if marker:
            root.set("synthetic_marker", marker)
        if money_currency:
            for row in root.findall(".//{MyBroker}p_code[@volume]"):
                row.set("p_code", money_currency)
        xml = ET.tostring(root, encoding="utf-8")
    end = calendar.monthrange(2030, month)[1]
    filename = filename or f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30).xml"
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=xml, filename=filename, request_id=f"save-{month}-{marker}"
        )
    return ack["intake_id"], (xml, filename)


def read(db, originals=None, assumptions=None, source_account=ACCOUNT):
    with db.session_factory() as session:
        return read_monthly_returns(
            session, source_account=source_account, originals=originals, assumptions=assumptions
        )


def snapshot(db):
    with db.engine.connect() as connection:
        return {
            table.name: connection.exec_driver_sql(
                f'SELECT * FROM "{table.name}" ORDER BY rowid'
            ).fetchall()
            for table in Base.metadata.sorted_tables
        }


def save_cancellation_long(db, *, mutate=None, request_id="custody-long"):
    raw = service_structure_xml(
        provisional_xml(
            candidate_count=0,
            extra_money=(("Комиссия", "Synthetic fee", "-1"),),
        )
    )
    root = ET.fromstring(raw)
    n = "{MyBroker}"
    table = root.find(n + "Trades3/" + n + "Report/" + n + "Tablix1")
    rows = ET.SubElement(table, n + "Details_Collection")
    row = ET.SubElement(
        rows,
        n + "Details",
        {
            "settlement_date": "2030-05-15T00:00:00",
            "settlement_time": "07:12:34",
            "place_name": "НРД",
            "oper_type": "Перевод",
            "p_name": "Synthetic bond\r\nRU000A000000",
            "comment_new": "Аннулирование выпуска SYNTH001.",
            "qty": "-10.0000000000",
            "acc_code": ACCOUNT,
        },
    )
    if mutate:
        mutate(root, row)
    raw = ET.tostring(root, encoding="utf-8")
    filename = "Брокерский 1234567 (01.03.30-31.07.30).xml"
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=raw, filename=filename, request_id=request_id
        )
    return ack["intake_id"], (raw, filename)


def read_all_originals(db, originals, *, expected=None, documents=None):
    from hermes_finance.services.source_monthly_returns import read_monthly_returns_with_originals

    with db.session_factory() as session:
        expected = (
            expected
            if expected is not None
            else {
                key: source_intake.read_intake(session, key)["manifest_digest"] for key in originals
            }
        )
        return read_monthly_returns_with_originals(
            session,
            source_account=ACCOUNT,
            expected_sources=expected,
            documents=documents if documents is not None else list(originals.values()),
        )


def proof_preview(db):
    from hermes_finance.services.source_return_proofs import preview_proof

    originals = dict(save_service_month(db, month) for month in (4, 5, 6))
    intake, original = save_cancellation_long(db)
    originals[intake] = original
    with db.session_factory() as session:
        expected = {
            key: source_intake.read_intake(session, key)["manifest_digest"] for key in originals
        }
        preview = preview_proof(
            session,
            source_account=ACCOUNT,
            documents=list(originals.values()),
            expected_sources=expected,
        )
    return originals, expected, preview


def proof_confirm(db, preview, request_id="proof-confirmed"):
    from hermes_finance.services.source_return_proofs import confirm_proof

    with db.session_factory() as session:
        return confirm_proof(
            session,
            source_account=ACCOUNT,
            form_token=preview["form_token"],
            preview_digest=preview["preview_digest"],
            request_id=request_id,
        )


def test_durable_proof_existing_catalogue_aba_uses_v1_tail_without_duplicate_clock(db):
    from sqlalchemy import func, select, text

    from hermes_finance.persistence import SourceIntakeRevision, SourceReturnProofDependency
    from hermes_finance.services.accounts import create_account

    with db.session_factory() as session:
        account = create_account(session, name="Synthetic ABA", account_type="brokerage")
        account_id = account.id
    _, _, preview = proof_preview(db)
    proof_confirm(db, preview)

    def tokens():
        with db.session_factory() as session:
            return (
                session.scalar(select(func.max(SourceIntakeRevision.seq))),
                session.scalar(select(func.max(SourceReturnProofDependency.seq))),
            )

    before = tokens()
    with db.engine.begin() as connection:
        connection.execute(
            text("UPDATE accounts SET name='Synthetic changed' WHERE id=:id"), {"id": account_id}
        )
        connection.execute(
            text("UPDATE accounts SET name='Synthetic ABA' WHERE id=:id"), {"id": account_id}
        )
    after = tokens()
    assert after[0] > before[0] and after[1:] == before[1:]
    assert read(db).source_proof["status"] == "stale"


@pytest.mark.parametrize("failure", ["missing", "extra", "generic", "bad_manifest", "bad_token"])
def test_durable_proof_rejected_preview_or_intent_has_no_writes(db, failure):
    from hermes_finance.services import source_return_proofs as proofs
    from hermes_finance.statement_import.mybroker import MyBrokerError

    originals, expected, preview = proof_preview(db)
    documents = list(originals.values())
    if failure == "generic":
        intake, raw = save_cancellation_long(
            db,
            request_id="unknown-transfer",
            mutate=lambda root, row: row.set("comment_new", "Unknown synthetic transfer"),
        )
        documents.append(raw)
        with db.session_factory() as session:
            expected[intake] = source_intake.read_intake(session, intake)["manifest_digest"]
    elif failure == "missing":
        documents.pop()
    elif failure == "extra":
        documents.append((b"Synthetic changed original", "extra.xml"))
    elif failure == "bad_manifest":
        expected[next(iter(expected))] = "0" * 64
    before = snapshot(db)
    with pytest.raises((proofs.ProofError, MyBrokerError)):
        if failure == "bad_token":
            proof_confirm(db, {**preview, "form_token": "synthetic-unknown-token"})
        else:
            with db.session_factory() as session:
                proofs.preview_proof(
                    session, source_account=ACCOUNT, documents=documents, expected_sources=expected
                )
    assert snapshot(db) == before


def test_durable_proof_preview_save_get_and_restart_no_xml_no_financial_writes(db):
    import json

    from hermes_finance.database import create_database

    originals, expected, preview = proof_preview(db)
    before = snapshot(db)
    assert preview["table_deltas"] == {
        "source_return_proofs": 1,
        "source_return_proof_dependencies": 0,
    }
    assert preview["financial_effects"] == preview["trigger_deltas"] == 0
    assert preview["cancellation_months"] == ["2030-05-01"]
    assert all(row.result.growth_kopecks is None for row in read(db).months)
    ack = proof_confirm(db, preview)
    assert ack["proof"]["status"] == "current"
    after = snapshot(db)
    for table in before:
        if table != "source_return_proofs":
            assert before[table] == after[table]
    assert len(after["source_return_proofs"]) == 1
    with db.session_factory() as session:
        from hermes_finance.persistence import SourceReturnProof

        row = session.get(SourceReturnProof, ack["proof"]["proof_id"])
        evidence = json.loads(row.evidence_json)
        assert set(evidence) == {"sources", "cancellations"}
        assert len(evidence["sources"]) == len(originals)
        assert all(set(item) == {"intake_id", "months"} for item in evidence["cancellations"])
        assert "<" not in row.evidence_json and "growth_kopecks" not in row.evidence_json
    result = read(db)
    assert result.source_proof["status"] == "current"
    assert (
        read(db, source_account="1234567").source_proof["proof_id"]
        == result.source_proof["proof_id"]
    )
    by_month = {row.result.closing_date.month: row for row in result.months}
    assert by_month[4].result.growth_kopecks == by_month[6].result.growth_kopecks == 60_000
    assert by_month[5].result.growth_kopecks is None
    assert "custody_cancellation_unresolved" in by_month[5].flags
    db.engine.dispose()
    restarted = create_database(db.database_path)
    try:
        assert read(restarted).to_dict() == result.to_dict()
    finally:
        restarted.engine.dispose()


@pytest.mark.parametrize(
    "change",
    ["classification_aba", "mapping_aba", "source_added", "parser", "physical_unavailable"],
)
def test_durable_proof_dependency_changes_never_revive_old_values(db, monkeypatch, change):
    from sqlalchemy import text

    from hermes_finance.services import source_return_proofs as proofs

    _, _, preview = proof_preview(db)
    proof_confirm(db, preview)
    if change == "classification_aba":
        with db.engine.begin() as connection:
            row = connection.exec_driver_sql(
                "SELECT id,narrative FROM source_intake_money_classifications LIMIT 1"
            ).one()
            connection.execute(
                text("UPDATE source_intake_money_classifications SET narrative=:n WHERE id=:id"),
                {"n": "Synthetic changed", "id": row.id},
            )
            connection.execute(
                text("UPDATE source_intake_money_classifications SET narrative=:n WHERE id=:id"),
                {"n": row.narrative, "id": row.id},
            )
    elif change == "mapping_aba":
        with db.engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT INTO security_reg_isin_mappings(reg_number,isin,created_at,updated_at) VALUES('SYNTH-REG','RU000A000000',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
            connection.exec_driver_sql(
                "DELETE FROM security_reg_isin_mappings WHERE reg_number='SYNTH-REG'"
            )
    elif change == "source_added":
        save_service_month(db, 7)
    elif change == "parser":
        monkeypatch.setattr(proofs, "VERSION", "future-proof-version")
    else:
        monkeypatch.setattr(proofs, "file_incarnation", lambda _: None)
    result = read(db)
    assert result.source_proof["status"] == "stale"
    assert all(
        row.result.growth_kopecks is None
        for row in result.months
        if row.result.closing_date.month in (4, 5, 6)
    )
    assert proof_confirm(db, preview)["proof"]["status"] == "stale"
    assert all(
        row.result.growth_kopecks is None
        for row in read(db).months
        if row.result.closing_date.month in (4, 5, 6)
    )


def test_durable_proof_stale_preview_replay_supersession_and_exact_no_write_ack(db):
    from hermes_finance.services.source_return_proofs import ProofError, preview_proof

    originals, expected, preview = proof_preview(db)
    with db.session_factory() as session:
        other = preview_proof(
            session,
            source_account=ACCOUNT,
            documents=list(originals.values()),
            expected_sources=expected,
        )
    ack = proof_confirm(db, preview)
    before = snapshot(db)
    assert proof_confirm(db, preview)["proof"]["proof_id"] == ack["proof"]["proof_id"]
    assert snapshot(db) == before
    with pytest.raises(ProofError, match="dependencies_changed"):
        proof_confirm(db, other, "outstanding-form")
    with pytest.raises(ProofError, match="request_conflict"):
        proof_confirm(db, {**preview, "preview_digest": "0" * 64})


def test_durable_proof_real_restore_and_fresh_copy_are_stale_without_changing_backup(db, tmp_path):
    from shutil import copyfile

    from hermes_finance.database import create_database
    from hermes_finance.services.backups import backup_directory, create_backup, restore_backup

    _, _, preview = proof_preview(db)
    proof_confirm(db, preview)
    saved = create_backup(db)
    path = backup_directory(db) / saved.name
    content = path.read_bytes()
    for _ in range(2):
        restore_backup(db, saved.id)
        assert path.read_bytes() == content
        result = read(db)
        assert result.source_proof["status"] == "stale"
        assert all(row.result.growth_kopecks is None for row in result.months)
    fresh = tmp_path / "isolated-restored.db"
    copyfile(path, fresh)
    isolated = create_database(fresh)
    try:
        assert read(isolated).source_proof["status"] == "stale"
    finally:
        isolated.engine.dispose()


def test_durable_proof_file_birth_identity_and_missing_capability_fail_closed(db, monkeypatch):
    from hermes_finance.services import source_return_proofs as proofs
    from hermes_finance.source_proof_file import file_incarnation

    assert file_incarnation(db.database_path) is not None
    _, _, preview = proof_preview(db)
    proof_confirm(db, preview)
    monkeypatch.setattr(proofs, "file_incarnation", lambda _: "0" * 64)
    assert read(db).source_proof["status"] == "stale"


def test_durable_proof_file_id_reuse_requires_same_birth_time(db, monkeypatch):
    import os
    from types import SimpleNamespace

    from hermes_finance.source_proof_file import file_incarnation

    original = file_incarnation(db.database_path)
    assert original is not None
    native = os.fstat

    def reused_inode(descriptor):
        info = native(descriptor)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_nlink=info.st_nlink,
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_birthtime_ns=getattr(info, "st_birthtime_ns", 1) + 1,
        )

    monkeypatch.setattr(os, "fstat", reused_inode)
    assert file_incarnation(db.database_path) not in (None, original)


def test_durable_proof_form_expires_and_restore_retires_open_api_preview(db, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app
    from hermes_finance.services import source_return_proofs as proofs

    originals, expected, preview = proof_preview(db)
    now = proofs.monotonic()
    with monkeypatch.context() as context:
        context.setattr(proofs, "monotonic", lambda: now + 901)
        with pytest.raises(proofs.ProofError, match="expired"):
            proof_confirm(db, preview)
    client = TestClient(create_app(database=db))
    files = [("files", (name, raw, "application/xml")) for raw, name in originals.values()]
    request = {
        "source_account": ACCOUNT,
        "expected_sources": [
            {"intake_id": key, "manifest_digest": value} for key, value in expected.items()
        ],
    }
    reply = client.post(
        "/api/source-returns/proofs/preview", data={"request": json.dumps(request)}, files=files
    ).json()
    with db.maintenance.restore():
        pass
    before = snapshot(db)
    response = client.post(
        "/api/source-returns/proofs/confirm",
        json={
            "source_account": ACCOUNT,
            "form_token": reply["form_token"],
            "preview_digest": reply["preview_digest"],
            "request_id": "after-restore",
            "attested": True,
        },
    )
    assert response.status_code == 409 and "expired" in response.text
    assert snapshot(db) == before


def test_durable_proof_tables_are_append_only_and_leave_nine_closed_periods_unchanged(db):
    from datetime import UTC, datetime

    from sqlalchemy.exc import IntegrityError

    from hermes_finance.persistence import ReportingMonth

    with db.session_factory() as session:
        for month in range(1, 10):
            end = date(2029, month, calendar.monthrange(2029, month)[1])
            session.add(
                ReportingMonth(
                    year=2029,
                    month=month,
                    period_start=end.replace(day=1),
                    period_end=end,
                    snapshot_date=end,
                    status="closed",
                    source="manual",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        session.commit()
    _, _, preview = proof_preview(db)
    before = snapshot(db)
    proof_confirm(db, preview)
    after = snapshot(db)
    for table in before:
        if table != "source_return_proofs":
            assert before[table] == after[table]
    assert len(after["reporting_months"]) == 9
    for table in ("source_return_proofs", "source_return_proof_dependencies"):
        for operation in (
            f"DELETE FROM {table}",
            f"UPDATE {table} SET {'id=id' if table.endswith('proofs') else 'seq=seq'}",
        ):
            with pytest.raises(IntegrityError):
                with db.engine.begin() as connection:
                    connection.exec_driver_sql(operation)


def test_durable_proof_api_preview_confirm_get_reload_and_lost_ack(db):
    import json

    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    originals, expected, _ = proof_preview(db)
    client = TestClient(create_app(database=db))
    files = [("files", (name, raw, "application/xml")) for raw, name in originals.values()]
    request = {
        "source_account": ACCOUNT,
        "expected_sources": [
            {"intake_id": key, "manifest_digest": value} for key, value in expected.items()
        ],
    }
    before = snapshot(db)
    reply = client.post(
        "/api/source-returns/proofs/preview", data={"request": json.dumps(request)}, files=files
    )
    assert reply.status_code == 200, reply.text
    assert reply.headers["cache-control"] == "no-store"
    assert snapshot(db) == before
    preview = reply.json()
    payload = {
        "source_account": ACCOUNT,
        "form_token": preview["form_token"],
        "preview_digest": preview["preview_digest"],
        "request_id": "api-proof",
        "attested": True,
    }
    assert (
        client.post(
            "/api/source-returns/proofs/confirm", json={**payload, "months": []}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/source-returns/proofs/confirm", json={**payload, "attested": False}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/source-returns/proofs/confirm", json={**payload, "attested": 1}
        ).status_code
        == 422
    )
    assert client.post("/api/source-returns/proofs/confirm", json=payload).status_code == 200
    # Lost ACK uses independent GET only; no re-upload or second command needed.
    recovered = client.get("/api/source-returns/proofs/requests/api-proof")
    assert recovered.status_code == 200 and recovered.json()["proof"]["status"] == "current"
    after = snapshot(db)
    for _ in range(2):
        result = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
        assert result.json()["source_proof"]["status"] == "current"
        april = next(x for x in result.json()["months"] if x["closing_date"] == "2030-04-30")
        assert april["growth_kopecks"] == 60_000
        assert isinstance(april["modified_dietz_return"], str)
        assert snapshot(db) == after


def test_original_bound_cancellation_keeps_event_month_unknown_and_unblocks_own_months(db):
    originals = dict(save_service_month(db, month) for month in (4, 5, 6))
    long_id, long_original = save_cancellation_long(db)
    originals[long_id] = long_original
    before = snapshot(db)
    assert all(row.result.growth_kopecks is None for row in read(db).months)
    bound = read_all_originals(db, originals)
    months = {row.result.closing_date.month: row for row in bound.months}
    for month in (4, 6):
        assert months[month].result.growth_kopecks == 60_000
        assert months[month].result.modified_dietz_return is not None
        assert months[month].coupons_kopecks == 1234
    assert months[5].result.growth_kopecks is months[5].result.modified_dietz_return is None
    assert "custody_cancellation_unresolved" in months[5].flags
    assert bound.period.growth_kopecks is None
    assert bound.financial_authority == "none"
    assert snapshot(db) == before
    assert all(row.result.growth_kopecks is None for row in read(db).months)


def test_original_bound_repeated_documents_do_not_create_cash_or_duplicate_default_flows(db):
    originals = dict([save_service_month(db)])
    intake, raw = save_cancellation_long(db)
    originals[intake] = raw
    first = read_all_originals(db, originals)

    def distinct_original(root, row):
        # Distinct immutable original, same native custody observation and fee.
        root.find(".//{MyBroker}Details[@sys_start_time]").set("sys_start_time", "02.04.2030 01:00")

    second, other_raw = save_cancellation_long(
        db, mutate=distinct_original, request_id="second-long"
    )
    assert second != intake
    originals[second] = other_raw
    before = snapshot(db)
    repeated = read_all_originals(db, originals)
    assert repeated.flows == first.flows
    assert [row.result for row in repeated.months] == [row.result for row in first.months]
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("settlement_date", "2030-02-28T00:00:00"),
        ("settlement_date", "2030-05-32T00:00:00"),
        ("settlement_date", "2030-05-15T01:00:00"),
        ("settlement_time", "25:00:00"),
        ("qty", "0"),
        ("qty", "1"),
        ("qty", "NaN"),
        ("qty", "-Infinity"),
        ("acc_code", "other-000"),
        ("place_name", "Other custody"),
        ("oper_type", "Вывод"),
        ("p_name", "Ambiguous instrument"),
        ("p_name", "Synthetic\r\ninvalid"),
        ("comment_new", "Unknown transfer"),
        ("comment_new", "Аннулирование выпуска SYNTH001. д.ф.01.04.30"),
        ("effective_date", "2030-04-01"),
    ],
)
def test_original_bound_unknown_transfer_is_still_document_wide(db, key, value):
    originals = dict(save_service_month(db, month) for month in (4, 5, 6))
    intake, original = save_cancellation_long(db, mutate=lambda root, row: row.set(key, value))
    originals[intake] = original
    result = read_all_originals(db, originals)
    for row in result.months:
        assert row.result.growth_kopecks is row.result.modified_dietz_return is None
        assert "4_Transfers_unsupported" in row.flags


@pytest.mark.parametrize("kind", ["text", "child", "comment", "pi", "other_branch"])
def test_original_bound_whole_tree_is_required(db, kind):
    def mutate(root, row):
        if kind == "text":
            row.text = "Unknown effect"
        elif kind == "child":
            ET.SubElement(row, "{MyBroker}Unknown")
        elif kind == "comment":
            row.append(ET.Comment("Unknown effect"))
        elif kind == "pi":
            row.append(ET.ProcessingInstruction("effect", "unknown"))
        else:
            root.find("{MyBroker}Trades4").set("unknown", "1")

    originals = dict([save_service_month(db)])
    intake, original = save_cancellation_long(db, mutate=mutate)
    originals[intake] = original
    assert all(
        row.result.growth_kopecks is None for row in read_all_originals(db, originals).months
    )


def test_original_bound_redemption_stays_unknown_no_synthetic_cash_and_replay(db):
    original = service_structure_xml(
        provisional_xml(
            candidate_count=0,
            extra_money=(("Перевод", "полное погашение номинала SYNTH-REG д.ф.15.04.30", "10000"),),
        )
    )
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session,
            document=original,
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="principal",
        )
        replay = source_intake.save_intake(
            session,
            document=original,
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="principal-replay",
        )
    assert ack["intake_id"] == replay["intake_id"]
    originals = {ack["intake_id"]: (original, "Брокерский 1234567 (01.04.30-30.04.30).xml")}
    intake, custody = save_cancellation_long(
        db, mutate=lambda root, row: row.set("settlement_date", "2030-04-15T00:00:00")
    )
    originals[intake] = custody
    before = snapshot(db)
    result = read_all_originals(db, originals)
    april = next(row for row in result.months if row.result.closing_date.month == 4)
    assert april.result.growth_kopecks is None
    assert "custody_cancellation_unresolved" in april.flags
    assert any(gap.code == "unrecognized_money" for gap in result.gaps)
    assert not any(flow.included for flow in result.flows)
    assert april.coupons_kopecks is april.dividends_kopecks is None
    assert snapshot(db) == before


@pytest.mark.parametrize("failure", ["missing", "extra", "duplicate", "filename", "manifest"])
def test_original_bound_requires_exact_all_originals_and_current_manifests(db, failure):
    from hermes_finance.statement_import.mybroker import MyBrokerError

    originals = dict([save_service_month(db), save_cancellation_long(db)])
    documents = list(originals.values())
    with db.session_factory() as session:
        expected = {
            key: source_intake.read_intake(session, key)["manifest_digest"] for key in originals
        }
    if failure == "missing":
        documents.pop()
    elif failure == "extra":
        documents.append((b"unknown", "unknown.xml"))
    elif failure == "duplicate":
        documents.append(documents[0])
    elif failure == "filename":
        documents[0] = (documents[0][0], "renamed.xml")
    else:
        expected[next(iter(expected))] = "0" * 64
    with pytest.raises((MyBrokerError, ValueError)):
        read_all_originals(db, originals, expected=expected, documents=documents)


def test_original_bound_api_is_no_store_read_only_and_get_remains_unchanged(db):
    import json

    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    originals = dict([save_service_month(db), save_cancellation_long(db)])
    with db.session_factory() as session:
        expected = [
            {
                "intake_id": key,
                "manifest_digest": source_intake.read_intake(session, key)["manifest_digest"],
            }
            for key in originals
        ]
    client = TestClient(create_app(database=db))
    before = snapshot(db)
    get_before = client.get(
        "/api/source-returns/monthly", params={"source_account": ACCOUNT}
    ).json()
    payload = {"source_account": ACCOUNT, "expected_sources": expected}
    files = [("files", (filename, raw, "application/xml")) for raw, filename in originals.values()]
    response = client.post(
        "/api/source-returns/monthly/originals", data={"request": json.dumps(payload)}, files=files
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    april = next(row for row in response.json()["months"] if row["closing_date"] == "2030-04-30")
    assert april["growth_kopecks"] == 60_000
    assert isinstance(april["modified_dietz_return"], str)
    assert response.json()["financial_authority"] == "none"
    for invalid_files, body, status in [
        (files[:-1], payload, 409),
        (files, {**payload, "assumptions": {}}, 422),
        (files, {**payload, "expected_sources": expected + expected}, 422),
    ]:
        error = client.post(
            "/api/source-returns/monthly/originals",
            data={"request": json.dumps(body)},
            files=invalid_files,
        )
        assert error.status_code == status
        assert error.headers["cache-control"] == "no-store"
    assert (
        client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
        == get_before
    )
    assert snapshot(db) == before


def service_structure_xml(raw, *, summary_variant=1):
    """Fabricated values on the inventoried service paths; no summary is an event."""
    from copy import deepcopy

    from test_statement_import_mybroker_endpoints import draft_structure_xml
    from test_statement_import_mybroker_metadata import metadata_xml

    n = "{MyBroker}"
    root = ET.fromstring(metadata_xml(raw))
    root.set("Textbox6", "Уполномоченное лицо")
    donor = ET.fromstring(draft_structure_xml(summary_variant=summary_variant))
    root.find(n + "Positions/" + n + "Report").append(
        deepcopy(donor.find(n + "Positions/" + n + "Report/" + n + "Tablix3"))
    )
    report = root.find(n + "Trades2/" + n + "Report")
    controls = donor.find(n + "Trades2/" + n + "Report")
    for child in controls:
        if child.tag != n + "Tablix1":
            report.append(deepcopy(child))
    table = report.find(n + "Tablix1")
    table.append(deepcopy(controls.find(n + "Tablix1/" + n + "Textbox116")))
    daily = controls.find(".//" + n + "comment")
    for group in table.findall(n + "settlement_date_Collection/" + n + "settlement_date"):
        rows = group.findall(n + "rn_Collection/" + n + "rn")
        for index, row in enumerate(rows):
            comment = row.find(n + "oper_type/" + n + "comment")
            for tag in ("Textbox95", "Textbox93"):
                display = deepcopy(daily.find(n + tag))
                if index < len(rows) - 1:
                    for scalar in display.iter():
                        for key in scalar.attrib:
                            scalar.set(key, "")
                comment.append(display)
            comment[:] = [
                comment.find(n + tag)
                for tag in ("money_volume_begin1_Collection", "Textbox95", "Textbox93", "Textbox11")
            ]
    report[:] = [
        report.find(n + tag)
        for tag in ("Tablix2", "Tablix1", "Tablix3", "Tablix5", "Tablix4", "Tablix6", "Tablix7")
    ]
    return ET.tostring(root, encoding="utf-8")


def save_service_month(db, month=4, *, mutate=None, summary_variant=1, row_account=ACCOUNT):
    raw = provisional_xml(
        beginning=str(9000 + (month - 4) * 1000),
        closing=str(10000 + (month - 4) * 1000),
        candidate_count=0,
        extra_money=(
            ("Внесено по распоряжению Клиента", "Synthetic funding", "500"),
            ("Выведено по распоряжению Клиента", "Synthetic withdrawal", "-100"),
            ("Перевод", "Погашение купона Synthetic stock", "12.34"),
            ("Перевод", "Дивиденды Synthetic stock", "5.66"),
        ),
    )
    root = ET.fromstring(service_structure_xml(raw, summary_variant=summary_variant))
    if mutate:
        mutate(root)
    raw = (
        ET.tostring(root, encoding="utf-8")
        .decode()
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(".04.2030", f".{month:02d}.2030")
        .replace(ACCOUNT, row_account)
        .encode()
    )
    end = calendar.monthrange(2030, month)[1]
    filename = f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30) (1).xml"
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=raw, filename=filename, request_id=f"service-{month}"
        )
    return ack["intake_id"], (raw, filename)


def test_filename_alias_uses_single_document_row_scope_and_does_not_write(db):
    save_month(db, candidate_count=0, extra=(("Купон", "Synthetic stock", "12.34"),))
    before = snapshot(db)
    native = read(db)
    alias = read(db, source_account="1234567")
    assert alias.months == native.months
    assert alias.flows == native.flows
    assert alias.months[0].coupons_kopecks == 1234
    assert alias.months[0].dividends_kopecks == 0
    assert not alias.gaps
    assert snapshot(db) == before


def test_filename_alias_conflicting_single_row_accounts_across_documents(db):
    save_service_month(db)
    save_service_month(db, 5, row_account="7654321-000")
    result = read(db, source_account="1234567")
    assert len(result.months) == 2
    assert "native_source_scope_ambiguous" in {gap.code for gap in result.gaps}
    for row in result.months:
        assert row.result.opening_kopecks is None
        assert row.result.contributions_kopecks is None
        assert row.coupons_kopecks is row.dividends_kopecks is None
    assert read(db).months[0].result.modified_dietz_return is not None


def test_multi_account_document_never_maps_filename_alias_or_returns_zero_income(db):
    def mutate(root):
        root.find(".//{MyBroker}Textbox11").set("acc_code", "7654321-000")

    save_service_month(db, mutate=mutate)
    for alias in (ACCOUNT, "1234567", "7654321-000"):
        result = read(db, source_account=alias)
        assert result.months[0].coupons_kopecks is None
        assert result.months[0].dividends_kopecks is None
        assert result.months[0].result.growth_kopecks is None
        assert "native_source_scope_ambiguous" in {gap.code for gap in result.gaps}
    assert read(db, source_account="1234567-001").months == ()


@pytest.mark.parametrize("summary_variant", range(4))
def test_exact_service_inventory_is_recomputed_without_changing_frozen_source(db, summary_variant):
    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    intake, original = save_service_month(db, summary_variant=summary_variant)
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
        assert set(view["document"]["syntax_blockers"]) == {
            "unparsed_source_rows",
            "4_Transfers_unsupported",
            "5_UFSR_unsupported",
        }
        assert source_return_blockers(view) == set()
        assert source_return_blockers({**view, "observations": []}) == set(
            view["document"]["syntax_blockers"]
        )
    row = read(db, source_account="1234567").months[0]
    assert row.result.contributions_kopecks == 50_000
    assert row.result.withdrawals_kopecks == 10_000
    assert row.result.growth_kopecks == 60_000
    assert row.coupons_kopecks == 1234 and row.dividends_kopecks == 566
    assert row.result.modified_dietz_return is not None
    assert not row.flags
    assert snapshot(db) == before
    # Explicit re-save remains compatible with the unchanged frozen manifest.
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=original[0], filename=original[1], request_id="re-save-service"
        )
    # Re-save is intentional; the preceding reads themselves made no writes.
    after = snapshot(db)
    assert before["source_intake_observations"] == after["source_intake_observations"]


@pytest.mark.parametrize(
    "path",
    [
        "Positions/Report/Tablix3/Details1_Collection/Details1",
        "Trades2/Report/Tablix2",
        "Trades2/Report/Tablix3",
        "Trades2/Report/Tablix1/settlement_date_Collection/settlement_date/rn_Collection/rn/oper_type/comment/Textbox95",
        "Trades2/Report/Tablix1/Textbox116",
        "Trades2/Report/Tablix7",
        "Trades3/Report/Tablix1",
        "Trades4/Report/Tablix1/Details_Collection/Details",
    ],
)
@pytest.mark.parametrize("change", ["attribute", "child", "foreign_child", "text"])
def test_service_exceptions_never_hide_unknown_content(db, path, change):
    def mutate(root):
        node = root.find("/".join("{MyBroker}" + part for part in path.split("/")))
        if change == "attribute":
            node.set("unrecognized", "0")
        elif change == "text":
            node.text = "Synthetic hidden content"
        else:
            ET.SubElement(node, "{MyBroker}Details" if change == "child" else "{Other}Details")

    save_service_month(db, mutate=mutate)
    result = read(db, source_account="1234567")
    assert result.months[0].result.contributions_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    assert {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"} & {
        gap.code for gap in result.gaps
    }


def test_monthly_api_three_service_reports_have_numbers_and_missing_months_stay_gaps(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    for month in (4, 5, 7):
        save_service_month(db, month)
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    body = client.get("/api/source-returns/monthly", params={"source_account": "1234567"}).json()
    assert len(body["months"]) == 4
    fields = (
        "opening_kopecks",
        "closing_kopecks",
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "modified_dietz_return",
        "coupons_kopecks",
        "dividends_kopecks",
    )
    for row in (body["months"][0], body["months"][1], body["months"][3]):
        assert all(row[field] is not None for field in fields)
        assert not row["flags"]
    gap = body["months"][2]
    assert all(gap[field] is None for field in fields)
    assert {"missing_endpoint", "unknown_flow", "flow_coverage_gap"} <= set(gap["flags"])
    assert body["period"]["chained_return"] is None
    assert len(body["flows"]) == 6  # summaries never duplicate the six external flows
    assert snapshot(db) == before


def test_monthly_api_three_contiguous_service_reports_chain_known_flows(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    for month in (4, 5, 6):
        save_service_month(db, month)
    before = snapshot(db)
    body = (
        TestClient(create_app(database=db))
        .get("/api/source-returns/monthly", params={"source_account": "1234567"})
        .json()
    )
    assert len(body["months"]) == 3
    for row in body["months"]:
        assert not row["flags"]
        assert row["contributions_kopecks"] == 50_000
        assert row["withdrawals_kopecks"] == 10_000
        assert row["growth_kopecks"] == 60_000
        assert row["modified_dietz_return"] is not None
        assert row["coupons_kopecks"] == 1234
        assert row["dividends_kopecks"] == 566
    assert body["period"]["contributions_kopecks"] == 150_000
    assert body["period"]["withdrawals_kopecks"] == 30_000
    assert body["period"]["growth_kopecks"] == 180_000
    assert body["period"]["chained_return"] is not None
    assert len(body["segments"]) == 1 and not body["segments"][0]["partial_segment"]
    assert snapshot(db) == before


@pytest.mark.parametrize("extra", [False, True])
def test_service_projection_retains_pending_rows_and_only_known_pending_captions(db, extra):
    from test_statement_import_mybroker import fixture

    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    def mutate(root):
        n = "{MyBroker}"
        pending = ET.fromstring(fixture(pending=True)).find(
            n + "Trades/" + n + "Report/" + n + "Tablix3"
        )
        row = pending.find(".//" + n + "Details2")
        row.attrib.update(
            p_name2="Synthetic security", Textbox16="RUB", place_name2="Synthetic place"
        )
        if extra:
            row.set("unknown_native_key", "0")
        root.find(n + "Trades/" + n + "Report").append(pending)

    intake, _ = save_service_month(db, mutate=mutate)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
        assert len(view["document"]["trades"]) == 2
        assert bool(source_return_blockers(view)) is extra


def withdrawal_summary(root):
    """A fifth exact display layout; fabricated totals are never Money rows."""
    from copy import deepcopy

    groups = root.find(".//{MyBroker}oper_group_Collection")
    withdrawal = deepcopy(groups[-1])
    withdrawal.set("oper_group", "Списано по распоряжению Клиента")
    withdrawal.find(".//{MyBroker}p_code6").set("volume6", "-999999.00")
    groups.insert(3, withdrawal)


@pytest.mark.parametrize("mutation", [None, "order", "label", "attribute", "child"])
def test_fifth_summary_is_exact_and_never_counts_display_money(db, mutation):
    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    def mutate(root):
        withdrawal_summary(root)
        groups = root.find(".//{MyBroker}oper_group_Collection")
        if mutation == "order":
            groups[2], groups[3] = groups[3], groups[2]
        elif mutation == "label":
            groups[3].set("oper_group", "Unknown synthetic withdrawal")
        elif mutation == "attribute":
            groups[3].set("extra", "0")
        elif mutation == "child":
            ET.SubElement(groups[3], "{MyBroker}Extra")

    intake, original = save_service_month(db, mutate=mutate)
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
        assert bool(source_return_blockers(view)) is bool(mutation)
        frozen = view["document"]
    result = read(db)
    if mutation is None:
        assert result.months[0].result.withdrawals_kopecks == 10_000
        assert result.months[0].result.modified_dietz_return is not None
    else:
        assert result.months[0].result.modified_dietz_return is None
    assert snapshot(db) == before
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=original[0], filename=original[1], request_id="summary-replay"
        )
        after = source_intake.read_intake(session, intake)
        assert after["document"] == frozen
        assert after["observations"] == view["observations"]


@pytest.mark.parametrize(
    "change", [None, "nonzero", "lexical_zero", "ordinary", "extra", "pending"]
)
def test_repo_zero_field_is_bounded_to_its_completed_native_row(db, change):
    from test_statement_import_mybroker import fixture

    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    def mutate(root):
        row = root.find(".//{MyBroker}Details[@trade_no]")
        if change != "ordinary":
            row.attrib.update(trade_no="B9001", repo_no="B9002", comment="репо ч.1")
        row.set(
            "course3",
            "1.0000" if change == "nonzero" else "0" if change == "lexical_zero" else "0.0000",
        )
        if change == "extra":
            row.set("unknown_native_key", "0")
        if change == "pending":
            row.attrib.pop("course3")
            pending = ET.fromstring(fixture(pending=True)).find(".//{MyBroker}Tablix3")
            pending.find(".//{MyBroker}Details2").set("course3", "0.0000")
            root.find("{MyBroker}Trades/{MyBroker}Report").append(pending)

    intake, _ = save_service_month(db, mutate=mutate)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    assert bool(source_return_blockers(view)) is bool(change)
    if change is None:
        trade = view["document"]["trades"][0]
        assert trade["identity"] is None and trade["repo_observed"]
        assert "unparsed_source_rows" in view["document"]["syntax_blockers"]


@pytest.mark.parametrize("change", ["ordinary_neighbor", "ordinal_mismatch", "reference_mismatch"])
def test_repo_zero_field_never_borrows_another_rows_identity(db, change):
    from copy import deepcopy

    from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

    def mutate(root):
        collection = root.find(
            "{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2/{MyBroker}Details_Collection"
        )
        ordinary = collection[0]
        repo = deepcopy(ordinary)
        repo.attrib.update(trade_no="B9001", repo_no="B9002", comment="репо ч.1", course3="0.0000")
        collection.append(repo)
        if change == "ordinary_neighbor":
            ordinary.set("course3", "0.0000")

    intake, _ = save_service_month(db, mutate=mutate)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    if change == "ordinal_mismatch":
        view["document"]["trades"].reverse()
    elif change == "reference_mismatch":
        for row in view["observations"]:
            refs = row["facts"].get("native_references", {})
            if refs.get("trade_no") == "B9001":
                refs["repo_no"] = "B9003"
    assert source_return_blockers(view)


@pytest.mark.parametrize(
    "change",
    [
        "summary_label",
        "currency_label",
        "duplicate",
        "order",
        "moved",
        "daily_empty",
        "daily_early_value",
        "connection_end",
    ],
)
def test_service_projection_rejects_inexact_known_shapes(db, change):
    from copy import deepcopy

    def mutate(root):
        n = "{MyBroker}"
        report = root.find(n + "Trades2/" + n + "Report")
        if change == "summary_label":
            report.find(".//" + n + "oper_group").set("oper_group", "Synthetic unsupported group")
        elif change == "currency_label":
            report.find(".//" + n + "p_code6").set("p_code6", "USD")
        elif change == "duplicate":
            report.append(deepcopy(report.find(n + "Tablix7")))
        elif change == "order":
            report[:] = list(reversed(report[:]))
        elif change == "moved":
            summary = report.find(n + "Tablix7")
            report.remove(summary)
            report.find(n + "Tablix1").append(summary)
        elif change.startswith("daily_"):
            displays = report.findall(".//" + n + "comment/" + n + "Textbox95/" + n + "Textbox83")
            displays[-1 if change == "daily_empty" else 0].set(
                "money_volume", "" if change == "daily_empty" else "1.00"
            )
        else:
            root.find(n + "Trades4/.//" + n + "Details").set("sys_end_time", "Synthetic end")

    save_service_month(db, mutate=mutate)
    row = read(db, source_account="1234567").months[0]
    assert row.result.growth_kopecks is None
    assert row.coupons_kopecks is row.dividends_kopecks is None


def test_saved_months_own_endpoints_seam_and_missing_month(db):
    april, apr = save_month(db)
    may, may_original = save_month(db, 5, beginning="11000", closing="12000", candidate_count=0)
    july, jul = save_month(
        db,
        7,
        beginning="13000",
        closing="14000",
        candidate_count=0,
        extra=(("Unknown", "Synthetic unknown", "17"),),
    )
    before = snapshot(db)
    result = read(db, {april: apr, may: may_original, july: jul})
    assert len(result.months) == 4
    a, m, missing, j = result.months
    assert a.result.opening_kopecks == 1_000_000
    assert a.result.closing_kopecks == 1_121_100
    assert a.result.contributions_kopecks == 100_000
    assert a.result.growth_kopecks == 21_100
    expected = Decimal(21100 * 30) / Decimal(1000000 * 30 + 100000 * 15)
    assert abs(a.result.modified_dietz_return - expected) < Decimal("1e-28")
    assert m.result.opening_kopecks == 1_200_000
    assert m.previous_closing_kopecks == 1_121_100
    assert "seam_mismatch" in m.flags
    assert missing.result.opening_date == date(2030, 5, 31)
    assert missing.result.missing_endpoint
    assert missing.result.modified_dietz_return is None
    assert j.result.modified_dietz_return is None
    assert "unknown_flow" in j.result.reason_codes
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is None
    assert result.period.xirr_period_return is None
    assert len(result.flows) == 1 and result.flows[0].status == "assumed"
    assert result.defaults_applied == result.flows
    assert "unrecognized_money" in {gap.code for gap in result.gaps}
    assert snapshot(db) == before
    assert all(count == 0 for count in _finite_tables(db).values())


def test_saved_v1_money_is_gap_without_reattached_original(db, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(source_intake, "persist_money_classifications", lambda *args: None)
        save_month(db)
    result = read(db)
    assert result.months[0].result.opening_kopecks == 1_000_000
    assert result.flows == ()
    assert result.defaults_applied == ()
    assert "classification_missing_legacy_intake" in {gap.code for gap in result.gaps}
    assert not result.period.assumptions_used
    assert result.months[0].result.modified_dietz_return is None
    assert result.period.growth_kopecks is None


def test_explicit_existing_choices_override_defaults(db):
    intake, original = save_month(db)
    initial = read(db, {intake: original})
    reference = initial.flows[0].source_references[0]
    _, _, _, ordinal, fingerprint = reference.split(":")
    choice = ProvisionalChoice(
        requirement_id=f"candidate:{ordinal}:{fingerprint[:12]}",
        source_references=(reference,),
        choice="exclude_from_external_schedule",
    )
    assumptions = ProvisionalAssumptions(schedule_mode="explicit_empty", selections=(choice,))
    result = read(db, {intake: original}, {intake: assumptions})
    assert result.flows[0].status == "confirmed"
    assert not result.flows[0].included
    assert not result.defaults_applied
    assert result.months[0].result.contributions_kopecks == 0
    assert result.months[0].result.growth_kopecks == 121_100
    included = choice.model_copy(update={"choice": "include_as_account_inflow"})
    result = read(
        db,
        {intake: original},
        {
            intake: assumptions.model_copy(
                update={"schedule_mode": "dated", "selections": (included,)}
            )
        },
    )
    assert result.flows[0].status == "confirmed" and result.flows[0].included
    assert result.months[0].result.contributions_kopecks == 100_000


def test_overlapping_originals_deduplicate_preserving_same_report_multiplicity(db):
    one, first = save_month(db, candidate_count=2)
    two, second = save_month(db, candidate_count=2, marker="overlap")
    result = read(db, {one: first, two: second})
    assert len(result.flows) == 2
    assert all(len(flow.source_references) == 2 for flow in result.flows)
    assert result.months[0].result.contributions_kopecks == 200_000
    assert "overlap_flow_deduplicated" in {gap.code for gap in result.gaps}


def test_internal_income_and_withdrawal_classification(db):
    intake, original = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Внесено по распоряжению Клиента", "Synthetic funding", "500"),
            ("Выведено по распоряжению Клиента", "Synthetic withdrawal", "-200"),
            ("Дивиденды", "Synthetic income", "30"),
        ),
    )
    result = read(db, {intake: original})
    assert [flow.amount_kopecks for flow in result.flows] == [50_000, -20_000]
    assert result.months[0].result.contributions_kopecks == 50_000
    assert result.months[0].result.withdrawals_kopecks == 20_000
    assert result.months[0].result.growth_kopecks == 91_100
    assert not result.gaps


def test_bad_original_only_blocks_its_month(db):
    april, original = save_month(db)
    may, valid = save_month(db, 5, beginning="10211", candidate_count=0)
    before = snapshot(db)
    result = read(db, {april: (b"wrong", original[1]), may: valid})
    assert result.months[0].result.missing_endpoint
    assert result.months[1].result.modified_dietz_return is not None
    assert "source_reader_unavailable" in {gap.code for gap in result.gaps}
    assert snapshot(db) == before


def test_bad_endpoint_and_other_account_never_become_zero(db):
    intake, original = save_month(db, missing_closing=True)
    result = read(db, {intake: original})
    assert result.months[0].result.closing_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    other = read(db, source_account="unrelated-native-account")
    assert other.months == ()
    assert other.period.growth_kopecks is None


def test_get_router_decimal_strings_integer_kopecks_and_gaps(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db)
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    response = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["source_account"] == ACCOUNT
    assert body["financial_authority"] == "none"
    assert body["approximate"] is True
    row = body["months"][0]
    assert type(row["opening_kopecks"]) is int
    assert row["opening_kopecks"] == 1_000_000
    assert isinstance(row["modified_dietz_return"], str)
    assert isinstance(body["period"]["chained_return"], str)
    assert body["flows"][0]["amount_kopecks"] == 100_000
    assert body["flows"][0]["status"] == "assumed"
    assert not body["gaps"]
    assert snapshot(db) == before
    assert client.get("/api/source-returns/monthly").status_code == 422
    assert (
        client.get("/api/source-returns/monthly", params={"source_account": ""}).status_code == 422
    )
    empty = client.get("/api/source-returns/monthly", params={"source_account": "other"})
    assert empty.status_code == 200 and empty.json()["months"] == []


def test_api_available_rates_are_decimal_strings(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db, candidate_count=0)
    body = (
        TestClient(create_app(database=db))
        .get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
        .json()
    )
    assert isinstance(body["months"][0]["modified_dietz_return"], str)
    assert isinstance(body["period"]["chained_return"], str)
    assert isinstance(body["period"]["xirr_period_return"], str)
    assert Decimal(body["months"][0]["modified_dietz_return"]) == Decimal("0.1211")


def test_missing_statement_blocks_period_flows_but_preserves_independent_segments(db):
    april, apr = save_month(db, beginning="9000", closing="9000", candidate_count=0)
    june, jun = save_month(db, 6, beginning="19000", closing="19000", candidate_count=0)
    result = read(db, {april: apr, june: jun})
    assert result.months[1].result.missing_endpoint
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is None
    assert result.period.contributions_kopecks is result.period.withdrawals_kopecks is None
    assert result.period.xirr_period_return is result.period.xirr_annualized_return is None
    for reasons in (result.period.growth_reason_codes, result.period.xirr_reason_codes):
        assert "flow_coverage_gap" in reasons and "unknown_flow" in reasons
    assert result.period.missing_endpoint
    assert len(result.segments) == 2
    for segment in result.segments:
        assert segment.growth_kopecks == 0
        assert segment.contributions_kopecks == segment.withdrawals_kopecks == 0
        assert segment.xirr_period_return == 0
    assert result.months[1].result.contributions_kopecks is None


def test_overlap_conflicting_endpoints_are_missing_not_arbitrarily_selected(db):
    one, first = save_month(db, candidate_count=0)
    two, second = save_month(db, candidate_count=0, marker="conflict", closing="20000")
    result = read(db, {one: first, two: second})
    assert result.months[0].result.opening_kopecks == 1_000_000
    assert result.months[0].result.closing_kopecks is None
    assert "overlapping_endpoint_conflict" in {gap.code for gap in result.gaps}


def test_bank_outgoing_and_coupon_are_not_double_counted(db):
    intake, original = save_month(db, extra=(("Перевод", "в АО Synthetic bank", "-100"),))
    result = read(db, {intake: original})
    assert result.months[0].result.contributions_kopecks == 100_000
    assert result.months[0].result.withdrawals_kopecks == 10_000
    assert {flow.classification for flow in result.flows} == {
        "external_deposit",
        "external_withdrawal",
    }


def test_seam_mismatch_chain_uses_months_own_opening(db):
    from decimal import ROUND_HALF_UP, localcontext

    april, apr = save_month(db, candidate_count=0)
    may, may_xml = save_month(db, 5, beginning="11000", closing="13000", candidate_count=0)
    result = read(db, {april: apr, may: may_xml})
    assert "seam_mismatch" in result.months[1].flags
    assert result.months[1].result.growth_kopecks == 200_000
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        expected = (1 + result.months[0].result.modified_dietz_return) * (
            1 + Decimal(200_000) / Decimal(1_200_000)
        ) - 1
    assert result.period.chained_return == expected
    assert result.period.growth_kopecks == 400_000


def test_stale_choice_membership_is_not_confirmation(db):
    intake, original = save_month(db)
    flow = read(db, {intake: original}).flows[0]
    reference = flow.source_references[0]
    _, _, _, ordinal, fingerprint = reference.split(":")
    choice = ProvisionalChoice(
        requirement_id=f"candidate:{ordinal}:{fingerprint[:12]}",
        source_references=("wrong-reference",),
        choice="include_as_account_inflow",
    )
    assumptions = ProvisionalAssumptions(schedule_mode="dated", selections=(choice,))
    result = read(db, {intake: original}, {intake: assumptions})
    assert result.flows[0].status == "assumed"
    assert "invalid_assumption_choice" in {gap.code for gap in result.gaps}
    assert result.months[0].result.modified_dietz_return is None


def test_long_report_does_not_invent_intermediate_month_end(db):
    xml = provisional_xml(candidate_count=0)
    filename = "Брокерский 1234567 (01.04.30-30.06.30).xml"
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=xml, filename=filename, request_id="long-report"
        )
    result = read(db)
    assert len(result.months) == 3
    assert result.months[0].result.opening_kopecks == 1_000_000
    assert result.months[0].result.closing_kopecks is None
    assert result.months[1].result.opening_kopecks is None
    assert result.months[1].result.closing_kopecks is None
    assert result.months[2].result.opening_kopecks is None
    assert result.months[2].result.closing_kopecks == 1_121_100
    assert result.period.growth_kopecks == 121_100
    assert result.period.xirr_period_return is not None
    assert len(result.segments) == 1
    segment = result.segments[0]
    assert (segment.start, segment.end) == (date(2030, 3, 31), date(2030, 6, 30))
    assert segment.partial_segment
    assert segment.chained_return is None
    assert segment.chain_reason_codes == ("missing_endpoint",)
    assert {key: asdict(segment)[key] for key in asdict(result.period)} == asdict(result.period)


def test_combined_native_client_operation_uses_signed_amount(db):
    intake, original = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Внесено/Выведено по распоряжению Клиента", "Synthetic inbound", "500"),
            ("Внесено/Выведено по распоряжению Клиента", "Synthetic outbound", "-200"),
        ),
    )
    result = read(db, {intake: original})
    assert result.months[0].result.contributions_kopecks == 50_000
    assert result.months[0].result.withdrawals_kopecks == 20_000
    assert {flow.status for flow in result.flows} == {"assumed"}


def test_segments_split_missing_month_and_keep_own_endpoints_and_flows(db):
    from decimal import ROUND_HALF_UP, localcontext

    april, apr = save_month(db)
    may, may_xml = save_month(db, 5, beginning="11000", closing="13000", candidate_count=0)
    july, jul = save_month(
        db,
        7,
        beginning="14000",
        closing="15000",
        candidate_count=0,
        extra=(("Выведено по распоряжению Клиента", "Synthetic withdrawal", "-500"),),
    )
    before = snapshot(db)
    result = read(db, {april: apr, may: may_xml, july: jul})
    first, second = result.segments
    assert (first.start, first.end) == (date(2030, 3, 31), date(2030, 5, 31))
    assert (second.start, second.end) == (date(2030, 6, 30), date(2030, 7, 31))
    assert first.partial_segment and second.partial_segment
    assert first.contributions_kopecks == 100_000
    assert first.withdrawals_kopecks == 0
    assert first.growth_kopecks == 300_000
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        expected = (1 + result.months[0].result.modified_dietz_return) * (
            1 + Decimal(200_000) / Decimal(1_200_000)
        ) - 1
    assert first.chained_return == expected
    assert second.contributions_kopecks == 0
    assert second.withdrawals_kopecks == 50_000
    assert second.growth_kopecks == 150_000
    assert abs(second.chained_return - result.months[-1].result.modified_dietz_return) < Decimal(
        "1e-58"
    )
    assert all(segment.xirr_annualized_return is not None for segment in result.segments)
    assert all(segment.xirr_period_return is not None for segment in result.segments)
    assert result.period.chained_return is None
    assert snapshot(db) == before


def test_api_segments_complete_partial_endpoint_and_unknown_flows(db):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db, candidate_count=0)
    client = TestClient(create_app(database=db))
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    segment = body["segments"][0]
    assert segment["start"] == "2030-03-31" and segment["end"] == "2030-04-30"
    assert segment["partial_segment"] is False
    assert type(segment["growth_kopecks"]) is int
    for field in ("chained_return", "xirr_annualized_return", "xirr_period_return"):
        assert isinstance(segment[field], str)
        assert segment[field] == body["period"][field]
    save_month(db, 5, candidate_count=0, missing_closing=True)
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    assert len(body["segments"]) == 1
    assert body["segments"][0]["partial_segment"] is True
    save_month(db, 6, extra=(("Unknown", "Synthetic unknown", "17"),))
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    assert len(body["segments"]) == 2
    segment = body["segments"][1]
    assert segment["start"] == "2030-05-31" and segment["end"] == "2030-06-30"
    assert segment["partial_segment"] is True
    for field in (
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "chained_return",
        "xirr_annualized_return",
        "xirr_period_return",
    ):
        assert segment[field] is None
    assert "unknown_flow" in segment["chain_reason_codes"]
    empty = client.get("/api/source-returns/monthly", params={"source_account": "other"}).json()
    assert empty["segments"] == []


@pytest.mark.parametrize("failure", ["unreadable", "ambiguous"])
@pytest.mark.parametrize("coverage", ["interior", "long"])
def test_unknown_source_flows_block_covered_metrics_and_keep_independent_months(
    db, monkeypatch, failure, coverage
):
    april, apr = save_month(db, beginning="8000", candidate_count=0)
    may, may_xml = save_month(
        db,
        5,
        beginning="9211",
        closing="14211",
        candidate_count=0,
        extra=(("Внесено по распоряжению Клиента", "Synthetic funding", "5000"),),
    )
    june, jun = save_month(db, 6, beginning="14211", closing="16711", candidate_count=0)
    originals = {april: apr, may: may_xml, june: jun}
    intact = read(db, originals)
    assert intact.period.contributions_kopecks == 500_000
    assert intact.period.growth_kopecks == 371_100
    assert intact.period.xirr_period_return is not None
    if coverage == "long":
        xml = provisional_xml(beginning="8000", closing="16711", candidate_count=0)
        filename = "Брокерский 1234567 (01.04.30-30.06.30).xml"
        with db.session_factory() as session:
            ack = source_intake.save_intake(
                session, document=xml, filename=filename, request_id="long-overlap"
            )
        failed = ack["intake_id"]
        originals[failed] = (xml, filename)
        # An independent month outside the unreadable report must remain usable.
        save_month(db, 7, beginning="16711", closing="17711", candidate_count=0)
        affected = (0, 1, 2)
    else:
        failed = may
        affected = (1,)
    if failure == "unreadable":
        originals[failed] = (b"corrupt synthetic original", originals[failed][1])
        expected_gap = "source_reader_unavailable"
    else:
        from copy import deepcopy

        reader = source_intake.read_intake

        def ambiguous(session, intake_id):
            view = reader(session, intake_id)
            if intake_id == failed:
                view = deepcopy(view)
                view["document"]["positions"][0]["source_account"] = "other-synthetic-account"
            return view

        monkeypatch.setattr(source_intake, "read_intake", ambiguous)
        expected_gap = "native_source_scope_ambiguous"
    before = snapshot(db)
    result = read(db, originals)
    assert expected_gap in {gap.code for gap in result.gaps}
    for index, row in enumerate(result.months):
        if index in affected:
            assert row.result.contributions_kopecks is None
            assert row.result.withdrawals_kopecks is None
            assert row.result.growth_kopecks is None
            assert row.result.modified_dietz_return is None
            assert "unknown_flow" in row.result.reason_codes
        else:
            assert row.result.growth_kopecks is not None
            assert row.result.modified_dietz_return is not None
            assert "unknown_flow" not in row.result.reason_codes
    assert result.period.contributions_kopecks is None
    assert result.period.withdrawals_kopecks is None
    assert result.period.growth_kopecks is None
    assert result.period.chained_return is None
    assert result.period.xirr_annualized_return is None
    assert result.period.xirr_period_return is None
    for reasons in (
        result.period.chain_reason_codes,
        result.period.growth_reason_codes,
        result.period.xirr_reason_codes,
    ):
        assert "unknown_flow" in reasons
    if coverage == "long":
        (segment,) = result.segments
        assert segment.partial_segment
        for field in (
            "contributions_kopecks",
            "withdrawals_kopecks",
            "growth_kopecks",
            "chained_return",
            "xirr_annualized_return",
            "xirr_period_return",
        ):
            assert getattr(segment, field) is None
        assert "unknown_flow" in segment.growth_reason_codes
        assert "unknown_flow" in segment.xirr_reason_codes
    else:
        assert len(result.segments) == 2
        assert all(segment.growth_kopecks is not None for segment in result.segments)
        assert all(segment.xirr_period_return is not None for segment in result.segments)
    assert snapshot(db) == before


def test_unreadable_overlap_blocks_segment_even_with_available_endpoints(db):
    one, _ = save_month(db)
    two, second = save_month(db, marker="unreadable-overlap")
    save_month(db, 5, candidate_count=0)
    result = read(db, {two: (b"corrupt synthetic original", second[1])})
    assert not result.months[0].result.missing_endpoint
    assert result.months[0].result.growth_kopecks is None
    assert result.months[1].result.growth_kopecks is not None
    (segment,) = result.segments
    assert segment.growth_kopecks is None
    assert segment.contributions_kopecks is None
    assert segment.xirr_period_return is None
    assert "unknown_flow" in segment.growth_reason_codes
    assert "unknown_flow" in segment.xirr_reason_codes
    assert one != two


@pytest.mark.parametrize("unknown_flow", [False, True])
def test_api_long_report_segment_retains_outer_metrics_and_flow_blockers(db, unknown_flow):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    extra = (("Unknown", "Synthetic unknown", "17"),) if unknown_flow else ()
    xml = provisional_xml(candidate_count=0, extra_money=extra)
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=xml,
            filename="Брокерский 1234567 (01.04.30-30.06.30).xml",
            request_id="long-api",
        )
    before = snapshot(db)
    response = TestClient(create_app(database=db)).get(
        "/api/source-returns/monthly", params={"source_account": ACCOUNT}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    (segment,) = body["segments"]
    assert segment["partial_segment"]
    assert segment["start"] == "2030-03-31"
    assert segment["end"] == "2030-06-30"
    assert all(row["missing_endpoint"] for row in body["months"])
    assert {key: segment[key] for key in body["period"]} == body["period"]
    assert segment["chained_return"] is None
    if unknown_flow:
        for field in (
            "contributions_kopecks",
            "withdrawals_kopecks",
            "growth_kopecks",
            "xirr_annualized_return",
            "xirr_period_return",
        ):
            assert segment[field] is None
        assert "unknown_flow" in segment["growth_reason_codes"]
        assert "unknown_flow" in segment["xirr_reason_codes"]
    else:
        assert segment["contributions_kopecks"] == 0
        assert segment["growth_kopecks"] == 121_100
        assert isinstance(segment["xirr_period_return"], str)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "operation,amount",
    [
        ("Внесено по распоряжению Клиента", "500"),
        ("Выведено по распоряжению Клиента", "-200"),
        ("Unknown", "17"),
    ],
)
def test_non_rub_money_blocks_month_period_and_segment_but_not_rub_neighbor(db, operation, amount):
    xml = ET.fromstring(
        provisional_xml(candidate_count=0, extra_money=((operation, "Synthetic USD row", amount),))
    )
    xml.findall(".//{MyBroker}p_code[@volume]")[-1].set("p_code", "USD")
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=ET.tostring(xml, encoding="utf-8"),
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="usd-money",
        )
    save_month(db, 5, beginning="10211", closing="11211", candidate_count=0)
    before = snapshot(db)
    result = read(db)
    foreign, rub = result.months
    reasons = {"currency_unsupported", "unknown_flow"}
    assert reasons <= set(foreign.flags)
    assert reasons <= set(foreign.result.reason_codes)
    for field in (
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "modified_dietz_return",
    ):
        assert getattr(foreign.result, field) is None
    assert rub.result.contributions_kopecks == 0
    assert rub.result.growth_kopecks == 100_000
    assert rub.result.modified_dietz_return is not None
    assert not reasons.intersection(rub.flags)
    (segment,) = result.segments
    assert (segment.start, segment.end) == (date(2030, 3, 31), date(2030, 5, 31))
    for totals in (result.period, segment):
        for field in (
            "contributions_kopecks",
            "withdrawals_kopecks",
            "growth_kopecks",
            "chained_return",
            "xirr_annualized_return",
            "xirr_period_return",
        ):
            assert getattr(totals, field) is None
        for field in ("chain_reason_codes", "growth_reason_codes", "xirr_reason_codes"):
            assert reasons <= set(getattr(totals, field))
    assert not result.flows
    assert any(
        gap.code == "currency_unsupported" and gap.month == date(2030, 4, 1) for gap in result.gaps
    )
    assert snapshot(db) == before


@pytest.mark.parametrize("currency", ["RUR", " rur ", " RuB "])
def test_ruble_currency_alias_deposit_counts_as_rub_flow(db, currency):
    save_month(db, money_currency=currency)
    before = snapshot(db)
    result = read(db)
    row = result.months[0]
    assert row.result.contributions_kopecks == 100_000
    assert row.result.growth_kopecks == 21_100
    assert row.result.modified_dietz_return is not None
    assert "currency_unsupported" not in row.flags
    assert "currency_unsupported" not in {gap.code for gap in result.gaps}
    assert len(result.flows) == 1 and result.flows[0].included
    assert snapshot(db) == before
    from hermes_finance.services.source_money_classifications import choose_classification

    with db.session_factory() as session:
        intake = result.flows[0].source_references[0].split(":")[1]
        choose_classification(
            session, int(intake), result.flows[0].source_references[0], "external_deposit"
        )
    confirmed = read(db)
    assert confirmed.flows[0].status == "confirmed"
    assert confirmed.months[0].result.contributions_kopecks == 100_000


def test_currency_gap_in_one_segment_does_not_null_independent_rub_segment(db):
    save_month(db, money_currency="USD")
    # Missing May separates the source history into independent segments.
    save_month(db, 6, beginning="11000", closing="12000", candidate_count=0)
    before = snapshot(db)
    result = read(db)
    foreign, rub = result.segments
    reasons = {"currency_unsupported", "unknown_flow"}
    assert (foreign.start, foreign.end) == (date(2030, 3, 31), date(2030, 4, 30))
    assert (rub.start, rub.end) == (date(2030, 5, 31), date(2030, 6, 30))
    for field in (
        "contributions_kopecks",
        "withdrawals_kopecks",
        "growth_kopecks",
        "chained_return",
        "xirr_annualized_return",
        "xirr_period_return",
    ):
        assert getattr(foreign, field) is None
        assert getattr(rub, field) is not None
    for field in ("chain_reason_codes", "growth_reason_codes", "xirr_reason_codes"):
        assert reasons <= set(getattr(foreign, field))
        assert not reasons.intersection(getattr(rub, field))
    assert rub.contributions_kopecks == 0 and rub.withdrawals_kopecks == 0
    assert rub.growth_kopecks == 100_000
    assert snapshot(db) == before


def test_overlapping_rur_and_rub_deposits_are_one_flow(db):
    save_month(db, money_currency="RUB")
    save_month(db, money_currency=" rur ", marker="legacy-currency-copy")
    result = read(db)
    assert len(result.flows) == 1 and len(result.flows[0].source_references) == 2
    assert result.months[0].result.contributions_kopecks == 100_000
    assert not {"currency_unsupported", "invalid_money_row"}.intersection(
        gap.code for gap in result.gaps
    )


@pytest.mark.parametrize("second_start,has_gap", [(15, False), (16, True)])
def test_flow_coverage_uses_date_union_separately_from_monthly_values(db, second_start, has_gap):
    xml_root = ET.fromstring(provisional_xml(candidate_count=0))
    for index, period in enumerate(("01.04.30-14.05.30", f"{second_start}.05.30-30.06.30")):
        xml_root.set("synthetic_marker", str(index))
        xml = ET.tostring(xml_root, encoding="utf-8")
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml,
                filename=f"Брокерский 1234567 ({period}).xml",
                request_id=f"coverage-union-{index}",
            )
    result = read(db)
    assert result.period.missing_endpoint
    assert result.period.chained_return is None
    assert result.months[0].result.opening_kopecks is not None
    assert result.months[-1].result.closing_kopecks is not None
    if has_gap:
        assert result.period.growth_kopecks is None
        assert result.period.xirr_period_return is None
        assert result.period.contributions_kopecks is None
        assert "flow_coverage_gap" in result.period.xirr_reason_codes
        assert "flow_coverage_gap" in result.months[1].flags
    else:
        assert result.period.growth_kopecks == 121_100
        assert result.period.xirr_period_return is not None
        assert result.period.contributions_kopecks == 0
        assert "flow_coverage_gap" not in {gap.code for gap in result.gaps}


@pytest.mark.parametrize(
    ("periods", "has_gap"),
    [
        (("10.04.30-20.06.30",), False),
        (("10.04.30-14.05.30", "15.05.30-20.06.30"), False),
        (("10.04.30-14.05.30", "16.05.30-20.06.30"), True),
    ],
)
def test_partial_calendar_edges_do_not_invalidate_covered_period_flows(db, periods, has_gap):
    for index, period in enumerate(periods):
        xml = provisional_xml(candidate_count=1 if index == 0 else 0)
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml,
                filename=f"Брокерский 1234567 ({period}).xml",
                request_id=f"partial-period-{index}",
            )
    before = snapshot(db)
    result = read(db)
    assert len(result.months) == 3
    assert all(row.result.missing_endpoint for row in result.months)
    # The calendar months at both edges still lack full-month flow coverage.
    for row in (result.months[0], result.months[-1]):
        assert row.result.contributions_kopecks is None
        assert "flow_coverage_gap" in row.flags
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is result.period.xirr_period_return is None
    if has_gap:
        assert result.period.contributions_kopecks is result.period.withdrawals_kopecks is None
    else:
        assert result.period.contributions_kopecks == 100_000
        assert result.period.withdrawals_kopecks == 0
    for reasons in (result.period.growth_reason_codes, result.period.xirr_reason_codes):
        assert ("flow_coverage_gap" in reasons) == has_gap
        assert ("unknown_flow" in reasons) == has_gap
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "structure,expected",
    [
        ("Transfers", "4_Transfers_unsupported"),
        ("UFSR", "5_UFSR_unsupported"),
        ("unparsed", "unparsed_source_rows"),
        ("unknown", "unknown_section"),
        ("position", "position_row_unclassified"),
    ],
)
@pytest.mark.parametrize("long_report", [False, True])
def test_financial_parser_blockers_null_only_covered_months(db, structure, expected, long_report):
    root = ET.fromstring(provisional_xml(candidate_count=0))
    if structure in {"Transfers", "UFSR"}:
        outer = "Trades3" if structure == "Transfers" else "Trades4"
        ET.SubElement(root.find(f"{{MyBroker}}{outer}/{{MyBroker}}Report"), "{MyBroker}Synthetic")
    elif structure == "unparsed":
        ET.SubElement(root.find("{MyBroker}Trades2/{MyBroker}Report"), "{MyBroker}rn")
    elif structure == "unknown":
        ET.SubElement(root, "{MyBroker}SyntheticSection")
    else:
        collection = root.find(".//{MyBroker}Details_Collection")
        ET.SubElement(collection, "{MyBroker}Details", {"acc_code": ACCOUNT})
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session,
            document=ET.tostring(root, encoding="utf-8"),
            filename=f"Брокерский 1234567 (01.04.30-{'31.05.30' if long_report else '30.04.30'}).xml",
            request_id="financial-gap",
        )
    if long_report:
        # Valid overlapping monthly statements cannot erase a bad document's uncertainty.
        save_month(db, candidate_count=0)
        save_month(db, 5, candidate_count=0)
    save_month(db, 6 if long_report else 5, candidate_count=0)
    before = snapshot(db)
    result = read(db)
    for row in result.months[:-1]:
        assert row.result.contributions_kopecks is row.result.withdrawals_kopecks is None
        assert row.result.growth_kopecks is row.result.modified_dietz_return is None
        assert {expected, "unknown_flow"} <= set(row.flags)
        assert any(
            gap.code == expected
            and gap.intake_id == ack["intake_id"]
            and gap.month == row.result.closing_date.replace(day=1)
            for gap in result.gaps
        )
    assert result.months[-1].result.modified_dietz_return is not None
    assert result.months[-1].result.growth_kopecks is not None
    affected_totals = [result.period]
    for segment in result.segments:
        if segment.start < result.months[-1].result.opening_date:
            affected_totals.append(segment)
        else:
            assert segment.growth_kopecks is not None
            assert segment.xirr_period_return is not None
    for totals in affected_totals:
        assert totals.growth_kopecks is None
        assert totals.contributions_kopecks is totals.withdrawals_kopecks is None
        assert totals.xirr_annualized_return is totals.xirr_period_return is None
        for reasons in (
            totals.growth_reason_codes,
            totals.xirr_reason_codes,
            totals.chain_reason_codes,
        ):
            assert {expected, "unknown_flow"} <= set(reasons)
    assert snapshot(db) == before


def test_non_financial_source_status_does_not_create_flow_uncertainty(db, monkeypatch):
    from copy import deepcopy

    save_month(db, candidate_count=0)
    reader = source_intake.read_intake

    def non_financial_status(session, intake_id):
        view = deepcopy(reader(session, intake_id))
        view["document"]["syntax_blockers"] = ["source_only", "review_pending"]
        return view

    monkeypatch.setattr(source_intake, "read_intake", non_financial_status)
    result = read(db)
    assert result.months[0].result.modified_dietz_return is not None
    assert result.period.growth_kopecks == 121_100
    assert result.period.xirr_period_return is not None
    assert not result.gaps


def test_service_reaggregation_withholds_two_negative_dietz_factors(db):
    for month, day, end in ((2, 27, 28), (3, 30, 31)):
        xml = (
            provisional_xml(
                beginning="100",
                closing="100",
                rub=("0", "0"),
                candidate_count=0,
                extra_money=(("Внесено по распоряжению Клиента", "Synthetic funding", "300"),),
            )
            .decode()
            .replace("2030-04-15", f"2030-{month:02d}-{day:02d}")
        )
        xml = xml.replace("2030-04-", f"2030-{month:02d}-").replace(
            ".04.2030", f".{month:02d}.2030"
        )
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=xml.encode(),
                filename=f"Брокерский 1234567 (01.{month:02d}.30-{end}.{month:02d}.30).xml",
                request_id=f"negative-factor-{month}",
            )
    result = read(db)
    assert all(row.result.modified_dietz_return < -1 for row in result.months)
    for totals in (result.period, *result.segments):
        assert totals.chained_return is None
        assert totals.chain_reason_codes == ("negative_dietz_factor",)
        assert totals.contributions_kopecks == 60_000
        assert totals.growth_kopecks == -60_000
        assert not totals.growth_reason_codes
        assert "negative_dietz_factor" not in totals.xirr_reason_codes


def test_service_reaggregation_allows_exact_zero_dietz_factor(db):
    xml = provisional_xml(beginning="100", closing="0", rub=("0", "0"), candidate_count=0)
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=xml,
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="zero-factor",
        )
    result = read(db)
    assert result.months[0].result.modified_dietz_return == -1
    assert result.period.chained_return == -1
    assert result.period.chain_reason_codes == ()


@pytest.fixture(scope="module")
def astra_results(tmp_path_factory, source_returns_database_factory):
    """Every XML reaches real parsing/intake/readers in a separate synthetic DB."""
    results = {}
    for case in ASTRA_CASES:
        database = source_returns_database_factory(tmp_path_factory.mktemp(case["case"]))
        try:
            results[case["case"]] = astra_replay(database, case)
        finally:
            database.engine.dispose()
    return results


@pytest.mark.parametrize("case", [case["case"] for case in ASTRA_CASES])
def test_astra_hunt_replays_every_fixture(astra_results, case):
    result = astra_results[case]
    if case == "08_missing_money":
        assert result["parser_error"] == "required_section_invalid"
        assert result["calculation"] == "not_run_parser_rejected"
        return
    assert "parser_error" not in result
    assert result["monthly"]["authority"] == "provisional"
    assert result["monthly"]["financial_authority"] == "none"
    # Source-only Save never grants accepted portfolio valuations or flow coverage.
    assert result["exact_xirr"]["annualized_rate"] is None
    assert result["exact_twrr"]["return_rate"] is None
    for metric in ("exact_xirr", "exact_twrr"):
        assert result[metric]["availability"] == "not_computable"
        assert "not_computable_scope_coverage_incomplete" in result[metric]["reason_codes"]


@pytest.mark.parametrize(
    "case,reason",
    [
        ("02_unknown", "unrecognized_money"),
        ("05_usd_deposit", "currency_unsupported"),
        ("06_fx_zero_rate", "currency_unsupported"),
        ("12_partial_month", "flow_coverage_gap"),
        ("13_negative_deposit", "invalid_external_flow"),
        ("14_zero_deposit", "invalid_external_flow"),
        ("19_partial_redemption", "unrecognized_money"),
        ("24_transfer_section", "4_Transfers_unsupported"),
    ],
)
def test_astra_hunt_existing_guards(astra_results, case, reason):
    result = astra_results[case]["monthly"]
    assert reason in {gap["code"] for gap in result["gaps"]}
    assert result["period"]["xirr_period_return"] is None
    assert result["period"]["chained_return"] is None
    assert all(row["result"]["modified_dietz_return"] is None for row in result["months"])


@pytest.mark.parametrize("case", ["01_control", "07_empty_money", "16_zero_fee"])
def test_astra_hunt_known_zero_is_not_missing(astra_results, case):
    result = astra_results[case]["monthly"]
    assert result["period"]["growth_kopecks"] == 90_000
    assert result["period"]["chained_return"] == Decimal("0.09")
    assert abs(result["period"]["xirr_period_return"] - Decimal("0.09")) < Decimal("1e-25")
    assert not result["gaps"]


def test_astra_hunt_occurrences_signs_and_unknown_identity(astra_results):
    duplicate = astra_results["10_duplicate_money"]["monthly"]
    assert len(duplicate["flows"]) == 2
    assert duplicate["period"]["contributions_kopecks"] == 20_000
    withdrawal = astra_results["15_negative_withdrawal"]["monthly"]["period"]
    assert withdrawal["withdrawals_kopecks"] == 10_000
    assert withdrawal["growth_kopecks"] == 100_000
    assert astra_results["09_empty_positions"]["monthly"]["period"]["xirr_period_return"] is None
    unknown = astra_results["20_unknown_security"]
    assert unknown["monthly"]["period"]["growth_kopecks"] == 90_000
    instrument = unknown["instruments"]["instruments"][0]
    assert instrument["instrument_type"] is None
    assert "instrument_type_unknown" in instrument["months"][0]["flags"]
    assert instrument["months"][0]["approximate"]


@pytest.mark.parametrize(
    "case,field",
    [
        ("17_nkd_buy", "buys_cost_kopecks"),
        ("18_nkd_sell", "sells_proceeds_kopecks"),
    ],
)
def test_astra_hunt_excludes_shaped_total_does_not_override_mybroker_definition(
    astra_results, case, field
):
    result = astra_results[case]
    assert result["classifications"] == ["trade_settlement"]
    assert result["monthly"]["months"][0]["coupons_kopecks"] == 0
    assert result["monthly"]["period"]["contributions_kopecks"] == 0
    instrument = result["instruments"]["instruments"][0]["months"][0]
    # Retain the frozen synthetic XML: explicit P=200, T=200, N=5 conflicts
    # with MyBroker T-includes-N. Never infer excludes from this arithmetic.
    assert instrument[field] is None
    assert {"trade_nkd_basis_unknown", "trade_nkd_basis_conflict"} <= set(instrument["flags"])


def test_astra_hunt_missing_may_does_not_become_zero_flows(db):
    for case in (ASTRA_CASES[0], ASTRA_CASES[-1]):
        with db.session_factory() as session:
            source_intake.save_intake(
                session,
                document=(ASTRA_ROOT / (case["case"] + ".xml")).read_bytes(),
                filename=case["filename"],
                request_id=case["case"],
            )
    result = read(db)
    assert "flow_coverage_gap" in result.period.xirr_reason_codes
    assert result.period.xirr_period_return is None
    assert result.period.chained_return is None
    assert result.period.growth_kopecks is None
    assert result.period.contributions_kopecks is None
    assert len(result.segments) == 2
    assert all(segment.xirr_period_return is not None for segment in result.segments)


@pytest.mark.parametrize("reattached", [False, True], ids=["saved", "reattached"])
@pytest.mark.parametrize(
    "case",
    [
        "03_typo_withdrawal",
        "11_duplicate_position",
        "21_outside_period",
        "22_hidden_amount",
        "23_hidden_wrapper",
    ],
)
def test_astra_hunt_uncertain_import_must_withhold_returns(astra_results, case, reattached):
    result = astra_results[case]
    if "parser_error" in result:
        return  # Rejecting the unsupported/ambiguous source is also a safe resolution.
    period = result["reattached_period"] if reattached else result["monthly"]["period"]
    assert period["xirr_period_return"] is None
    assert period["xirr_annualized_return"] is None
    assert period["chained_return"] is None
    assert period["growth_kopecks"] is None
    assert period["xirr_reason_codes"]
    if not reattached:
        assert all(
            row["result"]["modified_dietz_return"] is None for row in result["monthly"]["months"]
        )
        expected = {
            "03_typo_withdrawal": "unrecognized_money",
            "11_duplicate_position": "duplicate_position",
            "21_outside_period": "invalid_external_flow",
            "22_hidden_amount": "unparsed_source_rows",
            "23_hidden_wrapper": "unparsed_source_rows",
        }[case]
        assert expected in {gap["code"] for gap in result["monthly"]["gaps"]}
        for instrument in result["instruments"]["instruments"]:
            assert all(row["total_kopecks"] is None for row in instrument["months"])
        if case == "11_duplicate_position":
            assert result["row_counts"]["positions"] == 2
            instrument = result["instruments"]["instruments"][0]["months"][0]
            assert instrument["opening_quantity"] is instrument["closing_quantity"] is None
            assert (
                instrument["opening_value_kopecks"] is instrument["closing_value_kopecks"] is None
            )
            assert "duplicate_position" in instrument["flags"]


@pytest.mark.parametrize("reattached", [False, True], ids=["saved", "reattached"])
def test_astra_hunt_account_transfer_is_external_to_account(astra_results, reattached):
    result = astra_results["04_account_transfer"]
    if "parser_error" in result:
        return
    period = result["reattached_period"] if reattached else result["monthly"]["period"]
    if period["xirr_period_return"] is None:
        assert period["xirr_reason_codes"]
        assert period["chained_return"] is None
    else:
        # Once account crossing is supported, a withdrawal explains the entire NAV change.
        assert period["withdrawals_kopecks"] == 100_000
        assert period["growth_kopecks"] == 0
        assert period["xirr_period_return"] == 0
        assert period["chained_return"] == 0


@pytest.mark.parametrize("legacy", [False, True], ids=["current", "unflagged_saved_rows"])
@pytest.mark.parametrize("overlap", [False, True])
def test_duplicate_positions_block_endpoints_even_with_clean_overlap(
    db, monkeypatch, legacy, overlap
):
    from copy import deepcopy

    root = ET.fromstring(provisional_xml(beginning="100", closing="110", candidate_count=0))
    collection = root.find(".//{MyBroker}Details_Collection")
    collection.append(deepcopy(collection.find("{MyBroker}Details[@ISIN1]")))
    with db.session_factory() as session:
        intake = source_intake.save_intake(
            session,
            document=ET.tostring(root),
            filename="Брокерский 1234567 (01.04.30-30.04.30).xml",
            request_id="duplicate-position-source",
        )["intake_id"]
    if overlap:
        save_month(db, beginning="100", closing="110", candidate_count=0, marker="clean-copy")
    if legacy:
        reader = source_intake.read_intake

        def unflagged_rows(session, intake_id):
            view = deepcopy(reader(session, intake_id))
            if intake_id == intake:
                view["document"]["endpoint_conflicts"] = []
            return view

        monkeypatch.setattr(source_intake, "read_intake", unflagged_rows)
    before = snapshot(db)
    result = read(db)
    row = result.months[0].result
    assert row.opening_kopecks is row.closing_kopecks is None
    assert row.growth_kopecks is row.modified_dietz_return is None
    assert "duplicate_position" in row.reason_codes
    assert result.period.growth_kopecks is result.period.xirr_period_return is None
    assert any(gap.code == "duplicate_position" and gap.intake_id == intake for gap in result.gaps)
    assert snapshot(db) == before


@pytest.mark.parametrize("month", [2, 4, 12])
@pytest.mark.parametrize("filename", ["renamed.xml", "Брокерский 1234567 (31.02.30-31.03.30).xml"])
def test_inferred_periods_withhold_calendar_month_returns(db, month, filename):
    from datetime import timedelta

    intake, original = save_month(db, month, filename=filename)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
    first = date(2030, month, 1)
    last = date(2030, month, calendar.monthrange(2030, month)[1])
    assert (view["covered_from"], view["covered_to"]) == (first.isoformat(), last.isoformat())
    assert view["document"]["warnings"] == ["period_inferred_from_content"]
    for attached in (None, {intake: original}):
        result = read(db, originals=attached)
        assert len(result.months) == 1
        row = result.months[0].result
        assert (row.opening_date, row.closing_date) == (first - timedelta(days=1), last)
        assert row.opening_kopecks is row.closing_kopecks is None
        assert row.growth_kopecks is row.modified_dietz_return is None
        assert row.missing_endpoint
        assert {"source_period_inferred", "missing_endpoint", "unknown_flow"} <= set(
            row.reason_codes
        )
        assert result.period.growth_kopecks is result.period.chained_return is None
        assert result.period.xirr_annualized_return is result.period.xirr_period_return is None
        assert result.period.missing_endpoint
        assert "source_period_inferred" in result.period.growth_reason_codes
        inferred_gaps = [gap for gap in result.gaps if gap.code == "source_period_inferred"]
        assert len(inferred_gaps) == 1
        gap = inferred_gaps[0]
        assert gap.intake_id == intake
        assert gap.month == first
        assert gap.message == (
            "Statement period was inferred from activity dates; "
            "opening and closing balance dates are unverified."
        )


@pytest.mark.parametrize(
    "month,statement_filename",
    [
        (2, "Брокерский 1234567 (01.01.30-31.03.30).xml"),
        (1, "Брокерский 1234567 (16.01.30-31.01.30).xml"),
    ],
)
def test_renamed_long_and_partial_statements_cannot_supply_monthly_endpoints(
    db, month, statement_filename
):
    from hermes_finance.statement_import.mybroker import parse_mybroker

    # Synthetic balances belong to the actual report's outer dates. Activity
    # occurs only on the 17th, so renaming loses both report-period boundaries.
    raw = (
        provisional_xml(candidate_count=0)
        .decode()
        .replace(".04.2030", f".{month:02d}.2030")
        .replace("2030-04-", f"2030-{month:02d}-")
        .replace(f"15.{month:02d}.2030", f"17.{month:02d}.2030")
        .encode()
    )
    actual = parse_mybroker(raw, statement_filename)
    assert actual["covered_from"] == ("2030-01-01" if month == 2 else "2030-01-16")
    assert actual["covered_to"] == ("2030-03-31" if month == 2 else "2030-01-31")
    assert "period_inferred_from_content" not in actual.get("warnings", [])
    with db.session_factory() as session:
        intake = source_intake.save_intake(
            session, document=raw, filename="x.xml", request_id="renamed-outer-balances"
        )["intake_id"]
    save_month(db, month + 1, candidate_count=0)
    before = snapshot(db)
    for attached in (None, {intake: (raw, "x.xml")}):
        result = read(db, originals=attached)
        row = result.months[0].result
        assert row.closing_date.month == month
        assert row.opening_kopecks is row.closing_kopecks is None
        assert row.growth_kopecks is row.modified_dietz_return is None
        assert row.missing_endpoint
        assert "source_period_inferred" in row.reason_codes
        assert result.period.growth_kopecks is result.period.chained_return is None
        assert result.period.xirr_annualized_return is result.period.xirr_period_return is None
        # The separate valid monthly statement remains independently usable.
        assert result.months[1].result.modified_dietz_return is not None
        assert len(result.segments) == 1
        assert result.segments[0].growth_kopecks is not None
    assert snapshot(db) == before


@pytest.mark.parametrize("mismatch", [False, True])
def test_valid_filename_range_retains_computed_return_despite_period_warning(db, mismatch):
    raw = provisional_xml(candidate_count=0)
    if mismatch:
        raw = raw.replace(b".04.2030", b".05.2030")
    filename = "Брокерский 1234567 (01.04.30-30.04.30).xml"
    with db.session_factory() as session:
        intake = source_intake.save_intake(
            session, document=raw, filename=filename, request_id="valid-filename-period"
        )["intake_id"]
        view = source_intake.read_intake(session, intake)
    assert view["document"].get("warnings", []) == (
        ["filename_period_mismatch"] if mismatch else []
    )
    for attached in (None, {intake: (raw, filename)}):
        result = read(db, originals=attached)
        row = result.months[0].result
        assert row.growth_kopecks == 121_100
        assert row.modified_dietz_return is not None
        assert not row.missing_endpoint
        assert "source_period_inferred" not in row.reason_codes
        assert result.period.chained_return is not None


@pytest.mark.parametrize("overlap", [False, True])
def test_inferred_multimonth_period_blocks_every_covered_month(db, overlap):
    raw = provisional_xml().replace(b"2030-04-15", b"2030-05-15")
    with db.session_factory() as session:
        intake = source_intake.save_intake(
            session, document=raw, filename="x.xml", request_id="inferred-multimonth"
        )["intake_id"]
        view = source_intake.read_intake(session, intake)
    assert (view["covered_from"], view["covered_to"]) == ("2030-04-01", "2030-05-31")
    if overlap:
        for month in (4, 5):
            save_month(db, month, candidate_count=0)
    save_month(db, 6, candidate_count=0)
    before = snapshot(db)
    for attached in (None, {intake: (raw, "x.xml")}):
        result = read(db, originals=attached)
        for row in result.months[:2]:
            assert row.result.growth_kopecks is row.result.modified_dietz_return is None
            assert row.result.contributions_kopecks is row.result.withdrawals_kopecks is None
            assert row.result.missing_endpoint is not overlap
            assert {"source_period_inferred", "unknown_flow"} <= set(row.flags)
            assert any(
                gap.code == "source_period_inferred"
                and gap.intake_id == intake
                and gap.month == row.result.closing_date.replace(day=1)
                and gap.message
                for gap in result.gaps
            )
        assert result.period.growth_kopecks is result.period.chained_return is None
        assert result.period.xirr_annualized_return is result.period.xirr_period_return is None
        assert result.months[-1].result.modified_dietz_return is not None
        for segment in result.segments:
            if segment.start < date(2030, 5, 31):
                assert segment.growth_kopecks is segment.chained_return is None
                assert "source_period_inferred" in segment.growth_reason_codes
            else:
                assert segment.chained_return is not None
    assert snapshot(db) == before


def test_cash_event_outside_overlapping_filename_keeps_out_of_range_semantics(astra_results):
    from hermes_finance.statement_import.mybroker import parse_mybroker

    case = next(case for case in ASTRA_CASES if case["case"] == "21_outside_period")
    source = parse_mybroker((ASTRA_ROOT / (case["case"] + ".xml")).read_bytes(), case["filename"])
    assert (source["covered_from"], source["covered_to"]) == ("2030-04-01", "2030-04-30")
    # Only the May cash event is dated: filename stays authoritative; zero overlap is advisory.
    assert source.get("warnings") == ["filename_period_mismatch"]
    result = astra_results[case["case"]]
    assert "parser_error" not in result
    assert "invalid_external_flow" in {gap["code"] for gap in result["monthly"]["gaps"]}
    for period in (result["monthly"]["period"], result["reattached_period"]):
        assert period["growth_kopecks"] is None
        assert period["chained_return"] is None
        assert period["xirr_period_return"] is None


@pytest.mark.parametrize(
    "income",
    [
        (),
        (("Купон", "Synthetic coupon", "7"),),
        (("Перевод", "Дивиденды Synthetic issuer", "12.34"),),
        (("Купон", "Synthetic coupon", "7"), ("Перевод", "Дивиденды Synthetic issuer", "12.34")),
    ],
)
def test_unrecognized_money_nulls_income_subtotals_only_in_affected_month(db, income):
    from fastapi.testclient import TestClient

    from hermes_finance.main import create_app

    save_month(db, 4, candidate_count=0)
    save_month(
        db,
        5,
        candidate_count=0,
        extra=(*income, ("Перевод", "Synthetic unrecognized payment", "17")),
    )
    save_month(db, 6, candidate_count=0, extra=income)
    before = snapshot(db)
    response = TestClient(create_app(database=db)).get(
        "/api/source-returns/monthly", params={"source_account": ACCOUNT}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    april, may, june = body["months"]
    assert april["coupons_kopecks"] == april["dividends_kopecks"] == 0
    assert may["coupons_kopecks"] is may["dividends_kopecks"] is None
    assert "unknown_flow" in may["flags"]
    assert june["coupons_kopecks"] == (700 if any(row[0] == "Купон" for row in income) else 0)
    assert june["dividends_kopecks"] == (1234 if any(row[0] == "Перевод" for row in income) else 0)
    assert "unknown_flow" not in april["flags"] + june["flags"]
    assert body["period"]["growth_kopecks"] is None
    assert body["period"]["contributions_kopecks"] is None
    assert "unknown_flow" in body["period"]["growth_reason_codes"]
    assert any(
        gap["code"] == "unrecognized_money" and gap["month"] == "2030-05-01" for gap in body["gaps"]
    )
    assert snapshot(db) == before
