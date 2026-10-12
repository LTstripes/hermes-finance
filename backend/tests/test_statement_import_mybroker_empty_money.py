"""Fabricated originals only: exact empty Money diagnostics and zero authority."""

import hashlib
import json
from copy import deepcopy
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select
from test_statement_import_mybroker import FILENAME, native_money_xml, node
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_metadata import metadata_xml

from hermes_finance.main import create_app
from hermes_finance.persistence import Base
from hermes_finance.services.mybroker_import import (
    _prepare,
    parse_import_original,
    read_mybroker_import,
    read_mybroker_lineage,
    stage_mybroker,
)
from hermes_finance.statement_import.mybroker import (
    MAX_BYTES,
    MyBrokerError,
    digest,
    parse_mybroker,
)
from hermes_finance.statement_import.mybroker_empty_money import (
    MONEY_CHILDREN,
    parse_empty_money_layout,
)

NS = "{MyBroker}"
PATHS = [
    ".",
    f"{NS}Trades2",
    f"{NS}Trades2/{NS}Report",
    f"{NS}Trades2/{NS}Report/{NS}Tablix5",
    f"{NS}Trades2/{NS}Report/{NS}Tablix5/{NS}Textbox3",
    f"{NS}Trades2/{NS}Report/{NS}Tablix5/{NS}Textbox3/{NS}Textbox61",
    f"{NS}Trades2/{NS}Report/{NS}Tablix5/{NS}Textbox3/{NS}Textbox61/{NS}Textbox46",
    f"{NS}Trades2/{NS}Report/{NS}Tablix5/{NS}Textbox3/{NS}Textbox61/{NS}Textbox47",
]


def layout_xml(raw=None):
    root = ET.fromstring(raw or metadata_xml(native_money_xml()))
    root.set("Textbox6", "Уполномоченное лицо")
    report = root.find(f"{NS}Trades2/{NS}Report")
    original = {child.tag: child for child in report}
    report[:] = []
    for name in MONEY_CHILDREN:
        if f"{NS}{name}" in original:
            # Retain populated endpoints/summary from the synthetic source.
            report.append(original[f"{NS}{name}"])
        else:
            table = node(report, name)
            if name == "Tablix5":
                parent = node(node(table, "Textbox3"), "Textbox61")
                node(parent, "Textbox46")
                node(parent, "Textbox47")
    return ET.tostring(root, encoding="utf-8")


def evidence(raw, *, filename=FILENAME, expected=None):
    return parse_empty_money_layout(
        raw, filename, expected_document_sha256=expected or hashlib.sha256(raw).hexdigest()
    )


def blocked(raw):
    try:
        result = evidence(raw)
    except MyBrokerError as error:
        # Original S1 failures retain the established reject behavior.
        assert str(error) in {"family_unsupported", "required_section_invalid"}
    else:
        assert result["status"] == "BLOCKED"
        assert result["path"] is result["observed_nodes"] is None
        assert result["authority"] == "none" and result["derived_movements"] == 0


def snapshot(database):
    with database.session_factory() as session:
        return {
            table.name: [tuple(row) for row in session.execute(select(table))]
            for table in Base.metadata.sorted_tables
        }


def test_exact_five_nodes_are_original_bound_and_never_economic():
    raw = layout_xml()
    frozen = parse_mybroker(raw, FILENAME, money_linkage_version=None)
    result = evidence(raw)
    assert result == evidence(raw)
    assert result["diagnostic_parser"] == "mybroker-empty-money-layout-v1"
    assert result["source_parser"] == "mybroker-s1-v2"
    assert result["status"] == "EXACT_EMPTY_TREE_OBSERVED"
    assert result["observed_nodes"] == 5
    assert result["document_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["source_scope"] == {
        "filename_account": "1234567",
        "covered_from": "2030-01-01",
        "covered_to": "2030-01-31",
    }
    assert result["authority"] == "none"
    assert result["derived_movements"] == 0 and result["coverage_state"] == "unknown"
    assert result["source_warnings"] == frozen["syntax_blockers"]
    assert {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(
        result["source_warnings"]
    )
    assert parse_mybroker(raw, FILENAME, money_linkage_version=None) == frozen
    # Frozen whole S1 output captured from the baseline parser on this fixture.
    assert digest(frozen) == "310d42f40d12a060d8c401a99b292c8f03858b4c0cf6c8296fef116e51cf0fff"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "mutation",
    [
        "empty_attr",
        "zero_attr",
        "namespaced_attr",
        "text",
        "tail",
        "nbsp",
        "child",
        "namespace",
        "comment",
        "pi",
    ],
)
def test_every_ancestor_and_empty_node_rejects_hidden_or_economic_content(path, mutation):
    root = ET.fromstring(layout_xml())
    target = root if path == "." else root.find(path)
    if mutation in ("empty_attr", "zero_attr", "namespaced_attr"):
        target.set(
            "{MyBroker}extra" if mutation == "namespaced_attr" else "extra",
            "0" if mutation == "zero_attr" else "",
        )
    elif mutation in ("text", "tail", "nbsp"):
        setattr(
            target,
            "tail" if mutation == "tail" else "text",
            "\u00a0" if mutation == "nbsp" else "economic content",
        )
        # Root tail payload is invalid XML rather than a layout mismatch.
        if path == "." and mutation == "tail":
            with pytest.raises(MyBrokerError, match="^xml_invalid$"):
                evidence(ET.tostring(root))
            return
    elif mutation == "child":
        node(target, "Movement", volume="1.00")
    elif mutation == "namespace":
        target.tag = target.tag.replace("MyBroker", "Foreign")
    elif mutation == "comment":
        target.append(ET.Comment("extra"))
    else:
        target.append(ET.ProcessingInstruction("extra", "source"))
    blocked(ET.tostring(root))


