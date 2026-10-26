"""Synthetic original -> Money -> settlement API, immutable history and currentness."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import event, select
from test_statement_import_mybroker import FILENAME, ISIN
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _money_apply,
    _money_decide,
    _money_setup,
    money_batch_xml,
)

from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    BrokerMonthApply,
    ExpectedCashFlow,
    InvestmentCashFlow,
)


def move_payout_posted_date(xml, posted_date):
    from copy import deepcopy

    root = ET.fromstring(xml)
    for group in root.findall(".//{MyBroker}settlement_date"):
        new = deepcopy(group)
        new.set("settlement_date", posted_date + "T00:00:00")
        for row in list(new.find("{MyBroker}rn_Collection")):
            if row.find("{MyBroker}oper_type").get("oper_type") != "Перевод":
                new.find("{MyBroker}rn_Collection").remove(row)
        for row in list(group.find("{MyBroker}rn_Collection")):
            if row.find("{MyBroker}oper_type").get("oper_type") == "Перевод":
                group.find("{MyBroker}rn_Collection").remove(row)
        next(parent for parent in root.iter() if group in list(parent)).append(new)
    return ET.tostring(root, encoding="utf-8")


@pytest.fixture
def settlement(database, request):
    xml = money_batch_xml(coupons=("1000.00",))
    if getattr(request, "param", None) == "near":
        xml = move_payout_posted_date(xml, "2030-01-31")
    client, xml, money_intent, instrument_id, _ = _money_setup(database, xml)
    originals = [(FILENAME, xml)]
    with database.session_factory() as session:
        reviewed = _money_decide(session, money_intent, originals, instrument_id)
        _money_apply(session, reviewed, originals)
        actual = session.scalar(select(InvestmentCashFlow).order_by(InvestmentCashFlow.id))
        flow = ExpectedCashFlow(
            reporting_month_id=actual.reporting_month_id,
            account_id=actual.account_id,
            instrument_id=actual.instrument_id,
            flow_type="coupon",
            expected_date=date(2030, 2, 1),
            gross_amount_kopecks=112345,
            expected_tax_amount_kopecks=12345,
            expected_net_amount_kopecks=100000,
            source="synthetic-manual",
            source_as_of_date=date(2030, 1, 31),
            forecast_version="synthetic-v1",
        )
        session.add(flow)
        session.commit()
        intent = {
            "contract_version": "broker_payout_reconciliation_v1",
            "operation": "link",
            "base_request_id": money_intent.base_request_id,
            "reporting_month_id": actual.reporting_month_id,
            "account_id": actual.account_id,
            "investment_cash_flow_id": actual.id,
            "expected_cash_flow_id": flow.id,
        }
    return client, intent


def database_bytes(database):
    with closing(sqlite3.connect(database.engine.url.database)) as c:
        return "\n".join(c.iterdump())


def reviewed(client, intent, provider_key=None):
    first = client.post("/api/broker-months/payout-preview", json=intent)
    assert first.status_code == 200, first.text
    intent = {
        **intent,
        "claims": {
            "reference": "synthetic-original-review",
            "independent_event_reference": "synthetic-exact-event",
            "settlement_basis_reference": "synthetic-complete-settlement",
            "review_context_digest": first.json()["review_context_digest"],
            "provider_identity_key": provider_key,
            "actual_is_exact_event": intent["operation"] != "retire",
            "full_event_settled_not_partial": True,
            "exact_manual_row_is_same_event": intent["operation"] != "retire",
        },
    }
    result = client.post("/api/broker-months/payout-preview", json=intent)
    assert result.status_code == 200, result.text
    assert result.json()["can_apply"], result.json()["blockers"]
    return intent, result.json()


def accept(client, intent, request, provider_key=None):
    intent, plan = reviewed(client, intent, provider_key)
    payload = {**intent, "request_id": request, "confirmation_digest": plan["confirmation_digest"]}
    result = client.post("/api/broker-months/payout-apply", json=payload)
    assert result.status_code == 200, result.text
    get = client.get(f"/api/broker-months/{request}")
    assert get.status_code == 200, get.text
    assert get.json() == {k: v for k, v in result.json().items() if k != "duplicate"}
    return get.json(), payload


def test_api_separate_retirement_reaffirmation_chain_and_read_only_replay(database, settlement):
    client, intent = settlement
    r1, payload = accept(client, intent, "R1")
    assert r1["relations"][0]["state"] == "paid"
    predecessor = r1["relations"][0]["id"]
    with database.session_factory() as session:
        original = session.get(BrokerMonthApply, "R1").projection_json
    for retire_id, reaffirm_id in (("R2", "R3"), ("R4", "R5")):
        accept(client, {**intent, "operation": "retire", "predecessor_id": predecessor}, retire_id)
        next_row, _ = accept(
            client, {**intent, "operation": "reaffirm", "predecessor_id": predecessor}, reaffirm_id
        )
        assert next_row["relations"][0]["state"] == "paid"
        with database.session_factory() as session:
            old = session.get(AppliedPayoutReconciliation, predecessor)
            assert old.retired_request_id == retire_id
            new = session.get(AppliedPayoutReconciliation, next_row["relations"][0]["id"])
            assert new.supersedes_id == predecessor
            assert (
                json.loads(session.get(BrokerMonthApply, reaffirm_id).projection_json)["targets"][
                    0
                ]["predecessor_retirement_request_id"]
                == retire_id
            )
        predecessor = next_row["relations"][0]["id"]
    replay = client.post("/api/broker-months/payout-apply", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["duplicate"] and replay.json()["relations"][0]["state"] == "retired"
    with database.session_factory() as session:
        assert session.get(BrokerMonthApply, "R1").projection_json == original


def dividend_xml(amounts=("1000.00",), *, distinct=False, narrative=None, stamp="10"):
    root = ET.fromstring(money_batch_xml(coupons=amounts, distinct=distinct, stamp=stamp))
    index = 0
    for comment in root.findall(".//{MyBroker}comment"):
        if "погашение купона" in comment.get("comment", ""):
            comment.set(
                "comment",
                narrative
                or f'Дивиденды за {2029 - index if distinct else 2029} год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130.00 руб.).',
            )
            index += 1
    return ET.tostring(root, encoding="utf-8")


def dividend_setup(database, xml):
    from hermes_finance.domain.broker_money import MoneyIntentV2
    from hermes_finance.persistence import Instrument, SecurityRegIsinMapping

    client, _, legacy, _, saved = _money_setup(database, xml)
    with database.session_factory() as session:
        stock = session.scalar(select(Instrument).where(Instrument.isin == ISIN))
        session.add(
            SecurityRegIsinMapping(
                reg_number="1-01-00000-A",
                isin=ISIN,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()
        stock_id = stock.id
    return (
        client,
        MoneyIntentV2.model_validate(
            {**legacy.model_dump(), "contract_version": "broker_money_v2"}
        ),
        stock_id,
        saved,
    )


def dividend_review(session, intent, xml, stock_id):
    from hermes_finance.domain.broker_money import MoneyIntentV2
    from hermes_finance.services.broker_money import preview_money

    originals = xml if isinstance(xml, list) else [(FILENAME, xml)]
    inventory = preview_money(session, intent, originals)["inventory"]
    decisions = [
        {
            "role": "dividend",
            "seed": {k: row["occurrence"][k] for k in ("import_id", "section", "ordinal")},
            "instrument_id": stock_id,
        }
        for row in inventory
        if row["candidate_kind"] == "dividend_paid_candidate"
        and row["occurrence"]["import_id"] == inventory[0]["occurrence"]["import_id"]
    ]
    intent = MoneyIntentV2.model_validate({**intent.model_dump(), "money_decisions": decisions})
    plan = preview_money(session, intent, originals)
    for d, p in zip(decisions, plan["decisions"], strict=True):
        d["dividend_claims"] = {
            "reference": "synthetic-exact-original",
            "independent_net_basis_reference": "synthetic-final-net-settlement",
            "review_context_digest": p["review_context_digest"],
            "actual_ordinary_stock_dividend": True,
            "exact_row_stock_link": True,
            "complete_occurrence_set_is_one_event": True,
            "posted_amount_is_final_net_credit": True,
            "withholding_is_embedded_not_additional_cash_leg": True,
            "existing_target_is_same_payment": True,
        }
    return MoneyIntentV2.model_validate({**intent.model_dump(), "money_decisions": decisions})


@pytest.mark.parametrize(
    "amounts,distinct,count", [(("1000.00",), False, 1), (("1000.00", "1000.00"), True, 2)]
)
def test_dividend_v2_native_only_exact_net_tax_unknown_and_distinguishable_events(
    database, amounts, distinct, count
):
    from hermes_finance.persistence import BrokerMoneyOccurrenceOwner, CashBalance

    xml = dividend_xml(amounts, distinct=distinct)
    client, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        cash = [(r.id, r.amount_kopecks) for r in session.scalars(select(CashBalance))]
        intent = dividend_review(session, intent, xml, stock)
        result = _money_apply(session, intent, [(FILENAME, xml)], "dividends-v2")
        assert len(result["targets"]) == count
        assert all(t["effective"] for t in result["targets"])
        actuals = list(
            session.scalars(
                select(InvestmentCashFlow).where(InvestmentCashFlow.flow_type == "dividend")
            )
        )
        assert len(actuals) == count and len({r.source_row_key for r in actuals}) == count
        assert all(
            (
                r.net_amount_kopecks,
                r.amount_basis,
                r.gross_amount_kopecks,
                r.tax_amount_kopecks,
                r.commission_amount_kopecks,
            )
            == (100000, "broker_statement_net_v1", None, None, None)
            for r in actuals
        )
        assert (
            len(
                list(
                    session.scalars(
                        select(BrokerMoneyOccurrenceOwner).where(
                            BrokerMoneyOccurrenceOwner.role == "dividend"
                        )
                    )
                )
            )
            == count
        )
        assert [(r.id, r.amount_kopecks) for r in session.scalars(select(CashBalance))] == cash
        proof = json.loads(session.get(BrokerMonthApply, "dividends-v2").projection_json)
        assert all(
            e["observed_tax_kopecks"] == "13000" and e["tax_role"] == "annotation_only"
            for e in proof["dividend_evidence"]
        )
        assert "Дивиденды за" not in session.get(BrokerMonthApply, "dividends-v2").projection_json
    assert (
        client.get("/api/broker-months/dividends-v2").json()["contract_version"]
        == "broker_money_v2"
    )


def test_dividend_indistinguishable_multiplicity_blocks_without_creating_actual(database):
    from hermes_finance.services.broker_money import preview_money

    xml = dividend_xml(("1000.00", "1000.00"))
    _, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        intent = dividend_review(session, intent, xml, stock)
        plan = preview_money(session, intent, [(FILENAME, xml)])
        assert not plan["can_apply"] and "same_report_multiplicity" in plan["blockers"]
        assert list(session.scalars(select(InvestmentCashFlow))) == []


def test_live_replacement_api_and_receipt_rollback(database, settlement, monkeypatch):
    from sqlalchemy.orm import Session

    client, intent = settlement
    r1, _ = accept(client, intent, "R1")
    previous = r1["relations"][0]["id"]
    reaffirm = {**intent, "operation": "reaffirm", "predecessor_id": previous}
    requested, plan = reviewed(client, reaffirm)
    before = database_bytes(database)
    flush = Session.flush

    def fail_after_receipt(session, *args, **kwargs):
        if any(isinstance(row, AppliedPayoutReconciliation) for row in session.new):
            assert session.get(BrokerMonthApply, "failed-R3") is not None
            raise RuntimeError("synthetic-after-receipt-and-retirement")
        return flush(session, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "flush", fail_after_receipt)
        with pytest.raises(RuntimeError, match="synthetic-after-receipt-and-retirement"):
            client.post(
                "/api/broker-months/payout-apply",
                json={
                    **requested,
                    "request_id": "failed-R3",
                    "confirmation_digest": plan["confirmation_digest"],
                },
            )
    assert database_bytes(database) == before
    r3, _ = accept(client, reaffirm, "R3")
    assert r3["relations"][0]["state"] == "paid"
    with database.session_factory() as session:
        assert session.get(AppliedPayoutReconciliation, previous).retired_request_id == "R3"
    fork = client.post("/api/broker-months/payout-preview", json=reaffirm)
    assert "payout_predecessor_already_successored" in fork.json()["blockers"]


def test_preview_read_replay_after_close_are_zero_dml_and_changed_replay_conflicts(
    database, settlement
):
    from hermes_finance.services.reporting_months import close_reporting_month

    client, intent = settlement
    writes = []

    def trace(_connection, _cursor, statement, *_args):
        if statement.lstrip().split(" ", 1)[0].upper() in {
            "INSERT",
            "UPDATE",
            "DELETE",
            "REPLACE",
            "CREATE",
            "DROP",
            "ALTER",
        }:
            writes.append(statement)

    event.listen(database.engine, "before_cursor_execute", trace)
    try:
        reviewed(client, intent)
        assert writes == []
        _, payload = accept(client, intent, "R1")
        with database.session_factory() as session:
            close_reporting_month(session, intent["reporting_month_id"])
        before = database_bytes(database)
        writes.clear()
        assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "paid"
        assert client.post("/api/broker-months/payout-apply", json=payload).json()["duplicate"]
        assert (
            client.post(
                "/api/broker-months/payout-apply",
                json={**payload, "claims": {**payload["claims"], "reference": "changed"}},
            ).status_code
            == 409
        )
        assert writes == [] and database_bytes(database) == before
    finally:
        event.remove(database.engine, "before_cursor_execute", trace)


def test_ecf_aba_before_first_acceptance_and_after_acceptance_retirement(database, settlement):
    client, intent = settlement
    requested, plan = reviewed(client, intent)
    for delta in (1, -1):
        with database.session_factory() as session:
            row = session.get(ExpectedCashFlow, intent["expected_cash_flow_id"])
            row.expected_net_amount_kopecks += delta
            session.commit()
    before = database_bytes(database)
    stale = client.post(
        "/api/broker-months/payout-apply",
        json={**requested, "request_id": "old", "confirmation_digest": plan["confirmation_digest"]},
    )
    assert stale.status_code == 409 and "payout_preview_stale" in stale.text
    assert database_bytes(database) == before
    r1, _ = accept(client, intent, "R1")
    with database.session_factory() as session:
        row = session.get(ExpectedCashFlow, intent["expected_cash_flow_id"])
        row.notes = "synthetic nonmaterial note"
        session.commit()
    assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "paid"
    for delta in (1, -1):
        with database.session_factory() as session:
            row = session.get(ExpectedCashFlow, intent["expected_cash_flow_id"])
            row.expected_net_amount_kopecks += delta
            session.commit()
    old = client.get("/api/broker-months/R1").json()
    assert old["relations"][0]["state"] == "retired"
    retired = old["relations"][0]["retired_request_id"]
    r3, _ = accept(
        client,
        {**intent, "operation": "reaffirm", "predecessor_id": r1["relations"][0]["id"]},
        "R3",
    )
    assert r3["accepted"]["targets"][0]["predecessor_retirement_request_id"] == retired
    assert r3["relations"][0]["state"] == "paid"


def test_concurrent_confirmations_leave_exactly_one_receipt_and_relation(database, settlement):
    from threading import Barrier

    from hermes_finance.domain.payout_reconciliation import PayoutIntent
    from hermes_finance.services import actual_payouts
    from hermes_finance.statement_import.mybroker import MyBrokerError

    client, intent = settlement
    requested, plan = reviewed(client, intent)
    barrier = Barrier(2)

    def confirm(request):
        with database.session_factory() as session:
            barrier.wait(timeout=10)
            try:
                return actual_payouts.apply(
                    session,
                    PayoutIntent.model_validate(requested),
                    request_id=request,
                    confirmation_digest=plan["confirmation_digest"],
                )
            except MyBrokerError as error:
                return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, ["racer-a", "racer-b"]))
    assert sum(isinstance(r, dict) for r in results) == 1
    assert "payout_preview_stale" in results
    with database.session_factory() as session:
        assert len(list(session.scalars(select(AppliedPayoutReconciliation)))) == 1
        assert (
            len(
                list(
                    session.scalars(
                        select(BrokerMonthApply).where(
                            BrokerMonthApply.request_id.in_(("racer-a", "racer-b"))
                        )
                    )
                )
            )
            == 1
        )


@pytest.mark.parametrize("settlement", ["near"], indirect=True)
def test_scoped_close_future_unknown_paid_and_closed_preservation(database, settlement):
    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services.actual_payouts import close_blockers
    from hermes_finance.services.reporting_months import (
        CloseGuardError,
        close_reporting_month,
        create_reporting_month,
    )

    client, intent = settlement
    with database.session_factory() as session:
        blockers = close_blockers(session, intent["reporting_month_id"])
        from hermes_finance.services.broker_money import read_money

        assert [code for code, _ in blockers] == ["source_payout_identity_unresolved"], {
            "money": read_money(session, "money-accepted")["exceptions"],
            "actual_dates": [
                str(r.event_date) for r in session.scalars(select(InvestmentCashFlow))
            ],
        }
        before = database_bytes(database)
        with pytest.raises(CloseGuardError):
            close_reporting_month(session, intent["reporting_month_id"])
        assert database_bytes(database) == before
        manual = create_reporting_month(
            session, year=2030, month=3, snapshot_date=date(2030, 3, 31)
        )
        assert close_blockers(session, manual.id) == ()
    calendar = client.get(
        f"/api/payouts/calendar?month_id={intent['reporting_month_id']}&forecast_version=synthetic-v1"
    ).json()
    assert calendar[0]["actual_attribution_coverage"] == "unknown" and calendar[0]["items"] == []
    legacy_calendar = client.get(
        f"/api/expected-flows/calendar?month_id={intent['reporting_month_id']}&forecast_version=synthetic-v1"
    ).json()
    assert legacy_calendar[0]["actual_attribution_coverage"] == "unknown"
    assert legacy_calendar[0]["items"] == []
    accept(client, intent, "R1")
    with database.session_factory() as session:
        assert close_blockers(session, intent["reporting_month_id"]) == ()
        close_reporting_month(session, intent["reporting_month_id"])
        assert close_blockers(session, intent["reporting_month_id"]) == ()
        assert session.get(ReportingMonth, intent["reporting_month_id"]).status == "closed"
    assert (
        client.get(
            f"/api/payouts/calendar?month_id={intent['reporting_month_id']}&forecast_version=synthetic-v1"
        ).json()
        == []
    )


def create_provider_forecast(session, actual, *, identity="n:1", payment_date=date(2030, 2, 1)):
    from hermes_finance.persistence import InstrumentMarketMapping, PositionSnapshot
    from hermes_finance.services.applied_payouts import create_applied_payout

    if session.get(InstrumentMarketMapping, actual.instrument_id) is None:
        session.add(
            InstrumentMarketMapping(
                instrument_id=actual.instrument_id,
                provider="t_invest",
                provider_instrument_id="synthetic-shared-uid",
                excluded=False,
            )
        )
        session.flush()
    position = session.scalar(
        select(PositionSnapshot).where(
            PositionSnapshot.account_id == actual.account_id,
            PositionSnapshot.instrument_id == actual.instrument_id,
            PositionSnapshot.reporting_month_id == actual.reporting_month_id,
        )
    )
    app = create_applied_payout(
        session,
        reporting_month_id=actual.reporting_month_id,
        account_id=actual.account_id,
        instrument_id=actual.instrument_id,
        source_position_snapshot_id=position.id,
        provider="t_invest",
        provider_instrument_uid="synthetic-shared-uid",
        event_kind=actual.flow_type,
        identity_key=identity,
        payment_date=payment_date,
        per_unit_amount="999.00",
        currency="RUB",
        fetched_at=datetime.now(UTC),
    )
    session.commit()
    return app.id


def test_two_accounts_same_provider_event_independent_legacy_conversion_and_live_revision(
    database, settlement
):
    from test_statement_import_mybroker_endpoints import _broker_month_apply, _broker_month_preview

    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.applied_payouts import (
        append_applied_payout_revision,
        clear_applied_payout_reconciliation,
        get_applied_payout_reconciliation,
        set_applied_payout_reconciliation,
    )
    from hermes_finance.services.broker_identity_mappings import confirm_mapping

    client, intent_a = settlement
    with database.session_factory() as session:
        actual_a = session.get(InvestmentCashFlow, intent_a["investment_cash_flow_id"])
        app_a = create_provider_forecast(session, actual_a)
        legacy = set_applied_payout_reconciliation(
            session,
            app_a,
            expected_cash_flow_id=intent_a["expected_cash_flow_id"],
            counting_decision="count_manual",
        )
        session.commit()
        intent_a = {**intent_a, "applied_payout_id": app_a, "predecessor_id": legacy.id}
        instrument_id = actual_a.instrument_id
    r1, _ = accept(client, intent_a, "A-R1", provider_key="n:1")
    assert r1["relations"][0]["state"] == "paid"
    from test_close_readiness import _workflow_step

    step = _workflow_step(client, intent_a["reporting_month_id"], "future_payouts")
    assert step["state"] == "completed"
    assert "payout_reconciliation_changed" not in step["reason_codes"]
    with database.session_factory() as session:
        assert session.get(AppliedPayoutReconciliation, legacy.id).retired_request_id == "A-R1"
        account_b = create_account(session, name="Synthetic broker B", account_type="brokerage")
        for alias in ("7654321", "7654321-000"):
            confirm_mapping(
                session,
                provider="alfa_mybroker",
                subject_kind="account",
                provider_identity=alias,
                hermes_target_id=account_b.id,
            )
        scope_b = {"reporting_month_id": intent_a["reporting_month_id"], "account_id": account_b.id}
    xml_b = money_batch_xml(coupons=("1000.00",)).replace(b"1234567", b"7654321")
    filename_b = FILENAME.replace("1234567", "7654321")
    preview = _broker_month_preview(client, scope_b, xml_b, filename=filename_b)
    saved = _broker_month_apply(
        client, scope_b, preview, xml_b, filename=filename_b, request_id="base-b"
    )
    assert saved.status_code == 200, saved.text
    money_b = MoneyIntent(contract_version="broker_money_v1", base_request_id="base-b", **scope_b)
    with database.session_factory() as session:
        selected = _money_decide(session, money_b, [(filename_b, xml_b)], instrument_id)
        _money_apply(session, selected, [(filename_b, xml_b)], "money-b")
        actual_b = session.scalar(
            select(InvestmentCashFlow).where(InvestmentCashFlow.account_id == account_b.id)
        )
        app_b = create_provider_forecast(session, actual_b)
        intent_b = {
            **intent_a,
            **scope_b,
            "base_request_id": "base-b",
            "investment_cash_flow_id": actual_b.id,
            "applied_payout_id": app_b,
            "expected_cash_flow_id": None,
            "predecessor_id": None,
        }
    rb, _ = accept(client, intent_b, "B-R1", provider_key="n:1")
    assert rb["relations"][0]["state"] == "paid"
    assert client.get("/api/broker-months/A-R1").json()["relations"][0]["state"] == "paid"
    with database.session_factory() as session:
        a = session.get(AppliedPayoutReconciliation, r1["relations"][0]["id"])
        b = session.get(AppliedPayoutReconciliation, rb["relations"][0]["id"])
        assert a.provider_event_key != b.provider_event_key
        assert get_applied_payout_reconciliation(session, app_a) is None
        assert get_applied_payout_reconciliation(session, app_b) is None
        for action in (
            lambda: clear_applied_payout_reconciliation(session, app_a),
            lambda: set_applied_payout_reconciliation(
                session,
                app_a,
                expected_cash_flow_id=intent_a["expected_cash_flow_id"],
                counting_decision="keep_both",
            ),
        ):
            with pytest.raises(ValueError, match="actual_reconciliation_requires_review"):
                action()
        append_applied_payout_revision(
            session,
            app_b,
            revision_kind="revise",
            fetched_at=datetime.now(UTC),
            per_unit_amount="999.00",
        )
        session.commit()
    assert client.get("/api/broker-months/B-R1").json()["relations"][0]["state"] == "retired"
    assert client.get("/api/broker-months/A-R1").json()["relations"][0]["state"] == "paid"


@pytest.mark.parametrize(
    "narrative",
    [
        'Дивиденды за 2029 год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130.001 руб.).',
        'Дивиденды за 2029 год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130 руб.). возврат',
        "Дивиденды за 2029 год по акциям Synthetic stock (1-01-00000-A). (Удержан налог 130 руб.).",
        'Дивиденды\nза 2029 год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130 руб.).',
    ],
)
def test_dividend_exact_shape_does_not_expand_v1_or_accept_unsupported_text(database, narrative):
    from hermes_finance.domain.broker_money import MoneyIntent
    from hermes_finance.services.broker_money import preview_money

    xml = dividend_xml(narrative=narrative)
    _, intent, _, _ = dividend_setup(database, xml)
    before = database_bytes(database)
    with database.session_factory() as session:
        for selected in (
            intent,
            MoneyIntent.model_validate(
                {**intent.model_dump(), "contract_version": "broker_money_v1"}
            ),
        ):
            plan = preview_money(session, selected, [(FILENAME, xml)])
            assert all(o["candidate_kind"] != "dividend_paid_candidate" for o in plan["inventory"])
    assert database_bytes(database) == before


def test_dividend_v2_requires_identity_and_final_net_claims(database):
    from hermes_finance.domain.broker_money import MoneyIntentV2
    from hermes_finance.persistence import SecurityRegIsinMapping
    from hermes_finance.services.broker_money import preview_money

    xml = dividend_xml()
    _, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        intent = dividend_review(session, intent, xml, stock)
        data = intent.model_dump()
        data["money_decisions"][0]["dividend_claims"]["posted_amount_is_final_net_credit"] = False
        assert (
            "specific_final_net_dividend_claims_required"
            in preview_money(session, MoneyIntentV2.model_validate(data), [(FILENAME, xml)])[
                "blockers"
            ]
        )
        crosswalk = session.scalar(select(SecurityRegIsinMapping))
        session.delete(crosswalk)
        session.commit()
        assert (
            "exact_dividend_stock_identity_required"
            in preview_money(session, intent, [(FILENAME, xml)])["blockers"]
        )


@pytest.mark.parametrize("reverse", [False, True])
def test_dividend_complete_overlapping_originals_once_and_missing_union_zero_effect(
    database, reverse
):
    from test_statement_import_mybroker import apply, preview

    from hermes_finance.persistence import BrokerMoneyOccurrenceOwner
    from hermes_finance.services.broker_money import preview_money

    xml = dividend_xml()
    other = dividend_xml(stamp="11")
    assert other != xml
    if reverse:
        xml, other = other, xml
    _, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        apply(session, other, preview(session, other))
        originals = [(FILENAME, xml), (FILENAME, other)]
        before = database_bytes(database)
        assert (
            "overlapping_original_required"
            in preview_money(session, intent, originals[:1])["blockers"]
        )
        assert database_bytes(database) == before
        intent = dividend_review(session, intent, originals, stock)
        original_digest = preview_money(session, intent, originals)["confirmation_digest"]
        accepted = _money_apply(session, intent, originals, "dividend-overlap")
        assert len(accepted["targets"]) == 1
        assert len(list(session.scalars(select(InvestmentCashFlow)))) == 1
        assert len(list(session.scalars(select(BrokerMoneyOccurrenceOwner)))) == 2
        from hermes_finance.services.broker_money import apply_money

        replay = apply_money(
            session,
            intent,
            originals,
            confirmation_digest=original_digest,
            request_id="dividend-overlap",
        )
        assert replay["duplicate"]


def test_dividend_manual_gross_overlap_cannot_acquire_source_ownership(database):
    from hermes_finance.domain.broker_money import MoneyIntentV2
    from hermes_finance.services.broker_money import preview_money

    xml = dividend_xml()
    _, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        legacy = InvestmentCashFlow(
            reporting_month_id=intent.reporting_month_id,
            account_id=intent.account_id,
            instrument_id=stock,
            flow_type="dividend",
            event_date=date(2030, 1, 17),
            currency="RUB",
            gross_amount_kopecks=113000,
            tax_amount_kopecks=13000,
            commission_amount_kopecks=0,
            net_amount_kopecks=100000,
            amount_basis="gross_components",
            source="manual",
        )
        session.add(legacy)
        session.commit()
        requested = dividend_review(session, intent, xml, stock)
        assert (
            "legacy_payout_overlap"
            in preview_money(session, requested, [(FILENAME, xml)])["blockers"]
        )
        data = requested.model_dump()
        data["money_decisions"][0]["investment_cash_flow_id"] = legacy.id
        before = database_bytes(database)
        plan = preview_money(session, MoneyIntentV2.model_validate(data), [(FILENAME, xml)])
        assert not plan["can_apply"] and "dividend_legacy_target_unsupported" in plan["blockers"]
        assert database_bytes(database) == before


def test_dividend_separate_reversal_or_tax_cash_leg_blocks_native_creation(database):
    from hermes_finance.services.broker_money import preview_money

    xml = dividend_xml(("1000.00", "-130.00"))
    _, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        requested = dividend_review(session, intent, xml, stock)
        plan = preview_money(session, requested, [(FILENAME, xml)])
        assert (
            not plan["can_apply"]
            and "dividend_tax_or_reversal_cash_leg_unresolved" in plan["blockers"]
        )
        assert list(session.scalars(select(InvestmentCashFlow))) == []


@pytest.mark.parametrize("closed", [False, True])
def test_same_schema_physical_restore_invalidates_forms_preserves_rows_and_closed_calendar(
    database, settlement, tmp_path, closed
):
    import os
    import shutil
    from pathlib import Path

    from hermes_finance.services.reporting_months import close_reporting_month
    from hermes_finance.source_proof_file import file_incarnation

    client, intent = settlement
    r1, _ = accept(client, intent, "R1")
    next_intent, plan = reviewed(
        client, {**intent, "operation": "reaffirm", "predecessor_id": r1["relations"][0]["id"]}
    )
    if closed:
        with database.session_factory() as session:
            close_reporting_month(session, intent["reporting_month_id"])
    url = f"/api/payouts/calendar?month_id={intent['reporting_month_id']}&forecast_version=synthetic-v1"
    response = client.get(url)
    assert response.status_code == 200, response.text
    calendar = response.json()
    before = database_bytes(database)
    path = Path(database.engine.url.database)
    old_incarnation = file_incarnation(path)
    database.engine.dispose()
    import gc

    gc.collect()
    restored = tmp_path / "replacement-synthetic.db"
    shutil.copy2(path, restored)
    os.replace(restored, path)
    assert file_incarnation(path) != old_incarnation
    result = client.post(
        "/api/broker-months/payout-apply",
        json={
            **next_intent,
            "request_id": "old-form",
            "confirmation_digest": plan["confirmation_digest"],
        },
    )
    assert result.status_code == 409
    assert database_bytes(database) == before
    if closed:
        assert client.get(url).json() == calendar
    else:
        assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "stale"
        buckets = client.get(url).json()
        assert any(b["actual_attribution_coverage"] == "unknown" for b in buckets)
        assert all(not b["items"] for b in buckets)


@pytest.mark.parametrize("settlement", ["near"], indirect=True)
def test_distinct_exact_pair_future_and_consumers_preserve_unknown_subtotal(database, settlement):
    from hermes_finance.services.cash_flow_ladder import build_cash_flow_ladder
    from hermes_finance.services.forecast_passive_income import forecast_passive_income
    from hermes_finance.services.payout_calendar import INCOMPLETE_PAYOUT_WARNING
    from hermes_finance.services.scenario_frozen_base import materialize_frozen_base

    client, intent = settlement
    with database.session_factory() as session:
        assert (
            INCOMPLETE_PAYOUT_WARNING
            in forecast_passive_income(
                session, intent["reporting_month_id"], "synthetic-v1"
            ).warnings
        )
        assert (
            INCOMPLETE_PAYOUT_WARNING
            in build_cash_flow_ladder(
                session, intent["reporting_month_id"], forecast_version="synthetic-v1"
            ).warnings
        )
        assert (
            INCOMPLETE_PAYOUT_WARNING
            in materialize_frozen_base(
                session, intent["reporting_month_id"], forecast_version="synthetic-v1"
            ).payout_warnings
        )
    distinct = {**intent, "operation": "distinct"}
    first = client.post("/api/broker-months/payout-preview", json=distinct).json()
    distinct["claims"] = {
        "reference": "review",
        "independent_event_reference": "different-events",
        "settlement_basis_reference": "separate-identities",
        "review_context_digest": first["review_context_digest"],
        "actual_and_forecast_are_distinct": True,
        "actual_independent_event_key": "actual-event-A",
        "forecast_independent_event_key": "future-event-B",
    }
    plan = client.post("/api/broker-months/payout-preview", json=distinct).json()
    assert plan["can_apply"], plan["blockers"]
    payload = {
        **distinct,
        "request_id": "distinct",
        "confirmation_digest": plan["confirmation_digest"],
    }
    assert client.post("/api/broker-months/payout-apply", json=payload).status_code == 200
    obligations = client.get(
        f"/api/broker-months/payout-obligations?reporting_month_id={intent['reporting_month_id']}"
    ).json()
    assert obligations[0]["candidates"][0]["state"] == "future"
    with database.session_factory() as session:
        flow = session.get(ExpectedCashFlow, intent["expected_cash_flow_id"])
        flow.expected_net_amount_kopecks += 1
        session.commit()
        flow.expected_net_amount_kopecks -= 1
        session.commit()
    obligations = client.get(
        f"/api/broker-months/payout-obligations?reporting_month_id={intent['reporting_month_id']}"
    ).json()
    assert obligations[0]["candidates"][0]["state"] == "unresolved"


def test_reopen_changes_generation_without_rewriting_settlement_receipt(database, settlement):
    from hermes_finance.services.reporting_months import close_reporting_month

    client, intent = settlement
    r1, payload = accept(client, intent, "R1")
    with database.session_factory() as session:
        close_reporting_month(session, intent["reporting_month_id"])
        original = session.get(BrokerMonthApply, "R1").projection_json
    assert client.post(f"/api/months/{intent['reporting_month_id']}/reopen").status_code == 200
    get = client.get("/api/broker-months/R1").json()
    assert get["relations"][0]["state"] != "paid"
    before = database_bytes(database)
    assert client.post("/api/broker-months/payout-apply", json=payload).status_code == 200
    assert database_bytes(database) == before
    with database.session_factory() as session:
        assert session.get(BrokerMonthApply, "R1").projection_json == original


def test_dividend_v2_api_preserves_large_minor_string_without_js_number(database):
    xml = dividend_xml(("90071992547409.93",))
    client, intent, stock, _ = dividend_setup(database, xml)
    response = client.post(
        "/api/broker-months/preview",
        files=[("file", (FILENAME, xml, "application/xml"))],
        data={"intent": intent.model_dump_json()},
    )
    assert response.status_code == 200, response.text
    dividend = next(
        row
        for row in response.json()["inventory"]
        if row["candidate_kind"] == "dividend_paid_candidate"
    )
    assert dividend["amount_minor"] == "9007199254740993"
    with database.session_factory() as session:
        requested = dividend_review(session, intent, xml, stock)
        accepted = _money_apply(session, requested, [(FILENAME, xml)], "large-dividend")
        assert accepted["targets"][0]["facts"]["net_amount_kopecks"] == "9007199254740993"


@pytest.mark.parametrize("settlement", ["near"], indirect=True)
def test_retired_historical_forecast_outside_future_horizon_does_not_create_close_authority(
    database, settlement
):
    from hermes_finance.services.actual_payouts import close_blockers

    client, intent = settlement
    accept(client, intent, "R1")
    with database.session_factory() as session:
        forecast = session.get(ExpectedCashFlow, intent["expected_cash_flow_id"])
        forecast.expected_date = date(2029, 1, 1)
        session.commit()
        assert close_blockers(session, intent["reporting_month_id"]) == ()
    assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "retired"


def forecast_month(session, actual, *, year, month, snapshot_date):
    from types import SimpleNamespace

    from hermes_finance.services.positions import create_position_snapshot
    from hermes_finance.services.reporting_months import create_reporting_month

    period = create_reporting_month(session, year=year, month=month, snapshot_date=snapshot_date)
    create_position_snapshot(
        session,
        reporting_month_id=period.id,
        account_id=actual.account_id,
        instrument_id=actual.instrument_id,
        quantity="1",
        average_cost_per_unit="1000",
        market_price_per_unit="1000",
        price_date=snapshot_date,
    )
    return SimpleNamespace(
        reporting_month_id=period.id,
        account_id=actual.account_id,
        instrument_id=actual.instrument_id,
        flow_type=actual.flow_type,
    )


@pytest.mark.parametrize("settlement", ["near"], indirect=True)
def test_canonical_copies_draft_close_reopen_and_older_closed_projection(database, settlement):
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        reopen_reporting_month,
    )

    client, intent = settlement
    with database.session_factory() as session:
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        anchor = create_provider_forecast(session, actual)
        copied = forecast_month(
            session, actual, year=2029, month=12, snapshot_date=date(2029, 12, 31)
        )
        copy_id = create_provider_forecast(session, copied)
        historical = forecast_month(
            session, actual, year=2029, month=11, snapshot_date=date(2029, 11, 30)
        )
        historical_id = create_provider_forecast(session, historical)
        close_reporting_month(session, historical.reporting_month_id)
        intent = {**intent, "applied_payout_id": anchor}

    def calendar(month_id):
        result = client.get(
            f"/api/payouts/calendar?month_id={month_id}&forecast_version=synthetic-v1"
        )
        assert result.status_code == 200, result.text
        return result.json()

    historical_before = calendar(historical.reporting_month_id)
    assert historical_before[0]["items"][0]["source_id"] == historical_id
    r1, _ = accept(client, intent, "R1", provider_key="n:1")
    assert {r["id"] for r in r1["accepted"]["paid_forecasts"] if r["kind"] == "app"} == {
        anchor,
        copy_id,
    }
    assert calendar(intent["reporting_month_id"]) == []
    assert calendar(copied.reporting_month_id) == []
    assert calendar(historical.reporting_month_id) == historical_before
    with database.session_factory() as session:
        close_reporting_month(session, copied.reporting_month_id)
    assert calendar(copied.reporting_month_id) == []
    assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "paid"
    retirement = {
        **intent,
        "operation": "retire",
        "predecessor_id": r1["relations"][0]["id"],
    }
    before = database_bytes(database)
    refused = client.post("/api/broker-months/payout-preview", json=retirement).json()
    assert not refused["can_apply"]
    assert "payout_involved_scope_requires_reopen" in refused["blockers"]
    assert database_bytes(database) == before
    with database.session_factory() as session:
        reopen_reporting_month(session, copied.reporting_month_id)
    assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "stale"
    r3, _ = accept(
        client,
        {**retirement, "operation": "reaffirm"},
        "R3",
        provider_key="n:1",
    )
    assert r3["relations"][0]["state"] == "paid"
    assert calendar(historical.reporting_month_id) == historical_before
    with database.session_factory() as session:
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        unrelated = forecast_month(
            session, actual, year=2030, month=3, snapshot_date=date(2030, 3, 31)
        )
        create_provider_forecast(
            session, unrelated, identity="n:99", payment_date=date(2030, 12, 31)
        )
        close_reporting_month(session, unrelated.reporting_month_id)
        reopen_reporting_month(session, unrelated.reporting_month_id)
    assert client.get("/api/broker-months/R3").json()["relations"][0]["state"] == "paid"


def test_selected_forecast_month_reopen_before_first_link_invalidates_preview(database, settlement):
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        reopen_reporting_month,
    )

    client, intent = settlement
    with database.session_factory() as session:
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        selected = forecast_month(
            session, actual, year=2030, month=2, snapshot_date=date(2030, 2, 28)
        )
        forecast = session.get(ExpectedCashFlow, intent["expected_cash_flow_id"])
        forecast.reporting_month_id = selected.reporting_month_id
        forecast.expected_date = date(2030, 10, 15)
        session.commit()
    requested, plan = reviewed(client, intent)
    with database.session_factory() as session:
        close_reporting_month(session, selected.reporting_month_id)
        reopen_reporting_month(session, selected.reporting_month_id)
    before = database_bytes(database)
    stale = client.post(
        "/api/broker-months/payout-apply",
        json={
            **requested,
            "request_id": "obsolete-before-first-link",
            "confirmation_digest": plan["confirmation_digest"],
        },
    )
    assert stale.status_code == 409, stale.text
    assert database_bytes(database) == before
    accepted, _ = accept(client, intent, "fresh-after-reopen")
    assert accepted["relations"][0]["state"] == "paid"


@pytest.mark.parametrize("operation", ["link", "retire"])
@pytest.mark.parametrize("settlement", ["near"], indirect=True)
def test_reserved_close_race_cannot_commit_closed_unresolved_settlement(
    database, settlement, operation
):
    from threading import Barrier

    from hermes_finance.domain.payout_reconciliation import PayoutIntent
    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services import actual_payouts
    from hermes_finance.services.reporting_months import CloseGuardError, close_reporting_month
    from hermes_finance.statement_import.mybroker import MyBrokerError

    client, intent = settlement
    if operation == "retire":
        r1, _ = accept(client, intent, "R1")
        intent = {**intent, "operation": "retire", "predecessor_id": r1["relations"][0]["id"]}
    requested, plan = reviewed(client, intent)
    barrier = Barrier(2)

    def write(kind):
        with database.session_factory() as session:
            barrier.wait(timeout=10)
            try:
                if kind == "close":
                    return close_reporting_month(session, intent["reporting_month_id"]).status
                return actual_payouts.apply(
                    session,
                    PayoutIntent.model_validate(requested),
                    request_id="racing-settlement",
                    confirmation_digest=plan["confirmation_digest"],
                )
            except (CloseGuardError, MyBrokerError) as error:
                return getattr(error, "code", str(error))

    with ThreadPoolExecutor(max_workers=2) as pool:
        closed, result = list(pool.map(write, ["close", "settlement"]))
    with database.session_factory() as session:
        rows = list(session.scalars(select(AppliedPayoutReconciliation)))
        assert len(rows) == 1
        if closed == "closed":
            assert rows[0].retired_request_id is None
            assert session.get(ReportingMonth, intent["reporting_month_id"]).status == "closed"
            assert actual_payouts.future_states(session, intent["reporting_month_id"]) == {
                ("ecf", intent["expected_cash_flow_id"]): "paid"
            }
            if operation == "retire":
                assert "payout_involved_scope_requires_reopen" in result
                assert session.get(BrokerMonthApply, "racing-settlement") is None
        else:
            assert isinstance(result, dict)
            assert "source_payout_" in closed
            assert session.get(ReportingMonth, intent["reporting_month_id"]).status == "draft"
            assert (rows[0].retired_request_id is not None) == (operation == "retire")


@pytest.mark.parametrize(
    "narrative,tax",
    [
        (
            'Дивиденды за 2029 г. по акциям ПАО "Synthetic stock".  (1-01-00000-A). (Удержан налог 0 руб.).',
            "0",
        ),
        (
            'Дивиденды за 2029 год по акциям ПАО "Synthetic stock" (1-01-00000-A). (Удержан налог 130,25 руб.). Эмитентом уменьшена НОБ',
            "13025",
        ),
    ],
)
def test_dividend_supported_punctuation_zero_and_nob_are_annotation_only(database, narrative, tax):
    xml = dividend_xml(narrative=narrative)
    _, intent, stock, _ = dividend_setup(database, xml)
    with database.session_factory() as session:
        requested = dividend_review(session, intent, xml, stock)
        result = _money_apply(session, requested, [(FILENAME, xml)], "dividend-narrow-grammar")
        assert len(result["targets"]) == 1
        proof = json.loads(session.get(BrokerMonthApply, "dividend-narrow-grammar").projection_json)
        assert proof["dividend_evidence"][0]["observed_tax_kopecks"] == tax
        assert proof["dividend_evidence"][0]["tax_role"] == "annotation_only"
        actual = session.get(InvestmentCashFlow, result["targets"][0]["target_id"])
        assert actual.net_amount_kopecks == 100000
        assert actual.tax_amount_kopecks is None and actual.gross_amount_kopecks is None


@pytest.mark.parametrize("action", ["archive", "cancel", "dismiss"])
def test_actual_forecast_writers_retire_provenance_and_delete_api_retains_history(
    database, settlement, action
):
    from hermes_finance.persistence import AppliedProviderPayout, BrokerMoneyOccurrenceOwner
    from hermes_finance.services.applied_payouts import append_applied_payout_revision
    from hermes_finance.services.broker_money import material
    from hermes_finance.services.payout_provenance_lifecycle import archive_payout

    client, intent = settlement
    with database.session_factory() as session:
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        app_id = create_provider_forecast(session, actual)
        monetary_before = material(actual)
        owners_before = [material(r) for r in session.scalars(select(BrokerMoneyOccurrenceOwner))]
    intent = {**intent, "applied_payout_id": app_id}
    r1, _ = accept(client, intent, "R1", provider_key="n:1")

    def refused_delete():
        before = database_bytes(database)
        response = client.delete(f"/api/expected-flows/{intent['expected_cash_flow_id']}")
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "retained_by_actual_reconciliation"
        assert database_bytes(database) == before

    refused_delete()
    with database.session_factory() as session:
        original_receipt = session.get(BrokerMonthApply, "R1").projection_json
        if action == "archive":
            archive_payout(session, session.get(AppliedProviderPayout, app_id), "2030-01")
        else:
            append_applied_payout_revision(
                session,
                app_id,
                revision_kind=action,
                lifecycle="cancelled" if action == "cancel" else "dismissed",
                fetched_at=datetime.now(UTC),
            )
        session.commit()
        link = session.get(AppliedPayoutReconciliation, r1["relations"][0]["id"])
        assert link.retired_request_id is not None and link.archived_from_period is None
        assert link.applied_payout_id == app_id
        assert link.expected_cash_flow_id == intent["expected_cash_flow_id"]
        assert session.get(BrokerMonthApply, "R1").projection_json == original_receipt
        assert (
            material(session.get(InvestmentCashFlow, intent["investment_cash_flow_id"]))
            == monetary_before
        )
        assert [
            material(r) for r in session.scalars(select(BrokerMoneyOccurrenceOwner))
        ] == owners_before
    refused_delete()
    assert client.get("/api/broker-months/R1").json()["relations"][0]["state"] == "retired"


def test_future_and_close_without_competitors_do_not_scan_unrelated_economic_proofs(
    database, settlement, monkeypatch
):
    from hermes_finance.services import actual_payouts
    from hermes_finance.services.reporting_months import create_reporting_month

    _, intent = settlement  # The persisted forecast is outside the +/-3-day candidate window.

    def unexpected(*args, **kwargs):
        raise AssertionError("no competitor requires no settlement proof validation")

    monkeypatch.setattr(actual_payouts, "proof_blockers", unexpected)
    monkeypatch.setattr(actual_payouts.broker_months, "_readiness", unexpected)
    with database.session_factory() as session:
        manual = create_reporting_month(
            session, year=2031, month=2, snapshot_date=date(2031, 2, 28)
        )
        assert actual_payouts.future_states(session, manual.id) == {}
        assert actual_payouts.future_states(session, intent["reporting_month_id"]) == {}
        assert actual_payouts.close_blockers(session, intent["reporting_month_id"]) == ()


@pytest.mark.parametrize("settlement", ["near"], indirect=True)
def test_cross_month_reclose_never_revives_stale_paid_projection(database, settlement):
    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services.actual_payouts import future_states
    from hermes_finance.services.reporting_months import (
        close_hard_guards,
        close_reporting_month,
        reopen_reporting_month,
    )

    client, intent = settlement
    with database.session_factory() as session:
        session.delete(session.get(ExpectedCashFlow, intent["expected_cash_flow_id"]))
        session.commit()
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        forecast_scope = forecast_month(
            session, actual, year=2029, month=12, snapshot_date=date(2029, 12, 31)
        )
        app_id = create_provider_forecast(session, forecast_scope)
    month_b = forecast_scope.reporting_month_id
    intent = {**intent, "applied_payout_id": app_id, "expected_cash_flow_id": None}
    r1, _ = accept(client, intent, "cross-R1", provider_key="n:1")
    calendar_url = f"/api/payouts/calendar?month_id={month_b}&forecast_version=synthetic-v1"

    def check(expected):
        before = database_bytes(database)
        get = client.get("/api/broker-months/cross-R1").json()
        assert get["relations"][0]["state"] == ("paid" if expected == "paid" else "stale")
        assert get["accepted"] == r1["accepted"]
        with database.session_factory() as session:
            assert future_states(session, month_b) == {("app", app_id): expected}
        calendar = client.get(calendar_url)
        assert calendar.status_code == 200, calendar.text
        if expected == "paid":
            assert calendar.json() == []
        else:
            assert calendar.json() and all(not b["items"] for b in calendar.json())
            assert all(b["actual_attribution_coverage"] == "unknown" for b in calendar.json())
        assert database_bytes(database) == before

    check("paid")
    with database.session_factory() as session:
        assert close_hard_guards(session.get(ReportingMonth, month_b), session) == ()
        close_reporting_month(session, month_b)
    check("paid")  # Normal Close retains the reviewed projection.
    with database.session_factory() as session:
        reopen_reporting_month(session, month_b)
    check("unresolved")
    with database.session_factory() as session:
        # Actual A does not add a global HARD block to manual-only month B.
        assert close_hard_guards(session.get(ReportingMonth, month_b), session) == ()
        close_reporting_month(session, month_b)
    check("unresolved")  # A second Close must never silently reaffirm R1.
    with database.session_factory() as session:
        reopen_reporting_month(session, month_b)
    r3, _ = accept(
        client,
        {**intent, "operation": "reaffirm", "predecessor_id": r1["relations"][0]["id"]},
        "cross-R3",
        provider_key="n:1",
    )
    assert r3["relations"][0]["state"] == "paid"
    with database.session_factory() as session:
        close_reporting_month(session, month_b)
        assert future_states(session, month_b) == {("app", app_id): "paid"}
    assert client.get(calendar_url).json() == []
    old = client.get("/api/broker-months/cross-R1").json()
    assert old["accepted"] == r1["accepted"]
    assert old["relations"][0]["retired_request_id"] == "cross-R3"


@pytest.mark.parametrize("cross_month", [False, True])
def test_app_only_month_workflow_uses_actual_lineage_not_null_ecf(
    database, settlement, cross_month
):
    from test_close_readiness import _workflow_step

    from hermes_finance.persistence import AppliedProviderPayout, ReportingMonth
    from hermes_finance.services.month_close_workflow import _future_payout_dependencies

    client, intent = settlement
    with database.session_factory() as session:
        session.delete(session.get(ExpectedCashFlow, intent["expected_cash_flow_id"]))
        session.commit()
        actual = session.get(InvestmentCashFlow, intent["investment_cash_flow_id"])
        target = (
            forecast_month(session, actual, year=2029, month=12, snapshot_date=date(2029, 12, 31))
            if cross_month
            else actual
        )
        app_id = create_provider_forecast(session, target)
        review_month_id = target.reporting_month_id
    intent = {**intent, "applied_payout_id": app_id, "expected_cash_flow_id": None}

    def workflow(warning):
        before = database_bytes(database)
        with database.session_factory() as session:
            counts = _future_payout_dependencies(
                session,
                session.get(ReportingMonth, review_month_id),
                [session.get(AppliedProviderPayout, app_id)],
            )
            assert counts.position_missing == counts.quantity_changed == counts.mapping_changed == 0
            assert bool(counts.reconciliation_changed) is warning
            assert counts.affected_payouts == int(warning)
        step = _workflow_step(client, review_month_id, "future_payouts")
        assert ("payout_reconciliation_changed" in step["reason_codes"]) is warning
        assert step["state"] == ("warning" if warning else "completed")
        assert step["affects_close"] is False
        assert database_bytes(database) == before

    workflow(False)  # No ECF/actual link is not itself a reconciliation problem.
    r1, _ = accept(client, intent, "month-R1", provider_key="n:1")
    workflow(False)
    if cross_month:
        from hermes_finance.services.reporting_months import (
            close_reporting_month,
            reopen_reporting_month,
        )

        with database.session_factory() as session:
            close_reporting_month(session, review_month_id)
            reopen_reporting_month(session, review_month_id)
        assert client.get("/api/broker-months/month-R1").json()["relations"][0]["state"] == "stale"
        workflow(True)
    r3, _ = accept(
        client,
        {**intent, "operation": "reaffirm", "predecessor_id": r1["relations"][0]["id"]},
        "month-R3",
        provider_key="n:1",
    )
    workflow(False)  # Retained R1 history is not a legacy forecast link.
    accept(
        client,
        {**intent, "operation": "retire", "predecessor_id": r3["relations"][0]["id"]},
        "month-R4",
        provider_key="n:1",
    )
    workflow(True)  # The now-unresolved actual competitor still needs review.
    r5, _ = accept(
        client,
        {**intent, "operation": "reaffirm", "predecessor_id": r3["relations"][0]["id"]},
        "month-R5",
        provider_key="n:1",
    )
    assert r5["relations"][0]["state"] == "paid"
    workflow(False)
