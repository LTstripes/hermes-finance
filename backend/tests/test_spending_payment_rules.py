"""Payment annotations remain separate from diary receipts and closed report facts."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_spending_diary import MONTH, bank_row, csv_file, db, upload  # noqa: F401

from hermes_finance.main import create_app
from hermes_finance.persistence import SpendingOperation
from hermes_finance.services.spending_payment_rules import payment_rules_for_budget


def test_owner_rule_survives_reimport_cancel_and_ambiguous_replacement(db):  # noqa: F811
    with db.session_factory() as session:
        row = bank_row(amount="24000")
        upload(session, csv_file(row))
        op = session.scalar(select(SpendingOperation.id))
        session.commit()
    with TestClient(create_app(db)) as client:
        path = f"/api/spending/payment-rules/alfa/{op}?month={MONTH}"
        original = client.get(path).json()
        assert original["rule"] is None and original["fact_amount"] == "24000.00"
        body = dict(
            token=original["token"],
            note="Проезд на работу",
            mandatory_override=True,
            repeat=True,
            period_months=12,
            next_due="2031-10-03",
            amount="24000.00",
        )
        created = client.put(path, json=body)
        assert created.status_code == 200, created.text
        saved = created.json()
        assert saved["rule"]["monthly_amount"] == "2000.00"
        assert client.put(path, json=body).status_code == 409
        with db.session_factory() as session:
            upload(session, csv_file(row))
            assert len(payment_rules_for_budget(session)) == 1
            assert payment_rules_for_budget(session)[0]["next_due"] == date(2031, 10, 3)
            session.commit()
        assert client.get(path).json() == saved
        cancelled = client.put(
            path,
            json={
                **body,
                "token": saved["token"],
                "repeat": False,
                "period_months": None,
                "next_due": None,
                "amount": None,
            },
        ).json()
        assert cancelled["rule"]["was_recurring"] is True
        assert cancelled["rule"]["repeat"] is False and cancelled["rule"]["note"] == body["note"]
        with db.session_factory() as session:
            upload(session, csv_file(row, row))
            rule = payment_rules_for_budget(session)[0]
            assert rule["needs_review"] and rule["operation_id"] is None
            session.commit()
        candidate = client.get(path).json()
        assert candidate["rule"] is None
        attach = dict(token=candidate["token"], rule_id=rule["id"], version=rule["version"])
        back = client.post(path.replace("?", "/reattach?"), json=attach)
        assert back.status_code == 200, back.text
        assert back.json()["rule"]["id"] == rule["id"]
        assert back.json()["rule"]["note"] == body["note"]
        assert client.post(path.replace("?", "/reattach?"), json=attach).status_code == 409


def test_unknown_budget_inputs_and_category_precedence(db):  # noqa: F811
    with db.session_factory() as session:
        upload(session, csv_file(bank_row()))
        op = session.scalar(select(SpendingOperation.id))
        session.commit()
    with TestClient(create_app(db)) as client:
        path = f"/api/spending/payment-rules/alfa/{op}?month={MONTH}"
        card = client.get(path).json()
        body = dict(
            token=card["token"],
            note="",
            mandatory_override=None,
            repeat=True,
            period_months=None,
            next_due=None,
            amount=None,
        )
        assert client.put(path, json={**body, "amount": "1.999"}).status_code == 422
        assert client.put(path, json={**body, "amount": "-1"}).status_code == 422
        assert client.put(path, json={**body, "next_due": "2020-01-01"}).status_code == 422
        rule = client.put(path, json=body).json()["rule"]
        assert rule["mandatory"] == card["category_mandatory"]
        assert rule["monthly_amount"] is None and rule["amount_kopecks"] is None
        assert client.get(path.replace("alfa", "cash")).status_code == 404
        with db.session_factory() as session:
            upload(session, csv_file(bank_row(amount="501")), confirm_disappearance=True)
            lost = payment_rules_for_budget(session)[0]
            assert lost["needs_review"] and lost["mandatory"] is None
            session.commit()
        archive_path = f"/api/spending/archived-payment-rules/{lost['id']}?month={MONTH}"
        archived = client.post(archive_path, json={"version": lost["version"]})
        assert archived.status_code == 200, archived.text
        assert archived.json()["archived"] and archived.json()["note"] == body["note"]
        with db.session_factory() as session:
            assert payment_rules_for_budget(session) == []


def test_closed_month_entry_annotation_does_not_write_month(db):  # noqa: F811
    with TestClient(create_app(db)) as client:
        month = client.post(
            "/api/months", json=dict(year=2025, month=12, snapshot_date="2025-12-31")
        ).json()
        entry = client.post(
            "/api/expenses",
            json=dict(
                reporting_month_id=month["id"],
                category="Транспорт",
                amount={"amount": "700.00", "currency": "RUB"},
                expense_type="mandatory",
            ),
        ).json()
        from hermes_finance.persistence import ReportingMonth

        with db.session_factory() as session:
            session.get(ReportingMonth, month["id"]).status = "closed"
            session.commit()
        url = f"/api/spending/payment-rules/month_entries/{entry['id']}?month=2025-12"
        initial = client.get(url).json()
        assert initial["category_mandatory"]
        body = dict(
            token=initial["token"],
            note="Запись отчёта",
            mandatory_override=False,
            repeat=False,
            period_months=None,
            next_due=None,
            amount=None,
        )
        result = client.put(url, json=body)
        assert result.status_code == 200, result.text
        assert not result.json()["rule"]["mandatory"]
        assert client.get(f"/api/expenses?month_id={month['id']}").json() == [entry]
