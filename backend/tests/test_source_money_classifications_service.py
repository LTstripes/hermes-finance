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


@pytest.mark.parametrize(
    "operation,narrative,amount,expected",
    [
        ("Перевод", "Дивиденды Synthetic issuer", "12.34", "dividend"),
        ("Перевод", "Дивиденды Synthetic issuer", "0", "unknown"),
        ("Перевод", "Дивиденды Synthetic issuer", "-12.34", "unknown"),
        ("Перевод", "Дивиденды", "12.34", "unknown"),
        ("Перевод", "Synthetic дивиденды issuer", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic\nissuer", "12.34", "unknown"),
        ("Unknown", "Дивиденды Synthetic issuer", "12.34", "unknown"),
        ("Перевод", "Выплата дивидендов Synthetic issuer", "12.34", "unknown"),
        ("Перевод", "Погашение купона Synthetic bond", "12.34", "coupon"),
        ("Перевод", "Дивиденды Synthetic issuer НКД", "12.34", "unknown"),
        (
            "Перевод",
            "Дивиденды за 2031 год по акциям Synthetic issuer (Synthetic share).",
            "12.34",
            "dividend",
        ),
        ("пЕрЕвОд", "дИвИдЕнД пО Synthetic share", "12.34", "dividend"),
        ("Перевод", "Дивиденд по Synthetic issuer", "0", "unknown"),
        ("Перевод", "Дивиденд по Synthetic issuer", "-12.34", "unknown"),
        ("Перевод", "Дивиденд по", "12.34", "unknown"),
        ("Перевод", "Дивиденды   ", "12.34", "unknown"),
        ("Перевод", "Возврат ошибочно зачисленных дивидендов", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic issuer: ВОЗВРАТ выплаты", "12.34", "unknown"),
        ("Перевод", "Дивиденд по Synthetic share: возврат", "12.34", "unknown"),
        ("Перевод", "Перевод дивидендов на счет 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды на счет 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic issuer на счёт 7654321", "12.34", "unknown"),
        ("ПЕРЕВОД", "ДИВИДЕНД ПО Synthetic share НА СЧЁТ 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды со счета 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденд по Synthetic share со счёта 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды с  счёта 7654321", "12.34", "unknown"),
        ("Перевод", "Погашение купона Synthetic bond", "0", "coupon"),
        ("Перевод", "Погашение купона Synthetic bond", "-12.34", "unknown"),
        ("Дивиденды", "Возврат Synthetic dividend", "12.34", "unknown"),
        ("Дивиденды", "Synthetic dividend", "0", "unknown"),
    ],
)
def test_exact_dividend_transfer_default(operation, narrative, amount, expected):
    assert default_classification(operation, narrative, "unsupported", amount) == expected


@pytest.mark.parametrize("promo", ["Synthetic promo", "Акция Synthetic в подарок"])
def test_legacy_unknown_income_and_promo_refresh_on_new_save_preserving_user_choices(db, promo):
    intake, (raw, filename) = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Перевод", "Дивиденды Synthetic stock", "12.34"),
            (
                "Перевод",
                f"Выплата по поручению клиента в рамках {promo} "
                "в соответствии с Правилами проведения акции.",
                "30",
            ),
            ("Перевод", "Дивиденды Synthetic manual stock", "5.66"),
            (
                "Перевод",
                "Выплата по поручению клиента в рамках Synthetic manual promo "
                "в соответствии с Правилами проведения акции.",
                "20",
            ),
        ),
    )
    with db.session_factory() as session:
        rows = list(
            session.scalars(
                select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
            )
        )
        for row in rows:
            row.classification = "unknown"  # synthetic legacy default
        for row in rows[2:]:
            row.origin, row.status = "user_choice", "confirmed"
        session.commit()
    before = snapshot(db)
    assert "unrecognized_money" in {gap.code for gap in read(db).gaps}
    assert snapshot(db) == before
    legacy = saved_rows(db, intake)
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="save-4-None"
        )
    assert snapshot(db) == before  # Same-command replay never refreshes defaults.
    client = TestClient(create_app(database=db))
    response = client.post(
        "/api/broker-months/intakes",
        files={"file": (filename, raw, "application/xml")},
        data={"intent": '{"request_id": "refresh-legacy-defaults"}'},
    )
    assert response.status_code == 200, response.text
    rows = saved_rows(db, intake)
    assert [row.classification for row in rows] == [
        "dividend",
        "external_deposit",
        "unknown",
        "unknown",
    ]
    assert all((row.origin, row.status) == ("default_rule", "assumed") for row in rows[:2])
    assert [(row.id, row.source_reference, row.created_at) for row in rows] == [
        (row.id, row.source_reference, row.created_at) for row in legacy
    ]
    assert all((row.origin, row.status) == ("user_choice", "confirmed") for row in rows[2:])
    assert [row.updated_at for row in rows[2:]] == [row.updated_at for row in legacy[2:]]


