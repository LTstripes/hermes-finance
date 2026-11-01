"""Synthetic evidence enrichment of an existing SOURCE; no reimport."""

import json
from copy import deepcopy
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from test_statement_import_mybroker import FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_endpoints import (
    _broker_month_apply,
    _broker_month_preview,
    _broker_month_setup,
    draft_structure_xml,
)

from hermes_finance.main import create_app


def typed_bond_intake_xml(*, sell=False, copies=1):
    root = ET.fromstring(draft_structure_xml())
    table = root.find("{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2")
    table.set("Textbox118", "⁸ В случае сделки по облигации, сумма включает НКД.")
    table.set("Textbox73", "\r\nКомиссия\r\nбанка")
    table.set("Textbox64", "Сумма сделки \r\nв валюте расчетов⁸")
    trades = table.find("{MyBroker}Details_Collection")
    template = deepcopy(trades[0])
    trades.clear()
    rows = root.find(".//{MyBroker}Trades2//{MyBroker}rn_Collection")
    money_template = deepcopy(rows[0])
    rows.clear()
    direction = 1 if sell else -1
    for i in range(copies):
        trade = deepcopy(template)
        native = str(10000000001 + i)
        trade.set("trade_no", native + "\r\n" + str(2000000001 + i))
        trade.set("p_name", "Synthetic bond")
        trade.set("qty", "-2" if sell else "2")
        trade.set("summ_nkd", "3.50")
        trade.set("bank_tax", "2.45")
        trades.append(trade)
        for operation, description, amount in (
            ("Расчеты по сделке " + native, "Synthetic principal", str(direction * 996.50)),
            ("НКД по сделке", "c Synthetic bond", str(direction * 3.50)),
            ("Комиссия по сделке " + native, "Synthetic fee", "-2.45"),
        ):
            row = deepcopy(money_template)
            row.find("{MyBroker}oper_type").set("oper_type", operation)
            row.find(".//{MyBroker}comment").set("comment", description)
            row.find(".//{MyBroker}p_code[@volume]").set("volume", amount)
            rows.append(row)
    for row in list(rows)[:-1]:
        for tag, key in (
            ("Textbox83", "money_volume"),
            ("Textbox84", "all_volume"),
            ("Textbox93", "debet_volume"),
        ):
            row.find(".//{MyBroker}" + tag).set(key, "")
    security = root.find(".//{MyBroker}Details[@ISIN1]")
    security.set("active_type", "Облигации")
    security.set("active_name", "Synthetic bond")
    security.set("income_rest", str(10 + (2 * copies if sell else -2 * copies)))
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    opening = Decimal(400 if sell else 400 + copies * 1000)
    closing = opening + copies * (direction * Decimal(1000) - Decimal("2.45"))
    cash.set("income_rest", str(opening))
    cash.set("real_rest", str(closing))
    return ET.tostring(root)


@pytest.mark.parametrize("sell,copies", [(False, 1), (False, 2), (True, 1), (True, 2)])
def test_typed_bond_basis_preserves_complete_equivalent_sets(sell, copies):
    from hermes_finance.statement_import.broker_intake_evidence import read_intake_evidence

    evidence = read_intake_evidence(typed_bond_intake_xml(sell=sell, copies=copies), FILENAME)
    assert evidence["issues"] == []
    assert len(evidence["nkd_cohorts"]) == 1
    cohort = evidence["nkd_cohorts"][0]
    assert len(cohort["occurrences"]) == len(cohort["trade_identities"]) == copies
    assert cohort["signed_nkd_minor"] == (350 if sell else -350)
    assert all("trade_identity" not in row for row in cohort["occurrences"])


@pytest.mark.parametrize("mutation", ["missing_caption", "extra_nkd", "hidden_identity"])
def test_typed_source_evidence_never_guesses_missing_basis_or_occurrences(mutation):
    from hermes_finance.statement_import.broker_intake_evidence import read_intake_evidence

    root = ET.fromstring(typed_bond_intake_xml(copies=2))
    if mutation == "missing_caption":
        root.find("{MyBroker}Trades/{MyBroker}Report/{MyBroker}Tablix2").set(
            "Textbox118", "Unknown"
        )
    elif mutation == "extra_nkd":
        rows = root.find(".//{MyBroker}Trades2//{MyBroker}rn_Collection")
        rows.insert(0, deepcopy(rows[1]))
    else:
        root.find(".//{MyBroker}Details1").set("acc_code", "hidden")
    evidence = read_intake_evidence(ET.tostring(root), FILENAME)
    assert evidence["issues"]


