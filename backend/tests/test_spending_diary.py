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
    assert result["total_kopecks"] == 509_000
    assert {r["effective_reason"] for r in result["exceptions"]} == {
        "unknown_technical",
        "foreign_currency",
        "uncategorized",
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
    assert all(row["effective_reason"] == "new_category" for row in result["exceptions"])
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
    assert result["coverage_kind"] == "statement_and_manual" and result["partial"]
    assert result["coverage"]["full"] is False


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
        latest = client.get("/api/spending/months").json()["items"][-1]
        assert latest["has_statement"] and not latest["has_manual"]
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


def named_upload(
    session, content, *, month=MONTH, filename="Statement 01.10.2030 - 31.10.2030.CSV", **kwargs
):
    args = dict(source="alfa_csv", month=month, filename=filename, content=content)
    preview = diary.preview_upload(session, **args)
    return diary.apply_upload(session, **args, preview_token=preview["preview_token"], **kwargs)[
        "month"
    ]


@pytest.mark.parametrize(
    "month,filename,day,full,first,last",
    [
        ("2026-10", "Statement 01.10.2026 - 31.10.2026.CSV", "03.10.2026", True, 1, 31),
        ("2026-10", "Statement 16.10.2026 - 16.11.2026.CSV", "20.10.2026", False, 16, 31),
        ("2026-11", "Statement 16.10.2026 - 16.11.2026.CSV", "03.11.2026", False, 1, 16),
        ("2026-10", "unknown.CSV", "03.10.2026", False, 3, 3),
    ],
)
def test_statement_period_coverage_is_persisted_and_clipped(
    session, month, filename, day, full, first, last
):
    result = named_upload(
        session, csv_file(bank_row(operationDate=day)), month=month, filename=filename
    )
    assert result["coverage"] == {
        "from": date.fromisoformat(month + f"-{first:02d}"),
        "to": date.fromisoformat(month + f"-{last:02d}"),
        "full": full,
    }
    assert result["has_statement"] and not result["has_manual"]
    stored = session.scalar(select(SpendingUpload))
    assert (stored.period_from is not None) == (filename != "unknown.CSV")
    assert stored.date_from == stored.date_to == date.fromisoformat(month + f"-{int(day[:2]):02d}")


def test_full_requires_every_account_and_manual_does_not_change_it(session):
    named_upload(session, csv_file(bank_row(accountNumber="SYNTHETIC-A")))
    result = named_upload(
        session,
        csv_file(bank_row(accountNumber="SYNTHETIC-B")),
        filename="Statement 16.10.2030 - 16.11.2030.CSV",
    )
    assert not result["coverage"]["full"]
    result = upload(session, md_file(), source="manual_md")["month"]
    assert result["has_manual"] and result["has_statement"] and not result["coverage"]["full"]
    result = named_upload(session, csv_file(bank_row(accountNumber="SYNTHETIC-B")))
    assert result["coverage"]["full"]
    assert (
        named_upload(
            session, csv_file(bank_row(accountNumber="SYNTHETIC-B")), filename="unknown.csv"
        )["coverage"]["full"]
        is False
    )


def test_same_bytes_with_new_period_updates_metadata_without_replacing_identity(session):
    first = named_upload(session, csv_file(bank_row()), filename="unknown.csv")
    second = named_upload(session, csv_file(bank_row()))
    assert not first["coverage"]["full"] and second["coverage"]["full"]
    assert first["operations"][0]["id"] == second["operations"][0]["id"]


def test_cardless_savings_debit_and_obsidian_properties(session):
    result = named_upload(
        session,
        csv_file(
            bank_row(cardNumber="", category="Услуги"),
            bank_row(cardNumber="", category="Накопления", amount="99"),
        ),
    )
    assert result["total_kopecks"] == 50_000 and not result["exceptions"]
    assert {row["kind"] for row in result["operations"]} == {"purchase", "transfer"}
    content = md_file(("", "20", "Услуги", "ручная", "нал")).replace(
        b"---\n\n", "tags:\n  - finance\ncssclasses: []\n---\n\n".encode()
    )
    assert len(manual_operations(content, MONTH)["rows"]) == 1
    with pytest.raises(ValueError, match="month"):
        manual_operations(content.replace(b"finance_expenses: 1", b"finance_expenses: 2"), MONTH)


@pytest.mark.parametrize(
    "bank_changes,decision",
    [
        ({"category": "Между своими счетами"}, None),
        ({"category": "Накопления"}, None),
        ({"category": "Переводы СБП"}, None),
        ({}, "not_spending"),
    ],
)
def test_manual_duplicate_candidates_only_counted_statement_rows(session, bank_changes, decision):
    named_upload(session, csv_file(bank_row(**bank_changes)))
    if decision:
        diary.decide_operation(session, operation(session)["id"], action=decision)
    result = upload(
        session, md_file(("03.10", "500", "Продукты", "ручная", "альфа")), source="manual_md"
    )["month"]
    manual = next(row for row in result["operations"] if row["source"] == "manual_md")
    assert manual["included"] and manual["duplicate_candidates"] == []
    assert result["total_kopecks"] == 50_000


def test_history_unloaded_month_has_null_bars_and_known_month_entries(session):
    month = create_reporting_month(session, year=2030, month=9, snapshot_date=date(2030, 9, 30))
    create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Аренда",
        amount="123",
        expense_type="mandatory",
    )
    named_upload(session, csv_file(bank_row()))
    history = diary.list_months(session, until=MONTH, count=2)
    assert len(history["items"]) == 2 and not history["has_more"]
    unloaded, loaded = history["items"]
    assert not unloaded["loaded"] and unloaded["total"] is None
    assert unloaded["by_type"] == dict.fromkeys(("mandatory", "comfortable", "other"))
    assert unloaded["month_entries_total"] == {"amount": "123.00", "currency": "RUB"}
    assert loaded["coverage"]["full"] and loaded["by_type"]["other"]["amount"] == "500.00"
    assert diary.list_months(session, until=MONTH, count=1)["has_more"]


