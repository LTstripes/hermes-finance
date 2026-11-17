"""Synthetic acceptance of diary identity, replacement and month-fact separation."""

import csv
import io
import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hermes_finance.alfa_csv import COLUMNS, parse_alfa_csv
from hermes_finance.database import create_database
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Base,
    ExpenseEntry,
    SpendingOperation,
    SpendingUpload,
)
from hermes_finance.services import spending_diary as diary
from hermes_finance.services.expenses import create_expense_entry, total_expenses
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.spending_files import alfa_operations, manual_operations, merchant_key

MONTH = "2030-10"


def bank_row(**changes):
    row = dict.fromkeys(COLUMNS, "")
    row.update(
        operationDate="03.10.2030",
        transactionDate="05.10.2030",
        accountName="Synthetic",
        accountNumber="SYNTHETIC-A",
        cardNumber="SYNTHETIC-CARD",
        merchant="МОСКВА/МАГАЗИН",
        amount="500",
        currency="RUR",
        status="Выполнен",
        category="Продукты",
        type="Списание",
    )
    row.update(changes)
    return row


def csv_file(*rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def md_file(*rows, month=MONTH):
    text = f"---\nfinance_expenses: 1\nmonth: {month}\n---\n\n"
    text += "| Дата | Сумма | Категория | Описание | Оплата |\n|---|---|---|---|---|\n"
    text += "\n".join("| " + " | ".join(row) + " |" for row in rows)
    return text.encode("utf-8")


@pytest.fixture
def db(tmp_path):
    database = create_database(tmp_path / "synthetic-diary.db")
    Base.metadata.create_all(database.engine)
    yield database
    database.engine.dispose()


@pytest.fixture
def session(db):
    with db.session_factory() as session:
        yield session


def upload(session, content, *, source="alfa_csv", month=MONTH, **kwargs):
    args = dict(
        source=source,
        month=month,
        filename="synthetic.csv" if source == "alfa_csv" else "synthetic.md",
        content=content,
    )
    preview = diary.preview_upload(
        session, **args, **{k: v for k, v in kwargs.items() if k in {"choices", "skip_error_lines"}}
    )
    return diary.apply_upload(session, **args, preview_token=preview["preview_token"], **kwargs)


def operation(session, reason=None):
    rows = diary.read_month(session, MONTH)["operations"]
    return next(r for r in rows if r["effective_reason"] == reason)


def test_parser_keeps_all_sixteen_columns_dates_accounts_and_directions():
    content = csv_file(
        bank_row(),
        bank_row(type="Пополнение", cardNumber="", status=""),
        bank_row(
            accountNumber="SYNTHETIC-B", currency="USD", status="В обработке", transactionDate=""
        ),
    )
    assert content.startswith(b"\xef\xbb\xbf") and b"\r\n" not in content
    result = parse_alfa_csv(content)
    assert not result.errors and len(result.rows) == 3
    assert set(result.rows[0].fields) == set(COLUMNS)
    assert result.rows[0].transaction_date == date(2030, 10, 5)
    assert result.rows[2].transaction_date is None
    assert {r.direction for r in result.rows} == {"Списание", "Пополнение"}
    assert {r.fields["accountNumber"] for r in result.rows} == {"SYNTHETIC-A", "SYNTHETIC-B"}
    with pytest.raises(ValueError, match="заголовки"):
        parse_alfa_csv(b"wrong,headers\n1,2")


def test_spending_cash_technical_and_pending_acceptance(session):
    content = csv_file(
        bank_row(status="В обработке", transactionDate=""),
        bank_row(amount="2000", category="Наличные", merchant="ATM"),
        bank_row(amount="1000", type="Пополнение", category="Между своими счетами", cardNumber=""),
        bank_row(amount="1000", category="Кредиты", merchant="Погашение ОД", cardNumber=""),
    )
    upload(session, content)
    cash = operation(session, "cash_withdrawal_decision")
    diary.decide_operation(session, cash["id"], action="not_spending", remember=True)
    result = upload(
        session, md_file(("", "300", "Продукты", "Наличная покупка", "нал")), source="manual_md"
    )["month"]
    assert result["total_kopecks"] == 80_000
    assert result["pending_kopecks"] == 50_000
    assert result["undated_kopecks"] == 30_000
    assert len(session.scalars(select(SpendingOperation)).all()) == 5
    assert len(session.scalars(select(ExpenseEntry)).all()) == 0


def test_transfer_rule_and_bank_category_precedence(session):
    content = csv_file(
        bank_row(amount="50000", category="Переводы СБП", merchant="СБП Получатель", cardNumber="")
    )
    result = upload(session, content)["month"]
    assert result["total_kopecks"] == 0
    row = operation(session, "transfer_decision")
    diary.decide_operation(session, row["id"], action="not_spending", remember=True)
    later = csv_file(
        bank_row(
            operationDate="04.10.2030",
            amount="50000",
            category="Переводы СБП",
            merchant="СБП Получатель",
            cardNumber="",
        )
    )
    assert upload(session, later)["month"]["total_kopecks"] == 0
    diary.set_rule(
        session, scope="bank_category", key="Переводы СБП", action="expense", category="Другая"
    )
    diary.set_rule(
        session, scope="merchant", key="СБП Получатель", action="expense", category="Услуги"
    )
    result = diary.read_month(session, MONTH)
    # Explicit per-operation not-spending remains stronger than a saved merchant rule.
    assert result["total_kopecks"] == 5_000_000
    assert result["categories"][0]["category"] == "Услуги"
    assert merchant_key("СБП получатель/номер") == "СБП ПОЛУЧАТЕЛЬ\\НОМЕР"
    assert merchant_key("МОСКВА/магазин") == "МАГАЗИН"


def test_refund_candidate_without_card_and_next_month_negative_share(session):
    content = csv_file(
        bank_row(amount="1000"), bank_row(amount="400", type="Пополнение", cardNumber="", status="")
    )
    upload(session, content)
    refund = operation(session, "refund_candidate")
    result = diary.decide_operation(session, refund["id"], action="refund", category="Продукты")
    assert result["total_kopecks"] == 60_000 and result["returns_kopecks"] == -40_000
    upload(
        session,
        csv_file(
            bank_row(
                operationDate="03.11.2030",
                amount="700",
                type="Пополнение",
                cardNumber="",
                status="",
            )
        ),
        month="2030-11",
    )
    row = diary.read_month(session, "2030-11")["operations"][0]
    diary.decide_operation(session, row["id"], action="refund", category="Продукты")
    result = diary.read_month(session, "2030-11")
    assert result["total_kopecks"] == -70_000
    assert result["categories"][0]["share_percent"] is None
    assert (
        len(alfa_operations(csv_file(bank_row(), bank_row(type="Пополнение")), MONTH)["rows"]) == 2
    )
    assert (
        len(
            {
                r["fingerprint"]
                for r in alfa_operations(csv_file(bank_row(), bank_row(type="Пополнение")), MONTH)[
                    "rows"
                ]
            }
        )
        == 2
    )


def test_unknown_technical_cardless_utilities_foreign_uncategorized(session):
    result = upload(
        session,
        csv_file(
            bank_row(cardNumber="", category="Коммунальные услуги", amount="5000"),
            bank_row(category="Накопления", type="Пополнение", amount="10", cardNumber=""),
            bank_row(category="Комиссии", amount="20"),
            bank_row(currency="USD", amount="30"),
            bank_row(category="", amount="40"),
            bank_row(cardNumber="", merchant="Незнакомая услуга", category="Услуги", amount="50"),
        ),
    )["month"]
    assert result["total_kopecks"] == 504_000
    assert {r["effective_reason"] for r in result["exceptions"]} == {
        "unknown_technical",
        "foreign_currency",
        "uncategorized",
        "unknown_cardless",
    }
    foreign = operation(session, "foreign_currency")
    with pytest.raises(ValueError, match="Валютную"):
        diary.decide_operation(session, foreign["id"], action="expense", category="Продукты")
    assert any(c["category"] == "Без категории" for c in result["categories"])


def test_identical_rows_repeated_apply_rename_and_preview_zero_write(session):
    content = csv_file(bank_row(), bank_row(), bank_row())
    args = dict(source="alfa_csv", month=MONTH, filename="synthetic.csv", content=content)
    preview = diary.preview_upload(session, **args)
    assert len(preview["added"]) == 3 and not session.new and not session.dirty
    assert session.scalar(select(SpendingUpload)) is None
    result = diary.apply_upload(session, **args, preview_token=preview["preview_token"])
    assert result["month"]["total_kopecks"] == 150_000
    assert [r.ordinal for r in session.scalars(select(SpendingOperation))] == [1, 2, 3]
    assert (
        diary.apply_upload(session, **args, preview_token=preview["preview_token"])["changed"]
        is False
    )
    args["filename"] = "renamed.csv"
    assert (
        diary.apply_upload(session, **args, preview_token=preview["preview_token"])["changed"]
        is False
    )
    assert len(session.scalars(select(SpendingUpload)).all()) == 1


def test_partial_replacement_disappearance_and_accounts(session):
    upload(
        session,
        csv_file(
            bank_row(),
            bank_row(operationDate="08.10.2030"),
            bank_row(operationDate="25.10.2030"),
            bank_row(accountNumber="SYNTHETIC-B"),
        ),
    )
    args = dict(
        source="alfa_csv",
        month=MONTH,
        filename="part.csv",
        content=csv_file(bank_row(amount="600"), bank_row(operationDate="15.10.2030")),
    )
    preview = diary.preview_upload(session, **args)
    assert len(preview["disappearing"]) == 2
    with pytest.raises(ValueError, match="Подтвердите"):
        diary.apply_upload(session, **args, preview_token=preview["preview_token"])
    result = diary.apply_upload(
        session, **args, preview_token=preview["preview_token"], confirm_disappearance=True
    )
    assert result["month"]["total_kopecks"] == 210_000
    rows = session.scalars(select(SpendingOperation)).all()
    assert any(r.operation_date.day == 25 for r in rows)
    assert sum(r.account == "SYNTHETIC-B" for r in rows) == 1


def test_cross_month_operation_date_and_hold_normalization(session):
    content = csv_file(
        bank_row(operationDate="30.09.2030", transactionDate="03.10.2030"),
        bank_row(
            operationDate="31.10.2030", transactionDate="03.11.2030", merchant="МОСКВА/МАГАЗИН"
        ),
    )
    args = dict(source="alfa_csv", month=MONTH, filename="cross.csv", content=content)
    assert diary.preview_upload(session, **args)["outside_month"] == 1
    result = upload(session, content)["month"]
    row = result["operations"][0]
    diary.decide_operation(session, row["id"], action="expense", category="Выбранная")
    changed = csv_file(
        bank_row(
            operationDate="31.10.2030", transactionDate="04.11.2030", merchant="Москва\\Магазин"
        )
    )
    result = upload(session, changed)["month"]
    assert len(result["operations"]) == 1 and result["categories"][0]["category"] == "Выбранная"


def test_hold_changed_description_lost_decision_is_visible_and_no_double_count(session):
    upload(
        session,
        csv_file(bank_row(merchant="МОСКВА/ДЛИННОЕ", status="В обработке", transactionDate="")),
    )
    old = operation(session)
    diary.decide_operation(session, old["id"], action="expense", category="Выбранная")
    changed = csv_file(bank_row(merchant="МОСКВА/ДЛИННОЕ ОПИСАНИЕ"))
    preview = diary.preview_upload(
        session, source="alfa_csv", month=MONTH, filename="new.csv", content=changed
    )
    assert len(preview["decisions_not_transferred"]) == 1
    result = upload(session, changed, confirm_disappearance=True)["month"]
    assert len(result["operations"]) == 1 and result["total_kopecks"] is None
    assert result["operations"][0]["effective_reason"] == "decision_not_transferred"
    assert result["reviews"][0]["previous"]["id"] == old["id"]


def test_ambiguous_duplicate_decision_is_not_carried(session):
    upload(session, csv_file(bank_row(), bank_row()))
    row = operation(session)
    diary.decide_operation(session, row["id"], action="not_spending")
    # A changed group count cannot prove which indistinguishable purchase was excluded.
    result = upload(session, csv_file(bank_row(), bank_row(), bank_row()))["month"]
    assert result["reviews"] and result["total_kopecks"] is None
    assert len(result["operations"]) == 3


@pytest.mark.parametrize("payment", ["альфа", ""])
def test_manual_possible_duplicate_has_no_default_and_preserves_append_decision(session, payment):
    upload(session, csv_file(bank_row()))
    manual = md_file(("03.10", "500", "продукты", "ручная", payment))
    result = upload(session, manual, source="manual_md")["month"]
    assert result["total_kopecks"] == 50_000
    row = operation(session, "possible_duplicate")
    assert row["effective_action"] is None and row["included"] is False
    diary.decide_operation(session, row["id"], action="separate")
    result = upload(
        session,
        md_file(
            ("03.10", "500", "продукты", "ручная", payment),
            ("", "1 500,50", "Подарки", "новая", "нал"),
        ),
        source="manual_md",
    )["month"]
    assert result["total_kopecks"] == 250_050
    assert result["undated_kopecks"] == 150_050


def test_manual_cash_sber_never_matched_and_refund_undated(session):
    upload(session, csv_file(bank_row()))
    result = upload(
        session,
        md_file(
            ("03.10.2030", "500", "Продукты", "наличные", "нал"),
            ("04.10", "500", "Продукты", "сбер", "сбер"),
            ("", "-400", "Возвраты", "ручной возврат", "нал"),
        ),
        source="manual_md",
    )["month"]
    assert result["total_kopecks"] == 110_000
    assert not result["exceptions"]
    assert result["returns_kopecks"] == -40_000
    assert (
        sum(
            __import__("decimal").Decimal(c["share_percent"])
            for c in result["categories"]
            if c["share_percent"]
        )
        == 100
    )


def test_manual_same_duplicate_later_bank_deletion_reopens_decision(session):
    upload(session, csv_file(bank_row(), bank_row(operationDate="04.10.2030")))
    upload(session, md_file(("03.10", "500", "Продукты", "ручная", "альфа")), source="manual_md")
    row = operation(session, "possible_duplicate")
    target = row["duplicate_candidates"][0]
    diary.decide_operation(session, row["id"], action="duplicate", duplicate_of_id=target)
    changed = csv_file(bank_row(amount="600"), bank_row(operationDate="04.10.2030"))
    result = upload(session, changed, confirm_disappearance=True)["month"]
    manual = next(r for r in result["operations"] if r["source"] == "manual_md")
    assert manual["included"] is False and manual["effective_reason"] == "decision_not_transferred"


def test_file_errors_no_replacement_and_manual_explicit_skip(session):
    upload(session, csv_file(bank_row()))
    malformed = csv_file(bank_row(amount="unknown"))
    preview = diary.preview_upload(
        session, source="alfa_csv", month=MONTH, filename="bad.csv", content=malformed
    )
    assert preview["errors"] and not preview["applicable"]
    with pytest.raises(ValueError, match="ошибки"):
        diary.apply_upload(
            session,
            source="alfa_csv",
            month=MONTH,
            filename="bad.csv",
            content=malformed,
            preview_token=preview["preview_token"],
            confirm_disappearance=True,
        )
    assert diary.read_month(session, MONTH)["total_kopecks"] == 50_000
    wrong = md_file(("03.10", "1", "", "", "нал"), month="2030-11")
    with pytest.raises(ValueError, match="month"):
        manual_operations(wrong, MONTH)
    broken = md_file(("31.11", "1", "", "", "нал"), ("", "10", "", "", "нал"))
    parsed = manual_operations(broken, MONTH)
    assert len(parsed["errors"]) == 1 and len(parsed["rows"]) == 1
    result = upload(
        session, broken, source="manual_md", skip_error_lines=[parsed["errors"][0]["line"]]
    )
    assert result["month"]["total_kopecks"] == 51_000


@pytest.mark.parametrize("status", ["draft", "closed"])
def test_month_facts_unchanged_rent_plus_utilities_links_and_recurring(session, status):
    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    expense = create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Коммунальные услуги",
        amount="35000",
        expense_type="mandatory",
        is_recurring=True,
    )
    month.status = status
    session.commit()
    snapshot = {c.name: getattr(expense, c.name) for c in ExpenseEntry.__table__.columns}
    before_total = total_expenses(session, month.id)
    content = csv_file(
        bank_row(
            amount="5000",
            category="Коммунальные услуги",
            merchant="Коммунальные услуги",
            cardNumber="",
        )
    )
    result = upload(session, content)["month"]
    assert result["total_kopecks"] == 4_000_000
    assert {c.name: getattr(expense, c.name) for c in ExpenseEntry.__table__.columns} == snapshot
    assert total_expenses(session, month.id) == before_total
    assert month.status == status
    row = result["operations"][0]
    link = diary.create_link(session, expense.id, [row["id"]], remember=True)
    result = diary.read_month(session, MONTH)
    assert result["total_kopecks"] == 500_000
    assert result["links"][0]["month_amount_kopecks"] == 3_500_000
    assert result["links"][0]["diary_amount_kopecks"] == 500_000
    next_month = create_reporting_month(
        session, year=2030, month=11, snapshot_date=date(2030, 11, 30)
    )
    create_expense_entry(
        session,
        reporting_month_id=next_month.id,
        category=expense.category,
        amount="35000",
        expense_type="mandatory",
        is_recurring=True,
    )
    next_file = csv_file(
        bank_row(
            operationDate="03.11.2030",
            amount="6000",
            category="Коммунальные услуги",
            merchant="Коммунальные услуги",
            cardNumber="",
        )
    )
    result = upload(session, next_file, month="2030-11")["month"]
    assert result["total_kopecks"] == 600_000 and result["links"][0]["remembered"]
    diary.delete_link(session, link)
    assert diary.read_month(session, MONTH)["total_kopecks"] == 4_000_000


