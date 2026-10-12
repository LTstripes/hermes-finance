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
    BrokerMonthApply,
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
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, parse_mybroker


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
    client,
    intent,
    reviewed,
    xml,
    request_id="synthetic-batch",
    filename=FILENAME,
    supporting=None,
    decisions=None,
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
                    "reviewed_account_bindings": (
                        reviewed["account_bindings"] if decisions is None else decisions
                    ),
                }
            )
        },
    )


def broker_month_alias_xml(*, bond=False, unsupported=False):
    """Distinct fabricated codes: no suffix/name equivalence is assumed."""
    root = ET.fromstring(broker_month_xml(bond=bond, unsupported=unsupported))
    for row in root.iter():
        if "acc_code" in row.attrib:
            row.set(
                "acc_code",
                "ROW-B" if row.get("active_name") == "RUB" else "ROW-A",
            )
    return ET.tostring(root, encoding="utf-8")


def _all_month_tables(database):
    from hermes_finance.persistence import Base

    with database.session_factory() as session:
        return {
            t.name: [tuple(str(v) for v in row) for row in session.execute(select(t))]
            for t in Base.metadata.sorted_tables
        }


@pytest.mark.parametrize("invalid", ["missing", "partial", "duplicate", "unobserved", "target"])
def test_broker_month_multiple_new_aliases_require_exact_explicit_decisions(database, invalid):
    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_alias_xml()
    filename = FILENAME.replace("1234567", "7654321")
    before = _all_month_tables(database)
    plan = _broker_month_preview(client, intent, xml, filename=filename)
    assert _all_month_tables(database) == before  # Preview cannot stage mappings.
    assert plan["can_apply"], plan["conflicts"]
    assert plan["account_aliases"] == [
        {
            "identity": alias,
            "hermes_id": 1,
            "mapping_id": None,
            "action": "stage_create",
            "origins": [origin],
            "target_name": "Synthetic account",
        }
        for alias, origin in [
            ("7654321", "filename_account"),
            ("ROW-A", "acc_code"),
            ("ROW-B", "acc_code"),
        ]
    ]
    decisions = plan["account_bindings"]
    invalid_decisions = {
        "missing": [],
        "partial": decisions[:-1],
        "duplicate": decisions + [decisions[0]],
        "unobserved": decisions + [{"identity": "NEVER-OBSERVED", "hermes_id": 1}],
        "target": [{**d, "hermes_id": 999999} for d in decisions],
    }[invalid]
    rejected = _broker_month_apply(
        client, intent, plan, xml, filename=filename, decisions=invalid_decisions
    )
    assert rejected.status_code == 409
    assert rejected.json()["error"]["message"] == "broker_month_account_bindings_unconfirmed"
    assert _all_month_tables(database) == before
    accepted = _broker_month_apply(client, intent, plan, xml, filename=filename)
    assert accepted.status_code == 200, accepted.text
    reread = client.get("/api/broker-months/synthetic-batch")
    assert reread.json()["accepted"] == accepted.json()["accepted"]
    replay = _broker_month_apply(client, intent, plan, xml, filename=filename)
    assert replay.status_code == 200 and replay.json()["duplicate"]
    assert (
        _broker_month_apply(client, intent, plan, xml, filename=filename, decisions=[]).status_code
        == 409
    )
    fresh = _broker_month_preview(client, intent, xml, filename=filename)
    assert fresh["account_bindings"] == []
    assert all(a["action"] == "reuse" for a in fresh["account_aliases"])
    after = _all_month_tables(database)
    assert (
        _broker_month_apply(
            client, intent, fresh, xml, filename=filename, request_id="reuse"
        ).status_code
        == 200
    )
    current = _all_month_tables(database)
    for table in after:
        if table not in {"broker_month_applies", "executed_trade_applies"}:
            assert current[table] == after[table]


@pytest.mark.parametrize("change", ["row", "filename", "mapping", "inactive_target"])
def test_broker_month_alias_decisions_stale_preview_rolls_back_all_tables(database, change):
    from hermes_finance.persistence import Account
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_identity_mappings import confirm_mapping

    intent = _broker_month_setup(database)
    client = TestClient(create_app(database=database))
    xml = broker_month_alias_xml()
    filename = FILENAME.replace("1234567", "7654321")
    plan = _broker_month_preview(client, intent, xml, filename=filename)
    if change == "row":
        xml = xml.replace(b"ROW-B", b"ROW-C")
    elif change == "filename":
        filename = filename.replace("7654321", "7654322")
    else:
        with database.session_factory() as session:
            if change == "mapping":
                other = create_account(
                    session, name="Other synthetic broker", account_type="brokerage"
                )
                confirm_mapping(
                    session,
                    provider=PROVIDER,
                    subject_kind="account",
                    provider_identity="ROW-B",
                    hermes_target_id=other.id,
                )
            else:
                session.get(Account, 1).status = "closed"
                session.commit()
    before = _all_month_tables(database)
    response = _broker_month_apply(client, intent, plan, xml, filename=filename)
    assert (
        response.status_code == 409
        and response.json()["error"]["message"] == "broker_month_preview_stale"
    )
    assert _all_month_tables(database) == before
    if change == "mapping":
        fresh = _broker_month_preview(client, intent, xml, filename=filename)
        assert not fresh["can_apply"]
        assert "account_mapping_conflict" in fresh["conflicts"]
        assert _broker_month_apply(client, intent, fresh, xml, filename=filename).status_code == 409
        assert _all_month_tables(database) == before


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
    assert reviewed["account_bindings"] == []
    assert all(a["action"] == "reuse" for a in reviewed["account_aliases"])
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
        assert "canonical_trade_projection_changed" in refreshed["exceptions"]
        assert not refreshed["bookkeeping_ready"]
        assert (
            _broker_month_apply(
                client, intent, refreshed, xml, request_id="overlap-refresh"
            ).status_code
            == 200
        )
    for request_id in ("synthetic-batch", *([] if source_first else ["overlap-refresh"])):
        current = client.get(f"/api/broker-months/{request_id}").json()
        assert current["bookkeeping_ready"], current
        assert "canonical_trade_projection_changed" not in current["exceptions"]
    fresh = _broker_month_preview(client, intent, xml)
    assert fresh["bookkeeping_ready"], fresh
    assert client.get(f"/api/months/{intent['reporting_month_id']}/close-readiness").json()[
        "can_close"
    ]
    assert client.post(f"/api/months/{intent['reporting_month_id']}/close").status_code == 200
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


# #782: fabricated original-bound Money acceptance in the existing month lane.
def money_batch_xml(*, coupons=("1000.00", "2000.00"), distinct=False, nkd=False, stamp="10"):
    from copy import deepcopy

    from test_statement_import_mybroker_money_candidates import original

    root = ET.fromstring(broker_month_xml(bond=True))
    incoming = ET.fromstring(original(coupons=coupons))
    collection = root.find(".//{MyBroker}rn_Collection")
    extra = []
    coupon_index = 0
    for row in incoming.findall(".//{MyBroker}rn"):
        op = row.find("{MyBroker}oper_type")
        if op.get("oper_type") == "Перевод" or (nkd and op.get("oper_type") == "НКД по сделке"):
            # Separate amount leaves are still exact independent occurrences.
            for leaf in row.findall(".//{MyBroker}p_code[@volume]"):
                copy = deepcopy(row)
                leaves = copy.findall(".//{MyBroker}p_code[@volume]")
                for other in leaves:
                    if other.get("volume") != leaf.get("volume") or other is not leaves[0]:
                        parent = next(p for p in copy.iter() if other in list(p))
                        parent.remove(other)
                remaining = copy.find(".//{MyBroker}p_code[@volume]")
                if remaining is None:
                    remaining = deepcopy(leaf)
                    copy.find(".//{MyBroker}p_code_Collection/{MyBroker}p_code").append(remaining)
                remaining.set("volume", leaf.get("volume"))
                comment = copy.find("{MyBroker}oper_type/{MyBroker}comment")
                if distinct and "погашение купона" in comment.get("comment"):
                    comment.set(
                        "comment",
                        comment.get("comment").replace(
                            "SYNTHETIC-TOKEN", f"SYNTHETIC-{coupon_index}"
                        ),
                    )
                    coupon_index += 1
                copy.set("last_update", f"2030-01-17T10:00:{stamp}")
                extra.append(copy)
    collection.extend(extra)
    added = sum(Decimal(r.find(".//{MyBroker}p_code[@volume]").get("volume")) for r in extra)
    # Existing baseline endpoint has 400 RUB after its proved 1000 settlement.
    root.find(".//{MyBroker}Details[@active_name='RUB']").set(
        "real_rest", str(Decimal("400") + added)
    )
    return ET.tostring(root, encoding="utf-8")


def _money_setup(database, xml=None):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import Instrument

    scope = _broker_month_setup(database, bond=True)
    client = TestClient(create_app(database))
    xml = xml or money_batch_xml()
    plan = _broker_month_preview(client, scope, xml)
    response = _broker_month_apply(client, scope, plan, xml, request_id="base-money")
    assert response.status_code == 200, response.text
    saved = response.json()
    with database.session_factory() as session:
        bond_id = session.scalar(select(Instrument.id).where(Instrument.instrument_type == "bond"))
    intent = MoneyIntent(contract_version="broker_money_v1", base_request_id="base-money", **scope)
    return client, xml, intent, bond_id, saved


def _money_decide(session, intent, originals, bond_id, *, funding=True, operation="accept"):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.domain.historical_owner_flows import CLAIMS
    from hermes_finance.services.broker_money import preview_money

    inventory = preview_money(session, intent, originals)["inventory"]
    decisions = []
    for item in inventory:
        if item["occurrence"]["import_id"] != inventory[0]["occurrence"]["import_id"]:
            continue
        kind = item["candidate_kind"]
        if kind == "coupon_paid_candidate":
            decisions.append(
                {
                    "role": "coupon",
                    "operation": operation,
                    "seed": {k: item["occurrence"][k] for k in ("import_id", "section", "ordinal")},
                    "instrument_id": bond_id,
                }
            )
        if kind == "account_cash_in_candidate" and funding:
            decisions.append(
                {
                    "role": "account_funding",
                    "operation": operation,
                    "seed": {k: item["occurrence"][k] for k in ("import_id", "section", "ordinal")},
                }
            )
    intent = MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": decisions})
    plan = preview_money(session, intent, originals)
    for decision, proposed in zip(decisions, plan["decisions"], strict=True):
        if decision["role"] == "coupon":
            decision["coupon_claims"] = {
                "reference": "synthetic-row-review",
                "review_context_digest": proposed["review_context_digest"],
                "actual_coupon_payment": True,
                "exact_row_instrument_link": True,
                "complete_occurrence_set_is_one_event": True,
                "existing_target_is_same_payment": True,
            }
        elif proposed.get("h2_plan"):
            owner = proposed["owner_flow_intent"]
            owner["claims"] = {
                "provenance_kind": "owner_attested_source_row",
                "reference": "synthetic-account-boundary-review",
                "direction": "contribution",
                "source_set_fingerprint": proposed["h2_plan"]["source_set_fingerprint"],
                "review_context_digest": proposed["h2_plan"]["review_context_digest"],
                **dict.fromkeys(CLAIMS, True),
            }
            decision["owner_flow_intent"] = owner
    return MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": decisions})


def _money_apply(session, intent, originals, request_id="money-accepted"):
    from hermes_finance.services.broker_money import apply_money, preview_money

    plan = preview_money(session, intent, originals)
    assert plan["can_apply"], plan["blockers"]
    return apply_money(
        session,
        intent,
        originals,
        confirmation_digest=plan["confirmation_digest"],
        request_id=request_id,
    )