@pytest.mark.parametrize(
    "operation,narrative,amount,expected",
    [
        ("Перевод", "Выплата подарка в рамках акции Synthetic promo", "300", "external_deposit"),
        ("Payment", "ПОДАРЁННЫЕ СРЕДСТВА ПО АКЦИИ Synthetic promo", "300", "external_deposit"),
        ("Выплата", "Подарок по акции Synthetic promo", "300", "external_deposit"),
        ("Перевод", "Подарок по акции Synthetic promo", "0", "unknown"),
        ("Перевод", "Подарок по акции Synthetic promo", "-300", "unknown"),
        ("Перевод", "Подарок Synthetic promo", "300", "unknown"),
        ("Перевод", "Выплата по акции Synthetic promo", "300", "unknown"),
        ("Купон", "Подарок по акции Synthetic bond", "7", "coupon"),
        ("Дивиденды", "Подарок по акции Synthetic stock", "7", "dividend"),
        ("Перевод", "Погашение купона Подарок по акции Synthetic bond", "7", "coupon"),
        ("Перевод", "Дивиденды Подарок по акции Synthetic stock", "7", "dividend"),
        ("Payment", "Купон: подарок по акции Synthetic bond", "7", "unknown"),
        ("Payment", "Dividend: подарок по акции Synthetic stock", "7", "unknown"),
        ("Возврат", "Подарок по акции Synthetic promo", "300", "unknown"),
        ("Refund", "Подарок по акции Synthetic promo", "300", "unknown"),
        ("Перевод", "Возврат подарка по акции Synthetic promo", "300", "unknown"),
        ("Перевод", "Возмещение подарка по акции Synthetic promo", "300", "unknown"),
    ],
)
def test_promo_gift_default_and_exclusions(operation, narrative, amount, expected):
    assert default_classification(operation, narrative, "unsupported", amount) == expected


@pytest.mark.parametrize(
    "narrative",
    [
        "Подарок акционеру Synthetic",
        "Подарок за транзакцию Synthetic",
        "Подарок по акцизной программе Synthetic",
        "Подарок за реакцию Synthetic",
        "Продажа подаренных акций Synthetic",
        "Антиподарок по акции Synthetic",
        "Подарок Synthetic\nПродажа акций Synthetic",
        "Подарок Synthetic\rПродажа акций Synthetic",
        "Подарок Synthetic\r\nПродажа акций Synthetic",
        "Подарок Synthetic\nпо акции Synthetic",
        "Подарок по акции Synthetic\nдополнение Synthetic",
    ],
)
def test_promo_gift_requires_a_single_line_gift_and_promo_phrase(narrative):
    assert default_classification("Перевод", narrative, "unsupported", "300") == "unknown"


@pytest.mark.parametrize(
    "narrative",
    [
        "  Подарок  по  акции  Synthetic  ",
        "Подарок\tпо\tакции Synthetic",
        "Подарок\u00a0по\u00a0акции Synthetic",
        "Подарок\u202fв\u00a0рамках\tакции Synthetic",
        "ПОДАРЁННЫЕ\u00a0СРЕДСТВА ПО АКЦИИ Synthetic",
    ],
)
def test_promo_gift_normalizes_case_letters_and_whitespace(narrative):
    assert default_classification("Перевод", narrative, "unsupported", "300") == "external_deposit"


@pytest.mark.parametrize(
    "narrative",
    [
        "Отмена подарка по акции Synthetic",
        "Сторно подарка по акции Synthetic",
        "Подарок по акции, возвращённый брокеру Synthetic",
        "Подарок по акции, возвращенный брокеру Synthetic",
        "Возвращение подарка по акции Synthetic",
        "Reversal: подарок по акции Synthetic",
        "Reimbursement: подарок по акции Synthetic",
    ],
)
@pytest.mark.parametrize("amount", ["300", "-300"])
def test_promo_gift_reversals_stay_unknown(narrative, amount):
    assert default_classification("Перевод", narrative, "unsupported", amount) == "unknown"


