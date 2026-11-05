"""Synthetic current Money proof, source-period isolation and UI/export parity."""

import json
from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from types import SimpleNamespace
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
from test_statement_import_mybroker import ACCOUNT, FILENAME, ISIN
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
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_monthly_returns import read_monthly_result, read_monthly_returns


@pytest.fixture
def db(tmp_path, source_returns_database_factory):
    value = source_returns_database_factory(tmp_path)
    yield value
    value.engine.dispose()


def test_outside_period_old_overlap_preserves_custody_and_does_not_block_october(db):
    _, _, preview = proof_preview(db)
    proof_confirm(db, preview)
    save_service_month(db, 10)
    before = snapshot(db)
    result = read(db)
    assert result.source_proof["status"] == "current"
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


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "stale",
        "wrong_account",
        "wrong_row",
        "user_choice",
        "conflicting_user_choice",
        "multiple_owners",
        "multi_row",
        "unbound",
        "no_receipt",
        "wrong_date",
        "wrong_amount",
        "wrong_currency",
        "wrong_kind",
        "wrong_role",
        "skipped_instrument",
    ],
)
def test_existing_payout_receipt_requires_exact_current_source_and_account(monkeypatch, case):
    from hermes_finance.services import (
        broker_money,
        broker_money_ownership,
        mybroker_dispositions,
        source_return_evidence,
    )
    from hermes_finance.services.source_instrument_events import payout_attribution
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.statement_import.mybroker import digest

    row = {"ordinal": 3, "date": "2030-01-23", "amount": "17.23", "currency": "RUB"}
    view = {"id": 9}
    saved = {
        "classification": "coupon",
        "origin": "default_rule",
        "instrument_link_status": "unresolved_no_match",
        "instrument_id": None,
        "source_reference": source_reference(view["id"], row),
        "operation": "coupon",
        "narrative": "synthetic",
    }
    occurrence = {
        "import_id": 4,
        "section": "money",
        "ordinal": 3,
        "role": "coupon",
        "target_id": 11,
        "row_fingerprint": digest(row),
    }
    owner = {
        "key": [4, "money", 3],
        "role": "coupon",
        "target_id": 11,
        "row_fingerprint": digest(row),
    }
    receipt = SimpleNamespace(account_id=7, reporting_month_id=8, request_id="synthetic-receipt")
    facts = {
        "instrument_id": "1",
        "flow_type": "coupon",
        "account_id": "7",
        "reporting_month_id": "8",
        "currency": "RUB",
        "event_date": "2030-01-23",
        "net_amount_kopecks": "1723",
    }
    proof = {"occurrences": [occurrence]}
    target = {"role": "coupon", "target_id": 11, "facts": facts}
    instrument = SimpleNamespace(isin=ISIN, instrument_type="bond", currency="RUB")
    resolver = SimpleNamespace(instruments={1: instrument})
    month = SimpleNamespace(period_start=date(2030, 1, 1), period_end=date(2030, 1, 31))
    session = SimpleNamespace(get=lambda *_: month, info={})
    monkeypatch.setattr(
        source_return_evidence,
        "bound_import",
        lambda *_: None if case == "unbound" else SimpleNamespace(id=4),
    )
    monkeypatch.setattr(
        broker_money_ownership,
        "owners",
        lambda *_: [owner, owner] if case == "multiple_owners" else [owner],
    )
    monkeypatch.setattr(
        broker_money,
        "latest_proofs",
        lambda *_: {} if case == "no_receipt" else {("coupon", 11): (receipt, proof, target)},
    )
    monkeypatch.setattr(
        broker_money, "proof_blockers", lambda *_: ["stale"] if case == "stale" else []
    )
    monkeypatch.setattr(
        mybroker_dispositions,
        "resolve",
        lambda *_: (
            [{"isin": ISIN, "effective_state": "accepted"}] if case == "skipped_instrument" else []
        ),
    )
    if case == "wrong_account":
        facts["account_id"] = "99"
    elif case == "wrong_row":
        occurrence["row_fingerprint"] = "different"
    elif case == "user_choice":
        saved["origin"] = "user_choice"
    elif case == "conflicting_user_choice":
        saved["origin"] = "user_choice"
        saved["classification"] = "dividend"
    elif case == "multi_row":
        proof["occurrences"].append({**occurrence, "ordinal": 4})
    elif case == "wrong_date":
        facts["event_date"] = "2030-01-24"
    elif case == "wrong_amount":
        facts["net_amount_kopecks"] = "1724"
    elif case == "wrong_currency":
        facts["currency"] = "USD"
    elif case == "wrong_kind":
        instrument.instrument_type = "stock"
    elif case == "wrong_role":
        facts["flow_type"] = "dividend"
    result = payout_attribution(saved, resolver, {}, session=session, view=view, raw=row)
    if case in {"valid", "user_choice"}:
        assert result == (ISIN, "accepted_money", ())
    else:
        assert result == (None, "persisted_link", ("payout_link_unresolved_no_match",))