def test_link_lost_on_replacement_is_not_silently_double_counted(session):
    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    expense = create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Продукты",
        amount="500",
        expense_type="other",
    )
    upload(session, csv_file(bank_row()))
    diary.create_link(session, expense.id, [operation(session)["id"]])
    result = upload(
        session, csv_file(bank_row(merchant="Другой магазин")), confirm_disappearance=True
    )["month"]
    assert result["total_kopecks"] is None and result["reviews"]
    assert not result["links"][0]["confirmed"]
    assert session.scalar(select(ExpenseEntry)).amount_kopecks == 50_000


def test_unloaded_empty_manual_partial_month_and_stale_preview(session):
    assert diary.read_month(session, MONTH)["total_kopecks"] is None
    assert upload(session, md_file(), source="manual_md")["month"]["total_kopecks"] == 0
    args = dict(
        source="alfa_csv", month=MONTH, filename="synthetic.csv", content=csv_file(bank_row())
    )
    preview = diary.preview_upload(session, **args)
    diary.set_rule(session, scope="merchant", key="МАГАЗИН", action="not_spending")
    with pytest.raises(diary.PreviewChanged):
        diary.apply_upload(session, **args, preview_token=preview["preview_token"])
    result = upload(session, args["content"])["month"]
    assert result["coverage"] == "statement_and_manual" and result["partial"]


