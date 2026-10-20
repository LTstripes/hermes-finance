"""Synthetic upload persistence, choices, and monthly classification consumers."""

from collections import Counter
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_source_monthly_returns_service import db as db
from test_source_monthly_returns_service import read, save_month, snapshot
from test_statement_import_mybroker import ACCOUNT

from hermes_finance.main import create_app
from hermes_finance.persistence import SourceMoneyClassification
from hermes_finance.services import source_intake
from hermes_finance.services.source_money_classifications import default_classification


def saved_rows(db, intake_id):
    with db.session_factory() as session:
        return list(
            session.scalars(
                select(SourceMoneyClassification)
                .where(SourceMoneyClassification.intake_id == intake_id)
                .order_by(SourceMoneyClassification.id)
            )
        )


def test_upload_persists_every_row_replay_preserves_choices_and_get_income(db):
    intake, (xml, filename) = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Внесено по распоряжению Клиента", "Synthetic funding", "500"),
            ("Перевод", "погашение купона Synthetic bond A", "12.34"),
            ("Купон", "Synthetic coupon B", "5.66"),
            ("Комиссия", "Synthetic tariff", "-1.50"),
            ("Unknown", "Synthetic unknown", "7"),
        ),
    )
    rows = saved_rows(db, intake)
    assert Counter(row.classification for row in rows) == {
        "external_deposit": 1,
        "coupon": 2,
        "fee": 1,
        "unknown": 1,
    }
    assert len({row.source_reference for row in rows}) == 5
    assert all(row.observation_id and row.intake_id == intake for row in rows)
    assert all(row.origin == "default_rule" and row.status == "assumed" for row in rows)
    assert all(row.date == date(2030, 4, 15) for row in rows)
    assert [row.amount_kopecks for row in rows] == [50_000, 1234, 566, -150, 700]
    assert [row.narrative for row in rows] == [
        "Synthetic funding",
        "погашение купона Synthetic bond A",
        "Synthetic coupon B",
        "Synthetic tariff",
        "Synthetic unknown",
    ]
    client = TestClient(create_app(database=db))
    before = snapshot(db)
    response = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(flow["amount_kopecks"], flow["status"]) for flow in body["flows"]] == [
        (50_000, "assumed")
    ]
    assert body["defaults_applied"] == body["flows"]
    assert body["months"][0]["coupons_kopecks"] == 1800
    assert body["months"][0]["dividends_kopecks"] == 0
    assert body["months"][0]["modified_dietz_return"] is None
    assert {gap["code"] for gap in body["gaps"]} == {"unrecognized_money", "unknown_flow"}
    assert snapshot(db) == before
    unknown = rows[-1]
    url = f"/api/source-intakes/{intake}/money-classifications/{unknown.source_reference}"
    response = client.put(url, json={"classification": "dividend"})
    assert response.status_code == 200, response.text
    choice = response.json()
    assert choice["classification"] == "dividend"
    assert choice["origin"] == "user_choice" and choice["status"] == "confirmed"
    assert datetime.fromisoformat(choice["created_at"]) == unknown.created_at.replace(tzinfo=UTC)
    assert response.headers["cache-control"] == "no-store"
    assert client.put(url, json={"classification": "dividend"}).json() == choice
    with db.session_factory() as session:
        same_request = source_intake.save_intake(
            session, document=xml, filename=filename, request_id="save-4-None"
        )
        assert same_request["duplicate"]
        source_intake.save_intake(session, document=xml, filename=filename, request_id="reupload")
    after = saved_rows(db, intake)
    assert len(after) == 5
    assert [(row.id, row.created_at) for row in after] == [(row.id, row.created_at) for row in rows]
    assert after[-1].classification == "dividend" and after[-1].origin == "user_choice"
    body = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT}).json()
    assert body["months"][0]["dividends_kopecks"] == 700
    assert body["months"][0]["contributions_kopecks"] == 50_000
    assert isinstance(body["months"][0]["modified_dietz_return"], str)
    assert not body["gaps"]
    view = client.get(f"/api/broker-months/intakes/{intake}").json()
    assert len(view["money_classifications"]) == 5
    assert view["money_classifications"][-1]["status"] == "confirmed"


def test_put_confirm_default_and_reclassify_internal_transfer(db):
    intake, _ = save_month(db)
    client = TestClient(create_app(database=db))
    reference = saved_rows(db, intake)[0].source_reference
    url = f"/api/source-intakes/{intake}/money-classifications/{reference}"
    assert client.put(url, json={"classification": "external_deposit"}).status_code == 200
    result = read(db)
    assert result.flows[0].status == "confirmed" and result.flows[0].included
    assert not result.defaults_applied
    assert client.put(url, json={"classification": "internal_transfer"}).status_code == 200
    result = read(db)
    assert not result.flows and result.months[0].result.contributions_kopecks == 0
    assert result.months[0].result.modified_dietz_return is not None


