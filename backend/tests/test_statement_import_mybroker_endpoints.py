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


def broker_month_xml(*, unsupported=False, bond=False):
    """Supported fabricated monthly inventory; no guessed Money classification."""
    from copy import deepcopy

    root = ET.fromstring(endpoint_xml(rub_amounts=("1400.00", "400.00")))
    security = root.find(".//{MyBroker}Details[@ISIN1]")
    security.set("active_type", "Акции")
    security.set("active_name", "Synthetic stock")
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    trade.set("qty", "2")
    trade.set("p_name", "Synthetic stock")
    trade.set("Textbox14", "RUB")
    if unsupported:
        root.find(".//{MyBroker}comment").set(
            "comment", "Fabricated unclassified coupon-like posting"
        )
    if bond:
        row = deepcopy(security)
        row.set("ISIN1", "RU000A000001")
        row.set("active_type", "Облигации")
        row.set("active_name", "Synthetic bond")
        row.set("income_rest", "10")
        row.set("income_volume", "999.99")
        row.set("real_volume", "1000.01")
        root.find(".//{MyBroker}Details_Collection").append(row)
    return ET.tostring(root, encoding="utf-8")


def _broker_month_setup(database, *, bond=False):
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.services.reporting_months import create_reporting_month

    with database.session_factory() as session:
        if bond:
            create_instrument(
                session, name="Synthetic bond", instrument_type="bond", isin="RU000A000001"
            )
        month = create_reporting_month(session, year=2030, month=1, snapshot_date=date(2030, 1, 31))
        return {"reporting_month_id": month.id, "account_id": 1}