@pytest.mark.parametrize("operation", ["Отмена", "Сторно", "Возвращение", "Reversal"])
def test_promo_gift_reversal_operation_is_excluded(operation):
    assert (
        default_classification(operation, "Подарок по акции Synthetic", "unsupported", "300")
        == "unknown"
    )


@pytest.mark.parametrize(
    "operation,narrative,kind,amount,expected",
    [
        (
            "Перевод",
            "Подарок по акции (НДФЛ 35%) Synthetic",
            "unsupported",
            "300",
            "external_deposit",
        ),
        (
            "Перевод",
            "Подарок по акции без комиссии Synthetic",
            "unsupported",
            "300",
            "external_deposit",
        ),
        ("Перевод", "Подарок по акции (НДФЛ 35%) Synthetic", "unsupported", "-300", "tax"),
        ("Перевод", "Подарок по акции без комиссии Synthetic", "unsupported", "-300", "fee"),
        ("НДФЛ", "Synthetic withholding", "unsupported", "-3", "tax"),
        ("Комиссия", "Synthetic fee", "unsupported", "-3", "fee"),
        ("Перевод", "Подарок по акции Synthetic", "commission", "300", "fee"),
        ("Перевод", "Подарок по акции Synthetic", "settlement", "300", "trade_settlement"),
        ("Вывод", "Подарок по акции Synthetic", "unsupported", "300", "external_withdrawal"),
        ("Внесено", "Подарок по акции Synthetic", "unsupported", "300", "external_deposit"),
        ("Перевод", "в АО Synthetic подарок по акции", "unsupported", "300", "external_withdrawal"),
        (
            "Перевод",
            "Перевод в Synthetic банк: подарок по акции",
            "unsupported",
            "300",
            "external_withdrawal",
        ),
        ("Внутренний перевод", "Подарок по акции Synthetic", "unsupported", "300", "unknown"),
        ("Перевод", "Подарок по акции Synthetic НКД", "unsupported", "300", "unknown"),
        (
            "Перевод",
            "Подарок по акции Synthetic накопленный купонный доход",
            "unsupported",
            "300",
            "unknown",
        ),
        (
            "Перевод",
            "Подарок по акции Synthetic НКД по сделке",
            "unsupported",
            "300",
            "trade_settlement",
        ),
        (
            "Расчёты по сделке",
            "Подарок по акции Synthetic",
            "unsupported",
            "300",
            "trade_settlement",
        ),
    ],
)
def test_promo_gift_precedence(operation, narrative, kind, amount, expected):
    assert default_classification(operation, narrative, kind, amount) == expected


@pytest.mark.parametrize(
    "narrative",
    [
        "Подарок по акции (НДФЛ 35%) Synthetic",
        "Подарок\u00a0по\u00a0акции без комиссии Synthetic",
    ],
)
def test_promo_gift_tax_or_fee_mentions_are_contributions(db, narrative):
    intake, _ = save_month(
        db,
        beginning="1000",
        closing="1300",
        candidate_count=0,
        extra=(("Перевод", narrative, "300"),),
    )
    row = saved_rows(db, intake)[0]
    assert row.classification == "external_deposit"
    assert row.narrative == narrative
    assert (row.origin, row.status) == ("default_rule", "assumed")
    before = snapshot(db)
    result = read(db)
    assert result.months[0].result.contributions_kopecks == 30_000
    assert result.months[0].result.growth_kopecks == 0
    assert len(result.flows) == 1
    assert result.flows[0].status == "assumed"
    assert result.defaults_applied == result.flows
    assert not result.gaps
    assert snapshot(db) == before