def test_money_batch_atomic_net_coupons_h2_get_ten_replays_no_extra_cash(database):
    from hermes_finance.persistence import (
        BrokerMoneyOccurrenceOwner,
        CashBalance,
        ExternalFlow,
        HistoricalOwnerFlow,
        InvestmentCashFlow,
        MyBrokerImport,
    )
    from hermes_finance.services.broker_money import apply_money, preview_money, read_money

    client, xml, intent, bond, base = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        source = session.get(MyBrokerImport, base["import_id"])
        before = source.normalized_json, source.mappings_json, source.confirmation_digest
        cash = session.scalar(select(CashBalance.amount_kopecks))
        intent = _money_decide(session, intent, originals, bond)
        plan = preview_money(session, intent, originals)
        assert plan["expected_effects"] == {
            "new_coupon_facts": 2,
            "new_account_flow_facts": 1,
            "new_external_flows": 0,
            "cash_increment_minor": "0",
            "selected_coupon_net_minor": "300000",
        }
        saved = apply_money(
            session,
            intent,
            originals,
            confirmation_digest=plan["confirmation_digest"],
            request_id="money-accepted",
        )
        for _ in range(10):
            assert apply_money(
                session,
                intent,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="money-accepted",
            )["duplicate"]
        readback = read_money(session, saved["request_id"])
        assert readback["targets"] == saved["targets"]
        payouts = list(session.scalars(select(InvestmentCashFlow)))
        assert len(payouts) == 2 and sum(p.net_amount_kopecks for p in payouts) == 300000
        assert all(
            p.gross_amount_kopecks is None
            and p.tax_amount_kopecks is None
            and p.commission_amount_kopecks is None
            for p in payouts
        )
        flows = list(session.scalars(select(HistoricalOwnerFlow)))
        assert len(flows) == 1 and flows[0].boundary_amount_kopecks == 5000000
        assert session.scalar(select(func.count()).select_from(ExternalFlow)) == 0
        assert session.scalar(select(CashBalance.amount_kopecks)) == cash
        assert session.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 3
        assert before == (source.normalized_json, source.mappings_json, source.confirmation_digest)
        funding = next(t for t in readback["targets"] if t["role"] == "account_funding")
        assert funding["h2"]["account_scope"]["status"] == "authoritative"
        assert funding["h2"]["portfolio_scope"]["status"] == "unknown"
        assert "money_semantics_unsupported" not in readback["exceptions"]
        assert readback["bookkeeping_ready"]
        # Fresh reviewed identical request adds a receipt, never an economic fact.
        fresh = _money_decide(
            session, intent.model_copy(update={"money_decisions": []}), originals, bond
        )
        _money_apply(session, fresh, originals, "fresh-money")
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 2
        assert session.scalar(select(func.count()).select_from(HistoricalOwnerFlow)) == 1
    http_read = client.get("/api/broker-months/money-accepted").json()
    assert [t["facts"] for t in http_read["targets"]] == [t["facts"] for t in saved["targets"]]
    assert all(t["effective"] for t in http_read["targets"])


@pytest.mark.parametrize("claims", [False, True])
def test_money_distinct_equal_coupon_cannot_absorb_prior_payment(database, claims):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import BrokerMoneyOccurrenceOwner, BrokerMonthApply
    from hermes_finance.services.broker_money import apply_money, preview_money, read_money

    _, xml, intent, bond, _ = _money_setup(
        database, money_batch_xml(coupons=("1000", "1000"), distinct=True)
    )
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        reviewed = _money_decide(session, intent, originals, bond)
        first = MoneyIntent.model_validate(
            {
                **reviewed.model_dump(),
                "money_decisions": [
                    d.model_dump() for d in reviewed.money_decisions if d.seed.ordinal != 2
                ],
            }
        )
        saved = _money_apply(session, first, originals, "first-distinct-payment")
        target = next(t["target_id"] for t in saved["targets"] if t["role"] == "coupon")
        assert not saved["bookkeeping_ready"]
        decision = next(d.model_dump() for d in reviewed.money_decisions if d.seed.ordinal == 2)
        decision["investment_cash_flow_id"] = target
        decision["coupon_claims"] = None
        wrong = MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": [decision]})
        plan = preview_money(session, wrong, originals)
        if claims:
            decision["coupon_claims"] = {
                **reviewed.money_decisions[0].coupon_claims.model_dump(),
                "review_context_digest": plan["decisions"][0]["review_context_digest"],
            }
            wrong = MoneyIntent.model_validate(
                {**intent.model_dump(), "money_decisions": [decision]}
            )
            plan = preview_money(session, wrong, originals)
        else:
            assert "coupon_claim_binding_required" in plan["blockers"]
        assert "existing_payout_occurrence_set_conflict" in plan["blockers"]
        before = [
            session.scalar(select(func.count()).select_from(m))
            for m in (InvestmentCashFlow, BrokerMoneyOccurrenceOwner, BrokerMonthApply)
        ]
        with pytest.raises(MyBrokerError, match="existing_payout_occurrence_set_conflict"):
            apply_money(
                session,
                wrong,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="wrong-second-payment",
            )
        assert before == [
            session.scalar(select(func.count()).select_from(m))
            for m in (InvestmentCashFlow, BrokerMoneyOccurrenceOwner, BrokerMonthApply)
        ]
        assert not read_money(session, "first-distinct-payment")["bookkeeping_ready"]


@pytest.mark.parametrize("existing_v1", [False, True])
def test_money_requires_h2_v2_and_reviewed_upgrade_preserves_legacy_receipt(database, existing_v1):
    from test_statement_import_historical_owner_flows import attest

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.persistence import (
        BrokerMoneyOccurrenceOwner,
        HistoricalOwnerFlow,
        HistoricalOwnerFlowRevision,
    )
    from hermes_finance.services.broker_money import apply_money, preview_money
    from hermes_finance.services.historical_owner_flows import (
        apply_historical_owner_flow,
        preview_historical_owner_flow,
    )

    _, xml, intent, bond, base = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        v1 = attest(
            session,
            OwnerFlowIntent(
                account_id=intent.account_id, seed={"import_id": base["import_id"], "ordinal": 3}
            ),
        )
        legacy = None
        if existing_v1:
            plan = preview_historical_owner_flow(session, v1)
            legacy = apply_historical_owner_flow(
                session, v1, confirmation_digest=plan["confirmation_digest"], request_id="legacy-v1"
            )["readback"]
            assert legacy["effective_state"] == "accepted"
        decision = {"role": "account_funding", "seed": v1.seed.model_dump()}
        if not existing_v1:
            decision["owner_flow_intent"] = v1.model_dump()
        wrong = MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": [decision]})
        plan = preview_money(session, wrong, originals)
        reason = (
            "reviewed_version_reaffirmation_required" if existing_v1 else "money_h2_v2_required"
        )
        assert reason in plan["blockers"]
        before = session.scalar(select(func.count()).select_from(HistoricalOwnerFlowRevision))
        with pytest.raises(MyBrokerError, match=reason):
            apply_money(
                session,
                wrong,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="unreviewed-v1",
            )
        assert session.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 0
        assert (
            session.scalar(select(func.count()).select_from(HistoricalOwnerFlowRevision)) == before
        )
        if existing_v1:
            reviewed = _money_decide(session, intent, originals, bond, operation="reaffirm")
            upgraded = MoneyIntent.model_validate(
                {
                    **intent.model_dump(),
                    "money_decisions": [
                        d.model_dump()
                        for d in reviewed.money_decisions
                        if d.role == "account_funding"
                    ],
                }
            )
            saved = _money_apply(session, upgraded, originals, "reviewed-v2-upgrade")
            target = saved["targets"][0]
            assert target["target_id"] == legacy["flow_id"]
            assert target["h2"]["evidence"]["contract_version"] == "h2-a1-owner-rub-v2"
            assert target["h2"]["revision"] == legacy["revision"] + 1
            old = session.get(HistoricalOwnerFlowRevision, legacy["revision_id"])
            assert json.loads(old.evidence_json) == legacy["evidence"]
            assert session.scalar(select(func.count()).select_from(HistoricalOwnerFlow)) == 1


@pytest.mark.parametrize("distinct", [False, True])
def test_money_equal_value_coupons_require_distinguishable_full_observations(database, distinct):
    from hermes_finance.persistence import InvestmentCashFlow
    from hermes_finance.services.broker_money import preview_money

    _, xml, intent, bond, _ = _money_setup(
        database, money_batch_xml(coupons=("1000", "1000"), distinct=distinct)
    )
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        intent = _money_decide(session, intent, originals, bond)
        plan = preview_money(session, intent, originals)
        if distinct:
            assert plan["can_apply"], plan["blockers"]
            _money_apply(session, intent, originals)
            assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 2
        else:
            assert "same_report_multiplicity" in plan["blockers"] and not plan["can_apply"]


@pytest.mark.parametrize("overlap_first", [False, True])
def test_money_complete_overlapping_source_union_counts_each_coupon_once(database, overlap_first):
    from hermes_finance.persistence import BrokerMoneyOccurrenceOwner, InvestmentCashFlow
    from hermes_finance.services.broker_money import preview_money

    xml = money_batch_xml()
    overlap = money_batch_xml(stamp="11")
    client, _, intent, bond, _ = _money_setup(database, overlap if overlap_first else xml)
    other = xml if overlap_first else overlap
    with database.session_factory() as session:
        apply(session, other, preview(session, other))
        originals = [(FILENAME, overlap if overlap_first else xml), (FILENAME, other)]
        assert (
            "overlapping_original_required"
            in preview_money(session, intent, originals[:1])["blockers"]
        )
        intent = _money_decide(session, intent, originals, bond)
        _money_apply(session, intent, originals)
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 2
        assert session.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 6
    assert len(client.get("/api/broker-months/money-accepted").json()["targets"]) == 3


@pytest.mark.parametrize("existing_h2", [False, True])
def test_money_h2_cross_writer_both_orders_preserve_one_owner(database, existing_h2):
    from test_statement_import_historical_owner_flows import attest

    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.persistence import HistoricalOwnerFlow
    from hermes_finance.services.historical_owner_flows import (
        apply_historical_owner_flow,
        preview_historical_owner_flow,
    )

    _, xml, intent, bond, base = _money_setup(database)
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        owner = OwnerFlowIntent(
            evidence_version="h2-a1-owner-rub-v2",
            account_id=intent.account_id,
            seed={"import_id": base["import_id"], "ordinal": 3},
        )
        owner = attest(session, owner)
        if existing_h2:
            hplan = preview_historical_owner_flow(session, owner)
            assert hplan["can_apply"], hplan["blockers"]
            apply_historical_owner_flow(
                session,
                owner,
                confirmation_digest=hplan["confirmation_digest"],
                request_id="old-h2",
            )
        intent = _money_decide(session, intent, originals, bond)
        saved = _money_apply(session, intent, originals)
        assert session.scalar(select(func.count()).select_from(HistoricalOwnerFlow)) == 1
        if not existing_h2:
            plan = preview_historical_owner_flow(session, owner)
            assert "occurrence_already_owned" in plan["blockers"]
        # A coupon occurrence can never also become old/public H2.
        wrong = attest(
            session,
            OwnerFlowIntent(
                evidence_version="h2-a1-owner-rub-v2",
                account_id=intent.account_id,
                seed={"import_id": base["import_id"], "ordinal": 1},
            ),
        )
        assert (
            "occurrence_already_owned" in preview_historical_owner_flow(session, wrong)["blockers"]
        )
        assert len(saved["targets"]) == 3


