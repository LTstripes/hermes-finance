"""Synthetic #789/#792 exact tree and frozen-receipt acceptance."""

import hashlib
import json
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
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
