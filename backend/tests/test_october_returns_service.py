"""Synthetic current Money proof, source-period isolation and UI/export parity."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select
from test_broker_statement_evidence import (
    accept_bookkeeping,
    bonus_review,
    existing_statement,
)
from test_source_monthly_returns_service import (
    proof_confirm,
    proof_preview,
    read,
    save_cancellation_long,
    save_service_month,
    snapshot,
)
from test_statement_import_mybroker import ACCOUNT, FILENAME
from test_statement_import_mybroker import database as database
from test_statement_import_mybroker_preflight import original, saved_investment_preview

from hermes_finance.persistence import Instrument, SourceMoneyClassification
from hermes_finance.services import (
    ai_source_returns,
    returns_overall,
    returns_view,
    source_intake,
)
from hermes_finance.services import source_investment_proofs as proofs
from hermes_finance.services.ai_financial_review import (
    assemble_ai_financial_review,
    validate_ai_financial_review,
)
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.services.source_monthly_returns import read_monthly_returns


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    value = source_returns_database_factory(tmp_path)
    yield value
    value.engine.dispose()


def test_outside_period_old_overlap_and_stale_custody_proof_do_not_block_october(db):
    _, _, preview = proof_preview(db)
    proof_confirm(db, preview)
    save_service_month(db, 10)
    before = snapshot(db)
    result = read(db)
    assert result.source_proof["status"] == "stale"
    october = next(row for row in result.months if row.result.closing_date == date(2030, 10, 31))
    assert october.result.growth_kopecks is not None
    assert october.result.modified_dietz_return is not None
    assert any(row.result.growth_kopecks is None for row in result.months if row is not october)
    assert snapshot(db) == before


def _accept_money(client, source, raw, *, confirmed):
    request = {"base_request_id": "synthetic-batch"}
    if confirmed:
        request["broker_bonuses"] = [bonus_review(source)]
    files = {"file": (FILENAME, raw, "application/xml")}
    preview = client.post(
        "/api/broker-months/statement-evidence/preview",
        files=files,
        data={"intent": json.dumps(request)},
    )
    assert preview.status_code == 200, preview.text
    saved = client.post(
        "/api/broker-months/statement-evidence/apply",
        files=files,
        data={
            "confirmation": json.dumps(
                {
                    **request,
                    "request_id": "returns-money",
                    "confirmation_digest": preview.json()["confirmation_digest"],
                }
            )
        },
    )
    assert saved.status_code == 200, saved.text
    assert all(t["effective"] for t in saved.json()["targets"])


def test_bonus_source_binding_compares_parser_facts_and_rejects_mismatches(database):
    from hermes_finance.services.source_return_evidence import bound_import

    _, _, raw, source = existing_statement(database, gift=True)
    with database.session_factory() as session:
        saved = source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="bonus-binding"
        )
    before = snapshot(database)
    with database.session_factory() as session:
        view = source_intake.read_intake(session, saved["intake_id"])
        financial_source = bound_import(session, view)
        assert financial_source is not None
        assert financial_source.id == source["import_id"]
        # Accepted S1 adds derived fields which the immutable intake does not have.
        stored = json.loads(financial_source.normalized_json)
        assert "source_accounts" in stored and "source_accounts" not in view["document"]
        assert "cash_legs" in stored["trades"][0]
        assert "cash_legs" not in view["document"]["trades"][0]
        for field, value in (
            ("parser", "different-parser"),
            ("covered_to", "2030-02-28"),
            ("filename_account", "different-account"),
        ):
            changed = deepcopy(view)
            changed["document"][field] = value
            assert bound_import(session, changed) is None
        changed = deepcopy(view)
        bonus = next(r for r in changed["document"]["money"] if r["date"] == "2030-01-23")
        bonus["amount"] = "17.24"
        assert bound_import(session, changed) is None
        assert bound_import(session, {**view, "covered_to": "2030-02-28"}) is None
        assert bound_import(session, {**view, "document_sha256": "0" * 64}) is None
    assert snapshot(database) == before


@pytest.mark.parametrize("confirmed,stale", [(False, False), (True, False), (True, True)])
def test_only_current_exact_cash_gift_is_external_without_new_cash(database, confirmed, stale):
    client, scope, raw, source = existing_statement(database, gift=True)
    with database.session_factory() as session:
        saved = source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="returns-original"
        )
    # Reproduce a saved legacy UNKNOWN; a fresh Save uses the newer promo default.
    with database.session_factory() as session:
        bonus = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == saved["intake_id"],
                SourceMoneyClassification.date == date(2030, 1, 23),
            )
        )
        assert bonus.classification == "external_deposit"
        bonus.classification = "unknown"
        session.commit()
    accept_bookkeeping(client, scope, raw, source)
    _accept_money(client, source, raw, confirmed=confirmed)
    if stale:
        with database.session_factory() as session:
            session.get(Instrument, 1).name = "Synthetic changed metadata"
            session.commit()
    before = snapshot(database)
    with database.session_factory() as session:
        intake = source_intake.read_intake(session, saved["intake_id"])
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        ordinary = returns_view.read_overview(
            session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 1, 31)
        )
        exported = ai_source_returns.source_returns_section(
            session, as_of_date=date(2030, 1, 31), reporting_period=(2030, 1)
        )
    row = monthly.months[0]
    bonus = next(r for r in intake["money_classifications"] if str(r["date"]) == "2030-01-23")
    assert bonus["classification"] == "unknown"  # read never writes the classification
    eligible = confirmed and not stale
    assert len(monthly.flows) == int(eligible)
    if eligible:
        gift = monthly.flows[0]
        assert (gift.classification, gift.included, gift.status) == (
            "external_gift",
            True,
            "confirmed",
        )
        assert (gift.event_date, gift.amount_kopecks) == (date(2030, 1, 23), 1723)
        assert row.result.contributions_kopecks == 1723
        assert row.result.growth_kopecks == (
            row.result.closing_kopecks - row.result.opening_kopecks - 1723
        )
        # Gift on January23 has eight days' weight; real sale settlements in
        # this fixture are cash conversion, not additional contributions.
        with localcontext() as context:
            context.prec = 60
            expected_rate = Decimal(row.result.growth_kopecks * 31) / Decimal(
                row.result.opening_kopecks * 31 + 1723 * 8
            )
        assert row.result.modified_dietz_return == expected_rate
    assert (row.result.growth_kopecks is not None) == eligible
    assert (row.result.modified_dietz_return is not None) == eligible
    codes = {gap.code for gap in monthly.gaps}
    assert ("broker_gift_external_flow" in codes) == eligible
    assert ("unrecognized_money" in codes) == (not eligible)
    expected = None if row.result.growth_kopecks is None else str(row.result.growth_kopecks)
    assert ordinary["selected"]["pnl"]["value"] == expected
    interval = exported["data"]["accounts"][0]["intervals"][0]
    value = interval["account"]["metrics"]["pnl"]["value"]
    assert (value is None) == (not eligible)
    if eligible:
        assert interval["account"]["contributions"] == {"amount": "17.23", "currency": "RUB"}
        assert interval["account"]["external_flows"] == [
            {
                "date": "2030-01-23",
                "amount": {"amount": "17.23", "currency": "RUB"},
                "status": "confirmed",
            }
        ]
    assert snapshot(database) == before
    if eligible:
        from hermes_finance.persistence import MyBrokerImport
        from hermes_finance.services.source_return_evidence import effective_bonus

        with database.session_factory() as session:
            financial_source = session.get(MyBrokerImport, source["import_id"])
            raw_bonus = next(
                r for r in source["accepted"]["document"]["money"] if r["date"] == "2030-01-23"
            )
            assert effective_bonus(session, financial_source, raw_bonus)
            assert not effective_bonus(session, None, raw_bonus)
            assert not effective_bonus(
                session, financial_source, {**raw_bonus, "ordinal": raw_bonus["ordinal"] + 100}
            )
            assert not effective_bonus(session, financial_source, {**raw_bonus, "amount": "17.24"})
            from hermes_finance.domain.broker_statement_provisional import (
                ProvisionalAssumptions,
                ProvisionalChoice,
            )

            reference = monthly.flows[0].source_references[0]
            _, _, _, ordinal, fingerprint = reference.split(":")
            excluded = ProvisionalAssumptions(
                schedule_mode="explicit_empty",
                selections=(
                    ProvisionalChoice(
                        requirement_id=f"candidate:{ordinal}:{fingerprint[:12]}",
                        source_references=(reference,),
                        choice="exclude_from_external_schedule",
                    ),
                ),
            )
            authoritative = read_monthly_returns(
                session, source_account=ACCOUNT, assumptions={saved["intake_id"]: excluded}
            )
            assert authoritative.flows[0].included
            assert authoritative.months[0].result.contributions_kopecks == 1723
        assert snapshot(database) == before


@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("user_choice", [None, "unknown", "external_deposit", "fee"])
def test_cash_gift_resolves_unknown_but_preserves_other_economic_choices(
    database, confirmed, user_choice
):
    from hermes_finance.services.source_money_classifications import choose_classification

    client, scope, raw, source = existing_statement(database, gift=True)
    with database.session_factory() as session:
        saved = source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="promo-original"
        )
        intake = source_intake.read_intake(session, saved["intake_id"])
        bonus = next(r for r in intake["money_classifications"] if r["date"] == date(2030, 1, 23))
        assert bonus["classification"] == "external_deposit"
        if user_choice is not None:
            choose_classification(
                session, saved["intake_id"], bonus["source_reference"], user_choice
            )
    accept_bookkeeping(client, scope, raw, source)
    _accept_money(client, source, raw, confirmed=confirmed)
    before = snapshot(database)
    with database.session_factory() as session:
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        intake = source_intake.read_intake(session, saved["intake_id"])
    row = monthly.months[0].result
    eligible = confirmed and user_choice != "fee"
    expected_classification = user_choice or "external_deposit"
    bonus = next(r for r in intake["money_classifications"] if r["date"] == date(2030, 1, 23))
    assert bonus["classification"] == expected_classification
    assert ("broker_gift_external_flow" in {g.code for g in monthly.gaps}) == eligible
    if user_choice == "unknown" and not eligible:
        assert monthly.flows == ()
        assert row.contributions_kopecks is row.growth_kopecks is None
    elif user_choice == "fee":
        assert monthly.flows == ()
        assert row.contributions_kopecks == 0
        assert row.growth_kopecks == row.closing_kopecks - row.opening_kopecks
    else:
        assert len(monthly.flows) == 1
        assert monthly.flows[0].amount_kopecks == 1723
        assert row.contributions_kopecks == 1723
        assert monthly.flows[0].classification == (
            "external_gift" if eligible else "external_deposit"
        )
        assert row.growth_kopecks == row.closing_kopecks - row.opening_kopecks - 1723
    assert snapshot(database) == before


def test_overlapping_cash_gift_occurrences_count_once_without_borrowing_proof(database):
    client, scope, raw, source = existing_statement(database, gift=True)
    with database.session_factory() as session:
        source_intake.save_intake(session, document=raw, filename=FILENAME, request_id="gift-first")
        repeated = source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="gift-first"
        )
        assert repeated["duplicate"]
        # Different immutable original with the same economic occurrences.
        root = ET.fromstring(raw)
        ET.indent(root)
        overlapping = ET.tostring(root, encoding="utf-8")
        assert overlapping != raw
        source_intake.save_intake(
            session, document=overlapping, filename=FILENAME, request_id="gift-overlap"
        )
    accept_bookkeeping(client, scope, raw, source)
    _accept_money(client, source, raw, confirmed=True)
    before = snapshot(database)
    with database.session_factory() as session:
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
    assert len(monthly.flows) == 1
    gift = monthly.flows[0]
    assert (gift.classification, gift.amount_kopecks, gift.status) == (
        "external_gift",
        1723,
        "confirmed",
    )
    assert len(gift.source_references) == 2
    assert snapshot(database) == before


def test_in_kind_gift_without_cash_or_valuation_stays_unresolved(db):
    save_cancellation_long(
        db,
        mutate=lambda root, row: (
            row.set("qty", "1.0000000000"),
            row.set("comment_new", "Synthetic promotional security gift, no cash or valuation"),
        ),
    )
    before = snapshot(db)
    monthly = read(db)
    assert monthly.flows == ()
    assert all(row.result.growth_kopecks is None for row in monthly.months)
    assert "4_Transfers_unsupported" in {gap.code for gap in monthly.gaps}
    assert "broker_gift_external_flow" not in {gap.code for gap in monthly.gaps}
    assert snapshot(db) == before


@pytest.mark.parametrize("change", ["dependency", "withdrawn"])
def test_saved_investment_gift_proof_currentness_and_ai(database, monkeypatch, change):
    from test_statement_import_mybroker_preflight import investment_case

    from hermes_finance.services import broker_money, mybroker_preflight, source_report_preview

    client, scope, raw, source = existing_statement(database, gift=True)
    with database.session_factory() as session:
        saved = source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="gift-investment-source"
        )
        bonus = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == saved["intake_id"],
                SourceMoneyClassification.date == date(2030, 1, 23),
            )
        )
        bonus.classification, bonus.origin, bonus.status = "unknown", "user_choice", "confirmed"
        session.commit()
    accept_bookkeeping(client, scope, raw, source)
    _accept_money(client, source, raw, confirmed=True)
    _, _, _, report, _ = investment_case()
    monkeypatch.setattr(source_report_preview, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(source_report_preview, "parse_investment_report", lambda *_: report)
    with database.session_factory() as session:
        result = mybroker_preflight.preview_batch(
            session, originals=[(FILENAME, raw)], income_report=b"synthetic pdf"
        )["source_return_preview"]
        persistence = result["persistence"]
        assert persistence["available"], persistence
        proofs.confirm(
            session,
            form_token=persistence["form_token"],
            preview_digest=persistence["preview_digest"],
            request_id="gift-investment-proof",
        )
    before = snapshot(database)
    with database.session_factory() as session:
        saved_proof = proofs.read_reports(session, source_account=ACCOUNT)[0]
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        ordinary = returns_view.read_overview(
            session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 1, 31)
        )
        export = ai_source_returns.source_returns_section(
            session, as_of_date=date(2030, 1, 31), reporting_period=(2030, 1)
        )
    assert saved_proof["status"] == "current"
    interval = saved_proof["interval"]
    assert interval["contributions_kopecks"] == "1723"
    assert interval["pnl"]["value"] is not None
    assert monthly.months[0].result.growth_kopecks == int(interval["pnl"]["value"])
    assert ordinary["selected"]["pnl"]["value"] == interval["pnl"]["value"]
    selected = export["data"]["accounts"][0]["intervals"][0]["account"]
    assert selected["contributions"]["amount"] == "17.23"
    assert Decimal(selected["metrics"]["pnl"]["value"]["amount"]) == (
        Decimal(interval["pnl"]["value"]) / 100
    )
    assert snapshot(database) == before
    # A changed dependency invalidates the exact gift proof and saved investment proof.
    if change == "dependency":
        with database.session_factory() as session:
            session.get(Instrument, 1).name = "Changed synthetic gift proof dependency"
            session.commit()
    else:
        # Model absence of the previously present exact proof head without
        # changing any receipt or financial row.
        monkeypatch.setattr(broker_money, "latest_proofs", lambda session: {})
    with database.session_factory() as session:
        stale = proofs.read_reports(session, source_account=ACCOUNT)[0]
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        stale_export = ai_source_returns.source_returns_section(
            session, as_of_date=date(2030, 1, 31), reporting_period=(2030, 1)
        )
    assert stale["status"] == "stale"
    assert "investment_proof_dependencies_changed" in stale["reason_codes"]
    assert monthly.months[0].result.growth_kopecks is None
    assert stale_export["data"]["accounts"][0]["intervals"][0]["account"] is None


def test_saved_history_new_month_replay_and_ai_export_share_one_outer_result(database, monkeypatch):
    # Save the continuation before issuing the historical proof so its full
    # currentness contract is exercised without pretending an old proof survived.
    filename, raw = original(
        2,
        opening="10",
        closing="10",
        opening_value="1100",
        closing_value="1200",
        cash_open="990",
        cash_close="990",
    )
    with database.session_factory() as session:
        source_intake.save_intake(session, document=raw, filename=filename, request_id="new-month")
        create_reporting_month(session, year=2030, month=2, snapshot_date=date(2030, 2, 28))
    preview = saved_investment_preview(database, monkeypatch)["persistence"]
    with database.session_factory() as session:
        proofs.confirm(
            session,
            form_token=preview["form_token"],
            preview_digest=preview["preview_digest"],
            request_id="history-proof",
        )
    before = snapshot(database)
    with database.session_factory() as session:
        view = returns_view.read_overview(
            session, scope=f"source:{ACCOUNT}", start=date(2029, 12, 31), end=date(2030, 2, 28)
        )
        exported = ai_source_returns.source_returns_section(
            session, as_of_date=date(2030, 2, 28), reporting_period=(2030, 2)
        )
        overall = returns_overall.read_overall(session)
        context = returns_view.read_context(session)
        report = assemble_ai_financial_review(
            session, generated_at=datetime(2030, 3, 1, tzinfo=UTC), evaluated_on=date(2030, 3, 1)
        )
        validate_ai_financial_review(report)
    account = exported["data"]["accounts"][0]
    whole = next(i for i in account["intervals"] if i["ref"] == account["all_history_ref"])
    assert whole["closing_date"] == "2030-02-28"
    assert view["all_history"]["period"]["end"] == date(2030, 2, 28)
    assert context["source_history_periods"][f"source:{ACCOUNT}"]["end"] == date(2030, 2, 28)
    assert view["selected"]["pnl"]["value"] == view["all_history"]["pnl"]["value"]
    assert view["all_history"]["pnl"]["value"] is not None
    assert whole["account"]["metrics"]["pnl"]["value"]["amount"] == "190.00"
    assert overall["source_accounts"][0]["result"]["pnl"]["value"] == "19000"
    assert snapshot(database) == before
    with database.session_factory() as session:
        replay = source_intake.save_intake(
            session, document=raw, filename=filename, request_id="new-month"
        )
    assert replay["duplicate"]
    assert snapshot(database) == before