def test_bank_refund_direction_identity_negative_month_and_percentages(session):
    upload(
        session,
        csv_file(
            bank_row(amount="1000"),
            bank_row(
                amount="400", type="Пополнение", cardNumber="", status="", category="Продукты"
            ),
        ),
    )
    refund = operation(session, "refund_candidate")
    assert not refund["included"]
    result = diary.decide_operation(session, refund["id"], action="refund", category="Продукты")
    assert result["total_kopecks"] == 60_000 and result["returns_kopecks"] == -40_000
    same_amount = alfa_operations(csv_file(bank_row(), bank_row(type="Пополнение")), MONTH)["rows"]
    assert len({r["fingerprint"] for r in same_amount}) == 2
    later = upload(
        session,
        csv_file(
            bank_row(
                operationDate="03.11.2030",
                amount="400",
                type="Пополнение",
                cardNumber="",
                status="",
            )
        ),
        month="2030-11",
    )["month"]
    diary.decide_operation(
        session, later["operations"][0]["id"], action="refund", category="Продукты"
    )
    later = diary.read_month(session, "2030-11")
    assert later["total_kopecks"] == -40_000
    assert later["categories"][0]["share_percent"] is None
    assert session.scalars(select(ExpenseEntry)).all() == []


def test_preview_choices_apply_and_preserve_category_on_append(session):
    content = csv_file(bank_row(type="Пополнение", cardNumber="", status=""))
    args = dict(source="alfa_csv", month=MONTH, filename="synthetic.csv", content=content)
    preview = diary.preview_upload(session, **args)
    row = preview["after"]["operations"][0]
    choice = dict(
        fingerprint=row["fingerprint"], ordinal=row["ordinal"], action="refund", category="Возвраты"
    )
    preview = diary.preview_upload(session, **args, choices=[choice])
    assert preview["after"]["total_kopecks"] == -50_000
    assert session.scalars(select(SpendingOperation)).all() == []
    diary.apply_upload(session, **args, choices=[choice], preview_token=preview["preview_token"])
    result = upload(
        session,
        csv_file(
            bank_row(type="Пополнение", cardNumber="", status=""),
            bank_row(operationDate="04.10.2030"),
        ),
    )["month"]
    assert result["total_kopecks"] == 0
    assert (
        next(r for r in result["operations"] if r["amount_kopecks"] < 0)["category"] == "Возвраты"
    )


