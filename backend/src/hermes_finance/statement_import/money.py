"""Exact Decimal parsing for depository income-report cells.

Financial values never round-trip through binary float. Layout coordinates
are not handled here.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from hermes_finance.domain import RubleAmount

_DASH_CELLS = {
    "",
    "-",
    "—",
    "–",
    "−",
    "нет",
    "н/д",
    "н/а",
    "na",
    "n/a",
}
_SPACE_RE = re.compile(r"[\s\u00a0\u202f\u2009]+")
_AMOUNT_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_TRAILING_CURRENCY_RE = re.compile(
    r"(руб\.?|rur|rub|usd|eur|cny|gbp|kzt|₽)$",
    re.IGNORECASE,
)
INVALID = Ellipsis


def fold_text(value: str) -> str:
    collapsed = _SPACE_RE.sub(" ", value.replace("ё", "е").replace("Ё", "Е"))
    return collapsed.strip().lower()


def is_dash_cell(value: str | None) -> bool:
    if value is None:
        return True
    return fold_text(value) in _DASH_CELLS


def parse_report_date(value: str | None) -> date | None | object:
    """Parse DD.MM.YYYY. None = dash/empty. INVALID = malformed."""

    if value is None or is_dash_cell(value):
        return None
    text = _SPACE_RE.sub("", value.strip())
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return INVALID


def _normalize_decimal_text(value: str) -> str:
    text = _SPACE_RE.sub("", value.strip())
    text = text.replace("%", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return text


def parse_decimal(value: object | None) -> Decimal | None | object:
    """Parse an exact decimal cell.

    None = dash/missing. INVALID = malformed. Never accepts float.
    """

    if isinstance(value, float):
        raise TypeError("binary float is not allowed")
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else INVALID
    text = str(value)
    if is_dash_cell(text):
        return None
    normalized = _normalize_decimal_text(text)
    if not _AMOUNT_RE.fullmatch(normalized):
        return INVALID
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return INVALID
    if not amount.is_finite():
        return INVALID
    return amount


def normalize_currency(value: str | None) -> str | None:
    if value is None or is_dash_cell(value):
        return None
    key = _SPACE_RE.sub("", value).strip().upper().replace("Ё", "Е")
    key = key.replace("РУБ.", "РУБ")
    if key in {"RUB", "RUR", "РУБ", "₽"}:
        return "RUB"
    if key.isalpha() and 3 <= len(key) <= 4:
        return key
    return None


def split_amount_and_currency(value: str | None) -> tuple[object, str | None]:
    """Return (Decimal|None|INVALID, currency_or_None)."""

    if value is None or is_dash_cell(value):
        return None, None
    raw = _SPACE_RE.sub(" ", str(value)).strip()
    parts = raw.split(" ")
    currency: str | None = None
    amount_text = raw
    if len(parts) >= 2:
        maybe = normalize_currency(parts[-1])
        if maybe is not None:
            currency = maybe
            amount_text = " ".join(parts[:-1])
    else:
        glued = raw.replace(" ", "")
        match = _TRAILING_CURRENCY_RE.search(glued)
        if match:
            currency = normalize_currency(match.group(1))
            amount_text = glued[: match.start()]
    return parse_decimal(amount_text), currency


def kopecks(amount: Decimal) -> int:
    return RubleAmount.from_decimal(amount).kopecks