@pytest.mark.parametrize("failure", ["stale", "rollback", "late_rollback", "closed"])
def test_money_stale_closed_and_partial_stage_failure_leave_existing_draft_unchanged(
    database, monkeypatch, failure
):
    from hermes_finance.persistence import (
        BrokerMoneyOccurrenceOwner,
        HistoricalOwnerFlow,
        HistoricalOwnerFlowApply,
        HistoricalOwnerFlowOccurrence,
        HistoricalOwnerFlowRevision,
        InvestmentCashFlow,
        ReportingMonth,
    )
    from hermes_finance.services import broker_money
    from hermes_finance.statement_import.mybroker import MyBrokerError

    _, xml, intent, bond, _ = _money_setup(database)
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        intent = _money_decide(session, intent, originals, bond)
        plan = broker_money.preview_money(session, intent, originals)
        if failure in {"rollback", "late_rollback"}:
            stage = broker_money.h2.stage_historical_owner_flow

            def fail(*args, **kwargs):
                if failure == "late_rollback":
                    stage(*args, **kwargs)
                raise RuntimeError("synthetic-stage-failure")

            monkeypatch.setattr(
                broker_money.h2,
                "stage_historical_owner_flow",
                fail,
            )
        else:
            month = session.get(ReportingMonth, intent.reporting_month_id)
            month.status = "closed" if failure == "closed" else "draft"
            month.source = "excel_migration"
            session.commit()
        with pytest.raises((RuntimeError, MyBrokerError)):
            broker_money.apply_money(
                session,
                intent,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="failed-money",
            )
        for model in (
            InvestmentCashFlow,
            HistoricalOwnerFlow,
            BrokerMoneyOccurrenceOwner,
            HistoricalOwnerFlowOccurrence,
            HistoricalOwnerFlowRevision,
            HistoricalOwnerFlowApply,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.get(BrokerMonthApply, "base-money") is not None
        assert session.get(BrokerMonthApply, "failed-money") is None


def test_money_nkd_remains_scoped_close_blocker_after_coupon_and_h2_acceptance(database):
    _, xml, intent, bond, _ = _money_setup(database, money_batch_xml(nkd=True))
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        intent = _money_decide(session, intent, originals, bond)
        saved = _money_apply(session, intent, originals)
        assert not saved["bookkeeping_ready"]
        assert "money_semantics_unsupported" in saved["exceptions"]
        from hermes_finance.services.broker_months import broker_month_close_blockers

        assert any(
            code == "money_semantics_unsupported"
            for code, _ in broker_month_close_blockers(session, intent.reporting_month_id)
        )


@pytest.mark.parametrize("name", ["coupon", "h2", "bond", "zero_fee"])
def test_money_literal_pre_stock_json_and_fingerprint(name):
    from pathlib import Path

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.statement_import.mybroker import digest

    # Captured with the actual domain at main@5e02e838, before stock changes.
    # Expected JSON/hash are literals, never generated by the new serializer.
    frozen = json.loads(
        (Path(__file__).parent / "fixtures/broker_money_pre_stock.json").read_text()
    )
    case = next(c for c in frozen["cases"] if c["name"] == name)
    requested = MoneyIntent.model_validate(case["intent"])
    assert requested.model_dump(mode="json") == case["intent"]
    assert digest(requested.model_dump(mode="json")) == case["intent_digest"]
    assert (
        digest(
            [
                requested.model_dump(mode="json"),
                case["confirmation_digest"],
                case["original_hashes"],
            ]
        )
        == case["request_fingerprint"]
    )


@pytest.mark.parametrize("name", ["coupon", "h2", "bond", "zero_fee"])
def test_money_actual_pre_change_receipt_http_replay_is_immutable(database, name):
    from datetime import datetime
    from pathlib import Path

    path = Path(__file__).parent / "fixtures/broker_money_legacy_receipts.json"
    frozen = json.loads(path.read_text(encoding="utf-8"))
    case = next(c for c in frozen["cases"] if c["name"] == name)
    if name != "zero_fee":
        from hermes_finance.domain.broker_money import MoneyIntent

        assert MoneyIntent.model_validate(case["intent"]).model_dump(mode="json") == case["intent"]
    client, _, _, _ = _stock_setup(database)
    receipt = case["receipt"].copy()
    for field in ("reporting_month_id", "account_id", "import_id"):
        receipt[field] = int(receipt[field])
    receipt["accepted_at"] = datetime.fromisoformat(receipt["accepted_at"])
    with database.session_factory() as session:
        session.info["broker_money_stage"] = True
        session.add(BrokerMonthApply(**receipt))
        session.commit()
    before = _all_month_tables(database)
    for _ in range(10):
        response = client.post(
            "/api/broker-months/apply",
            files={
                "file": (
                    case["original_filename"],
                    case["original_xml"].encode(),
                    "application/xml",
                )
            },
            data={"confirmation": json.dumps(case["confirmation"])},
        )
        assert response.status_code == 200, response.text
        assert response.json()["duplicate"]
    # Replay does not plan or reaffirm old authority against changed source.
    assert not response.json()["bookkeeping_ready"]
    assert before == _all_month_tables(database)


def test_stock_fee_fractional_kopeck_rejected_before_draft(database):
    scope = _broker_month_setup(database)
    client = TestClient(create_app(database))
    before = _all_month_tables(database)
    response = client.post(
        "/api/broker-months/preview",
        files={"file": (FILENAME, stock_fee_xml(fee="-1.251"), "application/xml")},
        data={"intent": json.dumps(scope)},
    )
    assert response.status_code == 422
    assert "fractional_kopeck" in response.text
    assert before == _all_month_tables(database)


def stock_fee_xml(
    *,
    stamp="10",
    accrued=None,
    fee="-1.25",
    bank_fee="1.25",
    total="100.00",
    duplicate=False,
    second=False,
    prior_month_buy=False,
    missing_fee=False,
    missing_custody=False,
    nkd=False,
    nkd_amount="-0.01",
    opaque=False,
):
    """Exact native two-leg fabricated stock purchase; no real-source authority."""
    from copy import deepcopy

    root = ET.fromstring(broker_month_xml())
    stock = root.find(f".//{{MyBroker}}Details[@ISIN1='{ISIN}']")
    stock.set("income_rest", "0")
    stock.set("real_rest", "2" if second else "1")
    stock.set("forward_rest", "2" if second else "1")
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    trade.set("qty", "1")
    trade.set("summ_trade", total)
    trade.set("bank_tax", bank_fee)
    if accrued is None:
        trade.attrib.pop("summ_nkd", None)
    else:
        trade.set("summ_nkd", accrued)
    if prior_month_buy:
        trade.set("db_time", "31.12.2029 9:00:00\r\n31.12.2029 9:00:00")
    if missing_custody:
        trade.attrib.pop("save_depo_settlement_date", None)
    collection = root.find(".//{MyBroker}rn_Collection")
    settlement = collection.find("{MyBroker}rn")
    settlement.find(".//{MyBroker}oper_type").set("oper_type", "Расчеты по сделке 10000000001")
    settlement.find(".//{MyBroker}comment").attrib.pop("comment", None)
    settlement.find(".//{MyBroker}p_code[@volume]").set("volume", "-100.00")
    commission = deepcopy(settlement)
    commission.find(".//{MyBroker}oper_type").set("oper_type", "Комиссия по сделке 10000000001")
    commission.find(".//{MyBroker}p_code[@volume]").set("volume", fee)
    if not missing_fee:
        collection.append(commission)
    if duplicate:
        collection.append(deepcopy(commission))
    if second:
        other = deepcopy(trade)
        other.set("trade_no", "10000000002\r\n2000000002")
        next(parent for parent in root.iter() if trade in list(parent)).append(other)
        for row in (settlement, commission):
            other_row = deepcopy(row)
            op = other_row.find(".//{MyBroker}oper_type")
            op.set("oper_type", op.get("oper_type").replace("10000000001", "10000000002"))
            collection.append(other_row)
    if nkd or opaque:
        other = deepcopy(settlement)
        op = other.find(".//{MyBroker}oper_type")
        op.set("oper_type", "НКД по сделке" if nkd else "Synthetic opaque")
        other.find(".//{MyBroker}comment").set(
            "comment", "НКД по сделке 10000000001" if nkd else "opaque"
        )
        other.find(".//{MyBroker}p_code[@volume]").set("volume", nkd_amount if nkd else "1")
        collection.append(other)
        if opaque:
            opposite = deepcopy(other)
            opposite.find(".//{MyBroker}p_code[@volume]").set("volume", "-1")
            collection.append(opposite)
    for row in collection:
        row.set("last_update", f"2030-01-17T10:00:{stamp}")
    posted = sum(Decimal(r.find(".//{MyBroker}p_code[@volume]").get("volume")) for r in collection)
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("income_rest", "1000.00")
    cash.set("real_rest", str(Decimal("1000") + posted))
    return ET.tostring(root, encoding="utf-8")


def _stock_setup(database, xml=None):
    from hermes_finance.domain.broker_money import MoneyIntent

    scope = _broker_month_setup(database)
    client = TestClient(create_app(database))
    xml = xml or stock_fee_xml()
    plan = _broker_month_preview(client, scope, xml)
    response = _broker_month_apply(client, scope, plan, xml, request_id="base-stock")
    assert response.status_code == 200, response.text
    intent = MoneyIntent(contract_version="broker_money_v1", base_request_id="base-stock", **scope)
    return client, xml, intent, response.json()


def _stock_decide(session, intent, originals, *, claims=True, operation="accept"):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.broker_money import preview_money

    initial = preview_money(session, intent.model_copy(update={"money_decisions": []}), originals)
    decisions = []
    for trade in initial["trade_choices"]:
        item = next(
            o
            for o in initial["inventory"]
            if o["s1_kind"] == "commission" and o["trade_identity"] == trade["source_identity"]
        )
        decisions.append(
            {
                "role": "trade",
                "trade_id": trade["trade_id"],
                "expected_trade_revision": int(trade["revision"]["revision"]),
                "operation": operation,
                "seed": {k: item["occurrence"][k] for k in ("import_id", "section", "ordinal")},
            }
        )
    requested = MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": decisions})
    plan = preview_money(session, requested, originals)
    if claims:
        for decision, proposed in zip(decisions, plan["decisions"], strict=True):
            if proposed["action"] == "reuse":
                continue
            decision["trade_claims"] = {
                "proof_variant": "stock_buy_separate_fee_v1",
                "reference": "synthetic-stock-fee-review",
                "basis_reference": "synthetic-independent-source-convention-v1",
                "review_context_digest": proposed["review_context_digest"],
                "exact_row_settled_buy_link": True,
                "complete_occurrence_set_is_one_event": True,
                "fee_separately_charged": True,
                "native_total_basis_independently_proved": True,
                "native_total_basis": "excludes_separate_fee",
            }
    return MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": decisions})


@pytest.mark.parametrize("accrued", [None, "0"])
@pytest.mark.parametrize("prior_month_buy", [False, True])
def test_stock_fee_preview_apply_get_reload_close_exact_cash(database, accrued, prior_month_buy):
    from hermes_finance.persistence import ExecutedTradeOccurrence, ExecutedTradeRevision
    from hermes_finance.services.broker_money import apply_money, preview_money, read_money
    from hermes_finance.services.executed_trades import read_executed_trades

    client, xml, intent, _ = _stock_setup(
        database, stock_fee_xml(accrued=accrued, prior_month_buy=prior_month_buy)
    )
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        bare = _stock_decide(session, intent, originals, claims=False)
        before = _all_month_tables(database)
        assert not preview_money(session, bare, originals)["can_apply"]
        assert before == _all_month_tables(database)
        requested = _stock_decide(session, intent, originals)
        plan = preview_money(session, requested, originals)
        saved = _money_apply(session, requested, originals, "stock-fee")
        assert saved["bookkeeping_ready"], saved["exceptions"]
        assert read_money(session, "stock-fee")["accepted"] == saved["accepted"]
        execution = read_executed_trades(session)["trades"][0]
        evidence = execution["evidence"]
        assert execution["revision"] == 2
        assert evidence["accrued_interest"] == accrued
        assert evidence["fee_basis"] == "separate"
        assert {leg["role"] for leg in evidence["cash_legs"]} == {"settlement", "commission"}
        assert sum(leg["amount_minor"] for leg in evidence["cash_legs"]) == 10125
        proof = evidence["cash_reconciliation"]
        assert "nkd_leg" not in proof
        assert proof["signed_minor"] == {
            "settlement": "-10000",
            "commission": "-125",
            "native_total": "10000",
            "native_fee": "125",
        }
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutedTradeOccurrence)
                .where(ExecutedTradeOccurrence.section == "money")
            )
            == 2
        )
        assert session.scalar(select(CashBalance.amount_kopecks)) == 89875
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0
        for _ in range(10):
            assert apply_money(
                session,
                requested,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="stock-fee",
            )["duplicate"]
        for index in range(10):
            fresh = _stock_decide(session, intent, originals)
            _money_apply(session, fresh, originals, f"stock-reuse-{index}")
        assert session.scalar(select(func.count()).select_from(ExecutedTradeRevision)) == 2
        assert session.scalar(select(CashBalance.amount_kopecks)) == 89875
    reload = client.get("/api/broker-months/base-stock").json()
    assert reload["bookkeeping_ready"], reload["exceptions"]
    assert client.get(f"/api/months/{intent.reporting_month_id}/close-readiness").json()[
        "can_close"
    ]
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 200


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("second", [False, True])
def test_stock_fee_native_overlap_and_equal_amount_distinct_ids(database, reverse, second):
    from hermes_finance.persistence import ExecutedTradeOccurrence
    from hermes_finance.services.executed_trades import read_executed_trades

    docs = [stock_fee_xml(stamp="10", second=second), stock_fee_xml(stamp="11", second=second)]
    if reverse:
        docs.reverse()
    _, _, intent, _ = _stock_setup(database, docs[0])
    with database.session_factory() as session:
        apply(session, docs[1], preview(session, docs[1]))
        originals = [(FILENAME, doc) for doc in docs]
        requested = _stock_decide(session, intent, originals)
        saved = _money_apply(session, requested, originals)
        assert saved["bookkeeping_ready"], saved["exceptions"]
        executions = read_executed_trades(session)["trades"]
        assert len(executions) == (2 if second else 1)
        assert all(len(t["evidence"]["cash_legs"]) == 2 for t in executions)
        assert sum(
            leg["amount_minor"] for t in executions for leg in t["evidence"]["cash_legs"]
        ) == (20250 if second else 10125)
        assert session.scalar(
            select(func.count())
            .select_from(ExecutedTradeOccurrence)
            .where(ExecutedTradeOccurrence.section == "money")
        ) == (8 if second else 4)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"accrued": "0.01"}, "stock_accrued_interest_unsupported"),
        ({"bank_fee": "1.24"}, "stock_native_total_fee_control_mismatch"),
        ({"total": "101.25"}, "stock_native_total_fee_control_mismatch"),
        ({"fee": "1.25"}, "negative_posted_cash_nonzero_native_required"),
        ({"duplicate": True}, "same_report_multiplicity"),
        ({"nkd": True}, "stock_unexpected_linked_money"),
        ({"nkd": True, "nkd_amount": "0.01"}, "stock_unexpected_linked_money"),
        ({"missing_custody": True}, "settled_rub_cash_required"),
    ],
)
def test_stock_fee_invalid_native_material_blocks_without_writes(database, kwargs, code):
    from hermes_finance.services.broker_money import apply_money, preview_money

    client, xml, intent, _ = _stock_setup(database, stock_fee_xml(**kwargs))
    with database.session_factory() as session:
        requested = _stock_decide(session, intent, [(FILENAME, xml)])
        before = _all_month_tables(database)
        plan = preview_money(session, requested, [(FILENAME, xml)])
        assert code in plan["blockers"]
        assert not plan["can_apply"]
        with pytest.raises(MyBrokerError):
            apply_money(
                session,
                requested,
                [(FILENAME, xml)],
                confirmation_digest=plan["confirmation_digest"],
                request_id="stock-invalid-material",
            )
        assert before == _all_month_tables(database)
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 422