def test_non_rub_promo_gift_default_is_unconfirmable_and_withholds_returns(db):
    intake, _ = save_month(
        db,
        candidate_count=0,
        extra=(("Перевод", "Подарок по акции Synthetic foreign promo", "300"),),
        money_currency="USD",
    )
    row = saved_rows(db, intake)[0]
    assert row.currency == "USD"
    assert row.classification == "external_deposit"
    assert (row.origin, row.status) == ("default_rule", "assumed")
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    response = client.put(
        f"/api/source-intakes/{intake}/money-classifications/{row.source_reference}",
        json={"classification": "external_deposit"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "invalid_external_flow"
    assert snapshot(db) == before
    result = read(db)
    assert not result.flows
    reasons = {"currency_unsupported", "unknown_flow"}
    assert reasons <= {gap.code for gap in result.gaps}
    assert reasons <= set(result.months[0].flags)
    assert result.months[0].result.contributions_kopecks is None
    assert result.months[0].result.growth_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    for totals in (result.period, result.segments[0]):
        assert totals.contributions_kopecks is None
        assert totals.growth_kopecks is None
        assert totals.xirr_period_return is None
        assert reasons <= set(totals.growth_reason_codes)
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "narrative",
    [
        "Выплата подарка по акции Synthetic promo",
        "Выплата по поручению клиента в рамках Synthetic promo "
        "в соответствии с Правилами проведения акции.",
        "Выплата по поручению клиента в рамках Акция Synthetic в подарок "
        "в соответствии с Правилами проведения акции.",
    ],
)
def test_promo_gift_upload_and_coupon_compute_monthly_return(db, narrative):
    intake, _ = save_month(
        db,
        beginning="1000",
        closing="1307",
        candidate_count=0,
        extra=(
            ("Перевод", narrative, "300"),
            ("Купон", "Synthetic coupon", "7"),
        ),
    )
    rows = saved_rows(db, intake)
    assert [row.classification for row in rows] == ["external_deposit", "coupon"]
    assert all((row.origin, row.status) == ("default_rule", "assumed") for row in rows)
    before = snapshot(db)
    result = read(db)
    month = result.months[0]
    assert month.result.contributions_kopecks == 30_000
    assert month.result.withdrawals_kopecks == 0
    assert month.result.growth_kopecks == 700
    assert month.result.modified_dietz_return is not None
    assert month.coupons_kopecks == 700
    assert len(result.flows) == 1
    assert result.flows[0].amount_kopecks == 30_000
    assert not result.gaps
    assert snapshot(db) == before


def test_promo_gift_resave_refreshes_defaults_and_preserves_manual_put(db):
    intake, (raw, filename) = save_month(
        db,
        candidate_count=0,
        extra=(
            ("Перевод", "Подарок по акции Synthetic first promo", "300"),
            ("Перевод", "Подарок по акции Synthetic second promo", "200"),
        ),
    )
    with db.session_factory() as session:
        rows = list(
            session.scalars(
                select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
            )
        )
        for row in rows:
            row.classification = "unknown"  # synthetic pre-rule defaults
        session.commit()
    client = TestClient(create_app(database=db))
    reference = saved_rows(db, intake)[1].source_reference
    response = client.put(
        f"/api/source-intakes/{intake}/money-classifications/{reference}",
        json={"classification": "unknown"},
    )
    assert response.status_code == 200, response.text
    before = saved_rows(db, intake)
    assert "unknown_flow" in {gap.code for gap in read(db).gaps}
    assert [row.classification for row in saved_rows(db, intake)] == ["unknown", "unknown"]
    with db.session_factory() as session:
        # Same-request replay cannot refresh defaults.
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="save-4-None"
        )
    assert [row.classification for row in saved_rows(db, intake)] == ["unknown", "unknown"]
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="refresh-promo-gifts"
        )
    after = saved_rows(db, intake)
    assert [row.classification for row in after] == ["external_deposit", "unknown"]
    assert [(row.id, row.source_reference, row.created_at) for row in after] == [
        (row.id, row.source_reference, row.created_at) for row in before
    ]
    assert (after[0].origin, after[0].status) == ("default_rule", "assumed")
    assert (after[1].origin, after[1].status) == ("user_choice", "confirmed")
    assert after[1].updated_at == before[1].updated_at


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
    assert body["months"][0]["coupons_kopecks"] is None
    assert body["months"][0]["dividends_kopecks"] is None
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
    assert not result.flows
    assert result.months[0].result.contributions_kopecks is None
    assert result.months[0].result.modified_dietz_return is None
    assert "unrecognized_money" in {gap.code for gap in result.gaps}
    assert saved_rows(db, intake)[0].classification == "internal_transfer"


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
    assert read(db).months[0].coupons_kopecks == 2000
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
    assert result.months[0].coupons_kopecks is None
    assert result.months[0].dividends_kopecks is None
    assert result.months[0].result.contributions_kopecks is None
    assert {gap.code for gap in result.gaps} == {
        "overlap_flow_deduplicated",
        "unrecognized_money",
        "unknown_flow",
    }
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
    assert result.months[0].coupons_kopecks is None
    assert result.months[0].dividends_kopecks is None
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
    assert all(row.classification == "unknown" for row in rows)
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
    # Distinct opaque operations remain distinct evidence, never guessed income.
    result = read(db)
    assert result.months[0].coupons_kopecks is None
    assert result.months[0].dividends_kopecks is None
    assert result.period.growth_kopecks is None
    assert sum(gap.code == "unrecognized_money" for gap in result.gaps) == 4
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