def test_comparison_skips_partial_and_takes_three_latest_full_months(session):
    for number, amount, full in [
        (5, "900", True),
        (6, "100", True),
        (7, "9000", False),
        (8, "200", True),
        (9, "300", True),
        (10, "400", True),
    ]:
        named_upload(
            session,
            csv_file(bank_row(operationDate=f"03.{number:02d}.2030", amount=amount)),
            month=f"2030-{number:02d}",
            filename=f"Statement 01.{number:02d}.2030 - {30 if number in {6, 9} else 31}.{number:02d}.2030.CSV"
            if full
            else "unknown.csv",
        )
    upload(session, md_file(("", "100", "Новая", "наличные", "нал")), source="manual_md")
    result = diary.read_month(session, MONTH)
    comparison = result["comparison"]
    assert comparison["average_total"]["amount"] == "200.00"
    assert comparison["delta_percent"] == "150.00"
    assert comparison["months"] == [
        dict(month=f"2030-{m:02d}", has_manual=False) for m in (6, 8, 9)
    ]
    assert comparison["caveat"] == "missing_manual"
    food = next(category for category in result["categories"] if category["name"] == "Продукты")
    new = next(category for category in result["categories"] if category["name"] == "Новая")
    assert (
        food["average_3m"]["amount"] == "200.00"
        and food["delta_percent"] == "100.00"
        and not food["is_new"]
    )
    assert new["average_3m"]["amount"] == "0.00" and new["delta_percent"] is None and new["is_new"]
    assert diary.read_month(session, "2030-07")["comparison"] is None


def test_shares_sources_processing_returns_top_daily_and_category_history(session):
    from decimal import Decimal

    from hermes_finance.services import spending_insights as insights

    named_upload(
        session,
        csv_file(bank_row(operationDate="02.09.2030", amount="50")),
        month="2030-09",
        filename="Statement 01.09.2030 - 30.09.2030.CSV",
    )
    result = named_upload(
        session,
        csv_file(
            bank_row(amount="100", status="В обработке"),
            bank_row(operationDate="05.10.2030", amount="200", category="Услуги"),
        ),
    )
    result = upload(
        session,
        md_file(
            ("", "30", "Подарки", "без дня", "нал"),
            ("06.10", "40", "Услуги", "сбер", "сбер"),
            ("07.10", "7", "Другое", "без оплаты", ""),
            ("08.10", "-10", "Возврат", "возврат", "нал"),
        ),
        source="manual_md",
    )["month"]
    assert (
        sum(Decimal(category["share_percent"]) for category in result["positive_categories"]) == 100
    )
    assert result["refunds"]["amount"]["amount"] == "-10.00"
    assert result["processing_total"]["amount"] == "100.00"
    assert {key: value["amount"] for key, value in result["by_source"].items()} == dict(
        alfa="300.00", cash="20.00", sber="40.00", manual_other="7.00", month_entries="0.00"
    )
    assert result["cash"] == dict(withdrawn=None, recorded=dict(amount="20.00", currency="RUB"))
    assert len(result["top_purchases"]) == 5
    assert result["top_purchases"][0]["amount"]["amount"] == "200.00"
    assert result["daily"]["current"][2] == dict(
        day=3, cumulative=dict(amount="100.00", currency="RUB")
    )
    assert result["daily"]["current"][-1]["cumulative"]["amount"] == "337.00"
    assert result["daily"]["undated_total"]["amount"] == "30.00"
    assert result["daily"]["previous"]["points"][-1]["cumulative"]["amount"] == "50.00"
    category_id = next(
        category["id"] for category in result["categories"] if category["name"] == "Услуги"
    )
    history = insights.history(session, until=MONTH, count=2, category=category_id)["items"]
    assert [point["total"]["amount"] for point in history] == ["0.00", "240.00"]
    filtered = insights.operations(
        session, diary.read_month_base(session, MONTH), category=category_id, limit=1
    )
    assert (
        filtered["total_count"] == 2
        and filtered["filtered_total"]["amount"] == "240.00"
        and len(filtered["items"]) == 1
    )
    assert (
        insights.operations(session, diary.read_month_base(session, MONTH), source="cash")[
            "filtered_total"
        ]["amount"]
        == "20.00"
    )