@pytest.mark.parametrize("sell,copies", [(False, 1), (False, 2), (True, 2)])
def test_typed_statement_money_reuses_trade_writer_and_complete_group_readback(
    database, sell, copies
):
    from hermes_finance.persistence import BrokerMonthApply, Instrument
    from hermes_finance.services import broker_money
    from hermes_finance.services.broker_statement_money import plan_statement_money

    intent = _broker_month_setup(database)
    with database.session_factory() as session:
        session.get(Instrument, 1).instrument_type = "bond"
        session.commit()
    client = TestClient(create_app(database=database))
    raw = typed_bond_intake_xml(sell=sell, copies=copies)
    requested = intent
    preview = _broker_month_preview(client, requested, raw)
    assert preview["can_apply"], preview["conflicts"]
    response = _broker_month_apply(client, requested, preview, raw)
    assert response.status_code == 200, response.text
    with database.session_factory() as session:
        base = session.get(BrokerMonthApply, "synthetic-batch")
        money_intent, plan = plan_statement_money(session, base, (FILENAME, raw), payouts=[])
        broker_money.stage_money(
            session,
            money_intent,
            plan,
            base,
            request_id="typed-money",
            fingerprint="a" * 64,
            confirmation_digest=plan["confirmation_digest"],
        )
        session.commit()
        result = broker_money.read_money(session, "typed-money")
        assert not any(
            r in result["exceptions"]
            for r in [
                "commission_basis_unresolved",
                "settlement_principal_unresolved",
                "money_semantics_unsupported",
            ]
        ), result["exceptions"]
        assert len(result["targets"]) == copies
        proof = result["accepted"]
        assert len(proof["statement_groups"][0]["occurrences"]) == copies
        assert all(r["role"] == "trade" for r in proof["occurrences"])
        assert all(
            t["cash_proof"]["nkd_leg"]["direction"] == ("credit" if sell else "debit")
            for t in proof["targets"]
        )
        assert all(
            r["ordinal"] not in {o["ordinal"] for o in proof["statement_groups"][0]["occurrences"]}
            for r in proof["occurrences"]
        )


def add_synthetic_posting(raw, operation, narrative, amount, day="2030-01-20"):
    root = ET.fromstring(raw)
    collection = root.find(".//{MyBroker}Trades2//{MyBroker}settlement_date_Collection")
    group = deepcopy(collection[0])
    group.set("settlement_date", day + "T00:00:00")
    rows = group.find("{MyBroker}rn_Collection")
    row = deepcopy(rows[-1])
    rows.clear()
    row.set("last_update", day + "T15:00:00")
    row.find("{MyBroker}oper_type").set("oper_type", operation)
    row.find(".//{MyBroker}comment").set("comment", narrative)
    row.find(".//{MyBroker}p_code[@volume]").set("volume", amount)
    rows.append(row)
    collection.append(group)
    cash = root.find(".//{MyBroker}Details[@active_name='RUB']")
    cash.set("real_rest", str(Decimal(cash.get("real_rest")) + Decimal(amount)))
    return ET.tostring(root)


def existing_statement(database, *, gift=False):
    from test_statement_import_mybroker_metadata import metadata_xml

    from hermes_finance.persistence import BrokerMonthApply, Instrument
    from hermes_finance.services import broker_money
    from hermes_finance.services.statement_payout_adapter import reviewed_payout_intent

    scope = _broker_month_setup(database)
    with database.session_factory() as session:
        session.get(Instrument, 1).instrument_type = "bond"
        session.commit()
    raw = add_synthetic_posting(
        typed_bond_intake_xml(sell=True, copies=2),
        "Перевод",
        'погашение купона 4B02-00-12345-A-001P (Биржевые облигации АО "Synthetic") д.ф.20.01.30',
        "10.00",
        "2030-01-21",
    )
    raw = add_synthetic_posting(
        raw,
        "Комиссия",
        "Банка по исполнению расчетов на ФР (МБ и СПБ) за 22.01.2030 (ставка по тарифу 0,02%).",
        "-1.25",
        "2030-01-22",
    )
    if gift:
        raw = add_synthetic_posting(
            raw,
            "Перевод",
            "Выплата по поручению клиента в рамках Акция в подарок в соответствии с Правилами проведения акции.",
            "17.23",
            "2030-01-23",
        )
    raw = metadata_xml(raw)
    client = TestClient(create_app(database=database))
    source = _broker_month_apply(client, scope, _broker_month_preview(client, scope, raw), raw)
    assert source.status_code == 200, source.text
    source = source.json()
    with database.session_factory() as session:
        base = session.get(BrokerMonthApply, "synthetic-batch")
        row = next(
            r
            for r in source["accepted"]["document"]["money"]
            if r["date"] == "2030-01-21" and Decimal(r["amount"]) == Decimal("10.00")
        )
        facts = [
            {
                "document_sha256": source["accepted"]["document"]["document_sha256"],
                "ordinal": row["ordinal"],
                "kind": "coupon",
                "instrument_id": 1,
                "isin": session.get(Instrument, 1).isin,
                "net_kopecks": 1000,
                "date": row["date"],
                "pdf_sha256": "f" * 64,
            }
        ]
        intent, plan = reviewed_payout_intent(
            session,
            base_request_id=base.request_id,
            originals=[(FILENAME, raw)],
            facts=facts,
            review_reference="synthetic-original-review",
        )
        broker_money.apply_money(
            session,
            intent,
            [(FILENAME, raw)],
            request_id="existing-net-payout",
            confirmation_digest=plan["confirmation_digest"],
        )
    return client, scope, raw, source


