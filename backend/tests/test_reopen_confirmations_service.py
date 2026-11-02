"""Synthetic, dependency-scoped confirmation preservation across month reopen."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select
from test_statement_import_mybroker import FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _money_apply,
    _money_decide,
    _money_setup,
    money_batch_xml,
)
from test_statement_import_payout_reconciliation import accept, database_bytes, reviewed
from test_statement_import_payout_reconciliation import settlement as settlement

from hermes_finance.domain.broker_money import MoneyIntent
from hermes_finance.persistence import (
    BrokerMonthApply,
    ExpectedCashFlow,
    Instrument,
    InvestmentCashFlow,
)
from hermes_finance.services.broker_money import preview_money, read_money
from hermes_finance.services.reporting_months import close_reporting_month, reopen_reporting_month


def test_reopen_and_one_forecast_edit_preserve_independent_confirmations(database):
    client, xml, intent, instrument, _ = _money_setup(database, money_batch_xml())
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        other = Instrument(
            name="Synthetic second bond",
            instrument_type="bond",
            currency="RUB",
            isin="RU000A000002",
        )
        session.add(other)
        session.commit()
        decisions = [
            d.model_dump()
            for d in _money_decide(session, intent, originals, instrument).money_decisions
        ]
        coupons = [d for d in decisions if d["role"] == "coupon"]
        coupons[1]["instrument_id"] = other.id
        requested = MoneyIntent.model_validate(
            {**intent.model_dump(), "money_decisions": decisions}
        )
        plan = preview_money(session, requested, originals)
        for decision, proposed in zip(decisions, plan["decisions"], strict=True):
            if decision["role"] == "coupon":
                decision["coupon_claims"]["review_context_digest"] = proposed[
                    "review_context_digest"
                ]
        requested = MoneyIntent.model_validate(
            {**intent.model_dump(), "money_decisions": decisions}
        )
        _money_apply(session, requested, originals)
        actuals = list(session.scalars(select(InvestmentCashFlow).order_by(InvestmentCashFlow.id)))
        assert len(actuals) == 2
        forecasts = [
            ExpectedCashFlow(
                reporting_month_id=intent.reporting_month_id,
                account_id=intent.account_id,
                instrument_id=actual.instrument_id,
                flow_type="coupon",
                expected_date=date(2030, 2, 1),
                gross_amount_kopecks=actual.net_amount_kopecks + 100,
                expected_tax_amount_kopecks=100,
                expected_net_amount_kopecks=actual.net_amount_kopecks,
                source="synthetic",
                source_as_of_date=date(2030, 1, 31),
                forecast_version="synthetic-v1",
            )
            for actual in actuals
        ]
        session.add_all(forecasts)
        session.commit()
        pairs = [
            (actual.id, forecast.id) for actual, forecast in zip(actuals, forecasts, strict=True)
        ]
    payloads = []
    for i, (actual_id, forecast_id) in enumerate(pairs):
        _, payload = accept(
            client,
            {
                "contract_version": "broker_payout_reconciliation_v1",
                "operation": "link",
                "base_request_id": intent.base_request_id,
                "reporting_month_id": intent.reporting_month_id,
                "account_id": intent.account_id,
                "investment_cash_flow_id": actual_id,
                "expected_cash_flow_id": forecast_id,
            },
            f"scoped-{i}",
        )
        payloads.append(payload)
    with database.session_factory() as session:
        receipts = {
            r.request_id: r.projection_json for r in session.scalars(select(BrokerMonthApply))
        }
        close_reporting_month(session, intent.reporting_month_id)
        reopen_reporting_month(session, intent.reporting_month_id)
        assert read_money(session, "money-accepted")["bookkeeping_ready"]
        assert all(
            session.get(BrokerMonthApply, key).projection_json == value
            for key, value in receipts.items()
        )
    for i in range(2):
        assert (
            client.get(f"/api/broker-months/scoped-{i}").json()["relations"][0]["state"] == "paid"
        )
    before = database_bytes(database)
    assert client.post(f"/api/months/{intent.reporting_month_id}/reopen").status_code == 200
    assert database_bytes(database) == before
    with database.session_factory() as session:
        changed = session.get(ExpectedCashFlow, pairs[0][1])
        original = changed.expected_net_amount_kopecks
        for amount in (original + 1, original):
            changed.expected_net_amount_kopecks = amount
            session.commit()
            assert all(t["effective"] for t in read_money(session, "money-accepted")["targets"])
            assert session.get(InvestmentCashFlow, pairs[1][0]).tax_amount_kopecks is None
    assert client.get("/api/broker-months/scoped-0").json()["relations"][0]["state"] == "retired"
    assert client.get("/api/broker-months/scoped-1").json()["relations"][0]["state"] == "paid"
    before = database_bytes(database)
    for payload in payloads:
        assert client.post("/api/broker-months/payout-apply", json=payload).status_code == 200
    assert database_bytes(database) == before


@pytest.mark.parametrize(
    "difference",
    [
        "instrument",
        "date",
        "net",
        "kind",
        "unknown_date",
        "unknown_net",
        "unknown_kind",
        "unknown_zero_dividend",
    ],
)
def test_independent_payout_preserves_money_confirmations(database, difference):
    _, xml, intent, instrument, _ = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        other = Instrument(
            name="Synthetic independent bond", instrument_type="bond", currency="RUB"
        )
        session.add(other)
        session.commit()
        saved = _money_apply(
            session, _money_decide(session, intent, originals, instrument), originals
        )
        selected = next(t for t in saved["targets"] if t["role"] == "coupon")
        actual = session.get(InvestmentCashFlow, selected["target_id"])
        independent = InvestmentCashFlow(
            reporting_month_id=actual.reporting_month_id,
            account_id=actual.account_id,
            instrument_id=None if difference.startswith("unknown_") else instrument,
            flow_type=actual.flow_type,
            event_date=actual.event_date,
            net_amount_kopecks=actual.net_amount_kopecks,
            gross_amount_kopecks=actual.net_amount_kopecks,
            tax_amount_kopecks=0,
            commission_amount_kopecks=0,
            currency="RUB",
            source="synthetic-manual",
        )
        if difference == "instrument":
            independent.instrument_id = other.id
        elif difference.endswith("date"):
            independent.event_date += timedelta(days=1)
        elif difference.endswith("net"):
            independent.net_amount_kopecks += 1
        else:
            independent.flow_type = "dividend"
            if difference == "unknown_zero_dividend":
                independent.event_date = date(2030, 1, 20)
                independent.gross_amount_kopecks = independent.net_amount_kopecks = 0
        session.add(independent)
        session.commit()
        assert all(t["effective"] for t in read_money(session, "money-accepted")["targets"])
        session.delete(independent)
        session.commit()
        assert all(t["effective"] for t in read_money(session, "money-accepted")["targets"])


@pytest.mark.parametrize("identified", [True, False])
def test_operation_overlap_edit_retires_only_its_dependent_money_target(database, identified):
    _, xml, intent, instrument, _ = _money_setup(database)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        saved = _money_apply(
            session, _money_decide(session, intent, originals, instrument), originals
        )
        selected = next(t for t in saved["targets"] if t["role"] == "coupon")
        actual = session.get(InvestmentCashFlow, selected["target_id"])
        independent = InvestmentCashFlow(
            reporting_month_id=intent.reporting_month_id,
            account_id=intent.account_id,
            instrument_id=instrument if identified else None,
            flow_type="coupon",
            event_date=actual.event_date + timedelta(days=1),
            net_amount_kopecks=actual.net_amount_kopecks,
            gross_amount_kopecks=actual.net_amount_kopecks + 100,
            tax_amount_kopecks=100,
            commission_amount_kopecks=0,
            currency="RUB",
            source="synthetic-manual",
        )
        session.add(independent)
        session.commit()
        assert all(t["effective"] for t in read_money(session, "money-accepted")["targets"])
        original_date = independent.event_date
        for day in (actual.event_date, original_date):
            independent.event_date = day
            session.commit()
            current = read_money(session, "money-accepted")
            for target in current["targets"]:
                assert target["effective"] is (
                    target["target_id"] != selected["target_id"] or target["role"] != "coupon"
                )


def test_pending_payout_review_survives_unchanged_reopen(database, settlement):
    client, intent = settlement
    requested, plan = reviewed(client, intent)
    with database.session_factory() as session:
        close_reporting_month(session, intent["reporting_month_id"])
        reopen_reporting_month(session, intent["reporting_month_id"])
    payload = {
        **requested,
        "request_id": "review-survived",
        "confirmation_digest": plan["confirmation_digest"],
    }
    accepted = client.post("/api/broker-months/payout-apply", json=payload)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["relations"][0]["state"] == "paid"
    before = database_bytes(database)
    repeated = client.post("/api/broker-months/payout-apply", json=payload)
    assert repeated.status_code == 200 and repeated.json()["duplicate"]
    assert database_bytes(database) == before
