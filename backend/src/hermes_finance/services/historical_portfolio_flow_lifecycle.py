"""Transactional portfolio retirement across the entire dated catalogue."""

import json
from datetime import date

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from hermes_finance.domain.historical_owner_flows import SOURCE_CASH_PROVENANCE
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBoundaryCoverage,
    ClassNoCrossingCoverage,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    HistoricalPortfolioDependencyChange,
    HistoricalPortfolioFlowApply,
    HistoricalPortfolioFlowRevision,
    InKindBoundaryCoverage,
    MyBrokerImport,
)
from hermes_finance.services.historical_owner_flow_lifecycle import _values

HISTORY = (
    HistoricalPortfolioFlowRevision,
    HistoricalPortfolioFlowApply,
    HistoricalPortfolioDependencyChange,
)
DEPENDENCIES = (
    Account,
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    MyBrokerImport,
    HistoricalOwnerFlowRevision,
    HistoricalOwnerFlowOccurrence,
    ExternalFlow,
    ExternalTransferLink,
    ExternalTransferReconciliationEvidence,
    CashBoundaryCoverage,
    InKindBoundaryCoverage,
    ClassNoCrossingCoverage,
)


def _affects(session, row, evidence):
    from hermes_finance.services.historical_owner_flows import _rows

    # Source-aware coverage owns a separate authority. Preserve both sides of
    # provenance transitions so a legacy dependency cannot disappear silently.
    if isinstance(row, CashBoundaryCoverage) and _values(row, "provenance_kind") == {
        SOURCE_CASH_PROVENANCE
    }:
        return False
    deps = evidence["dependencies"]
    day = date.fromisoformat(evidence["core"]["event_date"])
    catalogue = {int(a["id"]) for a in deps["catalogue"]}
    if isinstance(row, Account):
        return (
            row in session.new
            or row in session.deleted
            or inspect(row).attrs.account_type.history.has_changes()
        )
    if isinstance(row, BrokerIdentityMapping):
        return "account" in _values(row, "subject_kind") or any(
            int(m["id"]) == row.id for m in deps["accepted_mappings"]
        )
    if isinstance(row, (HistoricalOwnerFlowRevision, HistoricalOwnerFlowOccurrence)):
        core = session.get(HistoricalOwnerFlow, row.flow_id)
        return row.flow_id == evidence["flow_id"] or core is None or core.event_date == day
    if isinstance(row, (ExternalTransferLink, ExternalTransferReconciliationEvidence)):
        link_ids = {int(t["id"]) for t in deps["transfer_links"]}
        target_ids = (
            {row.id} if isinstance(row, ExternalTransferLink) else _values(row, "transfer_link_id")
        )
        if target_ids.intersection(link_ids):
            return True
        for link_id in target_ids:
            link = (
                row
                if isinstance(row, ExternalTransferLink)
                else session.get(ExternalTransferLink, link_id)
            )
            legs = [f for f in _rows(session, ExternalFlow) if f.transfer_link_id == link_id]
            legs.extend(
                f
                for f in session.new
                if isinstance(f, ExternalFlow) and f.transfer_link_id == link_id
            )
            if (
                not legs
                or any(f.account_id in catalogue for f in legs)
                and (
                    link is None
                    or link.status != "resolved"
                    or len(legs) != 2
                    or min(f.event_date for f in legs) <= day <= max(f.event_date for f in legs)
                )
            ):
                return True
        return False
    if isinstance(row, ExternalFlow):
        if any(int(f["id"]) == row.id for f in deps["legacy_flows"]):
            return True
        if not _values(row, "account_id").intersection(catalogue):
            return False
        if day in _values(row, "event_date"):
            return True
        # Changing a linked leg can alter counterpart/transit relevance. Bind the
        # explicit link even for legs outside the reviewed source report range.
        return any(v is not None for v in _values(row, "transfer_link_id"))
    if isinstance(row, MyBrokerImport):
        if any(s["import_id"] == row.id for s in deps["sources"]):
            return True
        starts, ends = _values(row, "covered_from"), _values(row, "covered_to")
    elif isinstance(row, AccountPerformanceScopeMembership):
        if not _values(row, "account_id").intersection(catalogue):
            return False
        if any(int(m["id"]) == row.id for m in deps["memberships"]):
            return True
        starts, ends = _values(row, "effective_from"), _values(row, "effective_to")
    else:
        if any(int(c["id"]) == row.id for c in deps["coverage"][row.__tablename__]):
            return True
        starts, ends = _values(row, "covered_from"), _values(row, "covered_to")
    return any((start or date.min) <= day <= (end or date.max) for start in starts for end in ends)


def _before_flush(session, _context, _instances):
    from hermes_finance.services.historical_owner_flows import _rows
    from hermes_finance.services.historical_portfolio_flows import _append

    for row in (*session.dirty, *session.deleted):
        if isinstance(row, HISTORY) and (row in session.deleted or session.is_modified(row)):
            raise ValueError("historical portfolio history is append-only")
    changes = [
        r
        for r in (*session.new, *session.dirty, *session.deleted)
        if isinstance(r, DEPENDENCIES)
        and (r in session.new or r in session.deleted or session.is_modified(r))
    ]
    if not changes or not inspect(session.connection()).has_table(
        "historical_portfolio_flow_revisions"
    ):
        return
    session.execute(
        text("UPDATE historical_portfolio_flow_revisions SET revision = revision WHERE 0")
    )
    with session.no_autoflush:
        latest = {r.flow_id: r for r in _rows(session, HistoricalPortfolioFlowRevision)}
        for revision in session.new:
            if isinstance(revision, HistoricalPortfolioFlowRevision):
                latest[revision.flow_id] = revision
        for current in latest.values():
            if current.acceptance_state != "accepted":
                continue
            evidence = json.loads(current.evidence_json)
            if any(_affects(session, change, evidence) for change in changes):
                _append(
                    session,
                    current.flow_id,
                    current,
                    evidence,
                    "retire",
                    "retired",
                    "dependency_changed",
                )


def install_hooks():
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
