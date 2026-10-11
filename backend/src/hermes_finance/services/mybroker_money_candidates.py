"""Original-bound, zero-write diagnostics under the accepted #778 contract.

This standalone Python read surface consumes an accepted S1 import and its
original bytes. It has no HTTP/writer route. DTOs contain bounded pattern codes,
never source narratives; their source references are Owner-local evidence.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
from typing import Literal
from xml.etree import ElementTree as ET

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import Account, MyBrokerImport
from hermes_finance.services.mybroker_dispositions import accepted_account_binding
from hermes_finance.services.mybroker_import import _prepare
from hermes_finance.statement_import.mybroker import (
    NS,
    PARSER,
    PROVIDER,
    MyBrokerError,
    digest,
    parse_mybroker,
)

ADAPTER = "mybroker-money-candidates-v1"
CandidateKind = Literal[
    "coupon_paid_candidate", "account_cash_in_candidate", "trade_paid_nkd_candidate", "unsupported"
]
# Placeholder values stay opaque. Only delimiters and the complete observed
# shape are recognized; no token/issuer/date is extracted as an economic key.
COUPON = re.compile(
    r"погашение купона (?P<token>[^\r\n]+) \(облигации (?P<issuer>[^\r\n]+)\) "
    r"д\.ф\.(?P<date>[0-9]{2}\.[0-9]{2}\.[0-9]{2})"
)
CASH_IN = re.compile(r"из АО [^\r\n]+")
GROUPS = "m:Trades2/m:Report/m:Tablix1/m:settlement_date_Collection/m:settlement_date"
AMOUNTS = (
    "m:money_volume_begin1_Collection/m:money_volume_begin1/m:p_code_Collection/m:p_code/m:p_code"
)


@dataclass(frozen=True)
class MoneyOccurrence:
    import_id: int
    section: Literal["money"]
    ordinal: int
    row_fingerprint: str


@dataclass(frozen=True)
class MoneyObservation:
    occurrence: MoneyOccurrence
    # Exact rooted XML locator, including each amount leaf's document-local index.
    locator: str
    source_account: str
    account_id: int | None
    date: str
    signed_amount: str
    currency: str
    amount_minor: int | None
    s1_kind: str
    candidate_kind: CandidateKind
    authority: Literal["unproven"]
    summary_proof: Literal["unavailable"]
    instrument_id: None
    trade_identity: str | None
    economic_event_id: None
    reasons: tuple[str, ...]
    competing_occurrences: tuple[MoneyOccurrence, ...]


@dataclass(frozen=True)
class OverlappingMoneySource:
    import_id: int
    covered_from: str
    covered_to: str
    occurrences: tuple[MoneyOccurrence, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MoneyCandidateInventory:
    adapter: str
    import_id: int
    document_sha256: str
    parser: str
    covered_from: str
    covered_to: str
    section_inventory: dict[str, int]
    observations: tuple[MoneyObservation, ...]
    overlapping_sources: tuple[OverlappingMoneySource, ...]
    # Original-document subtotals only, never summed across reports or added to cash.
    source_subtotals: dict[str, str]
    exceptions: tuple[str, ...]
    authority: Literal["unproven"] = "unproven"
    coverage_state: Literal["unknown"] = "unknown"
    financial_apply_available: Literal[False] = False


def _original_equal(fresh: dict, stored: dict) -> bool:
    """Require all parser facts; allow only the established service enrichment.

    Fingerprints below still reference the FULL stored row (including accepted
    linkage), as historical_owner_flows/source_cash_coverage do.
    """
    for key, value in fresh.items():
        if key in ("money", "trades"):
            rows = stored.get(key, [])
            if len(rows) != len(value):
                return False
            if any(
                any(old.get(field) != fact for field, fact in row.items())
                for row, old in zip(value, rows, strict=True)
            ):
                return False
        elif stored.get(key) != value:
            return False
    return True


def _narratives(document: bytes):
    # S1 has already checked family, bounds, cardinalities, exact paths and leaves.
    root = ET.fromstring(document.decode("utf-8-sig"))
    ordinal = 0
    for group in root.findall(GROUPS, NS):
        for rn in group.findall("m:rn_Collection/m:rn", NS):
            op = rn.find("m:oper_type", NS)
            comment = op.find("m:comment", NS)
            for _ in comment.findall(AMOUNTS, NS):
                ordinal += 1
                locator = (
                    f"(/m:Report/m:Trades2/m:Report[@Name='3_BrokerMoneyMove']/m:Tablix1/"
                    f"m:settlement_date_Collection/m:settlement_date/"
                    f"m:rn_Collection/m:rn/m:oper_type/m:comment/{AMOUNTS})[{ordinal}]"
                )
                yield op.get("oper_type", ""), comment.get("comment", ""), locator


def _pattern(operation: str, narrative: str) -> CandidateKind:
    if len(narrative) > 4096:
        return "unsupported"
    if operation == "НКД по сделке":
        return "trade_paid_nkd_candidate"
    if operation == "Перевод":
        match = COUPON.fullmatch(narrative)
        if match and match["token"].strip() and match["issuer"].strip():
            try:
                day_number, month_number, year_number = map(int, match["date"].split("."))
                # Fixed Gregorian 2000-2099 anchor for calendar validity only,
                # never %y's pivot, a resolved narrative date or the cash date.
                date(2000 + year_number, month_number, day_number)
                return "coupon_paid_candidate"
            except ValueError:
                return "unsupported"
        if CASH_IN.fullmatch(narrative) and narrative[len("из АО ") :].strip():
            return "account_cash_in_candidate"
    return "unsupported"


def _minor(row: dict, reasons: set[str]) -> int | None:
    if row["currency"] != "RUB":
        reasons.add("currency_unsupported")
        return None
    with localcontext() as context:
        context.prec = 100  # S1 decimals are bounded to 48 source characters.
        minor = Decimal(row["amount"]) * 100
        if not minor:
            reasons.add("zero_amount")
        elif minor != minor.to_integral_value():
            reasons.add("fractional_kopecks")
        elif not -(2**63) <= minor <= 2**63 - 1:
            reasons.add("amount_overflow")
        else:
            return int(minor)
    return None


def _reference(import_id: int, row: dict) -> MoneyOccurrence:
    return MoneyOccurrence(import_id, "money", row["ordinal"], digest(row))


def read_money_candidates(
    session: Session, *, import_id: int, document: bytes, filename: str, account_id: int
) -> MoneyCandidateInventory:
    """Committed, zero-write public reader; stage callers use the pure builder."""
    with coherent_read_snapshot(session):
        return _read_money_candidates(
            session,
            import_id=import_id,
            document=document,
            filename=filename,
            account_id=account_id,
        )


def _read_money_candidates(
    session: Session, *, import_id: int, document: bytes, filename: str, account_id: int
) -> MoneyCandidateInventory:
    """Read an immutable S1 import, original and full accepted overlap inventory.

    No normalized client rows, mappings or guessed event keys are accepted.
    Original/parser/range/inventory mismatch refuses interpretation entirely.
    Missing/currently changed account links remain visible diagnostics.
    """
    with session.no_autoflush:
        source = session.get(MyBrokerImport, import_id, populate_existing=True)
        if source is None:
            raise MyBrokerError("import_not_found")
        stored = json.loads(source.normalized_json)
        fresh = parse_mybroker(
            document, filename, money_linkage_version=stored.get("money_linkage_version")
        )
        if (
            stored.get("provider") != PROVIDER
            or source.parser_version != PARSER
            or stored.get("parser") != source.parser_version
            or source.document_sha256 != fresh["document_sha256"]
            or source.covered_from.isoformat() != fresh["covered_from"]
            or source.covered_to.isoformat() != fresh["covered_to"]
            or not _original_equal(fresh, stored)
        ):
            raise MyBrokerError("money_original_s1_mismatch")
        # Reuse S1 settlement/commission precedence and every existing exception,
        # on a copy: this must never rewrite the saved JSON or old receipt.
        plan = _prepare(session, json.loads(source.normalized_json))
        exceptions = set(plan["blockers"]) | set(plan["conflicts"])
        exceptions.add("summary_proof_unavailable")
        if plan["missing_mappings"]:
            exceptions.add("source_mapping_unavailable")
        filename_binding = accepted_account_binding(session, source, stored["filename_account"])
        account = session.get(Account, account_id)
        filename_ok = filename_binding is not None and filename_binding["hermes_id"] == account_id
        if (
            account is None
            or account.status != "active"
            or account.account_type not in {"brokerage", "iis"}
        ):
            exceptions.add("selected_account_unavailable")
            filename_ok = False
        if not filename_ok:
            exceptions.add("filename_account_binding_unproven")

        overlaps = []
        overlap_rows = []
        for other in session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id)):
            if other.id == source.id:
                continue
            if other.covered_from > source.covered_to or other.covered_to < source.covered_from:
                continue
            prior = json.loads(other.normalized_json)
            if prior.get("provider") != PROVIDER:
                continue
            recorded = json.loads(other.mappings_json)
            aliases = {
                b["identity"]
                for b in recorded
                if b["kind"] == "account" and b["hermes_id"] == account_id
            }
            # Recorded ownership still exposes a competing source after mapping
            # withdrawal. Do not hide contradictory evidence through disappearance.
            if not aliases and prior["filename_account"] != stored["filename_account"]:
                continue
            rows = [r for r in prior["money"] if r["source_account"] in aliases]
            if not aliases:
                rows = prior["money"]
            findings = {"overlapping_source_ambiguity"}
            findings.update(prior.get("syntax_blockers", []))
            findings.update(prior.get("endpoint_blockers", []))
            findings.update(prior.get("endpoint_conflicts", []))
            for trade in prior["trades"]:
                findings.update(trade.get("blockers", []))
            if any(r["kind"] == "unsupported" for r in rows):
                findings.add("money_semantics_unsupported")
            for alias in {prior["filename_account"]} | {r["source_account"] for r in rows}:
                binding = accepted_account_binding(session, other, alias)
                if binding is None or binding["hermes_id"] != account_id:
                    findings.add("overlapping_account_binding_unproven")
            if other.document_sha256 == source.document_sha256:
                findings.add("document_coverage_conflict")
            overlaps.append(
                OverlappingMoneySource(
                    other.id,
                    prior["covered_from"],
                    prior["covered_to"],
                    tuple(_reference(other.id, r) for r in rows),
                    tuple(sorted(findings)),
                )
            )
            overlap_rows.extend((other.id, r) for r in rows)
            exceptions.update(findings)

        def signature(row):
            return row["source_account"], row["date"], row["amount"], row["currency"]

        multiplicity = Counter(signature(r) for r in stored["money"])

        # This comparison is an inventory diagnostic, never a one-to-one join
        # or economic equivalence assertion. All competing references are kept.
        def cash_signature(row):
            return row["date"], row["amount"], row["currency"]

        selected_counts = Counter(cash_signature(r) for r in stored["money"])
        overlapping_counts = Counter((i, cash_signature(r)) for i, r in overlap_rows)
        observations = []
        subtotals = {}
        for row, (operation, narrative, locator) in zip(
            stored["money"], _narratives(document), strict=True
        ):
            reasons = set()
            binding = accepted_account_binding(session, source, row["source_account"])
            row_ok = binding is not None and binding["hermes_id"] == account_id
            if not row_ok:
                reasons.add("row_account_binding_unproven")
            if not filename_ok:
                reasons.add("filename_account_binding_unproven")
            if not stored["covered_from"] <= row["date"] <= stored["covered_to"]:
                reasons.add("posted_date_outside_range")
            minor = _minor(row, reasons)
            kind = _pattern(operation, narrative) if row["kind"] == "unsupported" else "unsupported"
            if kind != "unsupported" and minor is not None:
                if (minor < 0) != (kind == "trade_paid_nkd_candidate"):
                    reasons.add("candidate_direction_invalid")
            if reasons:
                kind = "unsupported"
            if row["kind"] == "unsupported":
                reasons.update(
                    {
                        "money_semantics_unsupported",
                        "summary_proof_unavailable",
                        "economic_identity_unproven",
                    }
                )
                if kind == "unsupported":
                    reasons.add("source_pattern_unproven")
                elif kind == "coupon_paid_candidate":
                    reasons.add("instrument_link_unproven")
                elif kind == "account_cash_in_candidate":
                    reasons.update({"owner_crossing_unproven", "portfolio_externality_unproven"})
                else:
                    reasons.update({"trade_link_unproven", "paid_nkd_basis_unproven"})
            else:
                # Existing linkage is retained exactly, never promoted to new cash.
                reasons.update(plan["blockers"])
            if multiplicity[signature(row)] > 1:
                reasons.add("same_report_multiplicity")
            competing = tuple(
                _reference(i, r)
                for i, r in overlap_rows
                if r["date"] == row["date"]
                and r["amount"] == row["amount"]
                and r["currency"] == row["currency"]
            )
            if overlaps:
                reasons.add("overlapping_source_ambiguity")
                if any(
                    o.covered_from <= row["date"] <= o.covered_to
                    and overlapping_counts[o.import_id, cash_signature(row)]
                    != selected_counts[cash_signature(row)]
                    for o in overlaps
                ):
                    reasons.add("overlapping_source_multiplicity_mismatch")
                if any(
                    o.covered_from <= row["date"] <= o.covered_to
                    and not any(ref.import_id == o.import_id for ref in competing)
                    for o in overlaps
                ):
                    reasons.add("overlapping_source_event_missing")
            exceptions.update(reasons)
            if kind != "unsupported":
                with localcontext() as context:
                    context.prec = 100
                    subtotals[kind] = subtotals.get(kind, Decimal(0)) + Decimal(row["amount"])
            observations.append(
                MoneyObservation(
                    _reference(source.id, row),
                    locator,
                    row["source_account"],
                    binding["hermes_id"] if row_ok else None,
                    row["date"],
                    row["amount"],
                    row["currency"],
                    minor,
                    row["kind"],
                    kind,
                    "unproven",
                    "unavailable",
                    None,
                    row.get("trade_identity") if row["kind"] != "unsupported" else None,
                    None,
                    tuple(sorted(reasons)),
                    competing,
                )
            )
        return MoneyCandidateInventory(
            ADAPTER,
            source.id,
            source.document_sha256,
            source.parser_version,
            stored["covered_from"],
            stored["covered_to"],
            dict(stored["section_inventory"]),
            tuple(observations),
            tuple(overlaps),
            {k: format(v, "f") for k, v in sorted(subtotals.items())},
            tuple(sorted(exceptions)),
        )
