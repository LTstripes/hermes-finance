"""Instrument-only basis from an explicit trusted local review decision.

The configured private file is read afresh for each operation. It is not an
HTTP input, acceptance writer, proof registry or automatically generated proof.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, fields
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from hermes_finance.statement_import.mybroker import digest

FILE_VERSION = "source_bond_valuation_v1"
FILE_PATH_KEY = "reviewed_bond_valuation_path"
MAX_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class SourceRevision:
    intake_id: int
    document_sha256: str
    provider: str
    parser: str
    generation: int
    head_seq: int
    manifest_digest: str
    covered_from: str
    covered_to: str


@dataclass(frozen=True)
class BondEndpointBinding:
    intake_id: int
    native_account: str
    isin: str
    ordinal: int
    locator: str
    row_fingerprint: str
    side: Literal["opening", "closing"]
    valuation_date: date


@dataclass(frozen=True)
class ReviewedBondValuation:
    review_reference: str
    sources: tuple[SourceRevision, ...]
    endpoints: tuple[BondEndpointBinding, ...]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate review field")
        result[key] = value
    return result


def _record(record_type, value):
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(record_type)}:
        raise ValueError("invalid review record")
    integers = {"intake_id", "generation", "head_seq", "ordinal"}
    if any(type(v) is not (int if k in integers else str) for k, v in value.items()):
        raise ValueError("invalid review field type")
    if record_type is BondEndpointBinding:
        value = {**value, "valuation_date": date.fromisoformat(value["valuation_date"])}
    return record_type(**value)


def _file_signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def load_reviewed_basis(session, configured_path):
    """One bounded file snapshot; absent/revoked/stale never falls back or writes.

    Only trusted local configuration supplies the path. Operators replace the
    entire file atomically. Restoring an older accepted file is a new trusted
    activation, not something an append-only revocation history detects here.
    """
    from hermes_finance.source_proof_file import file_incarnation

    try:
        path = Path(configured_path)
        if not path.is_absolute() or path.is_symlink():
            return None
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or not 0 < before.st_size <= MAX_FILE_BYTES
            ):
                return None
            raw = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
        current = path.stat()
        if (
            len(raw) > MAX_FILE_BYTES
            or _file_signature(before) != _file_signature(after)
            or _file_signature(before) != _file_signature(current)
        ):
            return None
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "version",
                "status",
                "database_incarnation",
                "review_reference",
                "sources",
                "endpoints",
            }
            or payload["version"] != FILE_VERSION
            or payload["status"] != "accepted"
            or type(payload["sources"]) is not list
            or not 0 < len(payload["sources"]) <= 256
            or type(payload["endpoints"]) is not list
            or not 0 < len(payload["endpoints"]) <= 4096
        ):
            return None
        connection = session.connection()
        database_path = connection.engine.url.database
        physical = file_incarnation(Path(database_path)) if database_path else None
        if (
            not physical
            or connection.info.get("source_proof_incarnation") != physical
            or payload["database_incarnation"] != physical
        ):
            return None
        return ReviewedBondValuation(
            payload["review_reference"],
            tuple(_record(SourceRevision, row) for row in payload["sources"]),
            tuple(_record(BondEndpointBinding, row) for row in payload["endpoints"]),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None


def resolve_reviewed_basis(selected, native_scope, evidence):
    """Match the complete current selection inside the caller's coherent read.

    The records are supplied by a trusted, separately authorized reviewer caller;
    constructing this dataclass or matching its reference is NOT acceptance.
    Any malformed or stale packet supplies no basis, without changing sources.
    """
    if not isinstance(evidence, ReviewedBondValuation):
        return None
    try:
        if (
            not isinstance(evidence.review_reference, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", evidence.review_reference) is None
            or not isinstance(evidence.sources, tuple)
            or not isinstance(evidence.endpoints, tuple)
            or not evidence.sources
            or not evidence.endpoints
            or not selected
            or native_scope is None
            or len(native_scope) != 1
            or any(error or view is None for _, view, error in selected)
        ):
            return None
        current = []
        views = {}
        for original, view, _ in selected:
            doc = view["document"]
            if (
                original.id != view["id"]
                or original.document_sha256 != view["document_sha256"]
                or doc["document_sha256"] != view["document_sha256"]
                or doc["covered_from"] != view["covered_from"]
                or doc["covered_to"] != view["covered_to"]
            ):
                return None
            current.append(
                SourceRevision(
                    view["id"],
                    view["document_sha256"],
                    doc["provider"],
                    doc["parser"],
                    view["generation"],
                    view["head_seq"],
                    view["manifest_digest"],
                    view["covered_from"],
                    view["covered_to"],
                )
            )
            views[view["id"]] = view
        if (
            len(views) != len(selected)
            or any(not isinstance(s, SourceRevision) for s in evidence.sources)
            or any(
                type(value) is not int or value < 1
                for source in evidence.sources
                for value in (source.intake_id, source.generation, source.head_seq)
            )
            or len(set(evidence.sources)) != len(evidence.sources)
            or set(current) != set(evidence.sources)
            or any(not isinstance(b, BondEndpointBinding) for b in evidence.endpoints)
            or len(set(evidence.endpoints)) != len(evidence.endpoints)
        ):
            return None
        identities = set()
        for binding in evidence.endpoints:
            view = views[binding.intake_id]
            doc = view["document"]
            key = (binding.intake_id, binding.isin, binding.side)
            if key in identities:
                return None
            identities.add(key)
            if (
                doc["provider"] != "alfa_mybroker"
                or doc["parser"] != "mybroker-s1-v2"
                or "period_inferred_from_content" in doc.get("warnings", [])
                or binding.native_account not in native_scope
                or binding.side not in {"opening", "closing"}
                or type(binding.valuation_date) is not date
                or type(binding.ordinal) is not int
                or type(binding.intake_id) is not int
                or doc.get("endpoint_basis")
                != {
                    "beginning_value": "previous_day_eod",
                    "ending_value": "covered_to_eod",
                }
            ):
                return None
            closing = binding.side == "closing"
            day = date.fromisoformat(view["covered_to"] if closing else view["covered_from"])
            if binding.valuation_date != (day if closing else day - timedelta(days=1)):
                return None
            rows = [r for r in doc["positions"] if r["isin"] == binding.isin]
            if len(rows) != 1:
                return None
            row = rows[0]
            observations = [
                o
                for o in view["observations"]
                if o["section"] == "positions" and o["locator"] == binding.locator
            ]
            if (
                row["source_account"] != binding.native_account
                or row["ordinal"] != binding.ordinal
                or len(observations) != 1
                or observations[0]["row_class"] != "recognized"
                or observations[0]["facts"] != row
                or observations[0]["row_fingerprint"] != binding.row_fingerprint
                or digest(row) != binding.row_fingerprint
                or len(
                    [
                        p
                        for p in view["proposals"]
                        if p["isin"] == binding.isin and p["instrument_type"] == "bond"
                    ]
                )
                != 1
            ):
                return None
            for field in (
                "actual_quantity" if closing else "beginning_actual_quantity",
                "ending_value" if closing else "beginning_value",
            ):
                value = Decimal(row[field])
                if not value.is_finite() or value < 0:
                    return None
        return evidence
    except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
        return None


def review_reference(evidence, view, row, day, closing):
    """Used only after resolve_reviewed_basis; no inheritance by equal values."""
    if evidence is None:
        return None
    side = "closing" if closing else "opening"
    if any(
        b.intake_id == view["id"]
        and b.native_account == row["source_account"]
        and b.isin == row["isin"]
        and b.ordinal == row["ordinal"]
        and b.side == side
        and b.valuation_date == day
        for b in evidence.endpoints
    ):
        return "bond-basis:" + evidence.review_reference
    return None