def test_daily_previous_reasons_and_current_month_end(session):
    from hermes_finance.services.spending_insights import _daily

    named_upload(session, csv_file(bank_row()))
    assert diary.read_month(session, MONTH)["daily"]["previous_unavailable_reason"] == "not_loaded"
    named_upload(
        session,
        csv_file(bank_row(operationDate="02.09.2030")),
        month="2030-09",
        filename="unknown.csv",
    )
    result = diary.read_month(session, MONTH)
    assert (
        result["daily"]["previous_unavailable_reason"] == "partial"
        and result["daily"]["previous"] is None
    )
    assert len(_daily(result, today=date(2030, 10, 20))) == 3


def test_saved_exceptions_survive_new_session_and_decisions(db):
    from hermes_finance.services import spending_insights as insights

    with db.session_factory() as session:
        named_upload(
            session,
            csv_file(
                bank_row(category="Переводы СБП"),
                bank_row(category=""),
                bank_row(type="Пополнение", status="", amount="70"),
            ),
        )
        session.commit()
    with db.session_factory() as session:
        items = insights.exceptions(session, MONTH)["items"]
        assert {item["group"] for item in items} == {"transfer", "uncategorized", "refund"}
        assert next(item for item in items if item["group"] == "uncategorized")["remember_default"]
        assert not next(item for item in items if item["group"] == "refund")["remember_default"]
        assert diary.read_month(session, MONTH)["open_exceptions"] == dict(
            count=3, excluded_count=2, double_risk_count=0
        )
        result = insights.decide_exceptions(
            session,
            MONTH,
            [
                dict(
                    id=item["id"],
                    action="refund" if item["group"] == "refund" else "expense",
                    category="Еда",
                )
                for item in items
            ],
        )
        assert result["exceptions"]["count"] == 0 and result["month"]["total"]["amount"] == "930.00"


def test_screen_preview_two_files_decisions_duplicate_negative_id_and_atomic_apply(db):
    with TestClient(create_app(db)) as client:
        response = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={
                "statement": (
                    "Statement 01.10.2030 - 31.10.2030.CSV",
                    csv_file(bank_row()),
                    "text/csv",
                ),
                "manual": (
                    "manual.md",
                    md_file(("03.10", "500", "Продукты", "ручная", "альфа")),
                    "text/markdown",
                ),
            },
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["total_after"]["amount"] == "500.00" and preview["coverage"]["full"]
        duplicate = next(
            item for item in preview["exceptions"] if item["group"] == "possible_duplicate"
        )
        candidate = duplicate["candidates"][0]["id"]
        assert candidate < 0
        choice = dict(
            fingerprint=duplicate["fingerprint"],
            ordinal=duplicate["ordinal"],
            action="duplicate",
            duplicate_of_id=candidate,
        )
        response = client.post(
            f"/api/spending/preview/{preview['preview_id']}/decisions", json=dict(choices=[choice])
        )
        assert response.status_code == 200, response.text
        assert (
            response.json()["total_after"]["amount"] == "500.00"
            and not response.json()["exceptions"]
        )
        response = client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={})
        assert response.status_code == 200, response.text
        assert response.json()["month"]["total"]["amount"] == "500.00"
        assert response.json()["month"]["open_exceptions"]["count"] == 0
        assert client.get(f"/api/spending/preview/{preview['preview_id']}").json()["stale"]


def test_screen_preview_recalculates_refund_and_stale_concurrent_apply(db):
    with TestClient(create_app(db)) as client:
        files = {
            "statement": (
                "Statement 01.10.2030 - 31.10.2030.CSV",
                csv_file(bank_row(type="Пополнение", status="")),
                "text/csv",
            )
        }
        first = client.post("/api/spending/preview", data=dict(month=MONTH), files=files).json()
        second = client.post("/api/spending/preview", data=dict(month=MONTH), files=files).json()
        row = first["exceptions"][0]
        updated = client.post(
            f"/api/spending/preview/{first['preview_id']}/decisions",
            json=dict(
                choices=[
                    dict(
                        fingerprint=row["fingerprint"],
                        ordinal=row["ordinal"],
                        action="refund",
                        category="Возвраты",
                    )
                ]
            ),
        ).json()
        assert updated["total_after"]["amount"] == "-500.00" and not updated["exceptions"]
        assert client.get(f"/api/spending/month/{MONTH}").json()["loaded"] is False
        assert (
            client.post(f"/api/spending/preview/{first['preview_id']}/apply", json={}).status_code
            == 200
        )
        assert client.get(f"/api/spending/preview/{second['preview_id']}").json()["stale"]
        rejected = client.post(f"/api/spending/preview/{second['preview_id']}/apply", json={})
        assert rejected.status_code == 409 and rejected.json()["error"]["stale"]