@pytest.mark.parametrize("failure", ["stale", "rollback", "unproved", "bond_claims", "opaque"])
def test_stock_fee_unknown_basis_stale_and_rollback(database, monkeypatch, failure):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import Instrument
    from hermes_finance.services import executed_trades
    from hermes_finance.services.broker_money import apply_money, preview_money

    client, xml, intent, _ = _stock_setup(database, stock_fee_xml(opaque=failure == "opaque"))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _stock_decide(session, intent, originals)
        value = requested.model_dump()
        claims = value["money_decisions"][0]["trade_claims"]
        if failure == "unproved":
            claims["native_total_basis_independently_proved"] = False
        if failure == "bond_claims":
            claims.pop("proof_variant")
            claims.pop("basis_reference")
            claims["nkd_separately_posted"] = True
            claims["native_total_basis"] = "excludes_paid_nkd"
        requested = MoneyIntent.model_validate(value)
        plan = preview_money(session, requested, originals)
        if failure == "opaque":
            assert plan["can_apply"]
            saved = _money_apply(session, requested, originals)
            assert not saved["bookkeeping_ready"]
            assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 422
            return
        if failure == "stale":
            instrument = session.get(Instrument, 1)
            instrument.name = "Synthetic changed"
            session.commit()
        elif failure == "rollback":
            stage = executed_trades.stage_executed_trades

            def interrupted(*args, **kwargs):
                stage(*args, **kwargs)
                raise RuntimeError("synthetic after stock revision stage")

            monkeypatch.setattr(executed_trades, "stage_executed_trades", interrupted)
        before = _all_month_tables(database)
        with pytest.raises((MyBrokerError, RuntimeError)):
            apply_money(
                session,
                requested,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="stock-failed",
            )
        assert before == _all_month_tables(database)


def test_stock_fee_late_overlap_retires_old_authority_then_corroborates_once(database):
    from hermes_finance.persistence import ExecutedTradeOccurrence
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.executed_trades import read_executed_trades

    _, xml, intent, _ = _stock_setup(database)
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        requested = _stock_decide(session, intent, originals)
        first = _money_apply(session, requested, originals, "stock-original")
        second = stock_fee_xml(stamp="11")
        apply(session, second, preview(session, second))
        reread = read_money(session, "stock-original")
        assert reread["accepted"] == first["accepted"]
        assert not reread["bookkeeping_ready"]
        originals.append((FILENAME, second))
        # A source-union retirement needs specific reviewed reaffirmation.
        requested = _stock_decide(session, intent, originals, operation="reaffirm")
        saved = _money_apply(session, requested, originals, "stock-overlap-reviewed")
        assert saved["bookkeeping_ready"], saved["exceptions"]
        trade = read_executed_trades(session)["trades"][0]
        assert len(trade["evidence"]["cash_legs"]) == 2
        assert sum(leg["amount_minor"] for leg in trade["evidence"]["cash_legs"]) == 10125
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutedTradeOccurrence)
                .where(ExecutedTradeOccurrence.section == "money")
            )
            == 4
        )
        assert session.scalar(select(CashBalance.amount_kopecks)) == 89875
        assert read_money(session, "stock-original")["accepted"] == first["accepted"]


@pytest.mark.parametrize(
    "change,code",
    [
        ("pending", "settled_stock_buy_required"),
        ("sell", "settled_stock_buy_required"),
        ("fx", "settled_rub_cash_required"),
        ("date", "trade_cash_date_currency_conflict"),
        ("fraction", "trade_cash_exact_kopecks_required"),
        ("overflow", "trade_cash_amount_overflow"),
        ("repo", "repo_semantics_unsupported"),
        ("nkd", "stock_paid_nkd_unsupported"),
        ("identity", "stock_fee_native_identity_conflict"),
        ("unknown", "trade_cash_proof_variant_unsupported"),
    ],
)
def test_stock_fee_shared_typed_validation_rejects_unsupported_forms(change, code):
    from hermes_finance.services.broker_trade_money import cash_reasons

    source = {
        "state": "settled",
        "ids": ["1", "2"],
        "identity": "synthetic-native",
        "core": {"quantity": "1", "trade_amount": "100", "currency": "RUB"},
        "accrued_interest": None,
        "bank_commission": "1.25",
        "settlement_date": "2030-01-17",
        "depo_settlement_date": "2030-01-17",
        "repo_observed": False,
        "blockers": [],
    }
    groups = {
        "settlement": [{"amount": "-100", "date": "2030-01-17", "currency": "RUB"}],
        "commission": [{"amount": "-1.25", "date": "2030-01-17", "currency": "RUB"}],
    }
    proof = {
        "proof_variant": "stock_buy_separate_fee_v1",
        "native_ids": ["1", "2"],
        "source_identity": "synthetic-native",
        "claims": {
            "proof_variant": "stock_buy_separate_fee_v1",
            "reference": "synthetic-review",
            "basis_reference": "synthetic-independent-rule",
            "review_context_digest": "a" * 64,
            "exact_row_settled_buy_link": True,
            "complete_occurrence_set_is_one_event": True,
            "fee_separately_charged": True,
            "native_total_basis_independently_proved": True,
            "native_total_basis": "excludes_separate_fee",
        },
        "signed_minor": {
            "settlement": "-10000",
            "commission": "-125",
            "native_total": "10000",
            "native_fee": "125",
        },
    }
    assert cash_reasons(source, groups, proof) == []
    if change == "pending":
        source["state"] = "pending"
    elif change == "sell":
        source["core"]["quantity"] = "-1"
    elif change == "fx":
        source["core"]["currency"] = "USD"
    elif change == "date":
        groups["commission"][0]["date"] = "2030-01-18"
    elif change == "fraction":
        source["bank_commission"] = "1.251"
    elif change == "overflow":
        source["bank_commission"] = "92233720368547758.07"
        groups["commission"][0]["amount"] = "-92233720368547758.07"
    elif change == "repo":
        source["repo_observed"] = True
    elif change == "nkd":
        proof["nkd_leg"] = {}
    elif change == "identity":
        proof["native_ids"] = ["2", "1"]
    elif change == "unknown":
        proof["proof_variant"] = "future"
    assert code in cash_reasons(source, groups, proof)


@pytest.mark.parametrize(
    "shape", ["missing_fee", "ambiguous_primary", "wrong_owner", "different_date"]
)
def test_stock_fee_native_ownership_boundaries_block_apply_and_close(database, shape):
    from copy import deepcopy

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import ExecutedTrade, ExecutedTradeOccurrence
    from hermes_finance.services.broker_money import apply_money, preview_money

    xml = stock_fee_xml(missing_fee=shape == "missing_fee", second=shape == "wrong_owner")
    if shape in ("ambiguous_primary", "different_date"):
        root = ET.fromstring(xml)
        if shape == "ambiguous_primary":
            trade = root.find(".//{MyBroker}Details[@trade_no]")
            other = deepcopy(trade)
            other.set("trade_no", "10000000001\r\n2000000009")
            next(parent for parent in root.iter() if trade in list(parent)).append(other)
        else:
            fee = root.find(".//{MyBroker}rn_Collection")[1]
            other_date = deepcopy(root.find(".//{MyBroker}settlement_date"))
            other_date.set("settlement_date", "2030-01-18T00:00:00")
            collection = other_date.find("{MyBroker}rn_Collection")
            collection.clear()
            collection.append(deepcopy(fee))
            root.find(".//{MyBroker}rn_Collection").remove(fee)
            root.find(".//{MyBroker}settlement_date_Collection").append(other_date)
        xml = ET.tostring(root, encoding="utf-8")
    if shape == "ambiguous_primary":
        scope = _broker_month_setup(database)
        client = TestClient(create_app(database))
        before = _all_month_tables(database)
        plan = _broker_month_preview(client, scope, xml)
        response = _broker_month_apply(client, scope, plan, xml)
        assert response.status_code == 409
        assert before == _all_month_tables(database)
        return
    client, xml, intent, _ = _stock_setup(database, xml)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        if shape == "missing_fee":
            initial = preview_money(session, intent, originals)
            trade = session.scalar(select(ExecutedTrade))
            decision = {
                "role": "trade",
                "seed": {
                    k: initial["inventory"][0]["occurrence"][k]
                    for k in ("import_id", "section", "ordinal")
                },
                "trade_id": trade.id,
                "expected_trade_revision": 1,
            }
            requested = MoneyIntent.model_validate(
                {**intent.model_dump(), "money_decisions": [decision]}
            )
        elif shape == "ambiguous_primary":
            # S1 correctly leaves commission identity unavailable; manual trade selection cannot fix it.
            initial = preview_money(session, intent, originals)
            trade = session.scalar(select(ExecutedTrade))
            fee = next(o for o in initial["inventory"] if o["s1_kind"] == "commission")
            decision = {
                "role": "trade",
                "seed": {k: fee["occurrence"][k] for k in ("import_id", "section", "ordinal")},
                "trade_id": trade.id,
                "expected_trade_revision": 1,
            }
            requested = MoneyIntent.model_validate(
                {**intent.model_dump(), "money_decisions": [decision]}
            )
        else:
            requested = _stock_decide(session, intent, originals)
        if shape == "wrong_owner":
            # A second canonical execution cannot own the first one's fee leaf.
            item = preview_money(session, intent, originals)["inventory"][1]["occurrence"]
            wrong_trade = session.scalar(select(ExecutedTrade).order_by(ExecutedTrade.id.desc()))
            session.add(
                ExecutedTradeOccurrence(
                    trade_id=wrong_trade.id,
                    import_id=item["import_id"],
                    section="money",
                    ordinal=item["ordinal"],
                    source_fingerprint=item["row_fingerprint"],
                )
            )
            session.commit()
        plan = preview_money(session, requested, originals)
        assert not plan["can_apply"], plan
        before = _all_month_tables(database)
        with pytest.raises(MyBrokerError):
            apply_money(
                session,
                requested,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="stock-native-refused",
            )
        assert before == _all_month_tables(database)
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 422