def test_put_rejects_invalid_enum_extra_fields_sign_missing_and_cross_intake_ref(db):
    intake, _ = save_month(db)
    other, _ = save_month(db, 5)
    reference = saved_rows(db, intake)[0].source_reference
    client = TestClient(create_app(database=db))
    url = f"/api/source-intakes/{intake}/money-classifications/{reference}"
    before = snapshot(db)
    for payload in (
        {"classification": "invented"},
        {"classification": "coupon", "amount_kopecks": 0},
    ):
        assert client.put(url, json=payload).status_code == 422
    assert client.put(url, json={"classification": "external_withdrawal"}).status_code == 409
    for wrong_intake, wrong_ref in ((other, reference), (999, reference), (intake, "missing")):
        response = client.put(
            f"/api/source-intakes/{wrong_intake}/money-classifications/{wrong_ref}",
            json={"classification": "coupon"},
        )
        assert response.status_code == 404, response.text
    assert snapshot(db) == before


def test_overlap_deduplicates_income_and_persisted_choice_overrides_default(db):
    extra = (("Купон", "Synthetic coupon", "10"), ("Купон", "Synthetic coupon", "10"))
    one, _ = save_month(db, extra=extra)
    two, _ = save_month(db, extra=extra, marker="overlap")
    client = TestClient(create_app(database=db))
    reference = saved_rows(db, two)[0].source_reference
    assert (
        client.put(
            f"/api/source-intakes/{two}/money-classifications/{reference}",
            json={"classification": "internal_transfer"},
        ).status_code
        == 200
    )
    result = read(db)
    assert not result.flows
    assert result.months[0].coupons_kopecks == 2000
    assert result.months[0].result.contributions_kopecks == 0
    assert {gap.code for gap in result.gaps} == {"overlap_flow_deduplicated"}
    assert one != two


def test_legacy_intake_only_gaps_and_exact_resave_captures_classification(db, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(source_intake, "persist_money_classifications", lambda *args: None)
        intake, (xml, filename) = save_month(db)
    assert not saved_rows(db, intake)
    before = snapshot(db)
    result = read(db)
    assert "classification_missing_legacy_intake" in {gap.code for gap in result.gaps}
    assert result.months[0].result.contributions_kopecks is None
    assert snapshot(db) == before
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=xml, filename=filename, request_id="legacy-reattach"
        )
    result = read(db)
    assert result.flows[0].status == "assumed"
    assert "classification_missing_legacy_intake" not in {gap.code for gap in result.gaps}


@pytest.mark.parametrize(
    "operation,narrative,kind,amount,expected",
    [
        ("Перевод из Synthetic Банк", "", "unsupported", "1", "external_deposit"),
        ("Перевод", "incoming bank transfer", "unsupported", "1", "external_deposit"),
        ("Перевод", "в АО Synthetic bank", "unsupported", "-1", "external_withdrawal"),
        ("Тариф", "", "unsupported", "-1", "fee"),
        ("НДФЛ", "", "unsupported", "-1", "tax"),
        ("НКД по сделке", "", "unsupported", "-1", "trade_settlement"),
        ("Расчеты по сделке", "", "settlement", "-1", "trade_settlement"),
        ("Anything", "", "commission", "-1", "fee"),
        ("Перевод", "Synthetic mystery", "unsupported", "1", "unknown"),
    ],
)
def test_default_rules(operation, narrative, kind, amount, expected):
    assert default_classification(operation, narrative, kind, amount) == expected


def test_bound_closed_month_rejects_choice_until_explicit_reopen(db):
    from test_statement_import_broker_statement_provisional import FILENAME_APRIL, provisional_xml

    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.reporting_months import (
        create_reporting_month,
        reopen_reporting_month,
    )

    with db.session_factory() as session:
        account = create_account(session, name="Synthetic brokerage", account_type="brokerage")
        month = create_reporting_month(session, year=2030, month=4, snapshot_date=date(2030, 4, 30))
        ack = source_intake.save_intake(
            session,
            document=provisional_xml(),
            filename=FILENAME_APRIL,
            request_id="bound-save",
            account_id=account.id,
            reporting_month_id=month.id,
        )
        # Synthetic closed-state seed: the test targets classification immutability,
        # not unrelated Close readiness requirements.
        session.get(ReportingMonth, month.id).status = "closed"
        session.commit()
        month_id = month.id
    intake = ack["intake_id"]
    reference = saved_rows(db, intake)[0].source_reference
    client = TestClient(create_app(database=db))
    url = f"/api/source-intakes/{intake}/money-classifications/{reference}"
    before = snapshot(db)
    response = client.put(url, json={"classification": "internal_transfer"})
    assert response.status_code == 409
    assert "source_intake_editable_period_required" in response.text
    assert snapshot(db) == before
    with db.session_factory() as session:
        reopen_reporting_month(session, month_id)
    assert client.put(url, json={"classification": "internal_transfer"}).status_code == 200


