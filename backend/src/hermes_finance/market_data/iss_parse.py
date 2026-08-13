"""Deterministic MOEX ISS ``columns`` + ``data`` parsing by column name."""

from __future__ import annotations

import json
from decimal import Decimal, DecimalException
from typing import Any


class IssParseError(ValueError):
    """ISS payload cannot be interpreted as named column tables."""


def load_iss_json(text: str) -> Any:
    """Decode ISS JSON keeping numeric tokens as text."""

    try:
        return json.loads(text, parse_float=str, parse_int=str)
    except json.JSONDecodeError as error:
        raise IssParseError("response is not valid JSON") from error


def row_get(row: dict[str, object], *names: str) -> object:
    lookup = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lookup:
            return lookup[name.lower()]
    return None


def row_text(row: dict[str, object], *names: str) -> str | None:
    value = row_get(row, *names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_iss_table(block: object) -> list[dict[str, object]]:
    if not isinstance(block, dict):
        raise IssParseError("ISS table must be an object")
    columns = block.get("columns")
    data = block.get("data")
    if not isinstance(columns, list) or not isinstance(data, list):
        raise IssParseError("ISS table must contain columns and data lists")

    names: list[str] = []
    for column in columns:
        if column is None or isinstance(column, bool):
            raise IssParseError("ISS column name is missing")
        names.append(str(column))

    rows: list[dict[str, object]] = []
    for raw_row in data:
        if not isinstance(raw_row, list):
            raise IssParseError("ISS data row must be a list")
        mapped: dict[str, object] = {}
        for index, name in enumerate(names):
            mapped[name] = raw_row[index] if index < len(raw_row) else None
        rows.append(mapped)
    return rows


def parse_iss_payload(payload: object) -> dict[str, list[dict[str, object]]]:
    if not isinstance(payload, dict):
        raise IssParseError("ISS payload must be an object")
    tables: dict[str, list[dict[str, object]]] = {}
    for name, block in payload.items():
        if isinstance(block, dict) and "columns" in block and "data" in block:
            tables[str(name)] = parse_iss_table(block)
    return tables


def description_map(rows: list[dict[str, object]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in rows:
        name = row_text(row, "name")
        value = row_text(row, "value")
        if name is not None and value is not None:
            values[name.upper()] = value
    return values


def decimal_from_external(value: object, *, name: str = "value") -> Decimal:
    """Parse an ISS numeric token without financial arithmetic on binary float."""

    if isinstance(value, bool) or value is None:
        raise IssParseError(f"{name} is missing or not numeric")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except DecimalException as error:
            raise IssParseError(f"{name} is not a decimal") from error
    elif isinstance(value, float):
        # JSON libraries may materialize float; convert only via its text form.
        try:
            amount = Decimal(format(value, ".15g"))
        except DecimalException as error:
            raise IssParseError(f"{name} is not a decimal") from error
    else:
        raise IssParseError(f"{name} is not a decimal")
    if not amount.is_finite():
        raise IssParseError(f"{name} must be finite")
    return amount