def trade_money_xml(
    *,
    inclusive=True,
    duplicate_nkd=False,
    stamp="10",
    extra=False,
    prior_month_buy=False,
    native_linkage=False,
):
    from copy import deepcopy

    root = ET.fromstring(money_batch_xml(nkd=True, stamp=stamp))
    stock = root.find(f".//{{MyBroker}}Details[@ISIN1='{ISIN}']")
    stock.set("income_rest", "10")
    bond = root.find(".//{MyBroker}Details[@ISIN1='RU000A000001']")
    bond.set("real_rest", "11")
    bond.set("forward_rest", "11")
    trade = root.find(".//{MyBroker}Details[@trade_no]")
    if prior_month_buy:
        trade.set("db_time", "31.12.2029 9:00:00\r\n31.12.2029 9:00:00")
    trade.set("isin_reg", "RU000A000001")
    trade.set("qty", "1")
    trade.set("summ_trade", "10125.50" if inclusive else "10000.00")
    trade.set("summ_nkd", "125.50")
    trade.set("bank_tax", "10.00")
    collection = root.find(".//{MyBroker}rn_Collection")
    settlement = collection.find("{MyBroker}rn")
    settlement.find(".//{MyBroker}p_code[@volume]").set("volume", "-10000.00")
    fee = deepcopy(settlement)
    fee.find(".//{MyBroker}comment").set("comment", "Комиссия по сделке 10000000001")
    fee.find(".//{MyBroker}p_code[@volume]").set("volume", "-10.00")
    collection.append(fee)
    if duplicate_nkd:
        collection.append(
            deepcopy(
                next(
                    r
                    for r in collection
                    if r.find("{MyBroker}oper_type").get("oper_type") == "НКД по сделке"
                )
            )
        )
    if extra:
        other = deepcopy(fee)
        other.find(".//{MyBroker}comment").set("comment", "Synthetic unsupported REPO UFSR")
        other.find(".//{MyBroker}p_code[@volume]").set("volume", "-1.00")
        collection.append(other)
        node(root.find("{MyBroker}Trades3/{MyBroker}Report"), "Tablix1")
        node(root.find("{MyBroker}Trades4/{MyBroker}Report"), "Tablix1")
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("income_rest", "10000.00")
    cash.set(
        "real_rest",
        str(
            Decimal("52864.50") - (Decimal("125.50") if duplicate_nkd else 0) - (1 if extra else 0)
        ),
    )
    if native_linkage:
        for op in root.findall(".//{MyBroker}oper_type"):
            comment = op.find("{MyBroker}comment")
            if comment.get("comment", "").startswith(("Расчеты по сделке ", "Комиссия по сделке ")):
                op.set("oper_type", comment.attrib.pop("comment"))
    return ET.tostring(root, encoding="utf-8")


def _trade_decide(session, intent, originals, *, inclusive=True, claims=True, operation="accept"):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import ExecutedTrade, ExecutedTradeRevision
    from hermes_finance.services.broker_money import preview_money

    trade = session.scalar(select(ExecutedTrade))
    revision = session.scalar(
        select(ExecutedTradeRevision).order_by(ExecutedTradeRevision.revision.desc())
    )
    inventory = preview_money(
        session, intent.model_copy(update={"money_decisions": []}), originals
    )["inventory"]
    item = next(o for o in inventory if o["candidate_kind"] == "trade_paid_nkd_candidate")
    decision = {
        "role": "trade",
        "trade_id": trade.id,
        "expected_trade_revision": revision.revision,
        "operation": operation,
        "seed": {k: item["occurrence"][k] for k in ("import_id", "section", "ordinal")},
    }
    requested = MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": [decision]})
    plan = preview_money(session, requested, originals)
    if claims:
        decision["trade_claims"] = {
            "reference": "synthetic-independent-native-basis-review",
            "review_context_digest": plan["decisions"][0]["review_context_digest"],
            "exact_row_settled_buy_link": True,
            "complete_occurrence_set_is_one_event": True,
            "nkd_separately_posted": True,
            "fee_separately_charged": True,
            "native_total_basis_independently_proved": True,
            "native_total_basis": "includes_paid_nkd" if inclusive else "excludes_paid_nkd",
        }
    return MoneyIntent.model_validate({**requested.model_dump(), "money_decisions": [decision]})


@pytest.mark.parametrize("inclusive", [True, False])
@pytest.mark.parametrize("prior_month_buy", [False, True])
@pytest.mark.parametrize("native_linkage", [False, True])
def test_trade_money_reviewed_basis_revision_get_scoped_close_no_double_cash(
    database, inclusive, prior_month_buy, native_linkage
):
    from hermes_finance.persistence import (
        ExecutedTrade,
        ExecutedTradeOccurrence,
        ExecutedTradeRevision,
        ExternalFlow,
        HistoricalOwnerFlow,
    )
    from hermes_finance.services.broker_money import apply_money, preview_money, read_money
    from hermes_finance.services.executed_trades import read_executed_trades

    client, xml, intent, bond, _ = _money_setup(
        database,
        trade_money_xml(
            inclusive=inclusive, prior_month_buy=prior_month_buy, native_linkage=native_linkage
        ),
    )
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        coupon_intent = _money_decide(session, intent, originals, bond)
        _money_apply(session, coupon_intent, originals)
        bare = _trade_decide(session, intent, originals, inclusive=inclusive, claims=False)
        initial = preview_money(session, bare, originals)
        assert "paid_nkd_basis_unresolved" in initial["blockers"]
        assert [t["trade_id"] for t in initial["trade_choices"]] == [
            bare.money_decisions[0].trade_id
        ]
        if prior_month_buy:
            assert initial["trade_choices"][0]["core"]["trade_time"][:10] == "2029-12-31"
        assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 422
        requested = _trade_decide(session, intent, originals, inclusive=inclusive)
        plan = preview_money(session, requested, originals)
        assert plan["can_apply"], plan["blockers"]
        saved = apply_money(
            session,
            requested,
            originals,
            confirmation_digest=plan["confirmation_digest"],
            request_id="trade-cash",
        )
        reread = read_money(session, "trade-cash")
        assert saved["accepted"] == reread["accepted"]
        assert reread["bookkeeping_ready"], reread["exceptions"]
        execution = read_executed_trades(session)["trades"][0]
        assert execution["conflicts"] == []
        assert execution["revision"] == 2
        evidence = execution["evidence"]
        assert evidence["fee_basis"] == "separate"
        assert {leg["role"] for leg in evidence["cash_legs"]} == {
            "settlement",
            "commission",
            "paid_nkd",
        }
        assert sum(leg["amount_minor"] for leg in evidence["cash_legs"]) == 1013550
        assert all(
            not evidence["readiness"][kind]
            for kind in ("settlement", "commission", "cash_ownership", "unsupported")
        )
        assert session.scalar(select(CashBalance.amount_kopecks)) == 5286450
        assert session.scalar(select(func.count()).select_from(CashBalance)) == 1
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 2
        assert session.scalar(select(func.sum(InvestmentCashFlow.net_amount_kopecks))) == 300000
        assert session.scalar(select(func.count()).select_from(HistoricalOwnerFlow)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalFlow)) == 0
        assert session.scalar(select(func.count()).select_from(ExecutedTrade)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutedTradeOccurrence)
                .where(ExecutedTradeOccurrence.section == "money")
            )
            == 3
        )
        for _ in range(10):
            assert apply_money(
                session,
                requested,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="trade-cash",
            )["duplicate"]
        assert session.scalar(select(func.count()).select_from(ExecutedTradeRevision)) == 2
    readiness = client.get(f"/api/months/{intent.reporting_month_id}/close-readiness").json()
    assert readiness["can_close"], readiness
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 200
    with database.session_factory() as session:
        blocked = preview_money(session, requested, originals)
        assert "reporting_month_closed" in blocked["blockers"]


@pytest.mark.parametrize(
    "change,code",
    [
        ("unproved", "trade_cash_specific_proof_required"),
        ("fee_embedded", "trade_cash_specific_proof_required"),
        ("nkd_embedded", "trade_cash_specific_proof_required"),
        ("wrong_basis", "native_total_basis_control_mismatch"),
        ("stale_revision", "trade_revision_stale"),
    ],
)
def test_trade_money_equations_cannot_supply_independent_basis(database, change, code):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.broker_money import apply_money, preview_money

    _, xml, intent, _, _ = _money_setup(database, trade_money_xml())
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _trade_decide(session, intent, originals)
        value = requested.model_dump()
        decision = value["money_decisions"][0]
        if change == "wrong_basis":
            decision["trade_claims"]["native_total_basis"] = "excludes_paid_nkd"
        elif change == "stale_revision":
            decision["expected_trade_revision"] += 1
        else:
            field = {
                "unproved": "native_total_basis_independently_proved",
                "fee_embedded": "fee_separately_charged",
                "nkd_embedded": "nkd_separately_posted",
            }[change]
            decision["trade_claims"][field] = False
        requested = MoneyIntent.model_validate(value)
        plan = preview_money(session, requested, originals)
        assert code in plan["blockers"]
        assert not plan["can_apply"]
        before = _all_month_tables(database)
        with pytest.raises(MyBrokerError):
            apply_money(
                session,
                requested,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="refused",
            )
        assert before == _all_month_tables(database)


@pytest.mark.parametrize("reverse", [False, True])
def test_trade_money_overlap_both_orders_same_execution_three_cash_legs(database, reverse):
    from hermes_finance.persistence import ExecutedTrade, ExecutedTradeOccurrence
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.executed_trades import read_executed_trades

    docs = [trade_money_xml(stamp="10"), trade_money_xml(stamp="11")]
    if reverse:
        docs.reverse()
    _, xml, intent, bond, _ = _money_setup(database, docs[0])
    with database.session_factory() as session:
        apply(session, docs[1], preview(session, docs[1]))
        originals = [(FILENAME, doc) for doc in docs]
        coupons = _money_decide(session, intent, originals, bond)
        _money_apply(session, coupons, originals)
        trade = _trade_decide(session, intent, originals)
        saved = _money_apply(session, trade, originals, request_id="overlap-trade")
        assert saved["bookkeeping_ready"], saved["exceptions"]
        assert read_money(session, "overlap-trade")["bookkeeping_ready"]
        execution = read_executed_trades(session)["trades"][0]
        assert execution["conflicts"] == []
        assert len(execution["evidence"]["cash_legs"]) == 3
        assert sum(leg["amount_minor"] for leg in execution["evidence"]["cash_legs"]) == 1013550
        assert session.scalar(select(func.count()).select_from(ExecutedTrade)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutedTradeOccurrence)
                .where(ExecutedTradeOccurrence.section == "money")
            )
            == 6
        )
        assert session.scalar(select(CashBalance.amount_kopecks)) == 5286450