def test_save_classification_failure_rolls_back_complete_intake(db, monkeypatch):
    persist = source_intake.persist_money_classifications

    def fail(*args):
        persist(*args)
        args[0].flush()
        raise RuntimeError("synthetic classification failure")

    monkeypatch.setattr(source_intake, "persist_money_classifications", fail)
    before = snapshot(db)
    with pytest.raises(RuntimeError, match="synthetic classification failure"):
        save_month(db)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "amount,currency", [("1.001", "RUB"), ("1.00", "USD"), ("1000000000000000000", "RUB")]
)
def test_nonrepresentable_money_is_a_gap_never_a_flow(db, amount, currency):
    from test_statement_import_broker_statement_provisional import FILENAME_APRIL, provisional_xml

    xml = provisional_xml(cash_in=amount, candidate_currency=currency)
    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session, document=xml, filename=FILENAME_APRIL, request_id="invalid-minor"
        )
    row = saved_rows(db, ack["intake_id"])[0]
    assert row.currency == currency
    if currency == "RUB":
        assert row.amount_kopecks is None
    result = read(db)
    assert not result.flows
    if currency == "RUB":
        assert "invalid_external_flow" in {gap.code for gap in result.gaps}
        assert result.months[0].result.contributions_kopecks is None
    else:
        assert {"currency_unsupported", "unknown_flow"} <= {gap.code for gap in result.gaps}
        assert result.months[0].result.contributions_kopecks is None
        assert result.months[0].result.modified_dietz_return is None


def test_overlapping_confirmed_choices_conflict_withholds_metrics(db):
    one, _ = save_month(db)
    two, _ = save_month(db, marker="conflicting-choice")
    client = TestClient(create_app(database=db))
    for intake, classification in ((one, "external_deposit"), (two, "internal_transfer")):
        reference = saved_rows(db, intake)[0].source_reference
        response = client.put(
            f"/api/source-intakes/{intake}/money-classifications/{reference}",
            json={"classification": classification},
        )
        assert response.status_code == 200, response.text
    before = snapshot(db)
    response = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "overlap_flow_choice_conflict" in {gap["code"] for gap in body["gaps"]}
    assert body["flows"] == []
    assert body["months"][0]["modified_dietz_return"] is None
    assert body["months"][0]["contributions_kopecks"] is None
    for totals in (body["period"], body["segments"][0]):
        assert totals["growth_kopecks"] is None
        assert totals["xirr_period_return"] is None
        assert "unknown_flow" in totals["growth_reason_codes"]
        assert "unknown_flow" in totals["xirr_reason_codes"]
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "classification,amount", [("external_deposit", "1"), ("external_withdrawal", "-1")]
)
def test_put_non_rub_external_flow_returns_409_without_mutation(db, classification, amount):
    from test_statement_import_broker_statement_provisional import FILENAME_APRIL, provisional_xml

    with db.session_factory() as session:
        ack = source_intake.save_intake(
            session,
            document=provisional_xml(cash_in=amount, candidate_currency="USD"),
            filename=FILENAME_APRIL,
            request_id="non-rub-choice",
        )
    intake = ack["intake_id"]
    reference = saved_rows(db, intake)[0].source_reference
    before = snapshot(db)
    response = TestClient(create_app(database=db)).put(
        f"/api/source-intakes/{intake}/money-classifications/{reference}",
        json={"classification": classification},
    )
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "invalid_external_flow"
    assert snapshot(db) == before


@pytest.mark.parametrize("operation", ["Купон", "Дивиденды", "Unknown"])
def test_non_rub_money_is_disclosed_and_blocks_flow_dependent_metrics(db, operation):
    from xml.etree import ElementTree as ET

    from test_statement_import_broker_statement_provisional import FILENAME_APRIL, provisional_xml

    xml = ET.fromstring(
        provisional_xml(extra_money=((operation, "Synthetic foreign-currency income", "10"),))
    )
    # Retain the RUB deposit and change only the last (income/unknown) Money row.
    xml.findall(".//{MyBroker}p_code[@volume]")[-1].set("p_code", "USD")
    with db.session_factory() as session:
        source_intake.save_intake(
            session,
            document=ET.tostring(xml, encoding="utf-8"),
            filename=FILENAME_APRIL,
            request_id="foreign-income",
        )
    before = snapshot(db)
    result = read(db)
    reasons = {"currency_unsupported", "unknown_flow"}
    assert reasons <= {gap.code for gap in result.gaps}
    assert reasons <= set(result.months[0].flags)
    assert len(result.flows) == 1
    assert result.flows[0].amount_kopecks == 100_000
    assert result.months[0].result.contributions_kopecks is None
    assert result.months[0].result.growth_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    assert result.months[0].coupons_kopecks == 0
    assert result.months[0].dividends_kopecks == 0
    assert result.period.growth_kopecks is None
    assert result.period.xirr_period_return is None
    assert reasons <= set(result.period.growth_reason_codes)
    assert reasons <= set(result.period.xirr_reason_codes)
    assert snapshot(db) == before