def test_screen_preview_file_error_codes_manual_skip_and_removed_confirmation(db):
    with TestClient(create_app(db)) as client:
        files = {
            "manual": (
                "manual.md",
                md_file(
                    ("", "bad", "Продукты", "ручная", "нал"),
                    ("", "20", "Продукты", "ручная", "нал"),
                ),
                "text/markdown",
            )
        }
        preview = client.post("/api/spending/preview", data=dict(month=MONTH), files=files).json()
        assert (
            preview["file_errors"][0]["code"] == "invalid_amount"
            and "reason" not in preview["file_errors"][0]
        )
        assert not preview["applicable"]
        assert (
            client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={}).status_code
            == 422
        )
        applied = client.post(
            f"/api/spending/preview/{preview['preview_id']}/apply",
            json=dict(skip_unreadable_manual=True),
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["month"]["total"]["amount"] == "20.00"
        empty = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={"manual": ("manual.md", md_file(), "text/markdown")},
        ).json()
        assert empty["removed"] == 1 and empty["sets"][0]["removed_items"]
        assert (
            empty["sets"][0]["total_before"]["amount"] == "20.00"
            and empty["sets"][0]["total_after"]["amount"] == "0.00"
        )
        assert (
            client.post(f"/api/spending/preview/{empty['preview_id']}/apply", json={}).status_code
            == 422
        )
        assert (
            client.post(
                f"/api/spending/preview/{empty['preview_id']}/apply",
                json=dict(confirm_removal=True),
            ).status_code
            == 200
        )


def test_merge_rename_type_and_saved_api_decisions_and_template(db):
    with db.session_factory() as session:
        named_upload(
            session,
            csv_file(bank_row(category="Продукты"), bank_row(category="Услуги", amount="70")),
        )
        session.commit()
    with TestClient(create_app(db)) as client:
        categories = client.get("/api/spending/categories").json()
        assert all(category["expense_type"] == "other" for category in categories)
        first, second = categories
        assert (
            client.patch(
                f"/api/spending/categories/{second['id']}",
                json=dict(name="Общее", expense_type="mandatory"),
            ).status_code
            == 200
        )
        response = client.post(
            f"/api/spending/categories/{first['id']}/merge", json=dict(target_id=second["id"])
        )
        assert response.status_code == 200, response.text
        result = client.get(f"/api/spending/month/{MONTH}").json()
        assert len(result["categories"]) == 1 and result["categories"][0]["name"] == "Общее"
        assert result["by_type"]["mandatory"]["amount"] == "570.00"
        assert (
            client.get(
                f"/api/spending/categories/{second['id']}/history?until={MONTH}&count=1"
            ).json()["items"][0]["total"]["amount"]
            == "570.00"
        )
        rules = client.get("/api/spending/rules").json()
        assert rules and client.delete(f"/api/spending/rules/{rules[0]['id']}").status_code == 200
        template = client.get(f"/api/spending/manual-template?month={MONTH}")
        assert (
            template.status_code == 200
            and f"finance-expenses-{MONTH}.md" in template.headers["content-disposition"]
        )
        assert manual_operations(template.content, MONTH)["rows"] == []


def test_entry_link_preview_both_amounts_operations_and_automatic_next_month(db):
    with db.session_factory() as session:
        month = create_reporting_month(
            session, year=2030, month=10, snapshot_date=date(2030, 10, 31)
        )
        expense = create_expense_entry(
            session,
            reporting_month_id=month.id,
            category="Продукты",
            amount="700",
            expense_type="mandatory",
            is_recurring=True,
        )
        expense_id = expense.id
        session.commit()
    with TestClient(create_app(db)) as client:
        preview = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={
                "statement": (
                    "Statement 01.10.2030 - 31.10.2030.CSV",
                    csv_file(bank_row()),
                    "text/csv",
                )
            },
        ).json()
        assert preview["total_after"]["amount"] == "1200.00"
        entry = next(item for item in preview["exceptions"] if item["group"] == "entry_link")
        operation_id = entry["candidates"][0]["id"]
        updated = client.post(
            f"/api/spending/preview/{preview['preview_id']}/decisions",
            json=dict(
                entry_links=[
                    dict(
                        expense_entry_id=expense_id,
                        action="link",
                        operation_ids=[operation_id],
                        remember=True,
                    )
                ]
            ),
        ).json()
        assert updated["total_after"]["amount"] == "500.00"
        applied = client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={})
        assert applied.status_code == 200, applied.text
        result = applied.json()["month"]
        assert result["entry_links"][0]["month_amount"]["amount"] == "700.00"
        assert result["entry_links"][0]["diary_amount"]["amount"] == "500.00"
        assert not result["entry_links"][0]["automatic"]
        operations = client.get(f"/api/spending/operations?month={MONTH}").json()
        assert (
            len(operations["items"]) == 1
            and operations["items"][0]["linked_entry"]["amount"]["amount"] == "700.00"
        )
        link_id = client.get(f"/api/spending/entry-links?month={MONTH}").json()[0]["id"]
    with db.session_factory() as session:
        month = create_reporting_month(
            session, year=2030, month=11, snapshot_date=date(2030, 11, 30)
        )
        create_expense_entry(
            session,
            reporting_month_id=month.id,
            category="Продукты",
            amount="800",
            expense_type="mandatory",
            is_recurring=True,
        )
        result = named_upload(
            session,
            csv_file(bank_row(operationDate="03.11.2030")),
            month="2030-11",
            filename="Statement 01.11.2030 - 30.11.2030.CSV",
        )
        assert result["entry_links"][0]["automatic"]
        assert (
            result["entry_links"][0]["month_amount"]["amount"] == "800.00"
            and result["total"]["amount"] == "500.00"
        )
        assert result["daily"]["month_entries_total"]["amount"] == "0.00"
        session.commit()
    with TestClient(create_app(db)) as client:
        assert client.delete(f"/api/spending/entry-links/{link_id}").status_code == 200


