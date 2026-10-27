"""Immutable original-validated metadata authority. No financial writer.

Heads follow predecessor links, never timestamps. Reads need only persisted
proof and current dependencies; originals are required at Preview and Apply.
"""

import hashlib
import json
from calendar import monthrange
from datetime import UTC, date, datetime

from pydantic import ValidationError
from sqlalchemy import select, update

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain.broker_sections import CONTRACT, SectionBindings, SectionIntent
from hermes_finance.persistence import Account, BrokerMonthApply, MyBrokerImport, ReportingMonth
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services import mybroker_identity, mybroker_import
from hermes_finance.services.mybroker_dispositions import effective_bindings, resolve
from hermes_finance.services.mybroker_money_candidates import _original_equal
from hermes_finance.statement_import.mybroker import (
    PARSER,
    PROVIDER,
    MyBrokerError,
    canonical,
    digest,
    parse_mybroker,
)
from hermes_finance.statement_import.mybroker_identity import parse_identity
from hermes_finance.statement_import.mybroker_metadata import (
    METADATA_PARSER,
    parse_section_metadata,
)

SHAPES = {
    "4_Transfers": {
        "section": "4_Transfers",
        "status": "READY_SAFE_STRUCTURE",
        "pattern": "empty_transfers",
        "raw_inventory": 1,
        "derived_movements": 0,
        "period_scope": "unknown",
        "locator": "/m:Report/m:Trades3/m:Report[@Name='4_Transfers']/m:Tablix1",
    },
    "5_UFSR": {
        "section": "5_UFSR",
        "status": "READY_SAFE_STRUCTURE",
        "pattern": "ufsr_open_connection",
        "raw_inventory": 3,
        "derived_movements": 0,
        "period_scope": "unknown",
        "locator": "/m:Report/m:Trades4/m:Report[@Name='5_UFSR']/m:Tablix1/m:Details_Collection/m:Details",
    },
}


def _source_digest(source):
    return digest([source.normalized_json, source.mappings_json, source.parser_version])


def _intent(intent):
    value = intent.model_dump(mode="json")
    value["sections"] = sorted(value["sections"], key=lambda s: s["section"])
    return value


def _fingerprint(intent, confirmation, original_sha, filename_digest):
    return digest([intent, confirmation, original_sha, filename_digest])


def validated_proof(receipt):
    """Validate a known variant before any consumer interprets its fields."""
    p = journal.payload(receipt)
    try:
        if set(p) != {
            "contract_version",
            "intent",
            "bindings",
            "sections",
            "authority_token",
            "dependency_digest",
        }:
            return None
        if p["contract_version"] != CONTRACT:
            return None
        intent = SectionIntent.model_validate(p["intent"])
        if p["intent"] != _intent(intent) or (
            intent.import_id,
            intent.account_id,
            intent.reporting_month_id,
        ) != (receipt.import_id, receipt.account_id, receipt.reporting_month_id):
            return None
        if canonical(p["sections"]) != canonical(
            [SHAPES[s.section] for s in sorted(intent.sections, key=lambda s: s.section)]
        ):
            return None
        b = p["bindings"]
        SectionBindings.model_validate(b)
        if set(b) != {
            "base_request_id",
            "base_fingerprint",
            "base_confirmation",
            "base_projection",
            "source_digest",
            "provider",
            "original_sha256",
            "source_parser",
            "money_linkage_version",
            "filename_digest",
            "filename_account",
            "source_accounts",
            "covered_from",
            "covered_to",
            "month_identity",
            "mappings",
            "metadata_parser",
        }:
            return None
        if (
            b["base_request_id"] != intent.base_request_id
            or b["provider"] != PROVIDER
            or b["source_parser"] != PARSER
            or b["metadata_parser"] != METADATA_PARSER
        ):
            return None
        from hermes_finance.statement_import.mybroker import MONEY_LINKAGE

        if b["money_linkage_version"] not in (None, MONEY_LINKAGE):
            return None
        for field in (
            "base_fingerprint",
            "base_confirmation",
            "base_projection",
            "source_digest",
            "original_sha256",
            "filename_digest",
        ):
            if (
                not isinstance(b[field], str)
                or len(b[field]) != 64
                or any(c not in "0123456789abcdef" for c in b[field])
            ):
                return None
        for field in ("authority_token", "dependency_digest"):
            if (
                not isinstance(p[field], str)
                or len(p[field]) != 64
                or any(c not in "0123456789abcdef" for c in p[field])
            ):
                return None
        if (
            digest(p) != receipt.confirmation_digest
            or _fingerprint(
                p["intent"], receipt.confirmation_digest, b["original_sha256"], b["filename_digest"]
            )
            != receipt.request_fingerprint
        ):
            return None
        return p
    except (ValidationError, KeyError, TypeError, ValueError):
        return None