@pytest.mark.parametrize(
    "operation,narrative,amount,expected",
    [
        ("Выведено по распоряжению Клиента", "Вывод дивидендов", "-50", "external_withdrawal"),
        ("Вывод дивидендов", "Synthetic coupon", "-50", "external_withdrawal"),
        ("Внесено по распоряжению Клиента", "Купон", "50", "external_deposit"),
        ("Перевод", "в АО Synthetic дивиденды банк", "-50", "external_withdrawal"),
        ("Перевод из Synthetic Банк", "Купон", "50", "external_deposit"),
        ("Внутренний перевод", "Дивиденды", "50", "unknown"),
        ("НКД по сделке 123 Synthetic", "Купон", "-5", "trade_settlement"),
        (" НКД ПО СДЕЛКЕ: Synthetic ", "Купон", "-5", "trade_settlement"),
        ("Перевод", "НКД по сделке Synthetic coupon", "-5", "trade_settlement"),
        ("Расчёты по сделке", "Synthetic НКД купон", "-5", "trade_settlement"),
        ("Расчеты по сделке", "Synthetic НКД", "-5", "trade_settlement"),
        ("Deal settlement", "Synthetic НКД coupon", "-5", "trade_settlement"),
        ("НКД Synthetic", "Купон", "5", "unknown"),
        ("Купон", "Synthetic НКД correction", "5", "unknown"),
        (
            "Перевод",
            "погашение купона Synthetic (облигации Synthetic НДФЛ) д.ф.15.04.30",
            "5",
            "coupon",
        ),
    ],
)
def test_explicit_cash_and_nkd_semantics_precede_generic_income(
    operation, narrative, amount, expected
):
    assert default_classification(operation, narrative, "unsupported", amount) == expected


@pytest.mark.parametrize(
    "origin,status",
    [
        ("default_rule", "assumed"),
        ("user_choice", "confirmed"),
    ],
)
def test_resave_refreshes_only_assumed_default_rules(db, origin, status):
    intake, (xml, filename) = save_month(
        db,
        beginning="100",
        closing="0",
        candidate_count=0,
        extra=(
            ("Дивиденды", "Synthetic dividend", "100"),
            ("Выведено по распоряжению Клиента", "Вывод дивидендов", "-100"),
        ),
    )
    original_rows = saved_rows(db, intake)
    with db.session_factory() as session:
        row = session.get(SourceMoneyClassification, original_rows[-1].id)
        row.classification, row.origin, row.status = "dividend", origin, status
        session.commit()
    before = snapshot(db)
    with db.session_factory() as session:
        # An acknowledged command replay must remain read-only even for old defaults.
        source_intake.save_intake(
            session, document=xml, filename=filename, request_id="save-4-None"
        )
    assert snapshot(db) == before
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=xml, filename=filename, request_id="new-rules-resave"
        )
    rows = saved_rows(db, intake)
    assert len(rows) == 2
    assert [(r.id, r.source_reference, r.created_at) for r in rows] == [
        (r.id, r.source_reference, r.created_at) for r in original_rows
    ]
    assert (rows[-1].origin, rows[-1].status) == (origin, status)
    if (origin, status) == ("default_rule", "assumed"):
        assert rows[-1].classification == "external_withdrawal"
        result = read(db)
        assert result.months[0].dividends_kopecks == 10000
        assert result.period.withdrawals_kopecks == 10000
        assert result.period.growth_kopecks == 0
    else:
        assert rows[-1].classification == "dividend"
    before = snapshot(db)
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=xml, filename=filename, request_id="unchanged-resave"
        )
    after = saved_rows(db, intake)
    assert [(r.classification, r.updated_at) for r in after] == [
        (r.classification, r.updated_at) for r in rows
    ]


@pytest.mark.parametrize(
    "amount,closing,expected,field",
    [
        ("-100", "0", "external_withdrawal", "withdrawals_kopecks"),
        ("100", "200", "external_deposit", "contributions_kopecks"),
    ],
)
@pytest.mark.parametrize("proven", [True, False])
def test_internal_broker_transfer_crosses_selected_account(
    db, amount, closing, expected, field, proven
):
    narrative = (
        (
            f"Со счета {ACCOUNT} на счет 7654321-000 внутри брокера"
            if amount.startswith("-")
            else f"Со счета 7654321-000 на счет {ACCOUNT} внутри брокера"
        )
        if proven
        else "Внутри брокера"
    )
    intake, original = save_month(
        db,
        beginning="100",
        closing=closing,
        candidate_count=0,
        extra=(("Внутренний перевод", narrative, amount),),
    )
    assert saved_rows(db, intake)[0].classification == (expected if proven else "unknown")
    for originals in (None, {intake: original}):
        result = read(db, originals)
        if proven:
            assert getattr(result.period, field) == 10000
            assert result.period.growth_kopecks == 0
            assert result.period.xirr_period_return == 0
            assert not result.gaps
        else:
            assert result.period.growth_kopecks is None
            assert result.period.xirr_period_return is None
            assert "unrecognized_money" in {g.code for g in result.gaps}