def test_receipt_source_is_not_borrowed_across_overlapping_originals():
    from hermes_finance.services.source_return_evidence import payout_source_unambiguous

    first = {"id": 1, "covered_from": "2030-01-01", "covered_to": "2030-01-31"}
    overlap = {"id": 2, "covered_from": "2030-01-15", "covered_to": "2030-02-15"}
    assert payout_source_unambiguous([first, overlap], first, date(2030, 1, 14))
    assert not payout_source_unambiguous([first, overlap], first, date(2030, 1, 15))
    assert not payout_source_unambiguous([first, overlap], overlap, date(2030, 1, 15))
    assert payout_source_unambiguous([first, overlap], overlap, date(2030, 2, 1))


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "duplicate",
        "duplicate_update",
        "missing",
        "different_row",
        "user_choice",
        "conflicting_user_choice",
        "excluded_second_source",
        "two_proofs",
        "no_proof",
    ],
)
def test_overlap_receipt_requires_one_identical_unambiguous_group(monkeypatch, case):
    from hermes_finance.services import source_return_evidence as evidence
    from hermes_finance.services.source_money_classifications import source_reference

    row = {
        "ordinal": 1,
        "date": "2030-01-23",
        "amount": "17.23",
        "currency": "RUB",
        "source_account": "synthetic",
    }
    views = []
    for source_id in (1, 2):
        raw = dict(row)
        saved = {
            "classification": "coupon",
            "origin": "default_rule",
            "instrument_link_status": "not_parsed",
            "instrument_id": None,
            "operation": "coupon",
            "narrative": "synthetic",
            "source_reference": source_reference(source_id, raw),
        }
        views.append(
            {
                "id": source_id,
                "covered_from": "2030-01-01",
                "covered_to": "2030-01-31",
                "document": {"money": [raw]},
                "money_classifications": [saved],
            }
        )
    if case == "duplicate":
        views[1]["document"]["money"].append({**row, "ordinal": 2})
    elif case == "duplicate_update":
        views[1]["document"]["money"].append({**row, "ordinal": 2, "last_update": "later"})
    elif case == "missing":
        views[1]["document"]["money"].clear()
    elif case == "different_row":
        views[1]["document"]["money"][0]["amount"] = "17.24"
    elif case == "user_choice":
        views[1]["money_classifications"][0]["origin"] = "user_choice"
    elif case == "conflicting_user_choice":
        views[1]["money_classifications"][0]["origin"] = "user_choice"
        views[1]["money_classifications"][0]["classification"] = "dividend"
    monkeypatch.setattr(
        evidence,
        "effective_payout_match",
        lambda _s, v, *_args, **_kwargs: (
            (ISIN, f"receipt-{v['id']}", "coupon", 11, frozenset())
            if case != "no_proof" and (v["id"] == 1 or case == "two_proofs")
            else None
        ),
    )
    monkeypatch.setattr(evidence, "bound_import", lambda *_: None)
    monkeypatch.setattr(
        evidence,
        "_source_allows_payout",
        lambda _s, v, _isin: not (case == "excluded_second_source" and v["id"] == 2),
    )
    result = evidence.effective_overlapping_payout(
        None,
        views,
        views[0],
        views[0]["document"]["money"][0],
        views[0]["money_classifications"][0],
        None,
    )
    assert result == (ISIN if case in {"valid", "user_choice"} else None)


@pytest.mark.parametrize("confirmed", [False, True])
def test_cash_gift_keeps_account_flow_without_blocking_instrument_evidence(database, confirmed):
    client, scope, raw, source = existing_statement(database, gift=True)
    with database.session_factory() as session:
        saved = source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="gift-instrument-read"
        )
        bonus = session.scalar(
            select(SourceMoneyClassification).where(
                SourceMoneyClassification.intake_id == saved["intake_id"],
                SourceMoneyClassification.date == date(2030, 1, 23),
            )
        )
        bonus.classification = "unknown"
        session.commit()
    accept_bookkeeping(client, scope, raw, source)
    _accept_money(client, source, raw, confirmed=confirmed)
    before = snapshot(database)
    with database.session_factory() as session:
        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        result = read_instrument_returns(
            session,
            source_account=ACCOUNT,
            isin=ISIN,
            opening_date=date(2029, 12, 31),
            closing_date=date(2030, 1, 31),
            include_monthly_history=False,
        )
    analysis = next(row.analysis for row in result.instruments if row.isin == ISIN)
    if confirmed:
        assert len(monthly.flows) == 1
        assert monthly.flows[0].classification == "external_gift"
        assert monthly.flows[0].amount_kopecks == 1723
        row = monthly.months[0].result
        assert row.contributions_kopecks == 1723
        assert row.growth_kopecks == row.closing_kopecks - row.opening_kopecks - 1723
        assert "broker_gift_external_flow" in {gap.code for gap in monthly.gaps}
        assert "broker_gift_external_flow" not in {gap.code for gap in result.gaps}
        assert "broker_gift_external_flow" not in analysis.reason_codes
        assert not any(event.classification == "external_gift" for event in analysis.events)
    else:
        assert monthly.flows == ()
        assert "unrecognized_money" in {gap.code for gap in monthly.gaps}
        assert "unrecognized_money" in analysis.reason_codes
    assert snapshot(database) == before


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
        limited = read_monthly_result(
            session,
            source_account=ACCOUNT,
            opening_date=date(2029, 12, 31),
            closing_date=date(2030, 1, 31),
        )
        intake = source_intake.read_intake(session, saved["intake_id"])
    row = monthly.months[0].result
    assert limited == row
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