def test_preview_changed_items_lost_receipts_outside_range_and_cash_hint(session):
    original = csv_file(
        bank_row(status="В обработке", transactionDate=""), bank_row(operationDate="04.10.2030")
    )
    named_upload(session, original)
    diary.decide_operation(session, operation(session)["id"], action="not_spending")
    content = csv_file(
        bank_row(merchant="Другое описание"),
        bank_row(operationDate="04.10.2030", transactionDate="06.10.2030"),
        bank_row(operationDate="05.10.2030", category="Наличные", merchant="ATM"),
        bank_row(operationDate="30.09.2030"),
        bank_row(operationDate="01.11.2030"),
    )
    preview = diary.preview_upload(
        session,
        source="alfa_csv",
        month=MONTH,
        filename="Statement 01.10.2030 - 31.10.2030.CSV",
        content=content,
    )
    assert preview["sets"][0]["changed_items"] and preview["sets"][0]["removed_items"]
    assert preview["out_of_month"] == {
        "count": 2,
        "from": date(2030, 9, 30),
        "to": date(2030, 11, 1),
    }
    lost = next(item for item in preview["exceptions"] if item["carried_over_failed"])
    assert lost["previous_decisions"][0]["decision"] == "not_spending"
    cash = next(item for item in preview["exceptions"] if item["kind_hint"] == "cash_withdrawal")
    assert not cash["counted_now"] and cash["remember_key"] == "ATM"


def test_remembered_preview_rule_recalculates_other_rows_and_apply_matches(db):
    with TestClient(create_app(db)) as client:
        preview = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={
                "statement": (
                    "Statement 01.10.2030 - 31.10.2030.CSV",
                    csv_file(
                        bank_row(category=""), bank_row(category="", operationDate="04.10.2030")
                    ),
                    "text/csv",
                )
            },
        ).json()
        first = preview["exceptions"][0]
        choice = dict(
            fingerprint=first["fingerprint"],
            ordinal=first["ordinal"],
            action="not_spending",
            remember=True,
        )
        updated = client.post(
            f"/api/spending/preview/{preview['preview_id']}/decisions", json=dict(choices=[choice])
        )
        assert updated.status_code == 200, updated.text
        assert (
            updated.json()["total_after"]["amount"] == "0.00" and updated.json()["exceptions"] == []
        )
        applied = client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={})
        assert applied.status_code == 200, applied.text
        assert applied.json()["month"]["total"]["amount"] == "0.00"
        assert client.get("/api/spending/rules").json()[0]["action"] == "not_spending"