def _bindings(session, base, source, filename_digest):
    from hermes_finance.services import broker_months

    stored = json.loads(source.normalized_json)
    month = session.get(ReportingMonth, base.reporting_month_id, populate_existing=True)
    return {
        "base_request_id": base.request_id,
        "base_fingerprint": base.request_fingerprint,
        "base_confirmation": base.confirmation_digest,
        "base_projection": broker_months._projection(session, base),
        "source_digest": _source_digest(source),
        "provider": stored["provider"],
        "original_sha256": source.document_sha256,
        "source_parser": source.parser_version,
        "money_linkage_version": stored.get("money_linkage_version"),
        "filename_digest": filename_digest,
        "filename_account": stored["filename_account"],
        "source_accounts": stored["source_accounts"],
        "covered_from": stored["covered_from"],
        "covered_to": stored["covered_to"],
        "month_identity": [
            month.id,
            month.year,
            month.month,
            str(month.period_start),
            str(month.period_end),
            str(month.snapshot_date),
        ],
        "mappings": effective_bindings(session, source),
        "metadata_parser": METADATA_PARSER,
    }


def _authority_token(session, base):
    # Existing source/registry/catalogue change journal is monotonic. Existing
    # financial dependency receipts also retain snapshot and financial ABA.
    dependencies = sorted(
        r.request_id
        for r in session.scalars(select(BrokerMonthApply))
        if journal.kind(r) == journal.DEPENDENCY
        and journal.payload(r)["base_request_id"] == base.request_id
    )
    return digest([mybroker_identity._revision(session), dependencies])


def _heads(session, source_id, account_id, month_id):
    """One complete chain per key; malformed rows and forks grant nothing."""
    rows = list(
        session.scalars(
            select(BrokerMonthApply)
            .where(
                BrokerMonthApply.import_id == source_id,
                BrokerMonthApply.account_id == account_id,
                BrokerMonthApply.reporting_month_id == month_id,
            )
            .execution_options(populate_existing=True)
        )
    )
    histories = {s: {} for s in SHAPES}
    for row in rows:
        kind = journal.kind(row)
        if kind == "invalid":
            return {}, ["broker_month_receipt_invalid"]
        if kind != CONTRACT:
            continue
        p = validated_proof(row)
        for decision in p["intent"]["sections"]:
            histories[decision["section"]][row.request_id] = (
                row,
                p,
                decision["expected_predecessor"],
            )
    heads = {}
    for section, history in histories.items():
        if not history:
            continue
        children = {}
        for request_id, (_, _, predecessor) in history.items():
            if predecessor in children or (predecessor is not None and predecessor not in history):
                return {}, ["section_authority_chain_conflict"]
            children[predecessor] = request_id
        current, visited = children.get(None), set()
        while current is not None and current not in visited:
            visited.add(current)
            head = current
            current = children.get(current)
        if current is not None or visited != set(history):
            return {}, ["section_authority_chain_conflict"]
        heads[section] = history[head][:2]
    return heads, []