def test_old_investment_proof_becomes_stale_when_gift_proof_is_added(database, monkeypatch):
    from test_statement_import_mybroker_preflight import investment_case

    from hermes_finance.services import mybroker_preflight, source_report_preview

    # Isolate gift dependency currentness from v8's intentional rejection of
    # legacy unallocated instrument-cost semantics.
    client, scope, raw, source = existing_statement(
        database, gift=True, fee_narrative="account maintenance"
    )
    with database.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=FILENAME, request_id="old-proof-gift-source"
        )
    accept_bookkeeping(client, scope, raw, source)
    _, _, _, report, _ = investment_case()
    monkeypatch.setattr(source_report_preview, "extract_pdf_text_layer", lambda _: None)
    monkeypatch.setattr(source_report_preview, "parse_investment_report", lambda *_: report)
    with monkeypatch.context() as old:
        old.setattr(proofs, "SEMANTICS_REVISION", "source_investment_semantics_v2")
        with database.session_factory() as session:
            preview = mybroker_preflight.preview_batch(
                session, originals=[(FILENAME, raw)], income_report=b"synthetic pdf"
            )["source_return_preview"]["persistence"]
            assert preview["available"], preview
            proofs.confirm(
                session,
                form_token=preview["form_token"],
                preview_digest=preview["preview_digest"],
                request_id="old-proof-before-gift",
            )
    with database.session_factory() as session:
        assert proofs.read_reports(session, source_account=ACCOUNT)[0]["status"] == "current"
    _accept_money(client, source, raw, confirmed=True)
    with database.session_factory() as session:
        result = proofs.read_reports(session, source_account=ACCOUNT)[0]
    assert result["status"] == "stale"
    assert result["reason_codes"] == ["investment_proof_dependencies_changed"]


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