def test_account_mask_never_exposes_full_number_in_any_endpoint(db):
    account, card = "99990000111122223333", "9999888877776666"
    responses = []
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
        session.commit()
    with TestClient(create_app(db)) as client:

        def call(method, url, **kwargs):
            response = getattr(client, method)("/api/spending" + url, **kwargs)
            assert response.status_code == 200, response.text
            assert account not in response.text and card not in response.text
            responses.append((method, url))
            return (
                response.json()
                if "json" in response.headers.get("content-type", "")
                else response.text
            )

        files = {
            "file": (
                "Statement 01.10.2030 - 31.10.2030.CSV",
                csv_file(
                    bank_row(
                        accountNumber=account,
                        accountName="Синтетический счёт",
                        cardNumber=card,
                        merchant="МОСКВА/МАГАЗИН " + account + " " + card,
                        category="",
                    )
                ),
                "text/csv",
            )
        }
        data = dict(month=MONTH, source="alfa_csv")
        unsaved = call(
            "post", "/preview", data=dict(month=MONTH), files={"statement": files["file"]}
        )
        call("get", f"/preview/{unsaved['preview_id']}")
        preview = call("post", "/uploads/preview", data=data, files=files)
        assert preview["sets"][0]["label"] == "Синтетический счёт ··3333"
        result = call(
            "post",
            "/uploads/apply",
            data={**data, "preview_token": preview["preview_token"]},
            files=files,
        )
        operation_id = result["month"]["operations"][0]["id"]
        for url in (
            f"/months?until={MONTH}&count=12",
            f"/month/{MONTH}",
            f"/months/{MONTH}",
            f"/operations?month={MONTH}",
            f"/exceptions?month={MONTH}",
            "/categories",
            "/rules",
            f"/entry-links?month={MONTH}",
            f"/manual-template?month={MONTH}",
        ):
            call("get", url)
        saved = call("get", f"/exceptions?month={MONTH}")["items"][0]
        call(
            "post",
            f"/exceptions/decisions?month={MONTH}",
            json=dict(decisions=[dict(id=saved["id"], action="expense", category="Продукты")]),
        )
        call(
            "put",
            f"/operations/{operation_id}/decision",
            json=dict(action="expense", category="Продукты", remember=True),
        )
        category_id = call("get", "/categories")[-1]["id"]
        call("put", f"/categories/{category_id}", json=dict(name="Питание"))
        call("patch", f"/categories/{category_id}", json=dict(expense_type="mandatory"))
        call("get", f"/categories/{category_id}/history?until={MONTH}&count=1")
        rule_id = call(
            "put",
            "/rules",
            json=dict(scope="merchant", key="Другой продавец", action="not_spending"),
        )["id"]
        call("delete", f"/rules/{rule_id}")
        link_id = call(
            "post", "/links", json=dict(expense_entry_id=expense_id, operation_ids=[operation_id])
        )["id"]
        call("get", "/entry-links")
        call("delete", f"/links/{link_id}")
        link_id = call(
            "post", "/links", json=dict(expense_entry_id=expense_id, operation_ids=[operation_id])
        )["id"]
        call("delete", f"/entry-links/{link_id}")
        call("post", f"/month-expenses/{expense_id}/separate")
        screen = call(
            "post", "/preview", data=dict(month=MONTH), files={"statement": files["file"]}
        )
        call("get", f"/preview/{screen['preview_id']}")
        call("post", f"/preview/{screen['preview_id']}/decisions", json={})
        call("post", f"/preview/{screen['preview_id']}/apply", json={})
        # Exercise lost-decision receipts and their acknowledgement as API responses too.
        changed = {
            "file": (
                "Statement 01.10.2030 - 31.10.2030.CSV",
                csv_file(
                    bank_row(accountNumber=account, cardNumber=card, merchant="Изменённый продавец")
                ),
                "text/csv",
            )
        }
        preview = call("post", "/uploads/preview", data=data, files=changed)
        result = call(
            "post",
            "/uploads/apply",
            data={
                **data,
                "preview_token": preview["preview_token"],
                "confirm_disappearance": "true",
            },
            files=changed,
        )
        review = result["month"]["reviews"][0]
        call("post", f"/reviews/{review['id']}/acknowledge")
        category_ids = [category["id"] for category in call("get", "/categories")]
        call("post", f"/categories/{category_ids[0]}/merge", json=dict(target_id=category_ids[-1]))
    assert len(responses) >= 30


def test_complementary_statement_periods_close_gaps_without_widening_replacement(session):
    first = named_upload(
        session, csv_file(bank_row()), filename="Statement 01.10.2030 - 15.10.2030.CSV"
    )
    assert not first["coverage"]["full"]
    gap = named_upload(
        session,
        csv_file(bank_row(operationDate="25.10.2030")),
        filename="Statement 17.10.2030 - 31.10.2030.CSV",
    )
    assert not gap["coverage"]["full"] and len(gap["operations"]) == 2
    complete = named_upload(
        session,
        csv_file(bank_row(operationDate="16.10.2030")),
        filename="Statement 16.10.2030 - 16.10.2030.CSV",
    )
    assert complete["coverage"]["full"] and len(complete["operations"]) == 3
    assert {row["operation_date"].day for row in complete["operations"]} == {3, 16, 25}


def test_manual_new_category_is_counted_and_open_until_explicit_decision(session):
    from hermes_finance.services import spending_insights as insights

    content = md_file(("", "10", "Новая категория", "покупка", "нал"))
    result = upload(session, content, source="manual_md")["month"]
    exception = insights.exceptions(session, MONTH)["items"][0]
    assert exception["group"] == "new_category" and exception["counted_now"]
    assert result["total"]["amount"] == "10.00"
    assert not exception["remember_default"] and result["categories"][0]["type"] == "other"
    repeated = upload(session, content, source="manual_md")
    assert repeated["changed"] is False
    insights.decide_exceptions(
        session, MONTH, [dict(id=exception["id"], action="expense", category="Новая категория")]
    )
    assert insights.exceptions(session, MONTH)["count"] == 0


def test_month_entry_only_category_has_readonly_id_and_history_without_writes(session):
    from hermes_finance.services import spending_insights as insights

    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    create_expense_entry(
        session,
        reporting_month_id=month.id,
        category="Только в отчёте",
        amount="80",
        expense_type="mandatory",
    )
    upload(session, md_file(), source="manual_md")
    result = diary.read_month(session, MONTH)
    category_id = result["categories"][0]["id"]
    assert -(2**53) < category_id < 0
    assert (
        insights.history(session, until=MONTH, count=1, category=category_id)["items"][0]["total"][
            "amount"
        ]
        == "80.00"
    )
    assert insights.operations(
        session, diary.read_month_base(session, MONTH), category=category_id
    )["items"][0]["is_month_entry"]
    assert result["daily"]["undated_total"]["amount"] == "0.00"
    assert result["daily"]["month_entries_total"]["amount"] == "80.00"
    assert result["top_purchases"] == []
    assert session.scalar(select(diary.SpendingCategory)) is None