def accept_bookkeeping(client, scope, raw, source):
    from test_statement_import_mybroker_metadata import section_apply, section_preview

    intent = {
        "contract_version": "mybroker-section-disposition-v1",
        **scope,
        "base_request_id": "synthetic-batch",
        "import_id": source["import_id"],
        "sections": [{"section": s} for s in ["4_Transfers", "5_UFSR", "source_bookkeeping"]],
    }
    preview = section_preview(client, intent, raw)
    assert preview.status_code == 200, preview.text
    assert preview.json()["can_apply"], preview.json()["exceptions"]
    saved = section_apply(client, intent, raw, preview.json())
    assert saved.status_code == 200, saved.text
    assert all(s["disposition_status"] == "effective" for s in saved.json()["sections"])
    return intent, preview.json()


@pytest.mark.parametrize("gift", [False, True])
def test_existing_source_enrichment_preserves_payout_cash_and_facts_and_discloses_bonus(
    database, gift
):
    from sqlalchemy import select

    from hermes_finance.persistence import (
        BrokerMonthApply,
        CashBalance,
        ExecutedTrade,
        InvestmentCashFlow,
        MyBrokerImport,
        PositionSnapshot,
    )
    from hermes_finance.services.broker_money import material

    client, scope, raw, source = existing_statement(database, gift=gift)
    models = [CashBalance, ExecutedTrade, InvestmentCashFlow, MyBrokerImport, PositionSnapshot]
    with database.session_factory() as session:
        before = {
            model.__tablename__: [material(r) for r in session.scalars(select(model))]
            for model in models
        }
        source_before = material(session.get(BrokerMonthApply, "synthetic-batch"))
    accept_bookkeeping(client, scope, raw, source)
    request = {"base_request_id": "synthetic-batch"}
    files = {"file": (FILENAME, raw, "application/xml")}
    preview = client.post(
        "/api/broker-months/statement-evidence/preview",
        files=files,
        data={"intent": json.dumps(request)},
    )
    assert preview.status_code == 200, preview.text
    confirmation = {
        **request,
        "request_id": "trade-fee-proof",
        "confirmation_digest": preview.json()["confirmation_digest"],
    }
    for attempt in range(2):
        saved = client.post(
            "/api/broker-months/statement-evidence/apply",
            files=files,
            data={"confirmation": json.dumps(confirmation)},
        )
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["duplicate"] == bool(attempt)
        assert all(t["effective"] for t in result["targets"])
        assert [t["role"] for t in result["targets"]].count("trade") == 2
        assert [t["role"] for t in result["targets"]].count("account_fee") == 1
        assert result["exceptions"] == (["money_semantics_unsupported"] if gift else [])
    month = scope["reporting_month_id"]
    context = client.get(f"/api/months/{month}/draft-payouts").json()
    assert context["eligible_positions"] == (0 if gift else 1)
    assert client.get(f"/api/months/{month}/close-readiness").json()["can_close"] == (not gift)
    assert all(
        t["effective"]
        for t in client.get("/api/broker-months/existing-net-payout").json()["targets"]
    )
    with database.session_factory() as session:
        assert {
            model.__tablename__: [material(r) for r in session.scalars(select(model))]
            for model in models
        } == before
        assert material(session.get(BrokerMonthApply, "synthetic-batch")) == source_before