def _broker_month_preview(client, intent, xml, filename=FILENAME, supporting=None):
    response = client.post(
        "/api/broker-months/preview",
        files=[("file", (filename, xml, "application/xml")), *(supporting or [])],
        data={"intent": json.dumps(intent)},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _broker_month_apply(
    client, intent, reviewed, xml, request_id="synthetic-batch", filename=FILENAME, supporting=None
):
    return client.post(
        "/api/broker-months/apply",
        files=[("file", (filename, xml, "application/xml")), *(supporting or [])],
        data={
            "confirmation": json.dumps(
                {
                    **intent,
                    "confirmation_digest": reviewed["confirmation_digest"],
                    "request_id": request_id,
                }
            )
        },
    )


def test_broker_month_atomic_native_draft_get_close_and_replay(database):
    from hermes_finance.persistence import (
        BrokerIdentityMapping,
        BrokerMonthApply,
        ExecutedTrade,
        ExecutedTradeRevision,
    )
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import revoke_mapping

    intent = _broker_month_setup(database, bond=True)
    # Unrelated account remains advisory; a fresh mapping is staged in the batch.
    with database.session_factory() as session:
        create_account(session, name="Unrelated synthetic deposit", account_type="deposit")
        mapping = session.scalar(
            select(BrokerIdentityMapping).where(BrokerIdentityMapping.subject_kind == "instrument")
        )
        revoke_mapping(session, mapping.id)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml(bond=True)
    reviewed = _broker_month_preview(client, intent, xml)
    assert reviewed["can_apply"] and reviewed["bookkeeping_ready"], reviewed
    assert reviewed["cash_control_difference_kopecks"] == 0
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
    response = _broker_month_apply(client, intent, reviewed, xml)
    assert response.status_code == 200, response.text
    applied = response.json()
    readback = client.get("/api/broker-months/synthetic-batch").json()
    assert {k: v for k, v in applied.items() if k != "duplicate"} == readback
    assert readback["bookkeeping_ready"] and readback["status"] == "draft"
    with database.session_factory() as session:
        positions = list(session.scalars(select(PositionSnapshot).order_by(PositionSnapshot.id)))
        assert [p.market_value_kopecks for p in positions] == [100000, 100001]
        assert all(
            p.cost_basis_kopecks is None
            and p.unrealized_result_kopecks is None
            and p.accrued_interest_kopecks is None
            for p in positions
        )
        assert positions[1].bond_nkd_basis == "unknown"
        assert session.scalar(select(CashBalance)).amount_kopecks == 40000
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0
        assert session.scalar(select(func.count()).select_from(ExecutedTrade)) == 1
        assert session.scalar(select(func.count()).select_from(ExecutedTradeRevision)) == 1
    # Same original, fresh confirmation/key: reuse all economic rows.
    again = _broker_month_preview(client, intent, xml)
    replay = _broker_month_apply(client, intent, again, xml, request_id="fresh-replay")
    assert replay.status_code == 200, replay.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 2
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 1
        assert session.scalar(select(func.count()).select_from(ExecutedTradeRevision)) == 1
        assert session.scalar(select(func.count()).select_from(BrokerMonthApply)) == 2
    readiness = client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()
    assert readiness["can_close"]
    assert any(
        i["code"] == "active_account_snapshot_missing" and i["severity"] == "warning"
        for i in readiness["items"]
    )
    closed = client.post(f"/api/months/{intent['reporting_month_id']}/close")
    assert closed.status_code == 200 and closed.json()["status"] == "closed", closed.text
    exact_replay = _broker_month_apply(client, intent, reviewed, xml)
    assert exact_replay.status_code == 200 and exact_replay.json()["duplicate"]
    blocked = _broker_month_preview(client, intent, xml)
    assert "reporting_month_closed" in blocked["conflicts"]


def test_broker_month_unsupported_money_partial_draft_blocks_readiness_and_close(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml(unsupported=True)
    reviewed = _broker_month_preview(client, intent, xml)
    assert reviewed["can_apply"] and not reviewed["bookkeeping_ready"]
    assert "money_semantics_unsupported" in reviewed["exceptions"]
    assert len(reviewed["document"]["money"]) == 1
    response = _broker_month_apply(client, intent, reviewed, xml)
    assert response.status_code == 200, response.text
    assert not client.get("/api/broker-months/synthetic-batch").json()["bookkeeping_ready"]
    readiness = client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()
    assert not readiness["can_close"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    with database.session_factory() as session:
        assert session.scalar(select(ReportingMonth)).status == "draft"
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0


def test_broker_month_stale_and_late_failure_roll_back_entire_batch(database, monkeypatch):
    import hermes_finance.services.broker_months as service
    from hermes_finance.persistence import Base

    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database), raise_server_exceptions=False)
    xml = broker_month_xml()
    reviewed = _broker_month_preview(client, intent, xml)
    changed = xml.replace(b'real_volume="1000.00"', b'real_volume="1000.01"')
    assert _broker_month_apply(client, intent, reviewed, changed).status_code == 409
    with database.session_factory() as session:
        before = {
            t.name: session.scalar(select(func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
        }

    def interrupted(*args, **kwargs):
        raise RuntimeError("synthetic late interruption")

    monkeypatch.setattr(service, "stage_native_position", interrupted)
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 500
    with database.session_factory() as session:
        after = {
            t.name: session.scalar(select(func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
        }
    assert before == after


def test_broker_month_currency_manual_and_optional_evidence_fail_closed(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    novel = xml.replace(ISIN.encode(), b"RU000A000009")
    blocked = _broker_month_preview(client, intent, novel)
    assert not blocked["can_apply"] and "instrument_currency_unproven" in blocked["conflicts"]
    supporting = [
        ("supporting", ("synthetic.xml", b"fabricated optional evidence", "application/xml"))
    ]
    reviewed = _broker_month_preview(client, intent, xml, supporting=supporting)
    assert (
        "optional_evidence_unsupported" in reviewed["exceptions"]
        and not reviewed["bookkeeping_ready"]
    )
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 409
    with database.session_factory() as session:
        session.add(
            CashBalance(
                reporting_month_id=intent["reporting_month_id"],
                account_id=1,
                name="Manual",
                amount_kopecks=40000,
            )
        )
        session.commit()
    assert (
        "existing_cash_reconciliation_required"
        in _broker_month_preview(client, intent, xml)["conflicts"]
    )


@pytest.mark.parametrize("optional_first", [True, False])
def test_broker_month_all_receipts_block_account_preview_get_and_close(database, optional_first):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    supporting = [
        ("supporting", ("synthetic.xml", b"fabricated optional evidence", "application/xml"))
    ]
    first_files = supporting if optional_first else []
    first = _broker_month_preview(client, intent, xml, supporting=first_files)
    assert first["bookkeeping_ready"] == (not optional_first)
    result = _broker_month_apply(
        client, intent, first, xml, request_id="first", supporting=first_files
    )
    assert result.status_code == 200, result.text
    second_files = [] if optional_first else supporting
    second = _broker_month_preview(client, intent, xml, supporting=second_files)
    assert second["can_apply"] and not second["bookkeeping_ready"]
    assert "optional_evidence_unsupported" in second["exceptions"]
    result = _broker_month_apply(
        client, intent, second, xml, request_id="second", supporting=second_files
    )
    assert result.status_code == 200, result.text
    assert not result.json()["bookkeeping_ready"]
    for request_id in ("first", "second"):
        current = client.get(f"/api/broker-months/{request_id}").json()
        assert not current["bookkeeping_ready"]
        assert "optional_evidence_unsupported" in current["exceptions"]
    # A further clean upload cannot erase the applicable optional-document evidence.
    clean = _broker_month_preview(client, intent, xml)
    assert clean["can_apply"] and not clean["bookkeeping_ready"]
    assert "optional_evidence_unsupported" in clean["exceptions"]
    readiness = client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()
    assert not readiness["can_close"]
    assert any(i["code"] == "optional_evidence_unsupported" for i in readiness["items"])
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    with database.session_factory() as session:
        assert session.get(ReportingMonth, intent["reporting_month_id"]).status == "draft"
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 1
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 1
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 1


def test_broker_month_changed_projection_atomically_prevents_close(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    reviewed = _broker_month_preview(client, intent, xml)
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 200
    assert client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()[
        "can_close"
    ]
    with database.session_factory() as session:
        session.execute(update(CashBalance).values(amount_kopecks=40001))
        session.commit()
    readback = client.get("/api/broker-months/synthetic-batch").json()
    assert "source_projection_changed" in readback["exceptions"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422


@pytest.mark.parametrize("source_first", [True, False])
def test_broker_month_overlapping_reports_share_canonical_trade_and_projection(
    database, source_first
):
    from hermes_finance.persistence import ExecutedTrade, ExecutedTradeOccurrence

    intent = _broker_month_setup(database)
    xml = broker_month_xml()
    filename = FILENAME.replace("31.01.30", "20.01.30")
    narrow = ET.fromstring(xml)
    narrow.set("synthetic_revision", "narrow")
    narrow_xml = ET.tostring(narrow, encoding="utf-8")
    client = TestClient(create_app(database=database))

    def accept_narrow():
        with database.session_factory() as session:
            reviewed = preview(session, narrow_xml, filename)
            apply(session, narrow_xml, reviewed, filename)

    if source_first:
        accept_narrow()
    reviewed = _broker_month_preview(client, intent, xml)
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 200
    if not source_first:
        accept_narrow()
        refreshed = _broker_month_preview(client, intent, xml)
        assert (
            _broker_month_apply(
                client, intent, refreshed, xml, request_id="overlap-refresh"
            ).status_code
            == 200
        )
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ExecutedTrade)) == 1
        assert session.scalar(select(func.count()).select_from(ExecutedTradeOccurrence)) == 2
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 1
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0


def test_broker_month_two_native_ids_with_same_economics_stay_distinct(database):
    from copy import deepcopy

    from hermes_finance.persistence import ExecutedTrade

    intent = _broker_month_setup(database)
    root = ET.fromstring(broker_month_xml())
    security = root.find(".//{MyBroker}Details[@ISIN1]")
    security.set("real_rest", "12")
    security.set("forward_rest", "12")
    security.set("real_volume", "1200.00")
    root.find(".//{MyBroker}Details[@active_name='RUB']").set("income_rest", "2400.00")
    trade = deepcopy(root.find(".//{MyBroker}Details[@trade_no]"))
    trade.set("trade_no", "2001\n2002")
    root.find(".//{MyBroker}Tablix2/{MyBroker}Details_Collection").append(trade)
    money = deepcopy(root.find(".//{MyBroker}rn"))
    money.find(".//{MyBroker}comment").set("comment", "Расчеты по сделке 2001")
    root.find(".//{MyBroker}rn_Collection").append(money)
    xml = ET.tostring(root, encoding="utf-8")
    client = TestClient(create_app(database=database))
    reviewed = _broker_month_preview(client, intent, xml)
    assert reviewed["bookkeeping_ready"], reviewed
    response = _broker_month_apply(client, intent, reviewed, xml)
    assert response.status_code == 200, response.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ExecutedTrade)) == 2


def test_broker_month_conflicting_later_source_blocks_close_without_rewriting_rows(database):
    intent = _broker_month_setup(database)
    xml = broker_month_xml()
    client = TestClient(create_app(database=database))
    reviewed = _broker_month_preview(client, intent, xml)
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 200
    conflicting = xml.replace(b'real_volume="1000.00"', b'real_volume="1000.01"')
    with database.session_factory() as session:
        raw = preview(session, conflicting)
        assert raw["can_apply"]
        apply(session, conflicting, raw)
    assert (
        "overlapping_endpoint_conflict"
        in client.get("/api/broker-months/synthetic-batch").json()["exceptions"]
    )
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    with database.session_factory() as session:
        assert session.scalar(select(PositionSnapshot)).market_value_kopecks == 100000


def test_broker_month_close_holds_writer_through_source_recheck(database, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    from hermes_finance.services import broker_months
    from hermes_finance.services.reporting_months import close_reporting_month

    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    reviewed = _broker_month_preview(client, intent, xml)
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 200
    reserved, release = Event(), Event()
    original = broker_months._readiness

    def paused(session, receipt):
        result = original(session, receipt)
        reserved.set()
        assert release.wait(10)
        return result

    monkeypatch.setattr(broker_months, "_readiness", paused)

    def close():
        with database.session_factory() as session:
            close_reporting_month(session, intent["reporting_month_id"])

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(close)
        try:
            assert reserved.wait(10)
            with database.session_factory() as other:
                other.execute(text("PRAGMA busy_timeout=0"))
                with pytest.raises(OperationalError, match="database is locked"):
                    other.execute(update(CashBalance).values(amount_kopecks=1))
                other.rollback()
        finally:
            release.set()
        future.result(timeout=10)


def test_broker_month_quantity_cash_missingness_and_fractional_minor_units(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    fractional = xml.replace(b'real_volume="1000.00"', b'real_volume="1000.001"')
    assert (
        client.post(
            "/api/broker-months/preview",
            files={"file": (FILENAME, fractional, "application/xml")},
            data={"intent": json.dumps(intent)},
        ).status_code
        == 422
    )
    precision = xml.replace(b'real_rest="10"', b'real_rest="10.1234567"')
    assert (
        "quantity_precision_unsupported"
        in _broker_month_preview(client, intent, precision)["conflicts"]
    )
    missing = xml.replace(b' real_volume="1000.00"', b"")
    assert not _broker_month_preview(client, intent, missing)["can_apply"]


def test_broker_month_missing_canonical_occurrence_blocks_current_get_and_close(database):
    from sqlalchemy import delete

    from hermes_finance.persistence import ExecutedTradeOccurrence

    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    reviewed = _broker_month_preview(client, intent, xml)
    assert _broker_month_apply(client, intent, reviewed, xml).status_code == 200
    with database.session_factory() as session:
        session.execute(delete(ExecutedTradeOccurrence))
        session.commit()
    assert (
        "canonical_trade_projection_changed"
        in _broker_month_preview(client, intent, xml)["exceptions"]
    )
    assert (
        "canonical_trade_projection_changed"
        in client.get("/api/broker-months/synthetic-batch").json()["exceptions"]
    )
    assert not client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()[
        "can_close"
    ]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422


def test_broker_month_preview_discloses_intersecting_unsupported_money(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml(unsupported=True)
    narrow = FILENAME.replace("31.01.30", "20.01.30")
    with database.session_factory() as session:
        apply(session, xml, preview(session, xml, narrow), narrow)
    plan = _broker_month_preview(client, intent, broker_month_xml())
    assert "money_semantics_unsupported" in plan["exceptions"]
    assert not plan["bookkeeping_ready"]


def test_broker_month_balanced_endpoints_do_not_clear_unresolved_trade_principal(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml().replace(b'summ_trade="1000.00"', b'summ_trade="999.00"')
    plan = _broker_month_preview(client, intent, xml)
    assert plan["cash_control_difference_kopecks"] == 0
    assert plan["quantity_controls"][0]["difference"] == "0"
    assert plan["can_apply"] and not plan["bookkeeping_ready"]
    assert "settlement_principal_unresolved" in plan["exceptions"]
    result = _broker_month_apply(client, intent, plan, xml)
    assert result.status_code == 200, result.text
    assert not result.json()["bookkeeping_ready"]
    assert (
        "settlement_principal_unresolved"
        in client.get("/api/broker-months/synthetic-batch").json()["exceptions"]
    )
    assert not client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()[
        "can_close"
    ]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422


@pytest.mark.parametrize("missing_date", ["save_depo_settlement_date", "save_settlement_date"])
def test_broker_month_new_trade_missing_settlement_blocks_preview_get_and_close(
    database, missing_date
):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    root = ET.fromstring(broker_month_xml())
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    trade.attrib.pop(missing_date)
    root.find(".//{MyBroker}Details[@ISIN1]").set("income_rest", "10")
    xml = ET.tostring(root, encoding="utf-8")
    plan = _broker_month_preview(client, intent, xml)
    assert plan["cash_control_difference_kopecks"] == 0
    assert plan["can_apply"] and not plan["bookkeeping_ready"]
    assert "actual_settlement_missing" in plan["exceptions"]
    result = _broker_month_apply(client, intent, plan, xml)
    assert result.status_code == 200, result.text
    readback = client.get("/api/broker-months/synthetic-batch").json()
    assert "actual_settlement_missing" in readback["exceptions"]
    assert not readback["bookkeeping_ready"]
    readiness = client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()
    assert not readiness["can_close"]
    assert any(i["code"] == "actual_settlement_missing" for i in readiness["items"])
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422
    with database.session_factory() as session:
        assert session.get(ReportingMonth, intent["reporting_month_id"]).status == "draft"


def test_broker_month_affirmative_sold_out_position_is_source_zero_not_a_holding(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = (
        broker_month_xml()
        .replace(b'real_rest="10"', b'real_rest="0"')
        .replace(b'forward_rest="10"', b'forward_rest="0"')
        .replace(b'real_volume="1000.00"', b'real_volume="0"')
        .replace(b'qty="2"', b'qty="-8"')
        .replace(b'summ_trade="1000.00"', b'summ_trade="800.00"')
        .replace(b'volume="-1000.00"', b'volume="800.00"')
        .replace(b'real_rest="400.00"', b'real_rest="2200.00"')
    )
    plan = _broker_month_preview(client, intent, xml)
    assert plan["can_apply"] and plan["bookkeeping_ready"], plan
    assert plan["positions"][0]["action"] == "observed_zero"
    result = _broker_month_apply(client, intent, plan, xml)
    assert result.status_code == 200, result.text
    assert result.json()["bookkeeping_ready"]
    assert result.json()["accepted"]["position_ids"] == []
    assert result.json()["accepted"]["document"]["positions"][0]["actual_quantity"] == "0"
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
        assert session.scalar(select(CashBalance)).amount_kopecks == 220000
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 200


def test_broker_month_fractional_stock_is_a_preview_conflict(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = (
        broker_month_xml()
        .replace(b'real_rest="10"', b'real_rest="10.5"')
        .replace(b'forward_rest="10"', b'forward_rest="10.5"')
    )
    plan = _broker_month_preview(client, intent, xml)
    assert not plan["can_apply"]
    assert "quantity_precision_unsupported" in plan["conflicts"]
    assert _broker_month_apply(client, intent, plan, xml).status_code == 409
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0


def test_broker_month_inexact_sqlite_bond_quantity_is_rejected_before_apply(database):
    intent = _broker_month_setup(database, bond=True)
    client = TestClient(create_app(database=database))
    root = ET.fromstring(broker_month_xml(bond=True))
    bond = root.find(".//{MyBroker}Details[@ISIN1='RU000A000001']")
    for field in ("income_rest", "real_rest", "forward_rest"):
        bond.set(field, "999999999999.999999")
    xml = ET.tostring(root, encoding="utf-8")
    plan = _broker_month_preview(client, intent, xml)
    assert not plan["can_apply"]
    assert "quantity_precision_unsupported" in plan["conflicts"]
    result = _broker_month_apply(client, intent, plan, xml)
    assert result.status_code == 409, result.text
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MyBrokerImport)) == 0
        assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 0


def test_broker_month_close_refreshes_loaded_financial_facts_after_reservation(database):
    from hermes_finance.services.reporting_months import close_reporting_month

    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    plan = _broker_month_preview(client, intent, xml)
    assert _broker_month_apply(client, intent, plan, xml).status_code == 200
    with database.session_factory() as stale:
        cash = stale.scalar(select(CashBalance))
        assert cash.amount_kopecks == 40000
        with database.session_factory() as writer:
            writer.execute(update(CashBalance).values(amount_kopecks=1))
            writer.commit()
        with pytest.raises(ValueError, match="сохранённые позиции или cash"):
            close_reporting_month(stale, intent["reporting_month_id"])
    assert client.get(f"/api/months/{intent['reporting_month_id']}").json()["status"] == "draft"


def test_broker_month_missing_security_inventory_is_not_affirmative_zero(database):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    root = ET.fromstring(positions_only(broker_month_xml()))
    collection = root.find(".//{MyBroker}Details_Collection")
    collection.remove(collection.find("{MyBroker}Details[@ISIN1]"))
    cash = collection.find("{MyBroker}Details")
    cash.set("income_rest", "0")
    cash.set("real_rest", "0")
    xml = ET.tostring(root, encoding="utf-8")
    plan = _broker_month_preview(client, intent, xml)
    assert plan["can_apply"] and not plan["bookkeeping_ready"]
    assert "security_inventory_unproven" in plan["exceptions"]
    assert _broker_month_apply(client, intent, plan, xml).status_code == 200
    assert not client.get("/api/broker-months/synthetic-batch").json()["bookkeeping_ready"]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 422


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