def test_statement_loaded_after_manual_does_not_silently_double_count(session):
    result = upload(
        session, md_file(("03.10", "500", "Продукты", "ручная", "альфа")), source="manual_md"
    )["month"]
    assert result["total_kopecks"] == 50_000
    result = upload(session, csv_file(bank_row()))["month"]
    assert result["total_kopecks"] == 50_000
    assert any(row["effective_reason"] == "possible_duplicate" for row in result["exceptions"])


def test_whole_month_fact_graph_and_read_models_unchanged_by_diary(session):
    from hermes_finance.services.cash_balance import cash_balance_for_month
    from hermes_finance.services.monthly_summary import monthly_summary

    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Аренда",
        amount="35000",
        expense_type="mandatory",
    )
    month.status = "closed"
    session.commit()

    def graph():
        return {
            table.name: session.connection()
            .exec_driver_sql(f'SELECT * FROM "{table.name}"')
            .fetchall()
            for table in Base.metadata.sorted_tables
            if not table.name.startswith("spending_")
        }

    before = graph()
    before_cash = cash_balance_for_month(session, month.id)
    before_summary = monthly_summary(session, month.id)
    upload(session, csv_file(bank_row()))
    assert graph() == before
    session.commit()
    assert cash_balance_for_month(session, month.id) == before_cash
    assert monthly_summary(session, month.id) == before_summary