def test_preview_failed_apply_rolls_back_both_files(db, monkeypatch):
    with db.session_factory() as session:
        month = create_reporting_month(
            session, year=2030, month=10, snapshot_date=date(2030, 10, 31)
        )
        expense = create_expense_entry(
            session,
            reporting_month_id=month.id,
            category="Продукты",
            amount="100",
            expense_type="other",
        )
        expense_id = expense.id
        session.commit()
    with TestClient(create_app(db)) as client:
        preview = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={
                "statement": (
                    "Statement 01.10.2030 - 31.10.2030.CSV",
                    csv_file(bank_row()),
                    "text/csv",
                ),
                "manual": (
                    "manual.md",
                    md_file(("", "70", "Подарки", "ручная", "нал")),
                    "text/markdown",
                ),
            },
        ).json()
        operation_id = next(
            row["id"] for row in preview["operations"] if row["source"] == "alfa_csv"
        )
        updated = client.post(
            f"/api/spending/preview/{preview['preview_id']}/decisions",
            json=dict(
                entry_links=[
                    dict(expense_entry_id=expense_id, action="link", operation_ids=[operation_id])
                ]
            ),
        )
        assert updated.status_code == 200

        def fail(*args, **kwargs):
            raise ValueError("synthetic apply failure")

        monkeypatch.setattr(diary, "create_link", fail)
        assert (
            client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={}).status_code
            == 422
        )
        result = client.get(f"/api/spending/month/{MONTH}").json()
        assert result["operations"] == [] and not result["loaded"]
        assert not client.get(f"/api/spending/preview/{preview['preview_id']}").json()["stale"]
    with db.session_factory() as session:
        assert session.scalar(select(SpendingUpload)) is None
        assert len(session.scalars(select(ExpenseEntry)).all()) == 1


def test_migration_t1_metadata_and_classification_preserve_decisions(tmp_path):
    from _migration_helpers import run_alembic

    path = tmp_path / "synthetic-t1-upgrade.db"
    assert run_alembic(path, "upgrade", "0069_spending_diary").returncode == 0
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO spending_uploads(id,source,month,account,filename,sha256,date_from,date_to,uploaded_at) VALUES (1,'alfa_csv','2030-10','SYNTHETIC-A','Statement 01.10.2030 - 31.10.2030.CSV',?,'2030-10-03','2030-10-03','2030-11-05')",
            ("1" * 64,),
        )
        for index, category in enumerate(("Услуги", "Накопления"), 1):
            conn.execute(
                "INSERT INTO spending_operations(upload_id,source,month,operation_date,amount_kopecks,direction,currency,status,category,description,account,card,payment,kind,reason,merchant_key,fingerprint,ordinal,raw_json,decision,needs_review) VALUES (1,'alfa_csv','2030-10','2030-10-03',50000,'Списание','RUR','Выполнен',?,'Синтетика','SYNTHETIC-A','','альфа','exception','unknown_cardless','СИНТЕТИКА',?,1,?,'not_spending',0)",
                (category, str(index) * 64, '{"accountName":"Синтетический"}'),
            )
    applied = run_alembic(path, "upgrade", "head")
    assert applied.returncode == 0, applied.stderr
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT period_from,period_to,account_name,date_from,date_to FROM spending_uploads"
        ).fetchone() == ("2030-10-01", "2030-10-31", "Синтетический", "2030-10-03", "2030-10-03")
        assert conn.execute(
            "SELECT kind,reason,decision FROM spending_operations ORDER BY id"
        ).fetchall() == [("purchase", None, "not_spending"), ("transfer", None, "not_spending")]
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
    rejected = run_alembic(path, "downgrade", "0069_spending_diary")
    assert (
        rejected.returncode != 0 and "cannot discard statement coverage metadata" in rejected.stderr
    )


@pytest.mark.parametrize(
    "filename,content,field,code",
    [
        ("bad.xlsx", b"PK", "statement", "unsupported_extension"),
        ("bad.csv", b"bad,header\n", "statement", "csv_headers"),
        ("manual.md", md_file(month="2030-09"), "manual", "month_mismatch"),
        ("manual.md", b"no frontmatter", "manual", "missing_frontmatter"),
    ],
)
def test_screen_file_errors_are_codes_with_safe_parameters(db, filename, content, field, code):
    with TestClient(create_app(db)) as client:
        response = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={field: (filename, content, "application/octet-stream")},
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        assert not preview["applicable"] and preview["file_errors"][0]["code"] == code
        assert (
            "message" not in preview["file_errors"][0] and "reason" not in preview["file_errors"][0]
        )
        if code == "month_mismatch":
            assert preview["file_errors"][0]["file_month"] == "2030-09"
        assert (
            client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={}).status_code
            == 422
        )
        assert not client.get(f"/api/spending/month/{MONTH}").json()["loaded"]


def test_foreign_explicit_not_spending_resolves_without_mixing_currency(session):
    from hermes_finance.services import spending_insights as insights

    named_upload(session, csv_file(bank_row(currency="USD")))
    item = insights.exceptions(session, MONTH)["items"][0]
    assert item["amount"]["currency"] == "USD" and not item["counted_now"]
    result = insights.decide_exceptions(
        session, MONTH, [dict(id=item["id"], action="not_spending")]
    )
    assert result["exceptions"]["count"] == 0 and result["month"]["total"]["amount"] == "0.00"


