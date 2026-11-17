"""Alfa retail CSV v1: lossless row parsing, with no spending/month selection."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

COLUMNS = tuple(
    "operationDate transactionDate accountName accountNumber cardName cardNumber merchant "
    "amount currency status category mcc type comment bonusValue bonusTitle".split()
)
CONTRACT_VERSION = "alfa_csv_v1"


@dataclass(frozen=True)
class AlfaRow:
    line: int
    operation_date: date
    transaction_date: date | None
    amount_kopecks: int
    direction: str
    currency: str
    status: str
    fields: dict[str, str]


@dataclass(frozen=True)
class ParseResult:
    rows: list[AlfaRow]
    errors: list[dict]


def parse_date(value: str) -> date:
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
        raise ValueError("Ожидается дата ДД.ММ.ГГГГ")
    return datetime.strptime(value, "%d.%m.%Y").date()


def parse_alfa_csv(content: bytes) -> ParseResult:
    try:
        stream = io.StringIO(content.decode("utf-8-sig"), newline="")
    except UnicodeDecodeError as error:
        raise ValueError("Выгрузите CSV Альфы в UTF-8; XLSX не поддерживается") from error
    reader = csv.reader(stream, strict=True)
    try:
        if tuple(next(reader, [])) != COLUMNS:
            raise ValueError("Неизвестные заголовки: выгрузите CSV Альфы с 16 колонками")
        rows, errors = [], []
        for values in reader:
            line = reader.line_num
            try:
                if len(values) != len(COLUMNS):
                    raise ValueError("Ожидается 16 колонок")
                fields = dict(zip(COLUMNS, values, strict=True))
                amount = fields["amount"]
                if (
                    not re.fullmatch(r"\d{1,17}(?:\.\d{1,2})?", amount)
                    or Decimal(amount) <= 0
                    or Decimal(amount) * 100 > 9223372036854775807
                ):
                    raise ValueError("Сумма должна быть положительным числом с точкой")
                if fields["type"] not in {"Списание", "Пополнение"}:
                    raise ValueError("Неизвестное направление операции")
                if not fields["accountNumber"] or not fields["currency"]:
                    raise ValueError("Не указан счёт или валюта")
                rows.append(
                    AlfaRow(
                        line,
                        parse_date(fields["operationDate"]),
                        parse_date(fields["transactionDate"])
                        if fields["transactionDate"]
                        else None,
                        int((Decimal(amount) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)),
                        fields["type"],
                        fields["currency"],
                        fields["status"],
                        fields,
                    )
                )
            except ValueError as error:
                # Never echo a private row (account, card, merchant) into diagnostics.
                errors.append(
                    {
                        "line": line,
                        "reason": str(error)
                        if "Ожидается" in str(error) or "Сумма" in str(error) or "Не" in str(error)
                        else "Неверная дата операции",
                    }
                )
    except csv.Error as error:
        raise ValueError("Не удалось прочитать CSV: проверьте кавычки и колонки") from error
    return ParseResult(rows, errors)
