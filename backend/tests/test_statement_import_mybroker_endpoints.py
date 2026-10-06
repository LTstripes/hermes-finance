"""Synthetic #716 endpoint-evidence fixtures for the frozen MyBroker slice."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from test_statement_import_mybroker import (
    ACCOUNT,
    FILENAME,
    ISIN,
    apply,
    fixture,
    node,
    preview,
)
from test_statement_import_mybroker import (
    database as database,
)

from hermes_finance.main import create_app
from hermes_finance.persistence import (
    CashBalance,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.mybroker_import import (
    _source_affects_interval,
    read_mybroker_import,
    unresolved_class_source_ids,
)
from hermes_finance.statement_import.mybroker import MyBrokerError, parse_mybroker


def endpoint_xml(
    *,
    beginning: str | None = "8",
    values: bool = True,
    rub: bool = True,
    rub_rows: int = 1,
    rub_on_group: bool = False,
    rub_amounts: tuple[str | None, str | None] = ("500.00", "400.00"),
    unclassified: bool = False,
    forward: str = "10",
) -> bytes:
    root = ET.fromstring(fixture(forward=forward))
    group = root.find(".//{MyBroker}Positions").find(".//{MyBroker}active_type")
    security = group.find(".//{MyBroker}Details")
    collection = group.find("{MyBroker}Details_Collection")
    if beginning is not None:
        security.set("income_rest", beginning)
    if values:
        security.set("income_volume", "800.00")
        security.set("real_volume", "1000.00")
    if rub:
        if rub_on_group:
            group.set("active_type", "Валюта")
        for _ in range(rub_rows):
            row = node(collection, "Details", acc_code=ACCOUNT, active_name="RUB")
            if not rub_on_group:
                row.set("active_type", "Валюта")
            if rub_amounts[0] is not None:
                row.set("income_rest", rub_amounts[0])
            if rub_amounts[1] is not None:
                row.set("real_rest", rub_amounts[1])
    if unclassified:
        node(collection, "Details", acc_code=ACCOUNT)
    return ET.tostring(root, encoding="utf-8")


def positions_only(document: bytes) -> bytes:
    """Keep the endpoint Positions section and drop all trade/money rows."""
    root = ET.fromstring(document)
    for path in (
        "{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2",
        "{MyBroker}Trades2/{MyBroker}Report/{MyBroker}Tablix1",
    ):
        element = root.find(path)
        for child in list(element):
            element.remove(child)
    return ET.tostring(root, encoding="utf-8")


def limit_xml(*, security: int, unclassified: int) -> bytes:
    """Exact-position row counts for the consumed-row bound, no trades/money."""
    root = ET.fromstring(positions_only(endpoint_xml(rub=False)))
    group = root.find(".//{MyBroker}Positions").find(".//{MyBroker}active_type")
    collection = group.find("{MyBroker}Details_Collection")
    for row in collection.findall("{MyBroker}Details"):
        collection.remove(row)
    for _ in range(security):
        node(
            collection,
            "Details",
            acc_code=ACCOUNT,
            ISIN1=ISIN,
            real_rest="1",
            forward_rest="1",
            income_rest="1",
            income_volume="1",
            real_volume="1",
        )
    for _ in range(unclassified):
        node(collection, "Details", acc_code=ACCOUNT)
    return ET.tostring(root, encoding="utf-8")


def test_endpoint_fields_are_normalized_without_derivation():
    document = parse_mybroker(
        endpoint_xml(beginning="8.00", rub_amounts=("500.50", "-400.00")), FILENAME
    )
    assert document["parser"] == "mybroker-s1-v2"
    assert document["endpoint_basis"] == {
        "beginning_value": "previous_day_eod",
        "ending_value": "covered_to_eod",
    }
    position = document["positions"][0]
    assert position["actual_quantity"] == "10"
    assert position["forward_quantity"] == "10"
    assert position["beginning_actual_quantity"] == "8"
    assert position["beginning_value"] == "800"
    assert position["ending_value"] == "1000"
    assert document["rub_money"] == [
        {
            "section": "rub_money",
            "ordinal": 1,
            "source_account": ACCOUNT,
            "currency": "RUB",
            "beginning_amount": "500.5",
            "ending_amount": "-400",
        }
    ]
    assert document["endpoint_blockers"] == []
    assert document["endpoint_conflicts"] == []
    assert "Synthetic name" not in json.dumps(document)


def test_currency_row_requires_the_accepted_row_level_conjunction():
    root = ET.fromstring(endpoint_xml(rub=False))
    security = root.find(".//{MyBroker}Positions").find(".//{MyBroker}Details")
    security.set("active_type", "Валюта")
    security.set("active_name", "RUB")
    document = parse_mybroker(ET.tostring(root, encoding="utf-8"), FILENAME)
    assert len(document["positions"]) == 1 and document["rub_money"] == []
    assert "position_row_unclassified" not in document["endpoint_blockers"]

    # Group-only currency typing is not accepted placement evidence.
    group_only = parse_mybroker(endpoint_xml(rub_on_group=True), FILENAME)
    assert group_only["rub_money"] == []
    assert "position_row_unclassified" in group_only["endpoint_blockers"]
    assert "rub_money_unavailable" in group_only["endpoint_blockers"]

    unclassified = parse_mybroker(endpoint_xml(rub=False, unclassified=True), FILENAME)
    assert "position_row_unclassified" in unclassified["endpoint_blockers"]
    assert unclassified["rub_money"] == []
    assert "unparsed_source_rows" not in unclassified["syntax_blockers"]


def test_missing_endpoint_fields_are_visible_never_zero():
    document = parse_mybroker(endpoint_xml(beginning=None, values=False, rub=False), FILENAME)
    assert set(document["endpoint_blockers"]) == {
        "endpoint_beginning_quantity_unavailable",
        "endpoint_value_unavailable",
        "rub_money_unavailable",
    }
    position = document["positions"][0]
    assert position["beginning_actual_quantity"] is None
    assert position["beginning_value"] is None
    assert position["ending_value"] is None
    assert position["actual_quantity"] == "10"

    quiet = parse_mybroker(fixture(quiet=True), FILENAME)
    assert quiet["endpoint_blockers"] == []
    assert quiet["rub_money"] == []


def test_incomplete_rub_row_is_a_blocker_and_multiple_rows_conflict():
    partial = parse_mybroker(endpoint_xml(rub_amounts=("500", None)), FILENAME)
    assert partial["endpoint_blockers"] == ["rub_money_incomplete"]

    ambiguous = parse_mybroker(endpoint_xml(rub_rows=2), FILENAME)
    assert ambiguous["endpoint_conflicts"] == ["rub_money_ambiguous"]
    assert len(ambiguous["rub_money"]) == 2
    assert ambiguous["endpoint_blockers"] == []


def test_row_limit_counts_all_consumed_position_rows():
    allowed = parse_mybroker(limit_xml(security=10000, unclassified=0), FILENAME)
    assert len(allowed["positions"]) == 10000
    with pytest.raises(MyBrokerError, match="row_limit_exceeded"):
        parse_mybroker(limit_xml(security=10001, unclassified=0), FILENAME)

    allowed = parse_mybroker(limit_xml(security=0, unclassified=10000), FILENAME)
    assert allowed["positions"] == [] and allowed["rub_money"] == []
    assert "position_row_unclassified" in allowed["endpoint_blockers"]
    with pytest.raises(MyBrokerError, match="row_limit_exceeded"):
        parse_mybroker(limit_xml(security=0, unclassified=10001), FILENAME)

    allowed = parse_mybroker(limit_xml(security=5000, unclassified=5000), FILENAME)
    assert len(allowed["positions"]) == 5000
    assert "position_row_unclassified" in allowed["endpoint_blockers"]
    with pytest.raises(MyBrokerError, match="row_limit_exceeded"):
        parse_mybroker(limit_xml(security=5000, unclassified=5001), FILENAME)


def test_endpoint_evidence_preview_apply_and_financial_boundary(database):
    xml = endpoint_xml()
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        assert reviewed["blockers"] == [] and reviewed["conflicts"] == []
        assert reviewed["can_apply"]
        document = reviewed["document"]
        assert document["positions"][0]["ending_value"] == "1000"
        assert document["rub_money"][0]["ending_amount"] == "400"
        applied = apply(session, xml, reviewed)
        reread = read_mybroker_import(session, applied["import_id"])
        assert reread["document"] == applied["document"] == document
        assert reread["coverage_state"] == "unknown"
        for model in (ReportingMonth, PositionSnapshot, InvestmentCashFlow, CashBalance):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_changed_endpoint_value_makes_apply_stale(database):
    xml = endpoint_xml()
    changed = xml.replace(b'real_volume="1000.00"', b'real_volume="1001.00"')
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        with pytest.raises(MyBrokerError, match="preview_stale"):
            apply(session, changed, reviewed)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_same_bytes_remain_an_idempotent_duplicate(database):
    xml = endpoint_xml()
    with database.session_factory() as session:
        first = apply(session, xml, preview(session, xml))
        second = apply(session, xml, preview(session, xml))
        assert second["duplicate"] is True
        assert second["import_id"] == first["import_id"]
        assert second["document"] == first["document"]
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


def test_legacy_v1_same_hash_row_is_an_explicit_conflict(database):
    xml = endpoint_xml()
    with database.session_factory() as session:
        applied = apply(session, xml, preview(session, xml))
        stored = session.get(MyBrokerImport, applied["import_id"])
        legacy_json = stored.normalized_json.replace('"mybroker-s1-v2"', '"mybroker-s1-v1"')
        session.execute(
            update(MyBrokerImport)
            .where(MyBrokerImport.id == applied["import_id"])
            .values(parser_version="mybroker-s1-v1", normalized_json=legacy_json)
        )
        session.commit()
        session.expire_all()
        reviewed = preview(session, xml)
        assert "accepted_parser_version_conflict" in reviewed["conflicts"]
        assert not reviewed["can_apply"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, reviewed)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1


def test_ambiguous_rub_rows_refuse_apply(database):
    xml = endpoint_xml(rub_rows=2)
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        assert "rub_money_ambiguous" in reviewed["conflicts"]
        assert not reviewed["can_apply"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, reviewed)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_evidence_gaps_stay_visible_without_blocking_apply(database):
    xml = endpoint_xml(beginning=None, values=False, rub=False)
    expected = {
        "endpoint_beginning_quantity_unavailable",
        "endpoint_value_unavailable",
        "rub_money_unavailable",
    }
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        assert expected <= set(reviewed["blockers"])
        assert reviewed["can_apply"]
        applied = apply(session, xml, reviewed)
        assert set(applied["document"]["endpoint_blockers"]) == expected
        assert applied["document"]["positions"][0]["ending_value"] is None


def test_endpoint_values_do_not_widen_the_class_guard(database):
    with database.session_factory() as session:
        xml = positions_only(endpoint_xml())
        reviewed = preview(session, xml)
        account = next(b["hermes_id"] for b in reviewed["mappings"] if b["kind"] == "account")
        assert not _source_affects_interval(
            reviewed["document"],
            reviewed["mappings"],
            (account,),
            date(2030, 1, 1),
            date(2030, 1, 31),
            {},
        )
        apply(session, xml, reviewed)
        assert (
            unresolved_class_source_ids(session, (account,), date(2030, 1, 1), date(2030, 1, 31))
            == []
        )

        delta = positions_only(endpoint_xml(forward="20"))
        delta_reviewed = preview(session, delta)
        apply(session, delta, delta_reviewed)
        guarded = unresolved_class_source_ids(
            session, (account,), date(2030, 1, 1), date(2030, 1, 31)
        )
        assert len(guarded) == 1


def test_accepted_endpoint_quantity_conflict_remains(database):
    xml = endpoint_xml()
    with database.session_factory() as session:
        reviewed = preview(session, xml)
        account = next(b["hermes_id"] for b in reviewed["mappings"] if b["kind"] == "account")
        instrument = next(b["hermes_id"] for b in reviewed["mappings"] if b["kind"] == "instrument")
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
            PositionSnapshot(
                reporting_month_id=month.id,
                account_id=account,
                instrument_id=instrument,
                quantity=Decimal("9"),
                average_cost_per_unit_kopecks=0,
                market_price_per_unit_kopecks=0,
                market_value_kopecks=0,
                cost_basis_kopecks=0,
                unrealized_result_kopecks=0,
                price_date=date(2030, 1, 31),
            )
        )
        session.commit()
        conflicted = preview(session, xml)
        assert "accepted_endpoint_quantity_conflict" in conflicted["conflicts"]
        with pytest.raises(MyBrokerError, match="reconciliation_required"):
            apply(session, xml, conflicted)
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_http_endpoint_evidence_round_trip(database):
    client = TestClient(create_app(database=database))
    xml = endpoint_xml()
    files = {"file": (FILENAME, xml, "application/xml")}
    response = client.post("/api/mybroker-import/preview", files=files)
    assert response.status_code == 200, response.text
    body = response.json()
    confirmation = {
        "confirmation_digest": body["confirmation_digest"],
        "covered_from": body["document"]["covered_from"],
        "covered_to": body["document"]["covered_to"],
        "mappings": body["mappings"],
    }
    applied = client.post(
        "/api/mybroker-import/apply", files=files, data={"confirmation": json.dumps(confirmation)}
    )
    assert applied.status_code == 200, applied.text
    reread = client.get(f"/api/mybroker-import/{applied.json()['import_id']}").json()
    assert reread["document"] == applied.json()["document"]
    assert reread["document"]["parser"] == "mybroker-s1-v2"
    assert reread["document"]["positions"][0]["beginning_value"] == "800"
    assert reread["document"]["rub_money"][0]["ending_amount"] == "400"
    assert reread["coverage_state"] == "unknown"