@pytest.mark.parametrize("path", PATHS[1:])
@pytest.mark.parametrize("mutation", ["missing", "duplicate", "moved", "foreign_duplicate"])
def test_cardinality_and_placement_are_exact(path, mutation):
    root = ET.fromstring(layout_xml())
    target = root.find(path)
    parent = next(element for element in root.iter() if target in list(element))
    if mutation in ("missing", "moved"):
        parent.remove(target)
        if mutation == "moved":
            root.find(f"{NS}Trades3/{NS}Report").append(target)
    else:
        extra = deepcopy(target)
        if mutation == "foreign_duplicate":
            extra.tag = extra.tag.replace("MyBroker", "Foreign")
        parent.append(extra)
    blocked(ET.tostring(root))


@pytest.mark.parametrize("level", ["root", "money", "leaves"])
def test_order_and_expected_siblings_are_required(level):
    for mutation in ("reorder", "missing", "duplicate"):
        root = ET.fromstring(layout_xml())
        parent = {"root": root, "money": root.find(PATHS[2]), "leaves": root.find(PATHS[5])}[level]
        if mutation == "reorder":
            parent[:] = list(reversed(parent))
        elif mutation == "missing":
            parent.remove(parent[0])
        else:
            parent.append(deepcopy(parent[0]))
        blocked(ET.tostring(root))


@pytest.mark.parametrize("payload", [b"<!--extra-->", b"<?extra source?>"])
@pytest.mark.parametrize("placement", ["before", "after", "sibling"])
def test_comments_and_pis_cannot_disappear_outside_target(payload, placement):
    raw = layout_xml()
    if placement == "before":
        raw = payload + raw
    elif placement == "after":
        raw += payload
    else:
        raw = raw.replace(b"</ns0:Positions>", payload + b"</ns0:Positions>")
    blocked(raw)


@pytest.mark.parametrize("change", ["white", "bom", "payload"])
def test_altered_original_cannot_reuse_prior_hash(change):
    raw = layout_xml()
    original = evidence(raw)
    modified = {
        "white": raw.replace(b"<ns0:Textbox46", b" \n<ns0:Textbox46"),
        "bom": b"\xef\xbb\xbf" + raw,
        "payload": raw.replace(b"<ns0:Textbox46", b'<ns0:Textbox46 extra="0"'),
    }[change]
    stale = evidence(modified, expected=original["document_sha256"])
    assert stale["status"] == "BLOCKED"
    assert stale["document_sha256"] != original["document_sha256"]
    assert evidence(modified)["status"] == (
        "BLOCKED" if change == "payload" else "EXACT_EMPTY_TREE_OBSERVED"
    )


def test_only_xml_whitespace_and_exact_namespace_declarations():
    root = ET.fromstring(layout_xml())
    for path in PATHS:
        target = root if path == "." else root.find(path)
        target.text = target.tail = " \t\r\n"
    assert evidence(ET.tostring(root))["status"] == "EXACT_EMPTY_TREE_OBSERVED"
    raw = layout_xml().replace(b"<ns0:Textbox46", b'<ns0:Textbox46 xmlns:ns0="MyBroker"')
    blocked(raw)
    raw = layout_xml().replace(b"<ns0:Textbox46", b'<ns0:Textbox46 xmlns:foreign="Foreign"')
    blocked(raw)


@pytest.mark.parametrize(
    "path",
    [f"{NS}{name}" for name in ("Positions", "Trades", "Trades2", "Trades3", "Trades4")]
    + [f"{PATHS[2]}/{NS}{name}" for name in MONEY_CHILDREN],
)
def test_parent_character_data_between_expected_siblings_is_whitespace_only(path):
    root = ET.fromstring(layout_xml())
    root.find(path).tail = "economic content between siblings"
    blocked(ET.tostring(root))


def test_missing_observed_root_attribute_is_not_the_exact_family():
    root = ET.fromstring(layout_xml())
    root.attrib.pop("Textbox6")
    blocked(ET.tostring(root))