def test_trade_money_indistinguishable_nkd_and_unparsed_source_stay_blocked(database):
    from hermes_finance.services.broker_money import preview_money

    client, xml, intent, bond, _ = _money_setup(
        database, trade_money_xml(duplicate_nkd=True, extra=True)
    )
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _trade_decide(session, intent, originals)
        plan = preview_money(session, requested, originals)
        assert not plan["can_apply"]
        assert "same_report_multiplicity" in plan["blockers"]
        assert "money_semantics_unsupported" in plan["exceptions"]
        assert "4_Transfers_unsupported" in plan["exceptions"]
        assert "5_UFSR_unsupported" in plan["exceptions"]
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 422


@pytest.mark.parametrize("failure", ["stale", "rollback", "closed"])
def test_trade_money_stale_closed_and_late_revision_failure_roll_back(
    database, monkeypatch, failure
):
    from hermes_finance.persistence import Instrument
    from hermes_finance.services import executed_trades
    from hermes_finance.services.broker_money import apply_money, preview_money

    _, xml, intent, bond, _ = _money_setup(database, trade_money_xml())
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _trade_decide(session, intent, originals)
        if failure == "rollback":
            from hermes_finance.domain.broker_money import MoneyIntent

            coupons = _money_decide(session, intent, originals, bond)
            requested = MoneyIntent.model_validate(
                {
                    **requested.model_dump(),
                    "money_decisions": [
                        *coupons.model_dump()["money_decisions"],
                        *requested.model_dump()["money_decisions"],
                    ],
                }
            )
        plan = preview_money(session, requested, originals)
        assert plan["can_apply"]
        if failure == "stale":
            bond = session.scalar(select(Instrument).where(Instrument.instrument_type == "bond"))
            original_name = bond.name
            bond.name = "Synthetic temporary rename"
            session.commit()
            bond.name = original_name
            session.commit()
        elif failure == "closed":
            session.get(ReportingMonth, intent.reporting_month_id).status = "closed"
            session.commit()
        else:
            stage = executed_trades.stage_executed_trades

            def interrupted(*args, **kwargs):
                stage(*args, **kwargs)
                raise RuntimeError("synthetic failure after trade revision stage")

            monkeypatch.setattr(executed_trades, "stage_executed_trades", interrupted)
        before = _all_month_tables(database)
        with pytest.raises((MyBrokerError, RuntimeError)):
            apply_money(
                session,
                requested,
                originals,
                confirmation_digest=plan["confirmation_digest"],
                request_id="failed-trade",
            )
        assert before == _all_month_tables(database)


def test_trade_money_catalogue_a_b_a_retires_proof_and_requires_reviewed_reaffirm(database):
    from hermes_finance.persistence import Instrument
    from hermes_finance.services.broker_money import preview_money, read_money

    _, xml, intent, _, _ = _money_setup(database, trade_money_xml())
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _trade_decide(session, intent, originals)
        accepted = _money_apply(session, requested, originals, request_id="trade-first")
        original_proof = accepted["accepted"]
        bond = session.scalar(select(Instrument).where(Instrument.instrument_type == "bond"))
        name = bond.name
        bond.name = "Synthetic changed"
        session.commit()
        bond.name = name
        session.commit()
        read = read_money(session, "trade-first")
        assert read["accepted"] == original_proof
        assert "money_review_retired" in read["targets"][0]["exceptions"]
        requested = _trade_decide(session, intent, originals)
        assert (
            "reviewed_reaffirmation_required"
            in preview_money(session, requested, originals)["blockers"]
        )
        requested = _trade_decide(session, intent, originals, operation="reaffirm")
        saved = _money_apply(session, requested, originals, request_id="trade-reaffirm")
        assert saved["targets"][0]["effective"]


def test_trade_money_other_money_and_opaque_sections_block_close_after_accepted_trade(database):
    from hermes_finance.services.broker_money import read_money

    client, xml, intent, _, _ = _money_setup(database, trade_money_xml(extra=True))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _trade_decide(session, intent, originals)
        saved = _money_apply(session, requested, originals, request_id="trade-with-gap")
        assert saved["targets"][0]["effective"]
        assert {
            "money_semantics_unsupported",
            "4_Transfers_unsupported",
            "5_UFSR_unsupported",
        } <= set(saved["exceptions"])
        assert not read_money(session, "trade-with-gap")["bookkeeping_ready"]
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 422


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("summ_nkd", "125.51", "native_nkd_fee_amount_conflict"),
        ("bank_tax", "9.99", "native_nkd_fee_amount_conflict"),
        ("bank_tax", "0", "negative_posted_cash_nonzero_native_required"),
        ("summ_nkd", "125.501", "trade_cash_exact_kopecks_required"),
        ("qty", "-1", "settled_bond_buy_required"),
    ],
)
def test_trade_money_native_controls_cannot_be_waived(database, field, value, code):
    from hermes_finance.services.broker_money import preview_money

    root = ET.fromstring(trade_money_xml())
    root.find(".//{MyBroker}Details[@trade_no]").set(field, value)
    _, xml, intent, _, _ = _money_setup(database, ET.tostring(root))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        requested = _trade_decide(session, intent, originals)
        plan = preview_money(session, requested, originals)
        assert not plan["can_apply"]
        assert code in plan["blockers"]


def test_trade_money_fresh_repeat_is_revision_noop_and_reopen_does_not_reaffirm(database):
    from hermes_finance.persistence import ExecutedTradeRevision
    from hermes_finance.services.broker_money import preview_money, read_money

    client, xml, intent, bond, _ = _money_setup(database, trade_money_xml())
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        _money_apply(session, _money_decide(session, intent, originals, bond), originals)
        _money_apply(
            session, _trade_decide(session, intent, originals), originals, request_id="trade-once"
        )
        repeated = _trade_decide(session, intent, originals, claims=False)
        plan = preview_money(session, repeated, originals)
        assert plan["can_apply"], plan["blockers"]
        assert plan["decisions"][0]["action"] == "reuse"
        _money_apply(session, repeated, originals, request_id="trade-repeat")
        assert session.scalar(select(func.count()).select_from(ExecutedTradeRevision)) == 2
    assert client.post(f"/api/months/{intent.reporting_month_id}/close").status_code == 200
    assert client.post(f"/api/months/{intent.reporting_month_id}/reopen").status_code == 200
    with database.session_factory() as session:
        current = read_money(session, "trade-once")
        assert "money_review_retired" in current["targets"][0]["exceptions"]
        assert not current["bookkeeping_ready"]


def test_trade_money_repo_cannot_create_financial_source_draft(database):
    scope = _broker_month_setup(database, bond=True)
    client = TestClient(create_app(database))
    root = ET.fromstring(trade_money_xml())
    root.find(".//{MyBroker}Details[@trade_no]").set("repo_no", "SYNTHETIC-REPO")
    xml = ET.tostring(root)
    plan = _broker_month_preview(client, scope, xml)
    assert "repo_semantics_unsupported" in plan["exceptions"]
    assert not plan["bookkeeping_ready"]
    before = _all_month_tables(database)
    assert _broker_month_apply(client, scope, plan, xml).status_code == 409
    assert before == _all_month_tables(database)


@pytest.mark.parametrize("change", ["strip_proof", "delete_revision", "move_owner", "delete_owner"])
def test_trade_money_accepted_revision_and_occurrence_cannot_be_rewritten(database, change):
    from hermes_finance.persistence import ExecutedTradeOccurrence, ExecutedTradeRevision

    _, xml, intent, _, _ = _money_setup(database, trade_money_xml())
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        _money_apply(
            session,
            _trade_decide(session, intent, originals),
            originals,
            request_id="immutable-trade",
        )
        revision = session.scalar(
            select(ExecutedTradeRevision).where(ExecutedTradeRevision.revision == 2)
        )
        original = revision.evidence_json
        owner = session.scalar(
            select(ExecutedTradeOccurrence).where(ExecutedTradeOccurrence.section == "money")
        )
        if change == "strip_proof":
            evidence = json.loads(revision.evidence_json)
            del evidence["cash_reconciliation"]
            revision.evidence_json = json.dumps(evidence)
        elif change == "delete_revision":
            session.delete(revision)
        elif change == "move_owner":
            owner.section = "completed"
        else:
            session.delete(owner)
        with pytest.raises(MyBrokerError, match="append_only|ownership_is_permanent"):
            session.commit()
        session.rollback()
        assert session.get(type(revision), revision.id).evidence_json == original


def test_money_target_edit_delete_and_dependency_a_b_a_cannot_revive_authority(
    database, monkeypatch
):
    from datetime import UTC, datetime

    from hermes_finance.persistence import Instrument, InvestmentCashFlow
    from hermes_finance.services import broker_money_lifecycle
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.statement_import.mybroker import MyBrokerError

    _, xml, intent, bond, _ = _money_setup(database)
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        intent = _money_decide(session, intent, originals, bond)
        _money_apply(session, intent, originals)
        flow = session.scalar(select(InvestmentCashFlow))
        flow.net_amount_kopecks += 1
        with pytest.raises(MyBrokerError, match="money_target_requires_source_revision"):
            session.commit()
        session.rollback()
        session.delete(session.get(InvestmentCashFlow, flow.id))
        with pytest.raises(MyBrokerError, match="money_target_requires_source_revision"):
            session.commit()
        session.rollback()

        class BackdatedClock:
            @staticmethod
            def now(_timezone):
                return datetime(2001, 1, 1, tzinfo=UTC)

        monkeypatch.setattr(broker_money_lifecycle, "datetime", BackdatedClock)
        instrument = session.get(Instrument, bond)
        old = instrument.name
        instrument.name = "Synthetic renamed"
        session.commit()
        instrument.name = old
        session.commit()
        read = read_money(session, "money-accepted")
        assert all(not t["effective"] for t in read["targets"] if t["role"] == "coupon")
        assert all(t["effective"] for t in read["targets"] if t["role"] == "account_funding")
        assert "money_review_retired" in read["exceptions"]
        renewed = _money_decide(
            session,
            intent.model_copy(update={"money_decisions": []}),
            originals,
            bond,
            operation="reaffirm",
        )
        saved = _money_apply(session, renewed, originals, "reviewed-reaffirmation")
        assert all(t["effective"] for t in saved["targets"])
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 2


def money_coupon_pdf(*, month=1, net="1000,00"):
    from _statement_pdf import build_income_report_pdf

    return build_income_report_pdf(
        [
            {
                "payment_kind": "погашение купона",
                "isin": "RU000A000001",
                "security_name": "Synthetic bond",
                "record_date": f"15.{month:02d}.2030",
                "payment_date": f"17.{month:02d}.2030",
                "quantity": "10",
                "per_unit": str(Decimal(net.replace(",", ".")) / 10).replace(".", ","),
                "gross": net,
                "net": net,
                "tax": "-",
                "tax_rate": "-",
            }
        ]
    )