@pytest.mark.parametrize("amount,source_account", [("-100", "1234567"), ("100", "7654321")])
def test_transfer_is_internal_only_when_both_accounts_are_selected(amount, source_account):
    from hermes_finance.services.source_money_classifications import transfer_classification

    narrative = "Со счета 1234567 на счет 7654321 внутри брокера"
    assert (
        transfer_classification(
            "Внутренний перевод",
            narrative,
            amount,
            source_account=source_account,
            selected_accounts={"1234567", "7654321"},
        )
        == "internal_transfer"
    )
    assert default_classification(
        "Внутренний перевод",
        narrative,
        "unsupported",
        amount,
        source_account=source_account,
        selected_accounts={source_account},
    ) == ("external_withdrawal" if amount.startswith("-") else "external_deposit")
    assert (
        transfer_classification(
            "Внутренний перевод",
            narrative,
            str(-int(amount)),
            source_account=source_account,
            selected_accounts={"1234567", "7654321"},
        )
        == "unknown"
    )


@pytest.mark.parametrize(
    "operation,narrative",
    [
        ("Вывoд дивидендов", "Synthetic withdrawal"),
        ("Unknown", "Дивиденды"),
        ("Unknown", "Купон"),
        ("Дивиденды", "Synthetic negative income"),
    ],
)
def test_unsupported_operation_is_not_guessed_from_income_words(operation, narrative):
    assert default_classification(operation, narrative, "unsupported", "-100") == "unknown"


@pytest.mark.parametrize("amount", ["-100", "100"])
@pytest.mark.parametrize("manual", [False, True])
def test_transfer_full_scope_excludes_flow_without_changing_saved_choice(db, amount, manual):
    from hermes_finance.services.source_money_classifications import choose_classification
    from hermes_finance.services.source_monthly_returns import _money

    narrative = (
        f"Со счета {ACCOUNT} на счет 7654321-000 внутри брокера"
        if amount.startswith("-")
        else f"Со счета 7654321-000 на счет {ACCOUNT} внутри брокера"
    )
    intake, _ = save_month(
        db, candidate_count=0, extra=(("Внутренний перевод", narrative, amount),)
    )
    if manual:
        with db.session_factory() as session:
            choose_classification(
                session, intake, saved_rows(db, intake)[0].source_reference, "internal_transfer"
            )
    before = snapshot(db)
    with db.session_factory() as session:
        view = source_intake.read_intake(session, intake)
        gaps = []
        rows = _money(session, view, None, gaps, selected_accounts={ACCOUNT, "7654321-000"})
        assert len(rows) == 1 and not gaps
        flow = rows[0][1]
        assert flow.classification == "internal_transfer"
        assert not flow.included  # No contribution or withdrawal in the full-scope schedule.
        gaps = []
        account = _money(session, view, None, gaps)[0][1]
        assert account.included
        assert account.classification == (
            "external_withdrawal" if amount.startswith("-") else "external_deposit"
        )
        assert not gaps
    assert snapshot(db) == before


@pytest.mark.parametrize("operation", ["Дивиденды", "Перевод"])
@pytest.mark.parametrize(
    "reversal", ["возврат", "возвращены", "возвращено", "сторно", "перерасчет", "ПЕРЕРАСЧЁТ"]
)
def test_dividend_refund_and_reversal_forms(operation, reversal):
    narrative = f"Дивиденды Synthetic {reversal}"
    assert default_classification(operation, narrative, "unsupported", "12.34") == "unknown"


@pytest.mark.parametrize("prefix", ["Дивиденды", "Дивиденд по"])
@pytest.mark.parametrize(
    "separator", ["  ", "\t", "\u00a0", "\u2009", ": ", ":", "; ", ", ", " — "]
)
def test_dividend_context_separators(prefix, separator):
    assert (
        default_classification(
            "Перевод", f"{prefix}{separator}Synthetic issuer", "unsupported", "12.34"
        )
        == "dividend"
    )