def test_same_link_survives_status_update_separate_and_rule_invalidates_visible(session):
    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    expense = create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Продукты",
        amount="500",
        expense_type="other",
    )
    upload(session, csv_file(bank_row(status="В обработке", transactionDate="")))
    row = operation(session)
    link_id = diary.create_link(session, expense.id, [row["id"]])
    result = upload(session, csv_file(bank_row()))["month"]
    assert result["total_kopecks"] == 50_000 and result["links"][0]["confirmed"]
    diary.set_rule(session, scope="merchant", key="МАГАЗИН", action="not_spending")
    result = diary.read_month(session, MONTH)
    assert result["total_kopecks"] is None and result["links"][0]["needs_review"]
    diary.delete_link(session, link_id)
    diary.separate_month_expense(session, expense.id)
    assert diary.read_month(session, MONTH)["total_kopecks"] == 50_000


def test_api_multipart_reads_decisions_rules_links_and_private_allowlist(db):
    with TestClient(create_app(db)) as client:
        data = dict(source="alfa_csv", month=MONTH)
        files = {"file": ("synthetic.csv", csv_file(bank_row()), "text/csv")}
        preview = client.post("/api/spending/uploads/preview", data=data, files=files)
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert "SYNTHETIC-A" not in preview.text and "SYNTHETIC-CARD" not in preview.text
        result = client.post(
            "/api/spending/uploads/apply",
            data={**data, "preview_token": body["preview_token"]},
            files=files,
        )
        assert result.status_code == 200, result.text
        row = result.json()["month"]["operations"][0]
        result = client.put(
            f"/api/spending/operations/{row['id']}/decision",
            json=dict(action="expense", category="Еда", remember=True),
        )
        assert result.status_code == 200, result.text
        assert result.json()["categories"][0]["category"] == "Еда"
        assert client.get("/api/spending/rules").json()[0]["key"] == "МАГАЗИН"
        assert client.get(f"/api/spending/months/{MONTH}").json()["total_kopecks"] == 50_000
        assert client.get("/api/spending/months").json()[0]["coverage"] == "statement_only"
        assert (
            client.post(
                "/api/spending/uploads/preview",
                data=data,
                files={"file": ("bad.xlsx", b"PK", "application/octet-stream")},
            ).status_code
            == 422
        )


