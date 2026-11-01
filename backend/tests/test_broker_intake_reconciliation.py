"""Synthetic regression cases for reviewed replacement, never retained Owner data."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_statement_import_mybroker import FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _broker_month_apply,
    _broker_month_preview,
    _broker_month_setup,
    broker_month_xml,
    draft_structure_xml,
)

from hermes_finance.main import create_app
from hermes_finance.persistence import PositionQuoteProvenance, PositionSnapshot
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.statement_import.investment_money import parse_investment_money_security
from hermes_finance.statement_import.mybroker_identity import parse_identity


@pytest.mark.parametrize("period", ["полугодие", "1 полугодие", "2 полугодие"])
def test_halfyear_dividend_identity_only(period):
    text = f'Дивиденды за {period} 2030 г. по акциям МКПАО "Synthetic" (1-01-12345-A). (Удержан налог 17 руб.)'
    security = parse_investment_money_security(text)
    assert security.kind == "dividend"
    assert security.reg_number == "1-01-12345-A"
    assert parse_investment_money_security(text + " возврат") is None
    assert parse_investment_money_security(text.replace(period, "3 полугодие")) is None


def test_complete_duplicate_money_retains_occurrences_and_frozen_default():
    root = ET.fromstring(draft_structure_xml())
    rows = root.find(".//{MyBroker}rn_Collection")
    duplicate = deepcopy(rows[0])
    # Full daily structure expects balances only on the last row of a day.
    for tag, key in (
        ("Textbox83", "money_volume"),
        ("Textbox84", "all_volume"),
        ("Textbox93", "debet_volume"),
    ):
        rows[0].find(".//{MyBroker}" + tag).set(key, "")
    rows.append(duplicate)
    xml = ET.tostring(root)
    frozen = parse_identity(xml, FILENAME, incomplete_draft=True)
    assert "unparsed_source_rows" in frozen["conflicts"]
    current = parse_identity(xml, FILENAME, incomplete_draft=True, repeated_occurrences=True)
    assert current["draft_structure"]["contract"].endswith("v2")
    assert "money_occurrences_unresolved" in current["draft_structure"]["exceptions"]
    assert current["draft_structure"]["financial_authority"] == "none"
    assert parse_identity(xml, FILENAME, incomplete_draft=True) == frozen


@pytest.mark.parametrize("case", ["saved", "stale", "quote_changed", "sold", "rollback", "invalid"])
def test_reviewed_position_replacement_preserves_old_record_and_replay(database, case, monkeypatch):
    intent = _broker_month_setup(database)
    with database.session_factory() as session:
        old = create_position_snapshot(
            session,
            **intent,
            instrument_id=1,
            quantity="3",
            average_cost_per_unit="100",
            market_price_per_unit="120",
            price_date=date(2029, 12, 31),
        )
        old_id = old.id
    client = TestClient(create_app(database=database))
    xml = broker_month_xml()
    if case == "sold":
        xml = (
            xml.replace(b'real_rest="10"', b'real_rest="0"')
            .replace(b'forward_rest="10"', b'forward_rest="0"')
            .replace(b'real_volume="1000.00"', b'real_volume="0"')
            .replace(b'qty="2"', b'qty="-8"')
            .replace(b'summ_trade="1000.00"', b'summ_trade="800.00"')
            .replace(b'volume="-1000.00"', b'volume="800.00"')
            .replace(b'real_rest="400.00"', b'real_rest="2200.00"')
        )
    assert not _broker_month_preview(client, intent, xml)["can_apply"]
    reviewed_intent = {**intent, "reconcile_position_ids": [old_id]}
    if case == "invalid":
        reviewed_intent["reconcile_position_ids"] = [old_id, old_id + 10000]
        response = client.post(
            "/api/broker-months/preview",
            files={"file": (FILENAME, xml)},
            data={"intent": json.dumps(reviewed_intent)},
        )
        assert response.status_code == 422
        return
    plan = _broker_month_preview(client, reviewed_intent, xml)
    assert plan["can_apply"]
    if case == "stale":
        with database.session_factory() as session:
            session.get(PositionSnapshot, old_id).notes = "new review required"
            session.commit()
    if case == "quote_changed":
        with database.session_factory() as session:
            session.add(
                PositionQuoteProvenance(
                    position_snapshot_id=old_id,
                    reporting_month_id=intent["reporting_month_id"],
                    provider="synthetic",
                    provider_instrument_id="synthetic-uid",
                    quote_kind="last",
                    raw_price="120",
                    raw_price_basis="R",
                    normalized_price_kopecks=12000,
                    price_date=date(2029, 12, 31),
                    fetched_at_utc=datetime.now(UTC),
                    target_date=date(2029, 12, 31),
                    freshness="ok",
                    applied_at_utc=datetime.now(UTC),
                )
            )
            session.commit()
    if case == "rollback":
        from hermes_finance.services import mybroker_import
        from hermes_finance.statement_import.mybroker import MyBrokerError

        def fail_after_archive(session, parsed):
            assert session.get(PositionSnapshot, old_id).reporting_month_id is None
            raise MyBrokerError("synthetic_failure_after_archive")

        monkeypatch.setattr(mybroker_import, "stage_mybroker", fail_after_archive)
    response = _broker_month_apply(client, reviewed_intent, plan, xml)
    rejected = case in {"stale", "quote_changed", "rollback"}
    assert response.status_code == (409 if rejected else 200), response.text
    with database.session_factory() as session:
        old = session.get(PositionSnapshot, old_id)
        if rejected:
            assert old.reporting_month_id == intent["reporting_month_id"]
        else:
            assert old.reporting_month_id is None
            assert old.archived_from_period == "2030-01"
            active = list(
                session.scalars(
                    select(PositionSnapshot).where(
                        PositionSnapshot.reporting_month_id == intent["reporting_month_id"]
                    )
                )
            )
            if case == "sold":
                assert active == []
            else:
                assert len(active) == 1 and active[0].price_source == "broker_statement_native"
    if not rejected:
        assert _broker_month_apply(client, reviewed_intent, plan, xml).status_code == 200