@pytest.mark.parametrize("case", ["stale_aba", "rollback", "wrong_original", "client_amount"])
def test_statement_evidence_rejects_changed_context_or_client_facts_and_rolls_back(
    database, monkeypatch, case
):
    from sqlalchemy import select
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import CashBalance
    from hermes_finance.services import broker_money
    from hermes_finance.statement_import.mybroker import MyBrokerError

    client, scope, raw, source = existing_statement(database)
    accept_bookkeeping(client, scope, raw, source)
    request = {"base_request_id": "synthetic-batch"}
    files = {"file": (FILENAME, raw, "application/xml")}
    plan = client.post(
        "/api/broker-months/statement-evidence/preview",
        files=files,
        data={"intent": json.dumps(request)},
    ).json()
    confirmation = {
        **request,
        "request_id": "guarded-evidence",
        "confirmation_digest": plan["confirmation_digest"],
    }
    if case == "stale_aba":
        with database.session_factory() as session:
            cash = session.scalar(select(CashBalance))
            amount = cash.amount_kopecks
            cash.amount_kopecks += 1
            session.commit()
            cash.amount_kopecks = amount
            session.commit()
    elif case == "rollback":
        stage = broker_money.stage_money

        def fail_after_stage(*args, **kwargs):
            stage(*args, **kwargs)
            raise MyBrokerError("synthetic_stage_failure")

        monkeypatch.setattr(broker_money, "stage_money", fail_after_stage)
    elif case == "wrong_original":
        files = {
            "file": (
                FILENAME,
                raw.replace(b'bank_tax="2.45"', b'bank_tax="2.46"'),
                "application/xml",
            )
        }
    else:
        confirmation["amount_kopecks"] = 0
    before = _all_month_tables(database)
    response = client.post(
        "/api/broker-months/statement-evidence/apply",
        files=files,
        data={"confirmation": json.dumps(confirmation)},
    )
    assert response.status_code == (422 if case == "client_amount" else 409), response.text
    if case == "stale_aba":
        assert "statement_evidence_preview_stale" in response.text
    assert _all_month_tables(database) == before


@pytest.mark.parametrize("case", ["inactive_account", "wrong_account_type", "changed_projection"])
def test_fresh_statement_evidence_requires_unchanged_active_source(database, case):
    from sqlalchemy import select
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.persistence import Account, CashBalance

    client, scope, raw, source = existing_statement(database)
    with database.session_factory() as session:
        if case == "changed_projection":
            session.scalar(select(CashBalance)).amount_kopecks += 1
        else:
            account = session.get(Account, scope["account_id"])
            if case == "inactive_account":
                account.status = "frozen"
            else:
                account.account_type = "deposit"
        session.commit()
    before = _all_month_tables(database)
    response = client.post(
        "/api/broker-months/statement-evidence/preview",
        files={"file": (FILENAME, raw, "application/xml")},
        data={"intent": json.dumps({"base_request_id": "synthetic-batch"})},
    )
    assert response.status_code == 422, response.text
    assert (
        "source_projection_changed"
        if case == "changed_projection"
        else "active_brokerage_account_required"
    ) in response.text
    assert _all_month_tables(database) == before


def test_statement_evidence_confirmation_is_bound_to_physical_database(database):
    from test_statement_import_mybroker_endpoints import _all_month_tables

    from hermes_finance.database import create_database
    from hermes_finance.services import backups, broker_money

    client, scope, raw, source = existing_statement(database)
    accept_bookkeeping(client, scope, raw, source)
    request = {"base_request_id": "synthetic-batch"}
    files = {"file": (FILENAME, raw, "application/xml")}
    plan = client.post(
        "/api/broker-months/statement-evidence/preview",
        files=files,
        data={"intent": json.dumps(request)},
    ).json()
    snapshot = backups.create_backup(database)
    clone = create_database(backups.backup_directory(database) / snapshot.name)
    try:
        with database.session_factory() as original, clone.session_factory() as copied:
            assert broker_money._dependencies(original) == broker_money._dependencies(copied)
        copied_client = TestClient(create_app(database=clone))
        copied_plan = copied_client.post(
            "/api/broker-months/statement-evidence/preview",
            files=files,
            data={"intent": json.dumps(request)},
        ).json()
        assert plan["physical_incarnation"] != copied_plan["physical_incarnation"]
        assert plan["confirmation_digest"] != copied_plan["confirmation_digest"]
        before = _all_month_tables(clone)
        response = copied_client.post(
            "/api/broker-months/statement-evidence/apply",
            files=files,
            data={
                "confirmation": json.dumps(
                    {
                        **request,
                        "request_id": "old-physical-preview",
                        "confirmation_digest": plan["confirmation_digest"],
                    }
                )
            },
        )
        assert response.status_code == 409 and "statement_evidence_preview_stale" in response.text
        assert _all_month_tables(clone) == before
    finally:
        clone.engine.dispose()