def test_migration_empty_preserves_old_rows_and_refuses_loss(tmp_path):
    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-migration.db"
    assert run_alembic(path, "upgrade", "0068_owner_manual_gold_history").returncode == 0
    with sqlite3.connect(path) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version'"
            )
        ]
        before = {name: conn.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables}
    applied = run_alembic(path, "upgrade", "head")
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(path) as conn:
        assert {
            name: conn.execute(f'SELECT * FROM "{name}"').fetchall() for name in tables
        } == before
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("SELECT COUNT(*) FROM spending_operations").fetchone() == (0,)
        conn.execute(
            "INSERT INTO spending_categories(name, name_key, expense_type) VALUES ('Synthetic','SYNTHETIC','other')"
        )
    rejected = run_alembic(path, "downgrade", "0068_owner_manual_gold_history")
    assert rejected.returncode != 0 and "cannot discard spending diary data" in rejected.stderr


def test_api_stale_preview_links_separate_category_mapping_and_rollback(db):
    with db.session_factory() as session:
        month = create_reporting_month(
            session, year=2030, month=10, snapshot_date=date(2030, 10, 31)
        )
        expense = create_expense_entry(
            session,
            reporting_month_id=month.id,
            category="Продукты",
            amount="500",
            expense_type="other",
        )
        expense_id = expense.id
    with TestClient(create_app(db)) as client:
        data = dict(source="alfa_csv", month=MONTH)
        files = {"file": ("synthetic.csv", csv_file(bank_row()), "text/csv")}
        first = client.post("/api/spending/uploads/preview", data=data, files=files).json()
        rule = client.put(
            "/api/spending/rules",
            json=dict(scope="bank_category", key="Продукты", action="expense", category="Еда"),
        )
        assert rule.status_code == 200
        stale = client.post(
            "/api/spending/uploads/apply",
            data={**data, "preview_token": first["preview_token"]},
            files=files,
        )
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "preview_changed"
        assert client.get(f"/api/spending/months/{MONTH}").json()["operations"] == []
        preview = client.post("/api/spending/uploads/preview", data=data, files=files).json()
        result = client.post(
            "/api/spending/uploads/apply",
            data={**data, "preview_token": preview["preview_token"]},
            files=files,
        ).json()["month"]
        assert result["total_kopecks"] == 100_000
        operation_id = result["operations"][0]["id"]
        link = client.post(
            "/api/spending/links",
            json=dict(expense_entry_id=expense_id, operation_ids=[operation_id]),
        )
        assert link.status_code == 200
        read = client.get(f"/api/spending/months/{MONTH}").json()
        assert read["total_kopecks"] == 50_000 and read["links"][0]["confirmed"]
        assert client.delete(f"/api/spending/links/{link.json()['id']}").status_code == 200
        assert client.post(f"/api/spending/month-expenses/{expense_id}/separate").status_code == 200
        assert client.get(f"/api/spending/months/{MONTH}").json()["month_link_candidates"] == []
        categories = client.get("/api/spending/categories").json()
        category_id = next(c["id"] for c in categories if c["name"] == "Еда")
        assert (
            client.put(
                f"/api/spending/categories/{category_id}",
                json=dict(name="Питание", expense_type="mandatory"),
            ).status_code
            == 200
        )
        read = client.get(f"/api/spending/months/{MONTH}").json()
        assert read["operations"][0]["category"] == "Питание"
        assert read["operations"][0]["expense_type"] == "mandatory"
        assert (
            client.put(f"/api/spending/categories/{category_id}", json=dict(name="  ")).status_code
            == 422
        )
        assert client.delete(f"/api/spending/rules/{rule.json()['id']}").status_code == 200


