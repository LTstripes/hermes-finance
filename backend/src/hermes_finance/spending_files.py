"""Pure spending-file adapters and conservative classification; no persistence."""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from hermes_finance.alfa_csv import AlfaRow, parse_alfa_csv, parse_date

VERSION = "spending_diary_v1"
UNCATEGORIZED = "Без категории"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()


def normalize(value: str) -> str:
    return " ".join(value.replace("/", "\\").split()).upper()


def merchant_key(description: str) -> str:
    value = normalize(description)
    # Only a recognisable city prefix, never arbitrary slash-separated descriptions.
    if re.fullmatch(r"(?:Г\.? )?(?:МОСКВА|MOSCOW|САНКТ-ПЕТЕРБУРГ|SPB|КАЗАНЬ|KAZAN)\\[^\\]+", value):
        return value.split("\\", 1)[1]
    return value


def month_bounds(month: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("Месяц должен иметь формат ГГГГ-ММ")
    try:
        year, number = map(int, month.split("-"))
        return date(year, number, 1), date(year, number, calendar.monthrange(year, number)[1])
    except ValueError as error:
        raise ValueError("Неверный месяц") from error


def classify_alfa(row: AlfaRow) -> tuple[str, str | None]:
    f = row.fields
    category = normalize(f["category"])
    description = normalize(f["merchant"] or f["comment"])
    if row.currency != "RUR":
        return "exception", "foreign_currency"
    if row.status not in {"", "Выполнен", "В обработке"}:
        return "exception", "unknown_status"
    if category == "МЕЖДУ СВОИМИ СЧЕТАМИ":
        return "transfer", None
    if category == "КРЕДИТЫ" and "ПОГАШЕНИЕ ОД" in description:
        return "repayment", None
    if category == "НАКОПЛЕНИЯ" and row.direction == "Пополнение":
        return "interest", None
    if any(word in category + " " + description for word in ("ПЕРЕВОД", "СБП", "С КАРТЫ НА КАРТУ")):
        return "exception", "transfer_decision"
    if any(word in category + " " + description for word in ("НАЛИЧН", "БАНКОМАТ", "ATM")):
        return "exception", "cash_withdrawal_decision"
    if any(
        word in category + " " + description
        for word in ("КРЕДИТ", "ПРОЦЕНТ", "КОМИСС", "ОБСЛУЖИВАН")
    ):
        return "exception", "unknown_technical"
    if row.direction == "Пополнение":
        return "exception", "refund_candidate"
    if not f["cardNumber"] and category != "КОММУНАЛЬНЫЕ УСЛУГИ":
        return "exception", "unknown_cardless"
    return "purchase", "uncategorized" if not f["category"].strip() else None


def _ordinals(rows: list[dict]) -> list[dict]:
    counts = Counter()
    for row in rows:
        counts[row["fingerprint"]] += 1
        row["ordinal"] = counts[row["fingerprint"]]
    return rows


def alfa_operations(content: bytes, month: str) -> dict:
    start, end = month_bounds(month)
    parsed = parse_alfa_csv(content)
    rows, outside = [], 0
    for r in parsed.rows:
        if not start <= r.operation_date <= end:
            outside += 1
            continue
        f = r.fields
        description = f["merchant"] or f["comment"]
        kind, reason = classify_alfa(r)
        rows.append(
            dict(
                operation_date=r.operation_date,
                transaction_date=r.transaction_date,
                amount_kopecks=r.amount_kopecks * (1 if r.direction == "Списание" else -1),
                direction=r.direction,
                currency=r.currency,
                status=r.status,
                category=f["category"].strip() or UNCATEGORIZED,
                description=description,
                account=f["accountNumber"],
                card=f["cardNumber"],
                payment="альфа",
                kind=kind,
                reason=reason,
                merchant_key=merchant_key(description),
                fingerprint=digest(
                    [
                        f["accountNumber"],
                        f["cardNumber"],
                        r.operation_date,
                        r.direction,
                        r.amount_kopecks,
                        r.currency,
                        normalize(description),
                    ]
                ),
                raw_json=json.dumps(f, ensure_ascii=False),
                line=r.line,
            )
        )
    return dict(rows=_ordinals(rows), errors=parsed.errors, outside_month=outside)


def manual_operations(content: bytes, month: str) -> dict:
    start, end = month_bounds(month)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Ручной файл должен быть UTF-8 Markdown") from error
    front = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.S)
    if not front:
        raise ValueError("Нужен frontmatter finance_expenses: 1 и month")
    fields = {}
    for line in front[1].splitlines():
        key, sep, value = line.partition(":")
        if not sep or key.strip() in fields:
            raise ValueError("Неверный frontmatter")
        fields[key.strip()] = value.strip()
    if fields != {"finance_expenses": "1", "month": month}:
        raise ValueError("Версия finance_expenses или month не совпадает")
    rows, errors, header, separator = [], [], False, False
    for number, line in enumerate(
        text[front.end() :].splitlines(), 1 + text[: front.end()].count("\n")
    ):
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not header:
            if cells != ["Дата", "Сумма", "Категория", "Описание", "Оплата"]:
                raise ValueError("Ожидаются колонки Дата | Сумма | Категория | Описание | Оплата")
            header = True
            continue
        if not separator:
            if len(cells) != 5 or not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                raise ValueError("Неверный разделитель таблицы")
            separator = True
            continue
        try:
            if len(cells) != 5:
                raise ValueError("Ожидается пять колонок")
            when, amount, category, description, payment = cells
            when = parse_date(when + f".{start.year}" if len(when) == 5 else when) if when else None
            if when and not start <= when <= end:
                raise ValueError("Дата вне выбранного месяца")
            amount = re.sub(r"[ \u00a0]", "", amount).replace(",", ".")
            if (
                not re.fullmatch(r"-?\d{1,17}(?:\.\d{1,2})?", amount)
                or Decimal(amount) == 0
                or abs(Decimal(amount)) * 100 > 9223372036854775807
            ):
                raise ValueError("Нужна ненулевая сумма в рублях")
            kopecks = int((Decimal(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
            payment = payment.casefold()
            if payment not in {"нал", "сбер", "альфа", ""}:
                raise ValueError("Неизвестный способ оплаты")
            category = category or UNCATEGORIZED
            rows.append(
                dict(
                    operation_date=when,
                    transaction_date=None,
                    amount_kopecks=kopecks,
                    direction="Списание" if kopecks > 0 else "Пополнение",
                    currency="RUR",
                    status="",
                    category=category,
                    description=description,
                    account="",
                    card="",
                    payment=payment,
                    kind="purchase" if kopecks > 0 else "refund",
                    reason=None,
                    merchant_key=merchant_key(description),
                    fingerprint=digest(
                        [when, kopecks, normalize(category), normalize(description), payment]
                    ),
                    raw_json="{}",
                    line=number,
                )
            )
        except ValueError as error:
            errors.append(
                {
                    "line": number,
                    "reason": str(error)
                    if not str(error).startswith("time data")
                    else "Неверная дата",
                }
            )
    if not separator:
        raise ValueError("Не найдена таблица ручных трат")
    return dict(rows=_ordinals(rows), errors=errors, outside_month=0)