def test_family_and_original_bounds_are_reused():
    raw = layout_xml()
    cases = [
        (b"", "document_size_invalid"),
        (b" " * (MAX_BYTES + 1), "document_size_invalid"),
        (b"<!DOCTYPE Report>" + raw, "xml_declarations_unsupported"),
        (b"<!ENTITY hidden '0'>" + raw, "xml_declarations_unsupported"),
        (b"\xff", "xml_invalid"),
    ]
    for document, code in cases:
        with pytest.raises(MyBrokerError, match=f"^{code}$"):
            evidence(document)
    root = ET.fromstring(raw)
    target = root.find(PATHS[6])
    for _ in range(34):
        target = node(target, "nested")
    with pytest.raises(MyBrokerError, match="^xml_bounds_exceeded$"):
        evidence(ET.tostring(root))
    with pytest.raises(MyBrokerError, match="^filename_range_invalid$"):
        evidence(raw, filename="other.xml")


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_sources_and_accounts_do_not_share_verdicts(reverse):
    safe = layout_xml()
    unsafe = safe.replace(b"<ns0:Textbox47", b'<ns0:Textbox47 extra="0"')
    inputs = [
        (safe, FILENAME, "EXACT_EMPTY_TREE_OBSERVED"),
        (unsafe, FILENAME, "BLOCKED"),
        (unsafe, FILENAME.replace("1234567", "7654321"), "BLOCKED"),
    ]
    if reverse:
        inputs.reverse()
    for raw, filename, status in inputs * 2:
        result = evidence(raw, filename=filename)
        assert result["status"] == status
        assert result["source_scope"]["filename_account"] in filename
    assert (
        evidence(safe, filename=FILENAME.replace("1234567", "7654321"))["source_scope"]
        != (evidence(safe)["source_scope"])
    )


@pytest.mark.parametrize("legacy", [False, True])
def test_http_diagnostic_is_zero_write_and_preserves_receipts_replay_get(database, legacy):
    raw = layout_xml()
    parsed = parse_mybroker(raw, FILENAME, **({"money_linkage_version": None} if legacy else {}))
    with database.session_factory() as session:
        row = stage_mybroker(session, parsed)
        session.commit()
        saved = (row.normalized_json, row.confirmation_digest, row.parser_version)
        import_id = row.id
        original = _prepare(session, parse_import_original(session, raw, FILENAME))
        lineage = read_mybroker_lineage(session)
    before = snapshot(database)
    statements = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(database.engine, "before_cursor_execute", observe)
    try:
        client = TestClient(create_app(database=database))
        results = [
            client.post("/api/mybroker-import/preview", files={"file": (FILENAME, raw)})
            for _ in range(3)
        ]
        assert all(response.status_code == 200 for response in results)
        assert results[0].json() == results[1].json() == results[2].json()
        preview = results[0].json()
        assert preview["empty_money_layout_evidence"] == evidence(raw)
        assert {
            key: value
            for key, value in preview.items()
            if key not in ("metadata_evidence", "empty_money_layout_evidence")
        } == original
        assert not {"INSERT", "UPDATE", "DELETE", "REPLACE"} & set(statements)
    finally:
        event.remove(database.engine, "before_cursor_execute", observe)
    with database.session_factory() as session:
        row = stage_mybroker(session, parse_import_original(session, raw, FILENAME))
        session.commit()
        assert row.id == import_id
        assert (row.normalized_json, row.confirmation_digest, row.parser_version) == saved
        assert read_mybroker_lineage(session) == lineage
        assert read_mybroker_import(session, import_id)["document"] == json.loads(saved[0])
        assert "empty_money_layout" not in row.normalized_json
    assert snapshot(database) == before


def test_exact_blank_never_changes_source_month_get_close_or_money_blockers(database):
    from test_statement_import_mybroker_endpoints import (
        _broker_month_apply,
        _broker_month_preview,
        _broker_month_setup,
        broker_month_xml,
    )

    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    base = metadata_xml(broker_month_xml())
    base_plan = _broker_month_preview(client, intent, base)
    assert _broker_month_apply(client, intent, base_plan, base).status_code == 200
    month_url = "/api/broker-months/synthetic-batch"
    readiness_url = f"/api/months/{intent['reporting_month_id']}/close-readiness"
    original_get = client.get(month_url).json()
    original_readiness = client.get(readiness_url).json()
    before = snapshot(database)
    raw = layout_xml(base)
    root = ET.fromstring(raw)
    footer = node(root.find(f"{NS}Positions/{NS}Report"), "Tablix3", Textbox217="Synthetic tax")
    node(
        node(footer, "Details1_Collection"),
        "Details1",
        Textbox222="0.00",
        fSUMPAYED="0.00",
        fTOPAY="0.00",
    )
    raw = ET.tostring(root)
    assert evidence(raw)["status"] == "EXACT_EMPTY_TREE_OBSERVED"
    source = client.post("/api/mybroker-import/preview", files={"file": (FILENAME, raw)}).json()
    assert source["empty_money_layout_evidence"]["status"] == "EXACT_EMPTY_TREE_OBSERVED"
    plan = _broker_month_preview(client, intent, raw)
    assert not plan["can_apply"] and not plan["bookkeeping_ready"]
    assert {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"} <= set(
        plan["exceptions"]
    )
    response = _broker_month_apply(client, intent, plan, raw, request_id="diagnostic-blocked")
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "broker_month_reconciliation_required"
    assert client.get(month_url).json() == original_get
    assert client.get(readiness_url).json() == original_readiness
    assert not original_get["bookkeeping_ready"] and not original_readiness["can_close"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    assert snapshot(database) == before