def test_error_rows_never_become_zero_and_technical_cannot_be_forced_to_spending(session):
    for value in ("unknown", "NaN", "Infinity", "1.001", "1e3", "0", "-1", "9" * 50):
        parsed = parse_alfa_csv(csv_file(bank_row(amount=value)))
        assert parsed.errors and not parsed.rows
    upload(session, csv_file(bank_row(category="Между своими счетами")))
    technical = operation(session)
    with pytest.raises(ValueError, match="техническая"):
        diary.decide_operation(session, technical["id"], action="expense", category="Продукты")
    parsed = manual_operations(
        md_file(("03.11", "50", "", "", "нал"), ("", "unknown", "", "", "нал")), MONTH
    )
    assert len(parsed["errors"]) == 2 and not parsed["rows"]


def test_lost_receipt_keeps_chosen_category_and_both_link_amounts(session):
    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    expense = create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Еда",
        amount="35000",
        expense_type="mandatory",
    )
    upload(session, csv_file(bank_row()))
    row = operation(session)
    diary.decide_operation(session, row["id"], action="expense", category="Еда")
    diary.create_link(session, expense.id, [row["id"]])
    result = upload(
        session, csv_file(bank_row(merchant="Изменённый продавец")), confirm_disappearance=True
    )["month"]
    previous = result["reviews"][0]["previous"]
    assert previous["decision"] == "expense" and previous["decision_category"] == "Еда"
    assert previous["links"][0]["month_amount_kopecks"] == 3_500_000
    assert previous["links"][0]["diary_amount_kopecks"] == 50_000


def test_changed_bank_class_cannot_turn_confirmed_technical_row_into_spending(session):
    upload(session, csv_file(bank_row()))
    row = operation(session)
    diary.decide_operation(session, row["id"], action="expense", category="Продукты")
    result = upload(session, csv_file(bank_row(category="Между своими счетами")))["month"]
    assert result["total_kopecks"] == 0
    assert result["operations"][0]["effective_reason"] == "technical_decision_conflict"
    assert result["operations"][0]["effective_action"] == "expense"
