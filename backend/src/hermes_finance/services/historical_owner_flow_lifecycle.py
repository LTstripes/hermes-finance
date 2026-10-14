"""Transactional loss of H2 authority; a restored dependency cannot revive it."""

import json
from datetime import date

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from hermes_finance.domain.historical_owner_flows import (
    SECTION_FLOW_CONTRACT,
    SOURCE_CASH_FLOW_CONTRACTS,
    SOURCE_CASH_PROVENANCE,
)
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBoundaryCoverage,
    ExternalFlow,
    ExternalTransferLink,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowApply,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    MyBrokerImport,
)

HISTORY = (
    HistoricalOwnerFlow,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    HistoricalOwnerFlowApply,
)
DEPENDENCIES = (
    Account,
    BrokerIdentityMapping,
    AccountPerformanceScopeMembership,
    MyBrokerImport,
    ExternalFlow,
    ExternalTransferLink,
    CashBoundaryCoverage,
)


def _values(row, name):
    history = inspect(row).attrs[name].history
    return {getattr(row, name), *history.deleted, *history.added}


def _affects(row, core, evidence):
    account_id, day = core.account_id, core.event_date
    deps = evidence["dependencies"]
    if (
        isinstance(row, CashBoundaryCoverage)
        and evidence["contract_version"] in SOURCE_CASH_FLOW_CONTRACTS
    ):

        def old(name):
            values = inspect(row).attrs[name].history.deleted
            return values[0] if values else getattr(row, name)

        legacy_complete = (
            row.provenance_kind != SOURCE_CASH_PROVENANCE and row.coverage_state == "complete"
        )
        was_legacy_complete = (
            row not in inspect(row).session.new
            and old("provenance_kind") != SOURCE_CASH_PROVENANCE
            and old("coverage_state") == "complete"
        )
        if not legacy_complete and not was_legacy_complete:
            return False
    if isinstance(row, BrokerIdentityMapping):
        return any(
            any(a["mapping_id"] == row.id for a in b["accepted"]) for b in deps["bindings"]
        ) or (
            "alfa_mybroker" in _values(row, "provider")
            and "account" in _values(row, "subject_kind")
            and (
                account_id in _values(row, "hermes_account_id")
                or any(b["alias"] in _values(row, "provider_identity") for b in deps["bindings"])
            )
        )
    if isinstance(row, MyBrokerImport):
        if any(s["import_id"] == row.id for s in deps["sources"]):
            return True
        try:
            bindings = json.loads(row.mappings_json)
            return row.covered_from <= day <= row.covered_to and any(
                b["kind"] == "account" and b["hermes_id"] == account_id for b in bindings
            )
        except (ValueError, TypeError, KeyError):
            return True  # malformed accepted support cannot become a silent revival
    if isinstance(row, Account):
        return row.id == account_id and (
            row in inspect(row).session.deleted
            or inspect(row).attrs.account_type.history.has_changes()
        )
    if isinstance(row, ExternalTransferLink):
        return any(t["id"] == str(row.id) for t in deps["transfer_links"])
    if account_id not in _values(row, "account_id"):
        return False
    if isinstance(row, ExternalFlow):
        return day in _values(row, "event_date")
    if isinstance(row, AccountPerformanceScopeMembership):
        if any(m["id"] == str(row.id) for m in deps["membership"]):
            return True
        starts, ends = _values(row, "effective_from"), _values(row, "effective_to")
    else:
        if any(c["id"] == str(row.id) for c in deps["cash_coverage"]):
            return True
        starts, ends = _values(row, "covered_from"), _values(row, "covered_to")
    return any((start or date.min) <= day <= (end or date.max) for start in starts for end in ends)


def _before_flush(session, _context, _instances):
    from hermes_finance.services.historical_owner_flows import _append, _rows

    for row in (*session.dirty, *session.deleted):
        if isinstance(row, HISTORY) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("historical owner flow history is append-only")
    if not inspect(session.connection()).has_table("historical_owner_flows"):
        return
    # Watch every sanctioned flush: canonical #800 support includes shared
    # catalogue tokens, and later listeners can add receipts to this flush.
    # V3 retires only after comparing the actual persisted bound support.
    session.info["owner_flow_section_recheck"] = True
    changes = [
        r
        for r in (*session.new, *session.dirty, *session.deleted)
        if isinstance(r, DEPENDENCIES)
        and (r in session.new or r in session.deleted or session.is_modified(r))
    ]
    if not changes or not inspect(session.connection()).has_table("historical_owner_flows"):
        return
    # Acquire the writer inside the sanctioned dependency transaction, before
    # reading frozen acceptances. No commits or financial dependency edits here.
    session.execute(text("UPDATE historical_owner_flow_revisions SET revision = revision WHERE 0"))
    with session.no_autoflush:
        latest = {r.flow_id: r for r in _rows(session, HistoricalOwnerFlowRevision)}
        for revision in session.new:
            if isinstance(revision, HistoricalOwnerFlowRevision):
                latest[revision.flow_id] = revision
        for current in latest.values():
            if current.acceptance_state != "accepted":
                continue
            core = session.get(HistoricalOwnerFlow, current.flow_id)
            evidence = json.loads(current.evidence_json)
            if evidence.get("contract_version") == SECTION_FLOW_CONTRACT:
                continue
            if any(_affects(change, core, evidence) for change in changes):
                _append(
                    session,
                    current.flow_id,
                    current,
                    evidence,
                    "retire",
                    "retired",
                    "dependency_changed",
                )


def _after_flush_postexec(session, _context):
    from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
    from hermes_finance.services.historical_owner_flows import _append, _build, _rows, _support
    from hermes_finance.statement_import.mybroker import MyBrokerError, digest

    if not session.info.pop("owner_flow_section_recheck", False):
        return
    with session.no_autoflush:
        latest = {r.flow_id: r for r in _rows(session, HistoricalOwnerFlowRevision)}
        for current in latest.values():
            if current.acceptance_state != "accepted":
                continue
            evidence = json.loads(current.evidence_json)
            if evidence.get("contract_version") != SECTION_FLOW_CONTRACT:
                continue
            try:
                frozen = OwnerFlowIntent.model_validate(evidence["intent"])
                rebuilt, reasons, _, _ = _build(session, frozen)
                changed = (
                    bool(reasons)
                    or frozen.evidence_version != SECTION_FLOW_CONTRACT
                    or digest(_support(evidence)) != current.material_signature
                    or _support(rebuilt) != _support(evidence)
                )
            except (ValueError, TypeError, KeyError, MyBrokerError):
                changed = True
            if changed:
                _append(
                    session,
                    current.flow_id,
                    current,
                    evidence,
                    "retire",
                    "retired",
                    "dependency_changed",
                )


def _after_rollback(session):
    session.info.pop("owner_flow_section_recheck", None)


def install_hooks():
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
    if not event.contains(Session, "after_flush_postexec", _after_flush_postexec):
        event.listen(Session, "after_flush_postexec", _after_flush_postexec)
    if not event.contains(Session, "after_rollback", _after_rollback):
        event.listen(Session, "after_rollback", _after_rollback)