@pytest.mark.parametrize("pdf_first", [False, True])
def test_money_typed_pdf_corroborates_same_payout_in_both_orders_without_tax_invention(
    database, pdf_first
):
    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import (
        AppliedStatementEvent,
        BrokerMoneyOccurrenceOwner,
        InvestmentCashFlow,
    )
    from hermes_finance.services.broker_money import preview_money, read_money
    from hermes_finance.services.broker_months import broker_month_close_blockers, read_broker_month
    from hermes_finance.services.statement_import_apply import StatementApplyAction

    _, xml, intent, bond, _ = _money_setup(database, money_batch_xml(coupons=("1000",)))
    pdf = money_coupon_pdf()
    with database.session_factory() as session:
        if pdf_first:
            row = income_preview(session, pdf, intent.account_id).rows[0]
            result = income_apply(session, pdf, intent.account_id, (selection_from_row(row),))
            assert result.success, result
            flow_id = result.items[0].investment_cash_flow_id
        originals = [(FILENAME, xml)]
        reviewed = _money_decide(session, intent, originals, bond)
        if pdf_first:
            decisions = reviewed.model_dump()["money_decisions"]
            decisions[0]["investment_cash_flow_id"] = flow_id
            decisions[0]["coupon_claims"] = None
            reviewed = MoneyIntent.model_validate(
                {**reviewed.model_dump(), "money_decisions": decisions}
            )
            plan = preview_money(session, reviewed, originals)
            decisions[0]["coupon_claims"] = {
                "reference": "synthetic-exact-payment-link",
                "review_context_digest": plan["decisions"][0]["review_context_digest"],
                "actual_coupon_payment": True,
                "exact_row_instrument_link": True,
                "complete_occurrence_set_is_one_event": True,
                "existing_target_is_same_payment": True,
            }
            reviewed = MoneyIntent.model_validate(
                {**reviewed.model_dump(), "money_decisions": decisions}
            )
        saved = _money_apply(session, reviewed, originals)
        assert saved["bookkeeping_ready"]
        assert all(t["effective"] for t in saved["targets"])
        if not pdf_first:
            flow_id = saved["targets"][0]["target_id"]
            row = income_preview(session, pdf, intent.account_id).rows[0]
            result = income_apply(
                session,
                pdf,
                intent.account_id,
                (
                    selection_from_row(
                        row,
                        action=StatementApplyAction.LINK_EXISTING,
                        existing_cash_flow_id=flow_id,
                        expected_candidate_ids=(flow_id,),
                    ),
                ),
            )
            assert result.success, result
            assert session.get(InvestmentCashFlow, flow_id).tax_amount_kopecks is None
            assert session.get(InvestmentCashFlow, flow_id).gross_amount_kopecks is None
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 1
        assert session.scalar(select(AppliedStatementEvent.investment_cash_flow_id)) == flow_id
        assert (
            read_money(session, "money-accepted")["targets"][0]["components"]["tax_amount_kopecks"]
            is None
        )
        assert session.get(InvestmentCashFlow, flow_id).net_amount_kopecks == 100000
    # Independent GET/snapshot after PDF Apply, including the first Money receipt.
    with database.session_factory() as fresh:
        read = read_money(fresh, "money-accepted")
        assert read["bookkeeping_ready"], read["exceptions"]
        assert all(t["effective"] for t in read["targets"]), read["targets"]
        assert read_broker_month(fresh, intent.base_request_id)["exceptions"] == []
        assert broker_month_close_blockers(fresh, intent.reporting_month_id) == ()
        assert fresh.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 1
        assert fresh.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 2


def test_money_unrelated_month_cash_and_typed_payout_preserve_independent_authority(database):
    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row

    from hermes_finance.persistence import CashBalance, InvestmentCashFlow
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.broker_months import broker_month_close_blockers
    from hermes_finance.services.reporting_months import create_reporting_month

    _, xml, intent, bond, _ = _money_setup(database)
    with database.session_factory() as session:
        _money_apply(
            session, _money_decide(session, intent, [(FILENAME, xml)], bond), [(FILENAME, xml)]
        )
        other_month = create_reporting_month(
            session, year=2030, month=2, snapshot_date=date(2030, 2, 28)
        )
        cash = CashBalance(
            reporting_month_id=other_month.id,
            account_id=intent.account_id,
            name="Synthetic February",
            currency="RUB",
            amount_kopecks=100000,
        )
        session.add(cash)
        session.commit()
        pdf = money_coupon_pdf(month=2)
        row = income_preview(session, pdf, intent.account_id).rows[0]
        result = income_apply(session, pdf, intent.account_id, (selection_from_row(row),))
        assert result.success, result
        payout = session.get(InvestmentCashFlow, result.items[0].investment_cash_flow_id)
        for obj, field in ((cash, "amount_kopecks"), (payout, "net_amount_kopecks")):
            old = getattr(obj, field)
            for value in (old + 1, old):
                setattr(obj, field, value)
                session.commit()
                read = read_money(session, "money-accepted")
                assert all(t["effective"] for t in read["targets"]), read["targets"]
                assert read["bookkeeping_ready"], read["exceptions"]
                assert broker_month_close_blockers(session, intent.reporting_month_id) == ()
        with database.session_factory() as fresh:
            assert read_money(fresh, "money-accepted")["bookkeeping_ready"]


@pytest.mark.parametrize("change", ["event_aba", "revision_aba", "revision_scope_aba", "retract"])
def test_money_pdf_conflict_retires_only_its_target_and_cannot_restore_authority(database, change):

    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row

    from hermes_finance.persistence import (
        AppliedStatementEvent,
        AppliedStatementEventRevision,
        InvestmentCashFlow,
    )
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.broker_months import broker_month_close_blockers
    from hermes_finance.services.reporting_months import create_reporting_month
    from hermes_finance.services.statement_import_apply import StatementApplyAction
    from hermes_finance.services.statement_import_retract import retract_applied_statement_event

    _, xml, intent, bond, _ = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        saved = _money_apply(session, _money_decide(session, intent, originals, bond), originals)
        flow_id = saved["targets"][0]["target_id"]
        candidates = tuple(t["target_id"] for t in saved["targets"] if t["role"] == "coupon")
        pdf = money_coupon_pdf()
        row = income_preview(session, pdf, intent.account_id).rows[0]
        result = income_apply(
            session,
            pdf,
            intent.account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=flow_id,
                    expected_candidate_ids=candidates,
                ),
            ),
        )
        assert result.success, result
        assert read_money(session, "money-accepted")["bookkeeping_ready"]
        event = session.get(AppliedStatementEvent, result.items[0].applied_statement_event_id)
        if change == "retract":
            retracted = retract_applied_statement_event(session, event.id)
            assert not retracted.cash_flow_deleted
            assert retracted.investment_cash_flow_id == flow_id
        else:
            obj = (
                event
                if change == "event_aba"
                else session.get(AppliedStatementEventRevision, result.items[0].revision_id)
            )
            field = "material_fingerprint" if change == "event_aba" else "net_amount_kopecks"
            new_value = "b" * 64 if change == "event_aba" else obj.net_amount_kopecks + 1
            if change == "revision_scope_aba":
                create_reporting_month(session, year=2030, month=2, snapshot_date=date(2030, 2, 28))
                other_pdf = money_coupon_pdf(month=2)
                other_row = income_preview(session, other_pdf, intent.account_id).rows[0]
                other = income_apply(
                    session, other_pdf, intent.account_id, (selection_from_row(other_row),)
                )
                assert other.success
                field = "applied_statement_event_id"
                new_value = other.items[0].applied_statement_event_id
            old = getattr(obj, field)
            setattr(obj, field, new_value)
            session.commit()
            assert not read_money(session, "money-accepted")["targets"][0]["effective"]
            setattr(obj, field, old)
            session.commit()
        read = read_money(session, "money-accepted")
        assert not read["targets"][0]["effective"]
        assert "money_review_retired" in read["targets"][0]["exceptions"]
        # The other distinct payout and H2 did not depend on this optional PDF.
        assert all(t["effective"] for t in read["targets"][1:])
        assert not read["bookkeeping_ready"]
        assert "money_semantics_unsupported" in dict(
            broker_month_close_blockers(session, intent.reporting_month_id)
        )
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == (
            3 if change == "revision_scope_aba" else 2
        )


def test_money_conflicting_pdf_revision_is_rejected_without_changing_accepted_fact(database):
    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row

    from hermes_finance.persistence import InvestmentCashFlow
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.statement_import_apply import StatementApplyAction

    _, xml, intent, bond, _ = _money_setup(database, money_batch_xml(coupons=("1000",)))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        saved = _money_apply(session, _money_decide(session, intent, originals, bond), originals)
        flow_id = saved["targets"][0]["target_id"]
        pdf = money_coupon_pdf()
        row = income_preview(session, pdf, intent.account_id).rows[0]
        linked = income_apply(
            session,
            pdf,
            intent.account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=flow_id,
                    expected_candidate_ids=(flow_id,),
                ),
            ),
        )
        assert linked.success
        bad_pdf = money_coupon_pdf(net="1001,00")
        changed = income_preview(session, bad_pdf, intent.account_id).rows[0]
        result = income_apply(
            session,
            bad_pdf,
            intent.account_id,
            (selection_from_row(changed, action=StatementApplyAction.REVISE),),
        )
        assert not result.success
        assert read_money(session, "money-accepted")["bookkeeping_ready"]
        assert session.get(InvestmentCashFlow, flow_id).net_amount_kopecks == 100000
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 1


@pytest.mark.parametrize("change", ["event", "revision"])
def test_money_get_checks_pdf_support_even_without_lifecycle_retirement(database, change):
    from sqlalchemy import update
    from test_statement_import_apply import apply as income_apply
    from test_statement_import_apply import preview as income_preview
    from test_statement_import_apply import selection_from_row

    from hermes_finance.persistence import AppliedStatementEvent, AppliedStatementEventRevision
    from hermes_finance.services.statement_import_apply import StatementApplyAction

    client, xml, intent, bond, _ = _money_setup(database, money_batch_xml(coupons=("1000",)))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        saved = _money_apply(session, _money_decide(session, intent, originals, bond), originals)
        flow_id = saved["targets"][0]["target_id"]
        pdf = money_coupon_pdf()
        row = income_preview(session, pdf, intent.account_id).rows[0]
        result = income_apply(
            session,
            pdf,
            intent.account_id,
            (
                selection_from_row(
                    row,
                    action=StatementApplyAction.LINK_EXISTING,
                    existing_cash_flow_id=flow_id,
                    expected_candidate_ids=(flow_id,),
                ),
            ),
        )
        assert result.success
        # Synthetic corruption bypasses ORM retirement to exercise independent GET.
        if change == "event":
            session.execute(
                update(AppliedStatementEvent)
                .where(AppliedStatementEvent.id == result.items[0].applied_statement_event_id)
                .values(material_fingerprint="b" * 64)
            )
        else:
            session.execute(
                update(AppliedStatementEventRevision)
                .where(AppliedStatementEventRevision.id == result.items[0].revision_id)
                .values(net_amount_kopecks=100001)
            )
        session.commit()
    read = client.get("/api/broker-months/money-accepted").json()
    assert not read["targets"][0]["effective"]
    assert "money_target_revision_changed" in read["targets"][0]["exceptions"]
    assert "money_review_retired" not in read["targets"][0]["exceptions"]
    assert not read["bookkeeping_ready"]


@pytest.mark.parametrize("amount", ["1000.001", "92233720368547758.08", "-1000", "0"])
def test_money_fractional_overflow_negative_and_zero_are_never_financially_accepted(
    database, amount
):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.broker_money import preview_money

    if amount in {"1000.001", "92233720368547758.08"}:
        scope = _broker_month_setup(database, bond=True)
        client = TestClient(create_app(database))
        response = client.post(
            "/api/broker-months/preview",
            files={"file": (FILENAME, money_batch_xml(coupons=(amount,)), "application/xml")},
            data={"intent": json.dumps(scope)},
        )
        assert response.status_code == 422
        assert client.get("/api/broker-months?reporting_month_id=1").json() == []
        return
    _, xml, intent, bond, base = _money_setup(database, money_batch_xml(coupons=(amount,)))
    decision = {
        "role": "coupon",
        "seed": {"import_id": base["import_id"], "section": "money", "ordinal": 1},
        "instrument_id": bond,
    }
    requested = MoneyIntent.model_validate({**intent.model_dump(), "money_decisions": [decision]})
    with database.session_factory() as session:
        plan = preview_money(session, requested, [(FILENAME, xml)])
        assert not plan["can_apply"] and "money_semantics_not_supported" in plan["blockers"]


def test_money_preview_original_mismatch_and_missing_source_union_are_zero_write(database):
    from sqlalchemy import event

    from hermes_finance.services.broker_money import preview_money
    from hermes_finance.statement_import.mybroker import MyBrokerError

    _, xml, intent, _, _ = _money_setup(database)

    def no_write(_connection, _cursor, statement, _parameters, _context, _many):
        assert statement.split()[0].upper() not in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "REPLACE",
            "CREATE",
            "ALTER",
            "DROP",
        }

    event.listen(database.engine, "before_cursor_execute", no_write)
    try:
        with database.session_factory() as session:
            result = preview_money(session, intent, [(FILENAME, xml)])
            assert len(result["inventory"]) == 4
            missing = preview_money(
                session, intent, [(FILENAME, xml.replace(b"1000.00", b"1001.00"))]
            )
            assert "overlapping_original_required" in missing["blockers"]
            assert "original_not_in_accepted_source_union" in missing["blockers"]
            with pytest.raises(MyBrokerError):
                preview_money(session, intent, [("wrong.xml", xml)])
    finally:
        event.remove(database.engine, "before_cursor_execute", no_write)