def test_preview_before_distinguishes_loaded_empty_set_from_absent_account(session):
    upload(session, md_file(), source="manual_md")
    empty = diary.preview_upload(
        session, source="manual_md", month=MONTH, filename="manual.md", content=md_file()
    )
    assert empty["total_before"]["amount"] == "0.00"
    assert empty["sets"][0]["total_before"]["amount"] == "0.00"
    bank = diary.preview_upload(
        session,
        source="alfa_csv",
        month=MONTH,
        filename="synthetic.csv",
        content=csv_file(bank_row()),
    )
    assert bank["total_before"]["amount"] == "0.00" and bank["sets"][0]["total_before"] is None


def test_category_history_month_entries_are_filtered(session):
    from hermes_finance.services import spending_insights as insights

    month = create_reporting_month(session, year=2030, month=10, snapshot_date=date(2030, 10, 31))
    for name, amount in (("Первая", "70"), ("Вторая", "90")):
        create_expense_entry(
            session,
            reporting_month_id=month.id,
            category=name,
            amount=amount,
            expense_type="mandatory",
        )
    upload(session, md_file(), source="manual_md")
    category_id = next(
        category["id"]
        for category in diary.read_month(session, MONTH)["categories"]
        if category["name"] == "Первая"
    )
    item = insights.history(session, until=MONTH, count=1, category=category_id)["items"][0]
    assert item["total"]["amount"] == item["month_entries_total"]["amount"] == "70.00"


def test_preview_skip_is_preserved_when_next_decision_omits_skip_field(db):
    with TestClient(create_app(db)) as client:
        response = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={
                "manual": (
                    "manual.md",
                    md_file(
                        ("", "bad", "Продукты", "ошибка", "нал"),
                        ("", "70", "Новая", "ручная", "нал"),
                    ),
                    "text/markdown",
                )
            },
        )
        preview = response.json()
        preview_id = preview["preview_id"]
        line = preview["file_errors"][0]["line"]
        skipped = client.post(
            f"/api/spending/preview/{preview_id}/decisions", json=dict(skip_error_lines=[line])
        ).json()
        assert skipped["applicable"] and not skipped["blocking"]["unreadable_manual_rows"]
        row = skipped["exceptions"][0]
        chosen = client.post(
            f"/api/spending/preview/{preview_id}/decisions",
            json=dict(
                choices=[
                    dict(
                        fingerprint=row["fingerprint"],
                        ordinal=row["ordinal"],
                        action="expense",
                        category="Новая",
                    )
                ]
            ),
        ).json()
        assert chosen["applicable"] and not chosen["blocking"]["unreadable_manual_rows"]
        assert client.post(f"/api/spending/preview/{preview_id}/apply", json={}).status_code == 200


def test_combined_preview_does_not_defer_manual_category_created_by_statement(db):
    with TestClient(create_app(db)) as client:
        preview = client.post(
            "/api/spending/preview",
            data=dict(month=MONTH),
            files={
                "statement": (
                    "Statement 01.10.2030 - 31.10.2030.CSV",
                    csv_file(bank_row()),
                    "text/csv",
                ),
                "manual": (
                    "manual.md",
                    md_file(("", "70", "Продукты", "ручная", "нал")),
                    "text/markdown",
                ),
            },
        ).json()
        assert preview["exceptions"] == []
        response = client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={})
        assert response.status_code == 200, response.text
        assert response.json()["month"]["open_exceptions"]["count"] == 0
        assert response.json()["month"]["total"]["amount"] == "570.00"


@pytest.mark.parametrize("invalid", ["manual_format", "manual_row", "csv_row"])
def test_screen_preview_applies_only_valid_input(db, invalid):
    good_manual = md_file(("02.10", "150", "Продукты", "Синтетическая покупка", "нал"))
    good_statement = csv_file(bank_row())
    manual = {
        "manual_format": b"invalid",
        "manual_row": md_file(("02.10", "invalid", "Продукты", "Синтетическая покупка", "нал")),
    }.get(invalid, good_manual)
    statement = (
        csv_file(bank_row(), bank_row(amount="invalid")) if invalid == "csv_row" else good_statement
    )
    with TestClient(create_app(db)) as client:
        response = client.post(
            "/api/spending/preview",
            data={"month": MONTH},
            files={"statement": ("test.csv", statement), "manual": ("test.md", manual)},
        )
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["applicable"]
        assert len(preview["file_errors"]) == 1
        assert [item["kind"] for item in preview["sets"]] == [
            "manual" if invalid == "csv_row" else "statement"
        ]
        expected = "150.00" if invalid == "csv_row" else "500.00"
        assert preview["total_after"]["amount"] == expected
        result = client.post(f"/api/spending/preview/{preview['preview_id']}/apply", json={})
        assert result.status_code == 200, result.text
        saved = client.get(f"/api/spending/months/{MONTH}").json()
        assert saved["total"]["amount"] == expected
        assert saved["has_manual"] == (invalid == "csv_row")
        assert saved["has_statement"] == (invalid != "csv_row")