def _valid_current(session, row, p):
    base = session.get(BrokerMonthApply, p["intent"]["base_request_id"], populate_existing=True)
    source = session.get(MyBrokerImport, row.import_id, populate_existing=True)
    account = session.get(Account, row.account_id, populate_existing=True)
    if (
        base is None
        or source is None
        or journal.kind(base) != journal.SOURCE
        or (base.import_id, base.account_id, base.reporting_month_id)
        != (row.import_id, row.account_id, row.reporting_month_id)
    ):
        return False
    if (
        account is None
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        return False
    b = p["bindings"]
    if (
        journal.payload(base)["source_digest"] != b["source_digest"]
        or journal.payload(base)["projection_digest"] != b["base_projection"]
        or resolve(session, source)
    ):
        return False
    try:
        return b == _bindings(session, base, source, b["filename_digest"]) and p[
            "authority_token"
        ] == _authority_token(session, base)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def disposition(session, source, account_id, month_id, codes):
    """Called at source grain BEFORE blocker union. No other code is removed."""
    heads, errors = _heads(session, source.id, account_id, month_id)
    removed = {
        f"{section}_unsupported"
        for section, (row, p) in heads.items()
        if _valid_current(session, row, p)
    }
    return (set(codes) - removed) | set(errors)


def coverage_disposition(session, source, account_id, codes):
    """Read-only H2 provenance at exact source/month grain, never period coverage.

    Bind absence and the complete scoped journal, including malformed/forked
    history. Reuse the canonical head/currentness checks; do not select a head
    by time or infer a ReportingMonth from intersecting dates.
    """
    rows = list(
        session.scalars(
            select(BrokerMonthApply)
            .where(
                BrokerMonthApply.import_id == source.id,
                BrokerMonthApply.account_id == account_id,
            )
            .order_by(BrokerMonthApply.request_id)
            .execution_options(populate_existing=True)
        )
    )
    scopes, removed, errors = [], set(), set()
    for month_id in sorted({r.reporting_month_id for r in rows}):
        month = session.get(ReportingMonth, month_id, populate_existing=True)
        geometry = (
            [
                month.id,
                month.year,
                month.month,
                str(month.period_start),
                str(month.period_end),
                str(month.snapshot_date),
            ]
            if month
            else None
        )
        matching = bool(
            month
            and (source.covered_from, source.covered_to) == (month.period_start, month.period_end)
            and month.snapshot_date == month.period_end
            and month.period_start == date(month.year, month.month, 1)
            and month.period_end
            == date(month.year, month.month, monthrange(month.year, month.month)[1])
        )
        scoped = [r for r in rows if r.reporting_month_id == month_id]
        heads, refusals = _heads(session, source.id, account_id, month_id)
        errors.update(refusals)
        sections = []
        for section in SHAPES:
            head = heads.get(section)
            current = False
            dependency = None
            if head:
                row, proof = head
                base = session.get(BrokerMonthApply, proof["intent"]["base_request_id"])
                if base is not None and journal.kind(base) == journal.SOURCE:
                    try:
                        dependency = {
                            "bindings": _bindings(
                                session, base, source, proof["bindings"]["filename_digest"]
                            ),
                            "authority_token": _authority_token(session, base),
                        }
                    except (KeyError, TypeError, ValueError, AttributeError):
                        dependency = {"unavailable": True}
                current = matching and _valid_current(session, row, proof)
            if current:
                removed.add(f"{section}_unsupported")
            sections.append(
                {
                    "section": section,
                    "head_request_id": head[0].request_id if head else None,
                    "state": "blocked"
                    if refusals
                    else "effective"
                    if current
                    else "stale"
                    if head
                    else "absent",
                    "refusals": sorted(
                        set(refusals)
                        | ({"source_month_range_mismatch"} if not matching else set())
                        | ({"section_dependency_changed"} if head and not current else set())
                    ),
                    "current_dependency": dependency,
                }
            )
        scopes.append(
            {
                "reporting_month_id": month_id,
                "month_identity": geometry,
                "matching_range": matching,
                "journal": [
                    {
                        "request_id": r.request_id,
                        "kind": journal.kind(r),
                        "request_fingerprint": r.request_fingerprint,
                        "confirmation_digest": r.confirmation_digest,
                        "proof": journal.payload(r),
                        "payload_digest": digest(r.projection_json),
                    }
                    for r in scoped
                    if journal.kind(r)
                    not in {*journal.MONEY_KINDS, journal.PAYOUT, journal.PAYOUT_DEPENDENCY}
                ],
                "sections": sections,
            }
        )
    # Multiple monthly identities cannot donate a winner's exemption.
    if len([s for s in scopes if s["matching_range"]]) > 1:
        removed.clear()
        errors.add("section_month_scope_ambiguous")
    return {
        "import_id": source.id,
        "account_id": account_id,
        "original_sha256": source.document_sha256,
        "source_digest": _source_digest(source),
        "period_scope": "unknown",
        "absent_sections": sorted(
            section
            for section in SHAPES
            if not any(
                s["state"] != "absent"
                for scope in scopes
                for s in scope["sections"]
                if s["section"] == section
            )
        ),
        "scopes": scopes,
        "raw_blockers": sorted(set(codes)),
        "effective_blockers": sorted((set(codes) - removed) | errors),
    }


def _plan(session, intent, document, filename):
    from hermes_finance.services import broker_months

    base = session.get(BrokerMonthApply, intent.base_request_id, populate_existing=True)
    source = session.get(MyBrokerImport, intent.import_id, populate_existing=True)
    if (
        base is None
        or source is None
        or journal.kind(base) != journal.SOURCE
        or (base.import_id, base.account_id, base.reporting_month_id)
        != (intent.import_id, intent.account_id, intent.reporting_month_id)
    ):
        raise MyBrokerError("existing_source_draft_required")
    stored = json.loads(source.normalized_json)
    if (
        stored.get("provider") != PROVIDER
        or source.parser_version != PARSER
        or stored.get("parser") != PARSER
    ):
        raise MyBrokerError("section_source_parser_invalid")
    fresh = parse_mybroker(
        document, filename, money_linkage_version=stored.get("money_linkage_version")
    )
    if fresh["document_sha256"] != source.document_sha256 or not _original_equal(fresh, stored):
        raise MyBrokerError("section_original_mismatch")
    if (str(source.covered_from), str(source.covered_to)) != (
        fresh["covered_from"],
        fresh["covered_to"],
    ):
        raise MyBrokerError("section_source_range_invalid")
    metadata = parse_section_metadata(document, filename)
    month = session.get(ReportingMonth, intent.reporting_month_id, populate_existing=True)
    account = session.get(Account, intent.account_id, populate_existing=True)
    blockers = set()
    if month.status != "draft":
        blockers.add("reporting_month_closed")
    if (
        account is None
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        blockers.add("account_binding_invalid")
    accepted = journal.payload(base)
    if accepted["source_digest"] != _source_digest(source):
        blockers.add("source_authority_changed")
    if accepted["projection_digest"] != broker_months._projection(session, base):
        blockers.add("source_projection_changed")
    if (fresh["covered_from"], fresh["covered_to"]) != (
        str(month.period_start),
        str(month.period_end),
    ) or month.snapshot_date != month.period_end:
        blockers.add("source_month_range_mismatch")
    bindings = effective_bindings(session, source)
    if bindings != json.loads(source.mappings_json) or resolve(session, source):
        blockers.add("source_disposition_changed")
    identity = mybroker_identity._prepare(session, parse_identity(document, filename), [])
    blockers.update(identity["conflicts"])
    if not identity["can_stage"] or any(
        b["hermes_id"] != intent.account_id or b["mapping_id"] is None for b in identity["accounts"]
    ):
        blockers.add("account_mapping_conflict")
    current = mybroker_import._prepare(session, json.loads(source.normalized_json))
    blockers.update(current["conflicts"])
    if current["missing_mappings"]:
        blockers.add("accepted_mapping_changed")
    heads, errors = _heads(session, source.id, intent.account_id, intent.reporting_month_id)
    blockers.update(errors)
    for decision in intent.sections:
        observed = next(s for s in metadata["sections"] if s["section"] == decision.section)
        if {**observed, "locator": SHAPES[decision.section]["locator"]} != SHAPES[decision.section]:
            blockers.add("section_structure_unsupported")
        head = heads.get(decision.section)
        if decision.expected_predecessor != (head[0].request_id if head else None):
            blockers.add("section_predecessor_conflict")
        elif head and _valid_current(session, *head):
            blockers.add("section_authority_already_effective")
    p = {
        "contract_version": CONTRACT,
        "intent": _intent(intent),
        "bindings": _bindings(session, base, source, hashlib.sha256(filename.encode()).hexdigest()),
        "sections": [SHAPES[s.section] for s in sorted(intent.sections, key=lambda s: s.section)],
        "authority_token": _authority_token(session, base),
        "dependency_digest": broker_months._dependencies(session),
    }
    return {
        "proof": p,
        "confirmation_digest": digest(p),
        "exceptions": sorted(blockers),
        "can_apply": not blockers,
        "coverage_state": "unknown",
        "exact_return_ready": False,
    }


def preview_sections(session, intent, document, filename):
    with coherent_read_snapshot(session):
        return _plan(session, intent, document, filename)


def read_sections(session, request_id):
    with coherent_read_snapshot(session):
        row = session.get(BrokerMonthApply, request_id, populate_existing=True)
        p = validated_proof(row) if row else None
        if p is None:
            raise MyBrokerError("section_receipt_invalid")
        heads, errors = _heads(session, row.import_id, row.account_id, row.reporting_month_id)
        states = []
        for decision in p["intent"]["sections"]:
            head = heads.get(decision["section"])
            status = (
                "blocked"
                if errors or head is None
                else (
                    "superseded"
                    if head[0].request_id != request_id
                    else ("effective" if _valid_current(session, row, p) else "blocked")
                )
            )
            states.append(
                {
                    "section": decision["section"],
                    "disposition_status": status,
                    "head_request_id": head[0].request_id if head else None,
                }
            )
        return {
            "contract_version": CONTRACT,
            "request_id": request_id,
            "import_id": row.import_id,
            "account_id": row.account_id,
            "reporting_month_id": row.reporting_month_id,
            "accepted": p,
            "sections": states,
            "exceptions": errors,
            "status": session.get(ReportingMonth, row.reporting_month_id).status,
            "coverage_state": "unknown",
            "exact_return_ready": False,
        }


def apply_sections(session, intent, document, filename, *, confirmation_digest, request_id):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    fingerprint = _fingerprint(
        _intent(intent),
        confirmation_digest,
        hashlib.sha256(document).hexdigest(),
        hashlib.sha256(filename.encode()).hexdigest(),
    )
    session.rollback()
    try:
        session.execute(
            update(BrokerMonthApply)
            .where(BrokerMonthApply.request_id == "")
            .values(request_id=BrokerMonthApply.request_id)
        )
        session.expire_all()
        row = session.get(BrokerMonthApply, request_id, populate_existing=True)
        replay = row is not None
        if row:
            if journal.kind(row) != CONTRACT or row.request_fingerprint != fingerprint:
                raise MyBrokerError("idempotency_conflict")
            session.rollback()
        else:
            plan = _plan(session, intent, document, filename)
            if plan["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("section_preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError("section_acceptance_blocked")
            session.add(
                BrokerMonthApply(
                    request_id=request_id,
                    request_fingerprint=fingerprint,
                    confirmation_digest=confirmation_digest,
                    reporting_month_id=intent.reporting_month_id,
                    account_id=intent.account_id,
                    import_id=intent.import_id,
                    projection_json=canonical(plan["proof"]),
                    accepted_at=datetime.now(UTC),
                )
            )
            session.commit()
    except BaseException:
        session.rollback()
        raise
    return {**read_sections(session, request_id), "duplicate": replay}