@pytest.mark.parametrize(
    "direction",
    [
        "на счет",
        "на расчетный счет",
        "на брокерский счет",
        "со счета",
        "с счета",
        "с расчетного счета",
        "со брокерского счета",
    ],
)
@pytest.mark.parametrize("space", [" ", "  ", "\t", "\u00a0", "\u2009"])
@pytest.mark.parametrize("account", ["7654321", "7654321-000"])
def test_dividend_transfer_cash_account_directions(direction, space, account):
    narrative = f"Дивиденды Synthetic {direction} {account}".replace(" ", space)
    assert default_classification("Перевод", narrative, "unsupported", "12.34") == "unknown"


@pytest.mark.parametrize("operation", ["Выплата дивидендов", "Зачисление дивидендов", "Дивиденды"])
@pytest.mark.parametrize(
    "narrative",
    [
        "Дивиденды зачислены на счет",
        "Дивиденды Synthetic на брокерский счет 7654321",
        "Дивиденды Synthetic со счета 7654321",
    ],
)
def test_explicit_dividend_operation_keeps_credit_destination(operation, narrative):
    assert default_classification(operation, narrative, "unsupported", "12.34") == "dividend"


@pytest.mark.parametrize(
    "narrative", ["Дивиденды Synthetic на счет депо", "Дивиденды Synthetic на брокерский счет депо"]
)
def test_dividend_transfer_requires_numeric_cash_account_operand(narrative):
    assert default_classification("Перевод", narrative, "unsupported", "12.34") == "dividend"


@pytest.mark.parametrize(
    "narrative",
    [
        "Дивиденды Synthetic\rissuer",
        "Дивиденды\nSynthetic issuer",
        "Дивиденды Synthetic issuer\r\n",
        "Дивиденды: ",
        "Дивиденд по\u00a0",
    ],
)
def test_dividend_context_stays_nonempty_and_single_line(narrative):
    assert default_classification("Перевод", narrative, "unsupported", "12.34") == "unknown"


@pytest.mark.parametrize(
    "operation,narrative,amount,expected",
    [
        ("Перевод", "Дивиденды Synthetic возвращены", "12.34", "unknown"),
        ("Дивиденды", "Synthetic dividend возвращены", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic на брокерский счет 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic на расчетный счет 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic на\u00a0счет 7654321", "12.34", "unknown"),
        ("Перевод", "Дивиденды Synthetic", "0", "unknown"),
        ("Перевод", "Дивиденды Synthetic", "-12.34", "unknown"),
        ("Выплата дивидендов", "Дивиденды зачислены на счет", "12.34", "dividend"),
        ("Дивиденды", "Дивиденды Synthetic на счет 7654321", "12.34", "dividend"),
        ("Перевод", "Дивиденды: Synthetic issuer", "12.34", "dividend"),
        ("Перевод", "Дивиденды Synthetic на счет депо", "12.34", "dividend"),
    ],
)
def test_dividend_narrowing_monthly_consumer(db, operation, narrative, amount, expected):
    intake, original = save_month(db, candidate_count=0, extra=((operation, narrative, amount),))
    assert saved_rows(db, intake)[0].classification == expected
    before = snapshot(db)
    for originals in (None, {intake: original}):
        result = read(db, originals)
        month = result.months[0]
        assert not result.flows
        assert month.dividends_kopecks == (1234 if expected == "dividend" else None)
        if expected == "unknown":
            assert {"unrecognized_money", "unknown_flow"} <= {gap.code for gap in result.gaps}
            assert "unknown_flow" in month.flags
            assert month.result.contributions_kopecks is None
            assert month.result.growth_kopecks is None
            assert month.result.modified_dietz_return is None
            for totals in (result.period, result.segments[0]):
                assert totals.contributions_kopecks is None
                assert totals.growth_kopecks is None
                assert totals.xirr_period_return is None
                assert "unknown_flow" in totals.growth_reason_codes
        else:
            assert not result.gaps
            assert month.result.contributions_kopecks == 0
            assert month.result.growth_kopecks is not None
            assert month.result.modified_dietz_return is not None
    assert snapshot(db) == before


@pytest.mark.parametrize(
    "narrative",
    ["Дивиденды Synthetic возвращены", "Дивиденды Synthetic на\u00a0брокерский счет 7654321"],
)
@pytest.mark.parametrize("confirmed", [False, True])
def test_dividend_downgrade_requires_new_save_and_preserves_confirmed_choice(
    db, narrative, confirmed
):
    intake, (raw, filename) = save_month(
        db, candidate_count=0, extra=(("Перевод", narrative, "12.34"),)
    )
    with db.session_factory() as session:
        row = session.get(SourceMoneyClassification, saved_rows(db, intake)[0].id)
        row.classification = "dividend"  # Synthetic legacy assumed default.
        row.created_at = row.updated_at = datetime(2000, 1, 1)
        session.commit()
    if confirmed:
        from hermes_finance.services.source_money_classifications import choose_classification

        with db.session_factory() as session:
            choose_classification(
                session, intake, saved_rows(db, intake)[0].source_reference, "dividend"
            )
    original = saved_rows(db, intake)[0]
    before = snapshot(db)
    client = TestClient(create_app(database=db))
    assert client.get(f"/api/broker-months/intakes/{intake}").status_code == 200
    assert read(db).months[0].dividends_kopecks == 1234
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="save-4-None"
        )
    assert snapshot(db) == before
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="downgrade-dividend"
        )
    row = saved_rows(db, intake)[0]
    assert (row.id, row.source_reference, row.created_at) == (
        original.id,
        original.source_reference,
        original.created_at,
    )
    assert (row.origin, row.status) == (original.origin, original.status)
    assert row.classification == ("dividend" if confirmed else "unknown")
    if confirmed:
        assert row.updated_at == original.updated_at
        assert read(db).months[0].dividends_kopecks == 1234
    else:
        assert row.updated_at > original.updated_at
        assert "unrecognized_money" in {gap.code for gap in read(db).gaps}
    with db.session_factory() as session:
        source_intake.save_intake(
            session, document=raw, filename=filename, request_id="unchanged-dividend"
        )
    unchanged = saved_rows(db, intake)[0]
    assert (unchanged.classification, unchanged.updated_at) == (row.classification, row.updated_at)


