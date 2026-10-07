"""Transactional retirement on dependency loss, including CLOSED intervals."""

import json
from datetime import date, timedelta

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBoundaryCoverage,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    InKindBoundaryCoverage,
    InKindMovement,
    InvestmentCashFlow,
    MyBrokerImport,
    SourceCashCoverageApply,
    SourceCashCoverageRevision,
)
from hermes_finance.services.historical_owner_flow_lifecycle import _values

DEPENDENCIES = (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    MyBrokerImport,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowRevision,
    HistoricalOwnerFlowOccurrence,
    ExternalFlow,
    InvestmentCashFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    InKindMovement,
    InKindBoundaryCoverage,
    CashBoundaryCoverage,
)


def _intersects(row, start_name, end_name, a, b):
    return any(
        (start or date.min) <= b and (end or date.max) >= a
        for start in _values(row, start_name)
        for end in _values(row, end_name)
    )


def _affects(session, change, row, evidence):
    deps = evidence["dependencies"]
    account_id, start, end = row.account_id, row.covered_from, row.covered_to
    if isinstance(change, Account):
        return change.id == account_id and (
            change in session.deleted or inspect(change).attrs.account_type.history.has_changes()
        )
    if isinstance(change, BrokerIdentityMapping):
        return (
            any(m["id"] == str(change.id) for m in deps["mappings"])
            or "alfa_mybroker" in _values(change, "provider")
            and (
                account_id in _values(change, "hermes_account_id")
                or any(alias in _values(change, "provider_identity") for alias in deps["aliases"])
            )
        )
    if isinstance(change, MyBrokerImport):
        if any(s["import_id"] == change.id for s in deps["sources"]):
            return True
        if not _intersects(change, "covered_from", "covered_to", start, end):
            try:
                return any(
                    [t["core"]["source_account"], t["ids"][0]] in deps["trade_links"]
                    for payload in _values(change, "normalized_json")
                    for t in json.loads(payload)["trades"]
                    if t["ids"]
                )
            except (ValueError, KeyError, TypeError):
                return False
        try:
            return any(
                m["kind"] == "account"
                and (m["hermes_id"] == account_id or m["identity"] in deps["aliases"])
                for payload in _values(change, "mappings_json")
                for m in json.loads(payload)
            )
        except (ValueError, KeyError, TypeError):
            return True
    if isinstance(change, (HistoricalOwnerFlowRevision, HistoricalOwnerFlowOccurrence)):
        flow = session.get(HistoricalOwnerFlow, change.flow_id)
        return (
            flow is not None and flow.account_id == account_id and start <= flow.event_date <= end
        )
    if isinstance(change, (ExternalTransferLink, ExternalTransferReconciliationEvidence)):
        link_ids = {int(t["id"]) for t in deps["transfer_links"]}
        return (
            change.id in link_ids
            if isinstance(change, ExternalTransferLink)
            else bool(link_ids.intersection(_values(change, "transfer_link_id")))
        )
    if isinstance(change, ExternalFlow):
        linked_ids = {int(f["id"]) for f in deps["linked_legs"]}
        link_ids = {int(t["id"]) for t in deps["transfer_links"]}
        if change.id in linked_ids or link_ids.intersection(_values(change, "transfer_link_id")):
            return True
    if isinstance(change, InKindMovement):
        return account_id in (
            _values(change, "source_account_id") | _values(change, "destination_account_id")
        ) and any(start <= day <= end for day in _values(change, "event_date"))
    if account_id not in _values(change, "account_id"):
        return False
    if isinstance(change, AccountPerformanceScopeMembership):
        return _intersects(change, "effective_from", "effective_to", start - timedelta(days=1), end)
    if isinstance(change, (ExternalFlow, InvestmentCashFlow, HistoricalOwnerFlow)):
        return any(start <= day <= end for day in _values(change, "event_date"))
    if isinstance(change, CashBoundaryCoverage) and change.id == row.id:
        return session.info.get("source_cash_projection_write") != row.id
    return _intersects(change, "covered_from", "covered_to", start, end)


def _before_flush(session, _context, _instances):
    from hermes_finance.services.historical_owner_flows import _material, _rows
    from hermes_finance.services.source_cash_coverage import append_revision

    for change in (*session.dirty, *session.deleted):
        if isinstance(change, (SourceCashCoverageRevision, SourceCashCoverageApply)) and (
            change in session.deleted or session.is_modified(change)
        ):
            raise ValueError("source cash coverage history is append-only")
    changes = [
        r
        for r in (*session.new, *session.dirty, *session.deleted)
        if isinstance(r, DEPENDENCIES)
        and (r in session.new or r in session.deleted or session.is_modified(r))
    ]
    if not changes or not inspect(session.connection()).has_table("source_cash_coverage_revisions"):
        return
    session.execute(text("UPDATE source_cash_coverage_revisions SET revision = revision WHERE 0"))
    with session.no_autoflush:
        latest = {r.coverage_id: r for r in _rows(session, SourceCashCoverageRevision)}
        for revision in session.new:
            if isinstance(revision, SourceCashCoverageRevision):
                latest[revision.coverage_id] = revision
        for current in latest.values():
            row = session.get(CashBoundaryCoverage, current.coverage_id)
            if row is None:
                continue
            if row in session.deleted or any(
                inspect(row).attrs[n].history.has_changes()
                for n in ("account_id", "covered_from", "covered_to")
            ):
                raise ValueError("source cash coverage identity is immutable")
            if current.acceptance_state != "accepted":
                continue
            evidence = json.loads(current.evidence_json)
            if any(_affects(session, change, row, evidence) for change in changes):
                previous = _material(row)
                for name in row.__table__.columns.keys():
                    deleted = inspect(row).attrs[name].history.deleted
                    if deleted:
                        previous[name] = str(deleted[0])
                row.coverage_state = "unknown"
                append_revision(
                    session,
                    row,
                    current,
                    evidence,
                    "retire",
                    "retired",
                    previous,
                    "dependency_changed",
                )


def install_hooks():
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
