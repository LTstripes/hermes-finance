"""Explicit local crosswalk edits and derived-link refresh; no identity inference."""

import csv
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from hermes_finance.domain.money_security import normalize_registration_number
from hermes_finance.persistence import (
    ReportingMonth,
    SecurityRegIsinMapping,
    SourceIntakeOriginal,
    SourceMoneyClassification,
)
from hermes_finance.services import source_intake
from hermes_finance.services.money_instrument_links import (
    MoneyInstrumentResolver,
    apply_money_instrument_link,
)


def _validated(reg_number, isin, note):
    reg_number = normalize_registration_number(reg_number)
    isin = isin.strip().upper()
    # Same format contract as source_intake.InstrumentIdentity; no checksum inference.
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin) is None:
        raise ValueError("isin_invalid")
    return reg_number, isin, (note.strip() or None) if note is not None else None


def _as_dict(row):
    return {
        "id": row.id,
        "reg_number": row.reg_number,
        "isin": row.isin,
        "note": row.note,
        "created_at": row.created_at.replace(tzinfo=UTC).isoformat(),
        "updated_at": row.updated_at.replace(tzinfo=UTC).isoformat(),
    }


def list_mappings(session):
    return [
        _as_dict(row)
        for row in session.scalars(
            select(SecurityRegIsinMapping).order_by(SecurityRegIsinMapping.reg_number)
        )
    ]


def _upsert(session, reg_number, isin, note):
    row = session.scalar(
        select(SecurityRegIsinMapping).where(SecurityRegIsinMapping.reg_number == reg_number)
    )
    now = datetime.now(UTC)
    changed = row is None or (row.isin, row.note) != (isin, note)
    if row is None:
        row = SecurityRegIsinMapping(
            reg_number=reg_number, isin=isin, note=note, created_at=now, updated_at=now
        )
        session.add(row)
    elif changed:
        row.isin, row.note, row.updated_at = isin, note, now
    session.flush()
    return row, changed


def set_mapping(session, reg_number, isin, note=None):
    values = _validated(reg_number, isin, note)
    source_intake._reserve(session)
    try:
        row, _ = _upsert(session, *values)
        result = _as_dict(row)
        session.commit()
        return result
    except BaseException:
        session.rollback()
        raise


def remove_mapping(session, reg_number):
    reg_number = normalize_registration_number(reg_number)
    source_intake._reserve(session)
    try:
        row = session.scalar(
            select(SecurityRegIsinMapping).where(SecurityRegIsinMapping.reg_number == reg_number)
        )
        if row is not None:
            session.delete(row)
        session.commit()
        return {"removed": row is not None}
    except BaseException:
        session.rollback()
        raise


def import_csv(session, path: Path):
    """Validate the entire UTF-8 CSV before one atomic, idempotent upsert.

    Identical duplicate keys are allowed; conflicting normalized duplicates fail
    closed rather than making file order an implicit owner decision.
    """
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != ["reg_number", "isin", "note"]:
            raise ValueError("csv_header_invalid: expected reg_number,isin,note")
        for number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"csv_row_invalid: row {number}")
            try:
                values = _validated(row["reg_number"], row["isin"], row["note"])
            except ValueError as error:
                raise ValueError(f"{error}: row {number}") from None
            reg = values[0]
            if reg in rows and rows[reg] != values:
                raise ValueError(f"csv_duplicate_conflict: row {number}")
            rows[reg] = values
    source_intake._reserve(session)
    try:
        changed = sum(_upsert(session, *values)[1] for values in rows.values())
        session.commit()
        return {"processed": len(rows), "changed": changed}
    except BaseException:
        session.rollback()
        raise


def relink(session):
    """Refresh existing provisional link fields only; skip CLOSED bound months.

    The reserved write transaction pins mappings, catalog, effective identities
    and month state together. No classification rows or journal events are added.
    """
    source_intake._reserve(session)
    try:
        resolver = MoneyInstrumentResolver(session)
        editable = {}
        processed = changed = skipped_closed = 0
        for row in session.scalars(
            select(SourceMoneyClassification).order_by(SourceMoneyClassification.id)
        ):
            if row.intake_id not in editable:
                original = session.get(SourceIntakeOriginal, row.intake_id)
                state = source_intake._view(session, original, include_money_classifications=False)[
                    "state"
                ]
                month_id = state["reporting_month_id"]
                month = session.get(ReportingMonth, month_id) if month_id is not None else None
                editable[row.intake_id] = month_id is None or (
                    month is not None and month.status == "draft"
                )
            if not editable[row.intake_id]:
                skipped_closed += 1
                continue
            before = (
                row.security_reg_number,
                row.security_issuer,
                row.instrument_id,
                row.instrument_link_status,
            )
            apply_money_instrument_link(row, resolver)
            after = (
                row.security_reg_number,
                row.security_issuer,
                row.instrument_id,
                row.instrument_link_status,
            )
            changed += before != after
            processed += 1
        session.commit()
        return {"processed": processed, "changed": changed, "skipped_closed": skipped_closed}
    except BaseException:
        session.rollback()
        raise