def test_money_old_h2_coupon_owner_prevents_new_coupon_and_rolls_back_whole_batch(database):
    from test_statement_import_historical_owner_flows import attest

    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.services.broker_money import preview_money
    from hermes_finance.services.historical_owner_flows import (
        apply_historical_owner_flow,
        preview_historical_owner_flow,
    )

    _, xml, intent, bond, base = _money_setup(database)
    with database.session_factory() as session:
        old = attest(
            session,
            OwnerFlowIntent(
                evidence_version="h2-a1-owner-rub-v2",
                account_id=intent.account_id,
                seed={"import_id": base["import_id"], "ordinal": 1},
            ),
        )
        plan = preview_historical_owner_flow(session, old)
        apply_historical_owner_flow(
            session,
            old,
            confirmation_digest=plan["confirmation_digest"],
            request_id="legacy-wrong-owner",
        )
        reviewed = _money_decide(session, intent, [(FILENAME, xml)], bond)
        rejected = preview_money(session, reviewed, [(FILENAME, xml)])
        assert not rejected["can_apply"] and "occurrence_already_owned" in rejected["blockers"]


def test_money_revoked_h2_replay_stays_retired_and_cannot_be_reassigned(database):
    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.services import historical_owner_flows as h2
    from hermes_finance.services.broker_money import apply_money, preview_money

    _, xml, intent, bond, _ = _money_setup(database)
    with database.session_factory() as session:
        originals = [(FILENAME, xml)]
        reviewed = _money_decide(session, intent, originals, bond)
        plan = preview_money(session, reviewed, originals)
        saved = apply_money(
            session,
            reviewed,
            originals,
            confirmation_digest=plan["confirmation_digest"],
            request_id="money-revoke",
        )
        flow = next(t for t in saved["targets"] if t["role"] == "account_funding")
        revoke = OwnerFlowIntent(
            operation="revoke",
            flow_id=flow["target_id"],
            expected_revision=flow["h2"]["revision"],
            reason_code="attestation_withdrawn",
        )
        rplan = h2.preview_historical_owner_flow(session, revoke)
        h2.apply_historical_owner_flow(
            session,
            revoke,
            confirmation_digest=rplan["confirmation_digest"],
            request_id="h2-revoke",
        )
        replay = apply_money(
            session,
            reviewed,
            originals,
            confirmation_digest=plan["confirmation_digest"],
            request_id="money-revoke",
        )
        assert replay["duplicate"] and not replay["bookkeeping_ready"]
        assert "money_review_retired" in replay["exceptions"]
        fresh = _money_decide(session, intent, originals, bond)
        assert not preview_money(session, fresh, originals)["can_apply"]


@pytest.mark.parametrize("dependency", ["payout", "cash"])
def test_money_legacy_target_a_b_a_retires_preview_before_first_acceptance(database, dependency):
    from datetime import date

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.persistence import (
        BrokerMoneyOccurrenceOwner,
        BrokerMonthApply,
        InvestmentCashFlow,
    )
    from hermes_finance.services.broker_money import apply_money, preview_money
    from hermes_finance.statement_import.mybroker import MyBrokerError

    client, xml, intent, bond, _ = _money_setup(database, money_batch_xml(coupons=("1000",)))
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        target = InvestmentCashFlow(
            reporting_month_id=intent.reporting_month_id,
            account_id=intent.account_id,
            instrument_id=bond,
            flow_type="coupon",
            event_date=date(2030, 1, 17),
            gross_amount_kopecks=100000,
            tax_amount_kopecks=0,
            commission_amount_kopecks=0,
            net_amount_kopecks=100000,
            source="manual",
            currency="RUB",
        )
        session.add(target)
        session.commit()
        reviewed = _money_decide(session, intent, originals, bond, funding=False)
        decisions = reviewed.model_dump()["money_decisions"]
        decisions[0]["investment_cash_flow_id"] = target.id
        decisions[0]["coupon_claims"] = None
        reviewed = MoneyIntent.model_validate(
            {**reviewed.model_dump(), "money_decisions": decisions}
        )
        proposed = preview_money(session, reviewed, originals)
        decisions[0]["coupon_claims"] = {
            "reference": "synthetic-existing-payment-review",
            "review_context_digest": proposed["decisions"][0]["review_context_digest"],
            "actual_coupon_payment": True,
            "exact_row_instrument_link": True,
            "complete_occurrence_set_is_one_event": True,
            "existing_target_is_same_payment": True,
        }
        reviewed = MoneyIntent.model_validate(
            {**reviewed.model_dump(), "money_decisions": decisions}
        )
        confirmed = preview_money(session, reviewed, originals)
        assert confirmed["can_apply"]
        changed = target if dependency == "payout" else session.scalar(select(CashBalance))
        field = "net_amount_kopecks" if dependency == "payout" else "amount_kopecks"
        setattr(changed, field, getattr(changed, field) + 1)
        session.commit()
        setattr(changed, field, getattr(changed, field) - 1)
        session.commit()
        with pytest.raises(MyBrokerError, match="money_preview_stale"):
            apply_money(
                session,
                reviewed,
                originals,
                confirmation_digest=confirmed["confirmation_digest"],
                request_id="stale-legacy",
            )
        assert session.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 0
        journals = [
            r
            for r in session.scalars(select(BrokerMonthApply))
            if json.loads(r.projection_json).get("contract_version") == "broker_money_dependency_v1"
        ]
        assert len(journals) == 3
    # Dependency tokens are not user-facing financial receipts.
    assert (
        len(
            client.get(
                "/api/broker-months", params={"reporting_month_id": intent.reporting_month_id}
            ).json()
        )
        == 1
    )


def test_money_and_public_h2_simultaneous_writers_have_atomic_loser(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from test_statement_import_historical_owner_flows import attest

    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.persistence import HistoricalOwnerFlow, HistoricalOwnerFlowRevision
    from hermes_finance.services.broker_money import apply_money, preview_money
    from hermes_finance.services.historical_owner_flows import (
        apply_historical_owner_flow,
        preview_historical_owner_flow,
    )

    _, xml, intent, bond, base = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        reviewed = _money_decide(session, intent, originals, bond)
        mplan = preview_money(session, reviewed, originals)
        owner = attest(
            session,
            OwnerFlowIntent(
                evidence_version="h2-a1-owner-rub-v2",
                account_id=intent.account_id,
                seed={"import_id": base["import_id"], "ordinal": 3},
            ),
        )
        hplan = preview_historical_owner_flow(session, owner)
        assert mplan["can_apply"] and hplan["can_apply"]
    gate = Barrier(2)

    def writer(kind):
        with database.session_factory() as session:
            gate.wait(timeout=10)
            try:
                if kind == "money":
                    return apply_money(
                        session,
                        reviewed,
                        originals,
                        confirmation_digest=mplan["confirmation_digest"],
                        request_id="concurrent-money",
                    )
                return apply_historical_owner_flow(
                    session,
                    owner,
                    confirmation_digest=hplan["confirmation_digest"],
                    request_id="concurrent-h2",
                )
            except MyBrokerError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, ("money", "h2")))
    assert sum(isinstance(r, dict) for r in results) == 1, results
    assert any("stale" in r for r in results if isinstance(r, str)), results
    with database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(HistoricalOwnerFlow)) == 1
        assert session.scalar(select(func.count()).select_from(HistoricalOwnerFlowRevision)) == 1
        payouts = session.scalar(select(func.count()).select_from(InvestmentCashFlow))
        assert payouts == (2 if isinstance(results[0], dict) else 0)


def test_money_new_covering_report_missing_event_blocks_and_stales_old_confirmation(database):
    from hermes_finance.services.broker_money import apply_money, preview_money

    _, xml, intent, bond, _ = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        reviewed = _money_decide(session, intent, originals, bond)
        old = preview_money(session, reviewed, originals)
        missing = money_batch_xml(coupons=("1000",), stamp="11")
        apply(session, missing, preview(session, missing))
        with pytest.raises(MyBrokerError, match="money_preview_stale"):
            apply_money(
                session,
                reviewed,
                originals,
                confirmation_digest=old["confirmation_digest"],
                request_id="new-source-stale",
            )
        incomplete = preview_money(session, reviewed, originals)
        assert "overlapping_original_required" in incomplete["blockers"]
        complete = preview_money(session, reviewed, [*originals, (FILENAME, missing)])
        assert "overlapping_source_event_missing" in complete["blockers"]
        assert not complete["can_apply"]


@pytest.mark.parametrize("reuse_first", [False, True])
def test_money_incremental_distinct_coupons_keep_prior_authority_and_scoped_readiness(
    database, reuse_first
):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.broker_money import read_money
    from hermes_finance.services.broker_months import read_broker_month

    _, xml, intent, bond, _ = _money_setup(
        database, money_batch_xml(coupons=("1000", "1000"), distinct=True)
    )
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        all_rows = _money_decide(session, intent, originals, bond)
        first = MoneyIntent.model_validate(
            {
                **all_rows.model_dump(),
                "money_decisions": [
                    d.model_dump() for d in all_rows.money_decisions if d.seed.ordinal != 2
                ],
            }
        )
        accepted = _money_apply(session, first, originals, "coupon-a-and-funding")
        original_ids = [(t["role"], t["target_id"]) for t in accepted["targets"]]
        all_rows = _money_decide(session, intent, originals, bond)
        second = MoneyIntent.model_validate(
            {
                **all_rows.model_dump(),
                "money_decisions": [
                    d.model_dump()
                    for d in all_rows.money_decisions
                    if d.role == "coupon" and (reuse_first or d.seed.ordinal == 2)
                ],
            }
        )
        accepted_b = _money_apply(session, second, originals, "coupon-b")
        after_a = read_money(session, "coupon-a-and-funding")
        assert all(t["effective"] for t in after_a["targets"]), after_a["exceptions"]
        assert all(t["effective"] for t in accepted_b["targets"]), accepted_b["exceptions"]
        assert after_a["bookkeeping_ready"] and accepted_b["bookkeeping_ready"]
        assert original_ids == [(t["role"], t["target_id"]) for t in after_a["targets"]]
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 2
        assert len(accepted_b["current_targets"]) == 3
        monthly = read_broker_month(session, intent.base_request_id)
        assert monthly["money_acceptance"]["current_targets"] == accepted_b["current_targets"]


@pytest.mark.parametrize("dependency", ["instrument", "account"])
def test_money_identity_a_b_a_before_first_acceptance_cannot_restore_confirmation(
    database, dependency
):
    from hermes_finance.persistence import Account, BrokerMoneyOccurrenceOwner, Instrument
    from hermes_finance.services.broker_money import apply_money, preview_money

    _, xml, intent, bond, _ = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        reviewed = _money_decide(session, intent, originals, bond)
        old = preview_money(session, reviewed, originals)
        assert old["can_apply"]
        row = (
            session.get(Instrument, bond)
            if dependency == "instrument"
            else session.get(Account, intent.account_id)
        )
        field = "currency" if dependency == "instrument" else "status"
        original = getattr(row, field)
        setattr(row, field, "USD" if dependency == "instrument" else "frozen")
        session.commit()
        setattr(row, field, original)
        session.commit()
        with pytest.raises(MyBrokerError, match="money_preview_stale"):
            apply_money(
                session,
                reviewed,
                originals,
                confirmation_digest=old["confirmation_digest"],
                request_id="stale-identity",
            )
        assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0
        assert session.scalar(select(func.count()).select_from(BrokerMoneyOccurrenceOwner)) == 0