@pytest.mark.parametrize(
    "promo", ["Synthetic promo", "Акция Synthetic в подарок", "Synthetic подарённый бонус"]
)
@pytest.mark.parametrize("ending", ["", "."])
@pytest.mark.parametrize("spacing", [" ", "\t", "\u00a0", "\u202f"])
def test_client_order_promo_template_normalization(promo, ending, spacing):
    narrative = (
        f"ВЫПЛАТА ПО ПОРУЧЕНИЮ КЛИЕНТА В РАМКАХ {promo} "
        f"В СООТВЕТСТВИИ С ПРАВИЛАМИ ПРОВЕДЕНИЯ АКЦИИ{ending}"
    )
    narrative = spacing + narrative.replace(" ", spacing * 2) + spacing
    assert default_classification("Перевод", narrative, "unsupported", "30") == "external_deposit"


@pytest.mark.parametrize(
    "operation,promo,amount,prefix,suffix",
    [
        ("Перевод", "Synthetic promo", "0", "", "."),
        ("Перевод", "Synthetic promo", "-30", "", "."),
        ("Перевод", "", "30", "", "."),
        ("Перевод", "Synthetic promo", "30", "Synthetic prefix ", "."),
        ("Перевод", "Synthetic promo", "30", "", ". Synthetic suffix"),
        ("Перевод", "Synthetic\npromo", "30", "", "."),
        ("Перевод", "Synthetic\rpromo", "30", "", "."),
        ("Перевод", "Synthetic promo", "30", "", ".\n"),
        ("Refund", "Synthetic promo", "30", "", "."),
        ("Сторно", "Synthetic promo", "30", "", "."),
        ("Перевод", "Synthetic возврат", "30", "", "."),
        ("Перевод", "Synthetic возвращённый бонус", "30", "", "."),
        ("Перевод", "Synthetic возмещение", "30", "", "."),
        ("Перевод", "Synthetic отмена", "30", "", "."),
        ("Перевод", "Synthetic reversal", "30", "", "."),
        ("Перевод", "Synthetic reimbursement", "30", "", "."),
        ("Перевод", "Synthetic купон", "30", "", "."),
        ("Перевод", "Synthetic dividend", "30", "", "."),
    ],
)
def test_client_order_promo_template_boundaries_and_exclusions(
    operation, promo, amount, prefix, suffix
):
    narrative = (
        f"{prefix}Выплата по поручению клиента в рамках {promo} "
        f"в соответствии с Правилами проведения акции{suffix}"
    )
    assert default_classification(operation, narrative, "unsupported", amount) == "unknown"
