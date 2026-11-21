"""Payment annotations remain separate from diary receipts and closed report facts."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_spending_diary import MONTH, bank_row, csv_file, db, md_file, upload  # noqa: F401

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


def test_confirmed_manual_duplicate_moves_its_note_once(db):  # noqa: F811
    from hermes_finance.services import spending_diary as diary
    from hermes_finance.services.spending_payment_rules import card, save

    with db.session_factory() as session:
        upload(
            session,
            md_file(("03.10", "500", "Продукты", "Ручная покупка", "альфа")),
            source="manual_md",
        )
        manual_id = session.scalar(select(SpendingOperation.id))
        # An owner-approved separate expense first exists only in the manual file.
        diary.decide_operation(session, manual_id, action="expense", category="Продукты")
        source = card(session, MONTH, "alfa", manual_id)
        saved = save(
            session,
            MONTH,
            "alfa",
            manual_id,
            dict(
                token=source["token"],
                note="Сохранить заметку",
                mandatory_override=None,
                repeat=True,
                period_months=12,
                next_due=None,
                amount="500.00",
            ),
        )
        upload(session, csv_file(bank_row()))
        target = session.scalar(
            select(SpendingOperation.id).where(SpendingOperation.source == "alfa_csv")
        )
        diary.decide_operation(session, manual_id, action="duplicate", duplicate_of_id=target)
        bank = card(session, MONTH, "alfa", target)["rule"]
        assert bank["id"] == saved["rule"]["id"] and bank["note"] == "Сохранить заметку"
        assert not bank["needs_review"] and bank["was_recurring"]
        assert len(payment_rules_for_budget(session)) == 1


def test_two_month_rent_is_one_schedule_and_two_distinct_facts(db):  # noqa: F811
    with db.session_factory() as session:
        oct_row = bank_row(merchant="Аренда", amount="30000", category="Жильё")
        nov_row = {**oct_row, "operationDate": "03.11.2030", "transactionDate": "05.11.2030"}
        upload(session, csv_file(oct_row))
        upload(session, csv_file(nov_row), month="2030-11")
        october, november = session.scalars(
            select(SpendingOperation.id).order_by(SpendingOperation.id)
        ).all()
        session.commit()
    with TestClient(create_app(db)) as client:
        base = "/api/spending/payment-rules/alfa/"
        anchor = f"{base}{october}?month=2030-10"
        target = f"{base}{november}?month=2030-11"
        choose = target.replace("?", "/occurrence?")
        revert = target.replace("?", "/undo-occurrence?")
        root = client.get(anchor).json()
        schedule = client.put(
            anchor,
            json=dict(
                token=root["token"],
                note="Аренда",
                mandatory_override=True,
                repeat=True,
                period_months=1,
                next_due="2030-12-03",
                amount="30000",
            ),
        ).json()["rule"]
        before = client.get("/api/spending/months/2030-11").json()
        initial = client.get(target).json()
        assert (
            initial["rule"] is None
            and initial["decisions"] == []
            and len(initial["schedules"]) == 1
        )
        args = dict(
            token=initial["token"],
            rule_id=schedule["id"],
            version=schedule["version"],
            decision="payment",
        )
        paid = client.put(choose, json=args)
        assert paid.status_code == 200, paid.text
        assert client.put(choose, json=args).status_code == 409
        recorded = paid.json()
        assert recorded["rule"] is None and len(recorded["decisions"]) == 1
        row = recorded["decisions"][0]
        with db.session_factory() as session:
            rules = payment_rules_for_budget(session)
            assert len(rules) == 1 and rules[0]["monthly_amount"] == "30000.00"
            assert [
                (o["month"], o["operation_id"], o["decision"], o["needs_review"])
                for o in rules[0]["occurrences"]
            ] == [("2030-11", november, "payment", False)]
        after = client.get("/api/spending/months/2030-11").json()
        assert before["total"] == after["total"] == {"amount": "30000.00", "currency": "RUB"}
        # Reimporting the same receipt preserves the one owner's decision.
        with db.session_factory() as session:
            upload(session, csv_file(nov_row), month="2030-11")
            session.commit()
        assert client.get(target).json() == recorded
        as_separate = client.put(
            choose,
            json={
                **args,
                "token": recorded["token"],
                "version": row["rule_version"],
                "decision": "separate",
            },
        )
        assert as_separate.status_code == 200, as_separate.text
        standalone = as_separate.json()
        assert standalone["decisions"][0]["decision"] == "separate"
        undone = client.post(
            revert,
            json=dict(
                token=standalone["token"],
                occurrence_id=row["id"],
                version=standalone["decisions"][0]["rule_version"],
            ),
        )
        assert undone.status_code == 200 and undone.json()["decisions"] == []
        # Losing the real target never silently credits the new operation.
        confirmed = client.put(
            choose,
            json={
                **args,
                "token": undone.json()["token"],
                "version": undone.json()["schedules"][0]["version"],
            },
        )
        assert confirmed.status_code == 200
        with db.session_factory() as session:
            upload(
                session,
                csv_file({**nov_row, "amount": "31000"}),
                month="2030-11",
                confirm_disappearance=True,
            )
            session.commit()
        reopened = client.get(anchor).json()
        missing = reopened["rule"]["occurrences"][0]
        assert missing["needs_review"] and missing["operation_id"] is None
        removed = client.post(
            anchor.replace("?", "/undo-occurrence?"),
            json=dict(
                token=reopened["token"],
                occurrence_id=missing["id"],
                version=reopened["rule"]["version"],
            ),
        )
        assert removed.status_code == 200 and removed.json()["rule"]["occurrences"] == []


def test_paid_occurrence_follows_only_the_confirmed_bank_duplicate(db):  # noqa: F811
    from hermes_finance.services import spending_diary as diary
    from hermes_finance.services.spending_payment_rules import card, choose_occurrence, save

    with db.session_factory() as session:
        upload(
            session,
            csv_file(bank_row(operationDate="03.09.2030", transactionDate="05.09.2030")),
            month="2030-09",
        )
        anchor = session.scalar(select(SpendingOperation.id))
        rule = save(
            session,
            "2030-09",
            "alfa",
            anchor,
            dict(
                token=card(session, "2030-09", "alfa", anchor)["token"],
                note="",
                mandatory_override=True,
                repeat=True,
                period_months=1,
                next_due=None,
                amount="500.00",
            ),
        )["rule"]
        upload(
            session,
            md_file(("03.10", "500", "Продукты", "Ручная оплата", "альфа")),
            source="manual_md",
        )
        receipt = session.scalar(
            select(SpendingOperation.id).where(SpendingOperation.source == "manual_md")
        )
        diary.decide_operation(session, receipt, action="expense", category="Продукты")
        choose_occurrence(
            session,
            MONTH,
            "alfa",
            receipt,
            card(session, MONTH, "alfa", receipt)["token"],
            rule["id"],
            rule["version"],
            "payment",
        )
        upload(session, csv_file(bank_row()))
        assert payment_rules_for_budget(session)[0]["occurrences"][0]["needs_review"]
        target = session.scalar(
            select(SpendingOperation.id).where(
                SpendingOperation.month == MONTH, SpendingOperation.source == "alfa_csv"
            )
        )
        diary.decide_operation(session, receipt, action="duplicate", duplicate_of_id=target)
        occurrences = payment_rules_for_budget(session)[0]["occurrences"]
        assert [
            (row["operation_id"], row["decision"], row["needs_review"]) for row in occurrences
        ] == [(target, "payment", False)]


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