@pytest.mark.parametrize("different_description", [False, True])
def test_real_multi_original_receipt_projects_one_confirmed_payout_without_writes(
    database, monkeypatch, different_description
):
    from copy import deepcopy

    from test_source_monthly_returns_service import snapshot
    from test_statement_import_mybroker import apply, preview
    from test_statement_import_mybroker_endpoints import (
        _money_apply,
        _money_decide,
        _money_setup,
        money_batch_xml,
    )

    from hermes_finance.services import source_intake, source_return_evidence
    from hermes_finance.services.source_instrument_events import read_events
    from hermes_finance.services.source_instrument_returns import _identities
    from hermes_finance.services.source_monthly_returns import (
        _selected_sources,
        source_read_snapshot,
    )

    xml = money_batch_xml(coupons=("1000.00",))
    other = money_batch_xml(coupons=("1000.00",), stamp="11")
    _, _, intent, bond, _ = _money_setup(database, xml)
    with database.session_factory() as session:
        apply(session, other, preview(session, other))
        originals = [(FILENAME, xml), (FILENAME, other)]
        intent = _money_decide(session, intent, originals, bond, funding=False)
        _money_apply(session, intent, originals, "multi-source-payout")
    for index, raw_document in enumerate((xml, other)):
        with database.session_factory() as session:
            source_intake.save_intake(
                session,
                document=raw_document,
                filename=FILENAME,
                request_id=f"multi-source-intake-{index}",
            )
    if different_description:
        from hermes_finance.persistence import SourceMoneyClassification

        with database.session_factory() as session:
            choice = session.scalar(
                select(SourceMoneyClassification).where(
                    SourceMoneyClassification.intake_id == 2,
                    SourceMoneyClassification.classification == "coupon",
                )
            )
            assert choice is not None
            choice.narrative += " synthetic alternate saved description"
            session.commit()
    before = snapshot(database)
    with database.session_factory() as session, source_read_snapshot(session):
        selected, native = _selected_sources(session, ACCOUNT)
        assert native is not None and len(native) == 1
        views = [view for _, view, error in selected if view and not error]
        events, _ = read_events(session, views, _identities(views), next(iter(native)), [])
        payouts = [event for event in events if event.kind == "COUPON" and event.counted]
        assert len(payouts) == 1
        assert payouts[0].classification_status == "confirmed"
        assert len(payouts[0].source_references) == 2
        from hermes_finance.services.source_monthly_returns import read_monthly_returns

        monthly = read_monthly_returns(session, source_account=ACCOUNT)
        assert sum(m.coupons_kopecks or 0 for m in monthly.months) == 100000
        missing = deepcopy(views)
        coupon_ordinal = next(
            i
            for i, row in enumerate(missing[1]["money_classifications"])
            if row["classification"] == "coupon"
        )
        missing[1]["document"]["money"].pop(coupon_ordinal)
        missing_events, _ = read_events(
            session, missing, _identities(missing), next(iter(native)), []
        )
        assert not any(event.kind == "COUPON" and event.counted for event in missing_events)
        changed = deepcopy(views)
        changed[1]["document"]["money"][coupon_ordinal]["amount"] = "1000.01"
        changed_events, _ = read_events(
            session, changed, _identities(changed), next(iter(native)), []
        )
        assert not any(event.kind == "COUPON" and event.counted for event in changed_events)
        actual_match = source_return_evidence.effective_payout_match

        def conflicting_target(*args, **kwargs):
            result = actual_match(*args, **kwargs)
            if result and args[1]["id"] == views[1]["id"]:
                return (result[0], result[1], result[2], result[3] + 1, result[4])
            return result

        with monkeypatch.context() as patch:
            patch.setattr(source_return_evidence, "effective_payout_match", conflicting_target)
            conflict_events, _ = read_events(
                session, views, _identities(views), next(iter(native)), []
            )
            assert not any(event.kind == "COUPON" and event.counted for event in conflict_events)
        actual_allows = source_return_evidence._source_allows_payout
        with monkeypatch.context() as patch:
            patch.setattr(
                source_return_evidence,
                "_source_allows_payout",
                lambda s, v, isin: v["id"] != views[1]["id"] and actual_allows(s, v, isin),
            )
            excluded_events, _ = read_events(
                session, views, _identities(views), next(iter(native)), []
            )
            assert not any(event.kind == "COUPON" and event.counted for event in excluded_events)
    assert snapshot(database) == before


@pytest.mark.parametrize(
    "case", ["descriptions", "two_payments", "same_source_cohort", "stale_member"]
)
def test_canonical_payout_groups_preserve_exact_cohort_and_multiplicity(monkeypatch, case):
    from types import SimpleNamespace

    from hermes_finance.services import source_return_evidence as evidence
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.statement_import.mybroker import digest

    rows = [
        {
            "ordinal": i,
            "date": "2030-01-17",
            "amount": "100.00",
            "currency": "RUB",
            "source_account": "synthetic",
            "narrative": "same",
        }
        for i in range(2)
    ]
    if case == "descriptions":
        rows[1]["narrative"] = "another source description"
    one_source = case in {"two_payments", "same_source_cohort"}
    views = [
        {
            "id": i + 1,
            "covered_from": "2030-01-01",
            "covered_to": "2030-01-31",
            "document": {"money": rows if one_source else [rows[i]]},
            "money_classifications": [],
        }
        for i in range(1 if one_source else 2)
    ]
    members = []
    for view in views:
        for row in view["document"]["money"]:
            ref = source_reference(view["id"], row)
            view["money_classifications"].append(
                {"source_reference": ref, "classification": "coupon"}
            )
            members.append((ref, (view["id"], "money", row["ordinal"], digest(row))))
    cohort = frozenset(key for _, key in members)
    monkeypatch.setattr(evidence, "bound_import", lambda _, v: SimpleNamespace(id=v["id"]))

    def match(_, view, row, saved, resolver, **kwargs):
        key = (view["id"], "money", row["ordinal"], digest(row))
        if case == "stale_member" and view["id"] == 2:
            return None
        return (
            ISIN,
            "current-receipt",
            "coupon",
            row["ordinal"] if case == "two_payments" else 11,
            frozenset({key}) if case == "two_payments" else cohort,
        )

    monkeypatch.setattr(evidence, "effective_payout_match", match)
    result = evidence.canonical_payout_groups(None, views, object())
    if case in {"same_source_cohort", "stale_member"}:
        assert result == {}
    else:
        assert set(result) == {ref for ref, _ in members}
        assert len(set(result.values())) == (2 if case == "two_payments" else 1)
