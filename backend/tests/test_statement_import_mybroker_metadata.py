"""Synthetic #789/#792 exact tree and frozen-receipt acceptance."""

import hashlib
import json
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_mybroker import FILENAME, fixture, native_money_xml, node, repo_fixture
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_identity import inventory

from hermes_finance.main import create_app
from hermes_finance.services.mybroker_import import (
    _prepare,
    parse_import_original,
    preview_mybroker,
    read_mybroker_import,
    read_mybroker_lineage,
    stage_mybroker,
)
from hermes_finance.statement_import.mybroker import (
    MyBrokerError,
    canonical,
    digest,
    parse_mybroker,
)
from hermes_finance.statement_import.mybroker_metadata import parse_section_metadata


def section_setup(database, *, raw=None, base_id="section-base", supporting=None):
    from test_statement_import_mybroker_endpoints import (
        _broker_month_apply,
        _broker_month_preview,
        _broker_month_setup,
        broker_month_xml,
    )

    client = TestClient(create_app(database=database))
    scope = _broker_month_setup(database)
    raw = raw or metadata_xml(broker_month_xml())
    plan = _broker_month_preview(client, scope, raw, supporting=supporting)
    response = _broker_month_apply(
        client, scope, plan, raw, request_id=base_id, supporting=supporting
    )
    assert response.status_code == 200, response.text
    base = response.json()
    intent = {
        "contract_version": "mybroker-section-disposition-v1",
        **scope,
        "base_request_id": base_id,
        "import_id": base["import_id"],
        "sections": [{"section": "4_Transfers"}, {"section": "5_UFSR"}],
    }
    return client, intent, raw


def section_preview(client, intent, raw, *, filename=FILENAME):
    return client.post(
        "/api/broker-months/preview",
        files={"file": (filename, raw, "application/xml")},
        data={"intent": json.dumps(intent)},
    )


def section_apply(client, intent, raw, plan, *, request_id="section-proof", filename=FILENAME):
    return client.post(
        "/api/broker-months/apply",
        files={"file": (filename, raw, "application/xml")},
        data={
            "confirmation": json.dumps(
                {
                    **intent,
                    "confirmation_digest": plan["confirmation_digest"],
                    "request_id": request_id,
                }
            )
        },
    )