def test_income_assumptions_disclosed_until_all_income_is_confirmed(db):
    intake, _ = save_month(
        db,
        candidate_count=0,
        extra=(("Купон", "Synthetic coupon", "10"), ("Дивиденды", "Synthetic dividend", "20")),
    )
    client = TestClient(create_app(database=db))

    def month():
        response = client.get("/api/source-returns/monthly", params={"source_account": ACCOUNT})
        assert response.status_code == 200, response.text
        return response.json()["months"][0]

    initial = month()
    assert initial["income_assumptions_used"]
    assert not initial["assumptions_used"]  # Return schedule has no assumed external flows.
    assert initial["coupons_kopecks"] == 1000
    assert initial["dividends_kopecks"] == 2000
    for index, row in enumerate(saved_rows(db, intake)):
        response = client.put(
            f"/api/source-intakes/{intake}/money-classifications/{row.source_reference}",
            json={"classification": row.classification},
        )
        assert response.status_code == 200, response.text
        assert month()["income_assumptions_used"] is (index == 0)
    confirmed = month()
    assert confirmed["coupons_kopecks"] == initial["coupons_kopecks"]
    assert confirmed["dividends_kopecks"] == initial["dividends_kopecks"]
    assert confirmed["growth_kopecks"] == initial["growth_kopecks"]


def test_captured_text_is_bounded_listing_omits_it_and_long_rows_stay_distinct(db):
    from hermes_finance.domain.source_money_classifications import (
        NARRATIVE_MAX_LENGTH,
        OPERATION_MAX_LENGTH,
    )

    operation = "Купон" + "x" * 300
    prefix = "Synthetic private narrative " * 200
    extra = ((operation, prefix + "A", "10"), (operation, prefix + "B", "10"))
    intake, _ = save_month(db, candidate_count=0, extra=extra)
    save_month(db, candidate_count=0, extra=extra, marker="bounded-overlap")
    rows = saved_rows(db, intake)
    assert all(len(row.operation) == OPERATION_MAX_LENGTH for row in rows)
    assert all(len(row.narrative) == NARRATIVE_MAX_LENGTH for row in rows)
    assert rows[0].narrative != rows[1].narrative
    assert all(row.classification == "coupon" for row in rows)
    client = TestClient(create_app(database=db))
    before = snapshot(db)
    listing = client.get("/api/broker-months/intakes")
    assert listing.status_code == 200, listing.text
    assert len(listing.json()) == 2
    assert all("money_classifications" not in item for item in listing.json())
    assert prefix not in listing.text and operation not in listing.text
    view = client.get(f"/api/broker-months/intakes/{intake}")
    assert view.status_code == 200, view.text
    for row in view.json()["money_classifications"]:
        assert len(row["operation"]) <= OPERATION_MAX_LENGTH
        assert len(row["narrative"]) <= NARRATIVE_MAX_LENGTH
    # Two different long narratives, repeated in overlapping reports, are two incomes.
    assert read(db).months[0].coupons_kopecks == 2000
    assert snapshot(db) == before


@pytest.mark.parametrize("change", ["removed", "added"])
def test_legacy_resave_parser_count_drift_is_typed_409_and_atomic(db, monkeypatch, change):
    import json

    from hermes_finance.services import source_money_classifications as classifications

    with monkeypatch.context() as patch:
        patch.setattr(source_intake, "persist_money_classifications", lambda *args: None)
        intake, (xml, filename) = save_month(db)
    assert not saved_rows(db, intake)
    narratives = list(classifications._narratives(xml))
    changed = narratives[:-1] if change == "removed" else [*narratives, narratives[0]]
    monkeypatch.setattr(classifications, "_narratives", lambda _: iter(changed))
    before = snapshot(db)
    response = TestClient(create_app(database=db)).post(
        "/api/broker-months/intakes",
        files={"file": (filename, xml, "application/xml")},
        data={"intent": json.dumps({"request_id": "parser-drift-resave"})},
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["message"] == "source_intake_parser_revision_changed"
    assert not saved_rows(db, intake)
    assert snapshot(db) == before