def test_section_receipt_original_preview_get_close_and_ten_exact_replays(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    client, intent, raw = section_setup(database)
    before = _all_month_tables(database)
    response = section_preview(client, intent, raw)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["can_apply"], plan
    assert [s["raw_inventory"] for s in plan["proof"]["sections"]] == [1, 3]
    assert _all_month_tables(database) == before
    base_url = f"/api/broker-months/{intent['base_request_id']}"
    assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(
        client.get(base_url).json()["exceptions"]
    )
    month_url = f"/api/months/{intent['reporting_month_id']}"
    assert not client.get(month_url + "/close-readiness").json()["can_close"]
    accepted = section_apply(client, intent, raw, plan)
    assert accepted.status_code == 200, accepted.text
    assert [s["disposition_status"] for s in accepted.json()["sections"]] == ["effective"] * 2
    after = _all_month_tables(database)
    assert len(after["broker_month_applies"]) == len(before["broker_month_applies"]) + 1
    assert all(after[t] == before[t] for t in before if t != "broker_month_applies")
    assert (
        after["broker_month_applies"][: len(before["broker_month_applies"])]
        == before["broker_month_applies"]
    )
    assert client.get(base_url).json()["bookkeeping_ready"]
    assert client.get("/api/broker-months/section-proof").json()["accepted"] == plan["proof"]
    assert (
        len(
            client.get(
                f"/api/broker-months?reporting_month_id={intent['reporting_month_id']}"
            ).json()
        )
        == 1
    )
    assert client.get(month_url + "/close-readiness").json()["can_close"]
    assert client.post(month_url + "/close").status_code == 200
    closed = _all_month_tables(database)
    # Closing changes status/updated_at only and does not invalidate structural authority.
    for _ in range(10):
        replay = section_apply(client, intent, raw, plan)
        assert replay.status_code == 200 and replay.json()["duplicate"], replay.text
        assert [s["disposition_status"] for s in replay.json()["sections"]] == ["effective"] * 2
    assert _all_month_tables(database) == closed
    fresh = section_preview(client, intent, raw).json()
    assert not fresh["can_apply"] and "reporting_month_closed" in fresh["exceptions"]
    assert section_apply(client, intent, raw, fresh, request_id="closed-fresh").status_code == 409
    assert _all_month_tables(database) == closed


def _section_accept(client, intent, raw, request_id="section-proof"):
    response = section_preview(client, intent, raw)
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["can_apply"], plan
    accepted = section_apply(client, intent, raw, plan, request_id=request_id)
    assert accepted.status_code == 200, accepted.text
    return plan


@pytest.mark.parametrize("change", ["account", "snapshot", "cash", "source", "mapping"])
def test_section_aba_explicit_reacceptance_no_history_fallback(database, change):
    from datetime import UTC, date, datetime

    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import (
        Account,
        BrokerIdentityMapping,
        CashBalance,
        MyBrokerImport,
        ReportingMonth,
    )

    client, intent, raw = section_setup(database)
    first = _section_accept(client, intent, raw, "proof-A")
    before = _all_month_tables(database)
    with database.session_factory() as session:
        row, field, replacement = {
            "account": (
                session.get(Account, intent["account_id"]),
                "name",
                "Edited synthetic account",
            ),
            "snapshot": (
                session.get(ReportingMonth, intent["reporting_month_id"]),
                "snapshot_date",
                date(2030, 1, 30),
            ),
            "cash": (session.scalar(select(CashBalance)), "amount_kopecks", 40001),
            "source": (
                session.get(MyBrokerImport, intent["import_id"]),
                "confirmation_digest",
                "a" * 64,
            ),
            "mapping": (
                session.scalar(select(BrokerIdentityMapping)),
                "confirmed_at",
                datetime(2020, 1, 1, tzinfo=UTC),
            ),
        }[change]
        previous = getattr(row, field)
        setattr(row, field, replacement)
        session.commit()
        setattr(row, field, previous)
        session.commit()
    assert not client.get("/api/broker-months/section-base").json()["bookkeeping_ready"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    assert all(
        s["disposition_status"] == "blocked"
        for s in client.get("/api/broker-months/proof-A").json()["sections"]
    )
    stale = section_apply(client, intent, raw, first, request_id="stale-preview")
    assert stale.status_code == 409
    replay = section_apply(client, intent, raw, first, request_id="proof-A")
    assert replay.status_code == 200 and replay.json()["duplicate"]
    assert all(s["disposition_status"] == "blocked" for s in replay.json()["sections"])
    replacement_intent = {
        **intent,
        "sections": [{**s, "expected_predecessor": "proof-A"} for s in intent["sections"]],
    }
    second = _section_accept(client, replacement_intent, raw, "proof-B")
    assert client.get("/api/broker-months/section-base").json()["bookkeeping_ready"]
    assert all(
        s["disposition_status"] == "superseded"
        for s in client.get("/api/broker-months/proof-A").json()["sections"]
    )
    frozen = _all_month_tables(database)
    assert (
        frozen["broker_month_applies"][: len(before["broker_month_applies"])]
        == before["broker_month_applies"]
    )
    for _ in range(10):
        replay = section_apply(client, intent, raw, first, request_id="proof-A")
        assert replay.json()["duplicate"] and all(
            s["disposition_status"] == "superseded" for s in replay.json()["sections"]
        )
    assert _all_month_tables(database) == frozen
    with database.session_factory() as session:
        account = session.get(Account, intent["account_id"])
        name = account.name
        account.name = "Second ABA"
        session.commit()
        account.name = name
        session.commit()
    assert not client.get("/api/broker-months/section-base").json()["bookkeeping_ready"]
    assert all(
        s["disposition_status"] == "blocked"
        for s in section_apply(
            client, replacement_intent, raw, second, request_id="proof-B"
        ).json()["sections"]
    )
    wrong = section_preview(client, replacement_intent, raw).json()
    assert not wrong["can_apply"] and "section_predecessor_conflict" in wrong["exceptions"]
    third_intent = {
        **intent,
        "sections": [{**s, "expected_predecessor": "proof-B"} for s in intent["sections"]],
    }
    _section_accept(client, third_intent, raw, "proof-C")
    assert client.get("/api/broker-months/section-base").json()["bookkeeping_ready"]


def _section_second_source(client, intent, raw, base_id):
    from test_statement_import_mybroker_endpoints import _broker_month_apply, _broker_month_preview

    scope = {k: intent[k] for k in ("account_id", "reporting_month_id")}
    plan = _broker_month_preview(client, scope, raw)
    assert plan["can_apply"], plan
    response = _broker_month_apply(client, scope, plan, raw, request_id=base_id)
    assert response.status_code == 200, response.text
    return {**intent, "base_request_id": base_id, "import_id": response.json()["import_id"]}


@pytest.mark.parametrize("safe_first", [False, True])
def test_section_overlap_safe_source_never_clears_unsafe_source_both_orders(database, safe_first):
    from test_statement_import_mybroker_endpoints import (
        _all_month_tables,
        _broker_month_preview,
        broker_month_xml,
    )

    safe = metadata_xml(broker_month_xml())
    unsafe_root = ET.fromstring(safe)
    unsafe_root.find("{MyBroker}Trades3/{MyBroker}Report/{MyBroker}Tablix1").set("volume", "5.00")
    unsafe_root.find("{MyBroker}Trades4/{MyBroker}Report/{MyBroker}Tablix1").set(
        "Textbox4", "Неизвестен"
    )
    unsafe = ET.tostring(unsafe_root)
    client, first_intent, _ = section_setup(database, raw=safe if safe_first else unsafe)
    if safe_first:
        _section_accept(client, first_intent, safe, "old-safe-proof")
    second_intent = _section_second_source(
        client, first_intent, unsafe if safe_first else safe, "overlap-base"
    )
    safe_intent = first_intent if safe_first else second_intent
    if safe_first:
        safe_intent = {
            **safe_intent,
            "sections": [
                {**s, "expected_predecessor": "old-safe-proof"} for s in safe_intent["sections"]
            ],
        }
    _section_accept(client, safe_intent, safe, "safe-proof")
    before = _all_month_tables(database)
    for request_id in ("section-base", "overlap-base"):
        read = client.get(f"/api/broker-months/{request_id}").json()
        assert not read["bookkeeping_ready"]
        assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(read["exceptions"])
    assert not client.get(
        f"/api/months/{safe_intent['reporting_month_id']}/close-readiness"
    ).json()["can_close"]
    assert client.post(f"/api/months/{safe_intent['reporting_month_id']}/close").status_code == 422
    scope = {k: safe_intent[k] for k in ("account_id", "reporting_month_id")}
    preview = _broker_month_preview(client, scope, safe)
    assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(preview["exceptions"])
    assert _all_month_tables(database) == before


@pytest.mark.parametrize(
    "mutation", ["attr", "child", "status", "date", "duplicate", "foreign", "text", "pi"]
)
def test_section_unsafe_original_never_grants_or_partially_writes(database, mutation):
    from test_statement_import_mybroker_endpoints import _all_month_tables, broker_month_xml

    root = ET.fromstring(metadata_xml(broker_month_xml()))
    table = root.find("{MyBroker}Trades4/{MyBroker}Report/{MyBroker}Tablix1")
    details = table[0][0]
    if mutation == "attr":
        details.set("amount", "100")
    elif mutation == "child":
        node(details, "Movement", amount="1")
    elif mutation == "status":
        table.set("Textbox4", "Отключен")
    elif mutation == "date":
        details.set("sys_start_time", "29.02.2029 23:59")
    elif mutation == "duplicate":
        table[0].append(deepcopy(details))
    elif mutation == "foreign":
        details.tag = "{Foreign}Details"
    elif mutation == "text":
        details.text = "economic movement"
    else:
        details.append(ET.ProcessingInstruction("extra", "source"))
    raw = ET.tostring(root)
    client, intent, raw = section_setup(database, raw=raw)
    before = _all_month_tables(database)
    plan = section_preview(client, intent, raw).json()
    assert not plan["can_apply"] and "section_structure_unsupported" in plan["exceptions"]
    assert section_apply(client, intent, raw, plan).status_code == 409
    assert _all_month_tables(database) == before


@pytest.mark.parametrize(
    "case", ["bytes", "filename", "account", "import", "base", "sections", "extra", "parser"]
)
def test_section_wrong_original_scope_or_client_assertion_zero_write(database, case):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    client, intent, raw = section_setup(database)
    plan = section_preview(client, intent, raw).json()
    changed = dict(intent)
    filename = FILENAME
    if case == "bytes":
        raw += b"\n"
    elif case == "filename":
        filename = FILENAME.replace("1234567", "7654321")
    elif case in {"account", "import"}:
        changed[case + "_id"] = 999
    elif case == "base":
        changed["base_request_id"] = "missing"
    elif case == "sections":
        changed["sections"] = [{"section": "3_BrokerMoneyMove"}]
    elif case == "extra":
        changed["safe"] = True
    else:
        changed["source_parser"] = "future"
    before = _all_month_tables(database)
    assert section_apply(client, changed, raw, plan, filename=filename).status_code in {409, 422}
    assert _all_month_tables(database) == before


def test_section_one_section_and_changed_intent_replay_preserve_other_blocker(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    client, intent, raw = section_setup(database)
    single = {**intent, "sections": [{"section": "4_Transfers"}]}
    plan = _section_accept(client, single, raw)
    before = _all_month_tables(database)
    read = client.get("/api/broker-months/section-base").json()
    assert "4_Transfers_unsupported" not in read["exceptions"]
    assert "5_UFSR_unsupported" in read["exceptions"]
    assert section_apply(client, intent, raw, plan).status_code == 409
    replacement = {
        **single,
        "sections": [{"section": "4_Transfers", "expected_predecessor": "section-proof"}],
    }
    fresh = section_preview(client, replacement, raw).json()
    assert not fresh["can_apply"] and "section_authority_already_effective" in fresh["exceptions"]
    assert (
        section_apply(client, replacement, raw, fresh, request_id="competing-key").status_code
        == 409
    )
    assert _all_month_tables(database) == before


def _insert_section_history(database, intent, request_id, proof):
    from datetime import UTC, datetime

    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services.broker_sections import _fingerprint

    confirmation = digest(proof)
    b = proof.get("bindings", {})
    fingerprint = _fingerprint(
        proof.get("intent", {}), confirmation, b.get("original_sha256"), b.get("filename_digest")
    )
    with database.session_factory() as session:
        session.add(
            BrokerMonthApply(
                request_id=request_id,
                request_fingerprint=fingerprint,
                confirmation_digest=confirmation,
                reporting_month_id=intent["reporting_month_id"],
                account_id=intent["account_id"],
                import_id=intent["import_id"],
                projection_json=canonical(proof),
                accepted_at=datetime(2000, 1, 1, tzinfo=UTC),
            )
        )
        session.commit()


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "missing",
        "extra",
        "wrong-scope",
        "bool-inventory",
        "bad-bindings",
        "fork",
        "missing-predecessor",
        "cycle",
    ],
)
def test_section_malformed_journal_or_chain_fails_closed_without_fallback(database, case):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    client, intent, raw = section_setup(database)
    plan = _section_accept(client, intent, raw, "proof-A")
    bad = deepcopy(plan["proof"])
    if case == "unknown":
        bad["contract_version"] = "future"
    elif case == "missing":
        bad.pop("sections")
    elif case == "extra":
        bad["cash_id"] = 1
    elif case == "wrong-scope":
        bad["intent"]["account_id"] = 999
    elif case == "bool-inventory":
        bad["sections"][0]["raw_inventory"] = True
    elif case == "bad-bindings":
        bad["bindings"]["mappings"] = "unsafe"
    elif case == "missing-predecessor":
        for section in bad["intent"]["sections"]:
            section["expected_predecessor"] = "missing"
    elif case == "cycle":
        for section in bad["intent"]["sections"]:
            section["expected_predecessor"] = "bad-proof"
    # 'fork' is an independently sealed duplicate genesis. Old timestamp must
    # not resolve it, nor may current authority fall back to proof-A.
    _insert_section_history(database, intent, "bad-proof", bad)
    before = _all_month_tables(database)
    read = client.get("/api/broker-months/section-base").json()
    assert not read["bookkeeping_ready"]
    assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(read["exceptions"])
    expected = (
        "section_authority_chain_conflict"
        if case in {"fork", "missing-predecessor", "cycle"}
        else "broker_month_receipt_invalid"
    )
    assert expected in read["exceptions"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    assert all(
        s["disposition_status"] == "blocked"
        for s in client.get("/api/broker-months/proof-A").json()["sections"]
    )
    replay = section_apply(client, intent, raw, plan, request_id="proof-A")
    assert replay.status_code == 200 and replay.json()["duplicate"]
    assert all(s["disposition_status"] == "blocked" for s in replay.json()["sections"])
    assert _all_month_tables(database) == before


@pytest.mark.parametrize(
    "exception",
    [
        "4_Transfers_unsupported",
        "5_UFSR_unsupported",
        "optional_evidence_unsupported",
        "unparsed_source_rows",
        "commission_basis_unresolved",
        "position_row_unclassified",
        "money_summary_unproven",
        "repo_semantics_unsupported",
        "paid_nkd_unproven",
    ],
)
def test_section_frozen_legacy_mixed_or_unknown_exceptions_are_never_suppressed(
    database, exception
):
    from datetime import UTC, datetime

    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import BrokerMonthApply

    client, intent, raw = section_setup(database)
    with database.session_factory() as session:
        base = session.get(BrokerMonthApply, intent["base_request_id"])
        frozen = json.loads(base.projection_json)
        frozen["exceptions"] = [exception]
        # Synthetic pre-version historical receipt. A today's matching warning
        # cannot attribute this frozen exception to one original source.
        session.add(
            BrokerMonthApply(
                request_id="frozen-mixed",
                request_fingerprint=base.request_fingerprint,
                confirmation_digest=base.confirmation_digest,
                reporting_month_id=base.reporting_month_id,
                account_id=base.account_id,
                import_id=base.import_id,
                projection_json=canonical(frozen),
                accepted_at=datetime.now(UTC),
            )
        )
        session.commit()
    before = _all_month_tables(database)
    _section_accept(client, intent, raw)
    read = client.get("/api/broker-months/section-base").json()
    assert read["exceptions"] == [exception] and not read["bookkeeping_ready"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    after = _all_month_tables(database)
    assert all(after[t] == before[t] for t in before if t != "broker_month_applies")
    assert (
        after["broker_month_applies"][: len(before["broker_month_applies"])]
        == before["broker_month_applies"]
    )


def test_section_acceptance_stale_reserved_dependencies_and_late_failure_zero_write(
    database, monkeypatch
):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.domain.broker_sections import SectionIntent
    from hermes_finance.persistence import Account, BrokerMonthApply
    from hermes_finance.services import broker_sections

    client, intent, raw = section_setup(database)
    first = section_preview(client, intent, raw).json()
    with database.session_factory() as session:
        row = session.get(Account, intent["account_id"])
        row.name += " changed"
        session.commit()
    before = _all_month_tables(database)
    assert section_apply(client, intent, raw, first).status_code == 409
    assert _all_month_tables(database) == before
    # A failure at the final receipt flush is rollback, including all existing
    # dependency and financial rows. The writer has already revalidated original.
    fresh = section_preview(client, intent, raw).json()
    assert fresh["can_apply"]

    def fail_receipt(session, context, instances):
        if any(
            isinstance(row, BrokerMonthApply) and row.request_id == "late-failure"
            for row in session.new
        ):
            raise RuntimeError("synthetic late failure")

    from sqlalchemy.orm import Session

    event.listen(Session, "before_flush", fail_receipt)
    try:
        with (
            database.session_factory() as session,
            pytest.raises(RuntimeError, match="synthetic late failure"),
        ):
            broker_sections.apply_sections(
                session,
                SectionIntent.model_validate(intent),
                raw,
                FILENAME,
                confirmation_digest=fresh["confirmation_digest"],
                request_id="late-failure",
            )
    finally:
        event.remove(Session, "before_flush", fail_receipt)
    assert _all_month_tables(database) == before


def test_section_predecessor_and_full_dependencies_reread_inside_reserved_writer(
    database, monkeypatch
):

    from hermes_finance.domain.broker_sections import SectionIntent
    from hermes_finance.services import broker_sections

    client, intent, raw = section_setup(database)
    plan = section_preview(client, intent, raw).json()
    original_plan = broker_sections._plan
    observed = []

    def revalidate(session, *args, **kwargs):
        # Reservation is acquired before the dependency/source/head read. A
        # concurrent second SQLite writer cannot change facts during acceptance.
        from sqlalchemy import text

        with database.engine.connect() as competing:
            competing.exec_driver_sql("PRAGMA busy_timeout=1")
            from sqlalchemy.exc import OperationalError

            with pytest.raises(OperationalError, match="locked"):
                competing.execute(
                    text("UPDATE accounts SET name='raced' WHERE id=:id"),
                    {"id": intent["account_id"]},
                )
        observed.append(True)
        return original_plan(session, *args, **kwargs)

    monkeypatch.setattr(broker_sections, "_plan", revalidate)
    with database.session_factory() as session:
        result = broker_sections.apply_sections(
            session,
            SectionIntent.model_validate(intent),
            raw,
            FILENAME,
            confirmation_digest=plan["confirmation_digest"],
            request_id="reserved",
        )
    assert observed and not result["duplicate"]
    assert all(s["disposition_status"] == "effective" for s in result["sections"])


def metadata_xml(raw=None):
    root = ET.fromstring(raw or fixture())
    node(root.find("{MyBroker}Trades3/{MyBroker}Report"), "Tablix1")
    table = node(root.find("{MyBroker}Trades4/{MyBroker}Report"), "Tablix1", Textbox4="Подключен")
    node(
        node(table, "Details_Collection"),
        "Details",
        sys_start_time="29.02.2028 23:59",
        sys_end_time="-",
    )
    return ET.tostring(root, encoding="utf-8")


def evidence(raw):
    return parse_section_metadata(raw, FILENAME)


def test_exact_safe_trees_are_separate_original_bound_metadata():
    raw = metadata_xml()
    frozen = parse_mybroker(raw, FILENAME)
    # Whole S1 digest captured on unchanged live-main parser, including blockers.
    assert digest(frozen) == "1c744412e204c99f7563084d7eb43a79198a1e72235ace4ee1bc1f00f41edf47"
    result = evidence(raw)
    assert result == evidence(raw)
    assert result["metadata_parser"] == "mybroker-section-metadata-v1"
    assert result["source_parser"] == "mybroker-s1-v2"
    assert result["document_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["coverage_state"] == "unknown"
    assert [s["status"] for s in result["sections"]] == ["READY_SAFE_STRUCTURE"] * 2
    assert [s["raw_inventory"] for s in result["sections"]] == [1, 3]
    assert all(
        s["derived_movements"] == 0 and s["period_scope"] == "unknown" for s in result["sections"]
    )
    assert result["source_warnings"] == frozen["syntax_blockers"]
    assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(result["source_warnings"])
    assert "2028" not in canonical(result) and "sys_start_time" not in canonical(result)
    assert parse_mybroker(raw, FILENAME) == frozen
    plain = parse_mybroker(fixture(), FILENAME)
    for key in ("money", "trades", "positions", "rub_money"):
        assert frozen[key] == plain[key]


LEVELS = [("Trades3", i) for i in range(3)] + [("Trades4", i) for i in range(5)]


@pytest.mark.parametrize("outer,depth", LEVELS)
@pytest.mark.parametrize(
    "mutation", ["attr", "child", "namespace", "text", "tail", "comment", "pi"]
)
def test_every_node_is_exact_and_foreign_economic_or_hidden_content_blocks(outer, depth, mutation):
    root = ET.fromstring(metadata_xml())
    target = root.find(f"{{MyBroker}}{outer}")
    for _ in range(depth):
        target = target[0]
    if mutation == "attr":
        target.set("volume", "1.00")
    elif mutation == "child":
        node(target, "Movement", amount="1.00")
    elif mutation == "namespace":
        target.tag = target.tag.replace("MyBroker", "Foreign")
    elif mutation in ("text", "tail"):
        setattr(target, mutation, "economic content")
    elif mutation == "comment":
        target.append(ET.Comment("extra source node"))
    else:
        target.append(ET.ProcessingInstruction("extra", "source"))
    raw = ET.tostring(root, encoding="utf-8")
    try:
        result = evidence(raw)
    except MyBrokerError as error:
        # The unchanged S1 family rejects foreign wrappers/reports first.
        assert str(error) == "required_section_invalid"
    else:
        section = next(
            s
            for s in result["sections"]
            if s["section"].startswith("4_" if outer == "Trades3" else "5_")
        )
        assert section["status"] == "BLOCKED" and section["pattern"] is None
        assert section["derived_movements"] == 0


@pytest.mark.parametrize("outer,depth", LEVELS)
def test_missing_or_duplicate_fixed_node_blocks(outer, depth):
    for duplicate in (False, True):
        root = ET.fromstring(metadata_xml())
        parent = root
        target = root.find(f"{{MyBroker}}{outer}")
        for _ in range(depth):
            parent, target = target, target[0]
        if duplicate:
            parent.append(deepcopy(target))
        else:
            parent.remove(target)
        try:
            result = evidence(ET.tostring(root))
        except MyBrokerError as error:
            assert str(error) == "required_section_invalid"
        else:
            assert result["sections"][outer == "Trades4"]["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "start",
    [
        "29.02.2029 23:59",
        "31.04.2028 12:00",
        "01.01.2028 24:00",
        "01.01.2028 12:60",
        "1.01.2028 12:00",
        "01.01.2028 1:00",
        "01.01.2028 12:00:00",
        "01.01.0000 12:00",
        "０1.01.2028 12:00",
        " 01.01.2028 12:00",
        "01.01.2028 12:00\n",
        "",
    ],
)
def test_timestamp_is_ascii_exact_and_calendar_valid(start):
    raw = metadata_xml().replace(b"29.02.2028 23:59", start.encode())
    assert evidence(raw)["sections"][1]["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "field,value",
    [
        ("Textbox4", "Отключен"),
        ("Textbox4", "Подключен "),
        ("sys_end_time", ""),
        ("sys_end_time", "01.01.2030 12:00"),
        ("sys_end_time", " - "),
    ],
)
def test_only_proven_state_and_open_end_token_are_metadata(field, value):
    root = ET.fromstring(metadata_xml())
    target = root.find("{MyBroker}Trades4/{MyBroker}Report/{MyBroker}Tablix1")
    if field == "sys_end_time":
        target = target[0][0]
    target.set(field, value)
    assert evidence(ET.tostring(root))["sections"][1]["status"] == "BLOCKED"


def test_childless_reports_remain_separate_and_whitespace_changes_binding():
    assert [s["status"] for s in evidence(fixture())["sections"]] == ["BLOCKED"] * 2
    root = ET.fromstring(metadata_xml())
    for outer in ("Trades3", "Trades4"):
        for element in root.find(f"{{MyBroker}}{outer}").iter():
            element.text = element.tail = " \n\t"
    raw = ET.tostring(root)
    assert [s["status"] for s in evidence(raw)["sections"]] == ["READY_SAFE_STRUCTURE"] * 2
    assert evidence(raw)["document_sha256"] != evidence(metadata_xml())["document_sha256"]


@pytest.mark.parametrize("field", ["Textbox4", "sys_start_time", "sys_end_time"])
def test_missing_required_status_attribute_blocks(field):
    root = ET.fromstring(metadata_xml())
    target = root.find("{MyBroker}Trades4/{MyBroker}Report/{MyBroker}Tablix1")
    if field != "Textbox4":
        target = target[0][0]
    target.attrib.pop(field)
    assert evidence(ET.tostring(root))["sections"][1]["status"] == "BLOCKED"


@pytest.mark.parametrize("outer", ["Trades3", "Trades4"])
def test_additional_foreign_wrapper_cannot_hide_beside_safe_tree(outer):
    root = ET.fromstring(metadata_xml())
    extra = deepcopy(root.find(f"{{MyBroker}}{outer}"))
    extra.tag = f"{{Foreign}}{outer}"
    root.append(extra)
    result = evidence(ET.tostring(root))
    assert result["sections"][outer == "Trades4"]["status"] == "BLOCKED"
    assert "unknown_section" in result["source_warnings"]


@pytest.mark.parametrize("economic", [False, True])
def test_safe_metadata_never_grants_month_get_readiness_or_close_authority(database, economic):
    from test_statement_import_mybroker_endpoints import (
        _broker_month_apply,
        _broker_month_preview,
        _broker_month_setup,
        broker_month_xml,
    )

    intent = _broker_month_setup(database)
    raw = metadata_xml(broker_month_xml())
    if economic:
        root = ET.fromstring(raw)
        root.find("{MyBroker}Trades4/{MyBroker}Report/{MyBroker}Tablix1")[0][0].set(
            "volume", "1.00"
        )
        raw = ET.tostring(root)
    client = TestClient(create_app(database=database))
    source = client.post("/api/mybroker-import/preview", files={"file": (FILENAME, raw)}).json()
    assert source["metadata_evidence"]["sections"][0]["status"] == "READY_SAFE_STRUCTURE"
    assert source["metadata_evidence"]["sections"][1]["status"] == (
        "BLOCKED" if economic else "READY_SAFE_STRUCTURE"
    )
    plan = _broker_month_preview(client, intent, raw)
    assert not plan["bookkeeping_ready"]
    assert {"4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(plan["exceptions"])
    # Exercise the existing lifecycle solely in the synthetic test database.
    assert _broker_month_apply(client, intent, plan, raw).status_code == 200
    assert not client.get("/api/broker-months/synthetic-batch").json()["bookkeeping_ready"]
    readiness = client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()
    assert not readiness["can_close"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422


def test_daily_money_unknown_and_repo_still_block(database):
    root = ET.fromstring(metadata_xml(repo_fixture()))
    comment = root.find(".//{MyBroker}comment")
    node(comment, "Textbox95", all_volume="117.00", debet_volume="0")
    raw = ET.tostring(root)
    with database.session_factory() as session:
        before = inventory(session)
        result = preview_mybroker(session, document=raw, filename=FILENAME)
        assert [s["status"] for s in result["metadata_evidence"]["sections"]] == [
            "READY_SAFE_STRUCTURE"
        ] * 2
        assert {
            "unparsed_source_rows",
            "money_semantics_unsupported",
            "repo_semantics_unsupported",
            "4_Transfers_unsupported",
            "5_UFSR_unsupported",
        } <= set(result["blockers"])
        assert result["coverage_state"] == "unknown"
        assert inventory(session) == before


@pytest.mark.parametrize("legacy", [False, True])
def test_old_receipt_preview_replay_get_and_fingerprints_never_upgrade(database, legacy):
    raw = metadata_xml(native_money_xml())
    parsed = parse_mybroker(raw, FILENAME, **({"money_linkage_version": None} if legacy else {}))
    with database.session_factory() as session:
        row = stage_mybroker(session, parsed)  # synthetic historical receipt setup only
        session.commit()
        frozen = (row.normalized_json, row.confirmation_digest, row.parser_version)
        fingerprints = [digest(r) for r in json.loads(row.normalized_json)["money"]]
        original = _prepare(session, parse_import_original(session, raw, FILENAME))
        before = inventory(session)
        lineage = read_mybroker_lineage(session)
        for _ in range(2):
            reviewed = preview_mybroker(session, document=raw, filename=FILENAME)
            assert {k: v for k, v in reviewed.items() if k != "metadata_evidence"} == original
            assert reviewed["already_imported"] == row.id
            assert (
                stage_mybroker(session, parse_import_original(session, raw, FILENAME)).id == row.id
            )
            session.commit()
            assert inventory(session) == before
            assert read_mybroker_lineage(session) == lineage
            assert (row.normalized_json, row.confirmation_digest, row.parser_version) == frozen
            assert canonical(read_mybroker_import(session, row.id)["document"]) == frozen[0]
            assert [digest(r) for r in json.loads(row.normalized_json)["money"]] == fingerprints
        assert "metadata_evidence" not in row.normalized_json


def test_http_preview_repeated_original_is_zero_write_and_keeps_confirmation(database):
    raw = metadata_xml()
    with database.session_factory() as session:
        original = _prepare(session, parse_import_original(session, raw, FILENAME))
        before = inventory(session)
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(database.engine, "before_cursor_execute", observe)
    try:
        client = TestClient(create_app(database=database))
        first = client.post("/api/mybroker-import/preview", files={"file": (FILENAME, raw)})
        second = client.post("/api/mybroker-import/preview", files={"file": (FILENAME, raw)})
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert {k: v for k, v in first.json().items() if k != "metadata_evidence"} == original
        assert first.json()["metadata_evidence"] == evidence(raw)
        assert not {"INSERT", "UPDATE", "DELETE", "REPLACE"} & set(statements)
    finally:
        event.remove(database.engine, "before_cursor_execute", observe)
    with database.session_factory() as session:
        assert inventory(session) == before
