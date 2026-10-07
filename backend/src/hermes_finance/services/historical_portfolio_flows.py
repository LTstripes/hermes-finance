"""H2-B1: one source-owned non-transfer, with a complete dated universe.

This ledger owns no cash facts or source occurrences. Every read reconstructs
the server-discovered dependency inventory; reads never repair acceptance.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.historical_owner_flows import SOURCE_CASH_PROVENANCE
from hermes_finance.domain.historical_portfolio_flows import (
    OUTSIDE_CLAIMS,
    ROSTER_CLAIMS,
    PortfolioFlowIntent,
)
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
from hermes_finance.services.historical_owner_flows import (
    _binding,
    _core,
    _material,
    _rows,
    read_historical_owner_flow,
)
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest

CONTRACT = "h2-b1-non-transfer-rub-v1"


def _account_read(session, flow_id):
    # Internal builders run only under the outer portfolio read snapshot or
    # Apply's reserved writer. Starting a committed-read snapshot inside the
    # writer is forbidden; use the same H2-A1 builder in the existing transaction.
    return read_historical_owner_flow.__wrapped__(session, flow_id)


def _latest(session, flow_id):
    return session.scalar(
        select(HistoricalPortfolioFlowRevision)
        .where(HistoricalPortfolioFlowRevision.flow_id == flow_id)
        .order_by(HistoricalPortfolioFlowRevision.revision.desc())
        .limit(1)
    )


def _opaque_material(row):
    """Bind free text without returning native references/notes to this API."""
    material = _material(row)
    for key in ("notes", "source", "transfer_key", "evidence_reference", "provenance_reference"):
        if key in material:
            material[key] = digest(material[key])
    return material


def _covers(row, day):
    return row.covered_from <= day <= row.covered_to


def _inventory(session, flow):
    """No caller-selected sources, leg clipping, amount pairing or netting."""
    day = flow.event_date
    blockers = set()
    accounts = _rows(session, Account)
    catalogue_ids = {a.id for a in accounts}
    registry = _rows(session, BrokerIdentityMapping)
    # All providers are disclosed. Registry/current flags do not prove history.
    mappings = [m for m in registry if m.subject_kind == "account"]
    if any(m.status == "effective" and m.hermes_account_id not in catalogue_ids for m in mappings):
        blockers.add("unresolved_account_identity")
    memberships = [
        m
        for m in _rows(session, AccountPerformanceScopeMembership)
        if m.effective_from <= day and (m.effective_to is None or day <= m.effective_to)
    ]
    account_read = _account_read(session, flow.id)
    owners = _rows(session, HistoricalOwnerFlowOccurrence)
    source_flows, effective_owners = [], set()
    for other in _rows(session, HistoricalOwnerFlow):
        # Dated Money relevance only; no equal/opposite amount comparison.
        if other.event_date != day:
            continue
        readback = _account_read(session, other.id)
        other_owners = [o for o in owners if o.flow_id == other.id]
        source_flows.append(
            {
                "flow_id": other.id,
                "core": _core(other),
                "revisions": [
                    _material(r)
                    for r in _rows(session, HistoricalOwnerFlowRevision)
                    if r.flow_id == other.id
                ],
                "owners": [_material(o) for o in other_owners],
                "effective_state": readback["effective_state"],
                "blockers": readback["blockers"],
            }
        )
        if readback["effective_state"] == "accepted":
            effective_owners.update((o.import_id, o.section, o.ordinal) for o in other_owners)
    sources, bindings, accepted_mapping_ids = [], [], set()
    source_accounts = set()
    for source in _rows(session, MyBrokerImport):
        if not _covers(source, day):
            continue  # supported persisted ranges prove this report is unrelated
        try:
            accepted = json.loads(source.mappings_json)
            document = json.loads(source.normalized_json)
            for binding in accepted:
                accepted_mapping_ids.add(binding["mapping_id"])
                current = next((m for m in registry if m.id == binding["mapping_id"]), None)
                if (
                    current is None
                    or current.status != "effective"
                    or current.provider != PROVIDER
                    or current.subject_kind != binding["kind"]
                    or current.provider_identity != binding["identity"]
                    or (
                        current.hermes_account_id
                        if binding["kind"] == "account"
                        else current.hermes_instrument_id
                    )
                    != binding["hermes_id"]
                ):
                    blockers.add("accepted_mapping_changed")
            account_bindings = [b for b in accepted if b["kind"] == "account"]
            if not account_bindings:
                raise ValueError("unresolved_source_accounts")
            # An accepted report with an unregistered identity cannot be scoped away.
            if any(b["hermes_id"] not in catalogue_ids for b in account_bindings):
                blockers.add("unresolved_source_account_identity")
            source_accounts.update(b["hermes_id"] for b in account_bindings)
            if (
                source.parser_version != "mybroker-s1-v2"
                or document["parser"] != source.parser_version
                or document["provider"] != PROVIDER
                or document["document_sha256"] != source.document_sha256
                or document["covered_from"] != source.covered_from.isoformat()
                or document["covered_to"] != source.covered_to.isoformat()
            ):
                blockers.add("source_integrity_or_version")
            blockers.update(document["syntax_blockers"])
            for name in ("4_Transfers", "5_UFSR"):
                count = document["section_inventory"][name]
                if type(count) is not int or count < 0:
                    raise ValueError("invalid_section_count")
                if count:
                    blockers.add(name + "_unsupported")
            aliases = {b["identity"] for b in account_bindings}
            if document["filename_account"] not in aliases:
                blockers.add("unresolved_source_account_identity")
            for b in account_bindings:
                bindings.append(
                    {
                        "import_id": source.id,
                        **_binding(
                            session, source, b["identity"], b["hermes_id"], registry, blockers
                        ),
                    }
                )
            for row in document["money"]:
                # Unknown/malformed dates cannot prove a row is unrelated. Do
                # not skip opaque evidence merely because it fails date equality.
                if date.fromisoformat(row["date"]).isoformat() != row["date"]:
                    raise ValueError("invalid_money_date")
                if row["source_account"] not in aliases:
                    blockers.add("unresolved_source_account_identity")
                if row["date"] != day.isoformat():
                    continue
                if (
                    row["kind"] == "unsupported"
                    and (source.id, "money", row["ordinal"]) not in effective_owners
                ):
                    blockers.add("unresolved_dated_money_semantics")
            sources.append({"import_id": source.id, "material": _material(source)})
        except (ValueError, TypeError, KeyError):
            blockers.add("source_envelope_invalid")
            sources.append({"import_id": source.id, "material": _material(source)})
    all_legacy = _rows(session, ExternalFlow)
    all_links = _rows(session, ExternalTransferLink)
    legacy = [f for f in all_legacy if f.account_id in catalogue_ids and f.event_date == day]
    links = []
    for link in all_links:
        legs = [f for f in all_legacy if f.transfer_link_id == link.id]
        if legs and not any(f.account_id in catalogue_ids for f in legs):
            continue
        # Unresolved/one-legged relevance cannot be dismissed by a date window.
        if (
            len(legs) != 2
            or link.status != "resolved"
            or min(f.event_date for f in legs) <= day <= max(f.event_date for f in legs)
        ):
            links.append(link)
            legacy.extend(f for f in legs if f not in legacy)
    # Full counterparts and reconciliation are loaded by explicit identity.
    link_ids = {t.id for t in links} | {f.transfer_link_id for f in legacy if f.transfer_link_id}
    links = [t for t in all_links if t.id in link_ids]
    legacy.extend(f for f in all_legacy if f.transfer_link_id in link_ids and f not in legacy)
    reconciliation = [
        r
        for r in _rows(session, ExternalTransferReconciliationEvidence)
        if r.transfer_link_id in link_ids
    ]
    if legacy or links:
        blockers.add("legacy_transfer_or_flow_identity_unresolved")
    coverage = {}
    for model in (CashBoundaryCoverage, InKindBoundaryCoverage, ClassNoCrossingCoverage):
        rows = [
            r
            for r in _rows(session, model)
            if _covers(r, day)
            and (model is not CashBoundaryCoverage or r.provenance_kind != SOURCE_CASH_PROVENANCE)
        ]
        coverage[model.__tablename__] = [_opaque_material(r) for r in rows]
        if model is CashBoundaryCoverage and any(r.coverage_state == "complete" for r in rows):
            blockers.add("legacy_complete_coverage_not_source_reconciled")
    deps = {
        "catalogue": [_material(a, ("id", "account_type")) for a in accounts],
        "memberships": [_material(m) for m in memberships],
        "account_mappings": [_opaque_material(m) for m in mappings],
        "accepted_mappings": [
            _opaque_material(m) for m in registry if m.id in accepted_mapping_ids
        ],
        "sources": sources,
        "bindings": bindings,
        "source_account_ids": sorted(source_accounts),
        "source_flows": source_flows,
        "legacy_flows": [_opaque_material(f) for f in sorted(legacy, key=lambda f: f.id)],
        "transfer_links": [_opaque_material(t) for t in links],
        "reconciliation": [_opaque_material(r) for r in reconciliation],
        "coverage": coverage,
        "target_flow_revision_id": account_read["revision_id"],
        "target_flow_revision": account_read["revision"],
        "target_effective_state": account_read["effective_state"],
        "target_core": account_read["core"],
        "target_occurrences": account_read["owned_occurrences"],
        "target_source_set_fingerprint": account_read["evidence"].get("source_set_fingerprint"),
        # Structural journal IDs are monotonic. Restoring A after B cannot make
        # the accepted support compare equal again, even for SQL bypass writers.
        "dependency_change_ids": [
            c.id
            for c in _rows(session, HistoricalPortfolioDependencyChange)
            if (c.covered_from is None or c.covered_from <= day)
            and (c.covered_to is None or day <= c.covered_to)
            and (c.account_id is None or c.account_id in catalogue_ids)
            and (
                c.table_name != "broker_identity_mappings"
                or c.mapping_kind == "account"
                or c.row_id in accepted_mapping_ids
            )
        ],
    }
    if account_read["effective_state"] != "accepted":
        blockers.add("account_flow_ineffective")
    return deps, sorted(blockers), account_read


def _build(session, flow, intent):
    deps, reasons, account = _inventory(session, flow)
    blockers = set(reasons)
    catalogue = {int(a["id"]): a for a in deps["catalogue"]}
    roster = intent.roster
    entries = roster.entries if roster else []
    tracked = sorted(e.account_id for e in entries if e.disposition == "tracked")
    included = []
    if roster is None:
        blockers.add("dated_roster_claims_missing")
    else:
        if (
            roster.event_date != flow.event_date
            or set(roster.catalogue_account_ids) != set(catalogue)
            or {e.account_id for e in entries} != set(catalogue)
        ):
            blockers.add("complete_catalogue_binding_required")
        for name in ROSTER_CLAIMS:
            if not getattr(roster, name):
                blockers.add(name + "_unconfirmed")
        for entry in entries:
            if not entry.historical_disposition_confirmed:
                blockers.add("historical_disposition_unconfirmed")
            matched = [m for m in deps["memberships"] if int(m["account_id"]) == entry.account_id]
            if entry.disposition != "tracked":
                if (
                    entry.account_id in deps["source_account_ids"]
                    or any(m["include_in_returns"] == "True" for m in matched)
                    or entry.account_id == flow.account_id
                ):
                    blockers.add("historical_disposition_contradicted")
                continue
            if len(matched) != 1:
                blockers.add("dated_membership_missing_or_ambiguous")
            elif matched[0]["include_in_returns"] == "True":
                included.append(entry.account_id)
                if catalogue.get(entry.account_id, {}).get("account_type") != "brokerage":
                    blockers.add("included_account_type_unsupported")
    source_memberships = [m for m in deps["memberships"] if int(m["account_id"]) == flow.account_id]
    not_in_scope = (
        flow.account_id in tracked
        and len(source_memberships) == 1
        and source_memberships[0]["include_in_returns"] == "False"
    )
    if not_in_scope:
        blockers.add("source_account_not_in_scope")
    elif flow.account_id not in included:
        blockers.add("source_account_inclusion_unproven")
    context = digest(
        {
            "contract": CONTRACT,
            "flow_id": flow.id,
            "dependencies": deps,
            "roster_entries": [e.model_dump(mode="json") for e in entries],
            "tracked_account_ids": tracked,
            "included_account_ids": sorted(included),
        }
    )
    if roster and roster.review_context_digest != context:
        blockers.add("roster_binding_mismatch")
    outside = intent.outside
    if outside is None:
        blockers.add("outside_universe_claims_missing")
    else:
        if (
            outside.flow_id != flow.id
            or outside.flow_revision_id != account["revision_id"]
            or outside.source_set_fingerprint != deps["target_source_set_fingerprint"]
            or outside.review_context_digest != context
        ):
            blockers.add("outside_claim_binding_mismatch")
        for name in OUTSIDE_CLAIMS:
            if not getattr(outside, name):
                blockers.add(name + "_unconfirmed")
    evidence = {
        "contract_version": CONTRACT,
        "flow_id": flow.id,
        "core": _core(flow),
        "dependencies": deps,
        "roster": roster.model_dump(mode="json") if roster else None,
        "outside": outside.model_dump(mode="json") if outside else None,
        "tracked_account_ids": tracked,
        "included_account_ids": sorted(included),
        "review_context_digest": context,
    }
    return evidence, sorted(blockers), account, not_in_scope


def _plan(session, intent):
    flow = session.get(HistoricalOwnerFlow, intent.flow_id)
    if flow is None:
        raise MyBrokerError("flow_not_found")
    current = _latest(session, flow.id)
    blockers = set()
    if (current.revision if current else 0) != intent.expected_portfolio_revision:
        blockers.add("stale_portfolio_revision")
    if intent.operation == "revoke":
        account = _account_read(session, flow.id)
        evidence = json.loads(current.evidence_json) if current else None
        if current is None:
            blockers.add("portfolio_acceptance_not_found")
        action = "noop" if current and current.acceptance_state == "revoked" else "revoked"
        # Withdrawal never depends on positive source/roster support. Bind all
        # current structural material, including malformed sources, for staleness.
        withdrawal = {
            model.__tablename__: [_opaque_material(r) for r in _rows(session, model)]
            for model in (
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
        }
    else:
        evidence, reasons, account, _ = _build(session, flow, intent)
        blockers.update(reasons)
        withdrawal = None
        identical = bool(current and json.loads(current.evidence_json) == evidence)
        action = "accepted" if current is None else "reaffirmed"
        if current and current.acceptance_state == "accepted" and identical:
            action = "noop"
        elif current and intent.operation == "accept":
            blockers.add("reviewed_reaffirmation_required")
    if account["revision"] != intent.expected_flow_revision:
        blockers.add("stale_flow_revision")
    result = {
        "flow_id": flow.id,
        "evidence": evidence,
        "account_scope": account["account_scope"],
        "portfolio_scope": {"status": "unknown", "classification": None},
        "cash_coverage": "unknown",
        "target": _material(current) if current else None,
        "withdrawal_context": withdrawal,
        "candidate_action": action,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "review_context_digest": evidence.get("review_context_digest") if evidence else None,
        "source_set_fingerprint": account["evidence"].get("source_set_fingerprint"),
    }
    result["confirmation_digest"] = digest(
        {
            "contract": CONTRACT,
            "intent": intent.model_dump(mode="json"),
            "plan": result,
        }
    )
    return result


@coherent_read_operation
def preview_historical_portfolio_flow(session: Session, intent: PortfolioFlowIntent):
    return _plan(session, intent)


@coherent_read_operation
def read_historical_portfolio_flow(session: Session, flow_id: str):
    flow = session.get(HistoricalOwnerFlow, flow_id)
    if flow is None:
        raise MyBrokerError("flow_not_found")
    account = _account_read(session, flow_id)
    current = _latest(session, flow_id)
    blockers, evidence, state = [], None, "unaccepted"
    if current is None:
        blockers.append("portfolio_acceptance_missing")
        if account["effective_state"] != "accepted":
            blockers.append("account_flow_ineffective")
    if current:
        state = current.acceptance_state
        evidence = json.loads(current.evidence_json)
        try:
            if evidence["contract_version"] != CONTRACT:
                raise ValueError("invalid_contract")
            frozen = PortfolioFlowIntent(
                flow_id=flow_id,
                expected_flow_revision=account["revision"],
                expected_portfolio_revision=current.revision,
                roster=evidence["roster"],
                outside=evidence["outside"],
            )
            rebuilt, reasons, _, _ = _build(session, flow, frozen)
            blockers.extend(reasons)
            if digest(evidence) != current.material_signature or rebuilt != evidence:
                blockers.append("frozen_dependency_changed")
        except (ValueError, TypeError, KeyError, MyBrokerError):
            blockers.append("accepted_portfolio_envelope_invalid")
        if state == "accepted" and blockers:
            state = "invalidated"
    effective = state == "accepted"
    # A unique explicit exclusion is disclosed separately even before acceptance.
    membership = [
        m
        for m in _rows(session, AccountPerformanceScopeMembership)
        if m.account_id == flow.account_id
        and m.effective_from <= flow.event_date
        and (m.effective_to is None or flow.event_date <= m.effective_to)
    ]
    excluded = len(membership) == 1 and membership[0].include_in_returns is False
    status = "authoritative" if effective else "not_in_scope" if excluded else "unknown"
    if excluded:
        blockers.append("source_account_not_in_scope")
    return {
        "flow_id": flow_id,
        "core": _core(flow),
        "account_scope": account["account_scope"],
        "account_effective_state": account["effective_state"],
        "account_revision": account["revision"],
        "portfolio_scope": {
            "status": status,
            "classification": "external_" + flow.direction if effective else None,
        },
        "boundary_amount_kopecks": flow.boundary_amount_kopecks if effective else None,
        "authority_kind": "owner_attested_source_row",
        "cash_coverage": "unknown",
        "revision": current.revision if current else 0,
        "revision_id": current.id if current else None,
        "acceptance_state": current.acceptance_state if current else "unaccepted",
        "effective_state": state,
        "blockers": sorted(set(blockers)),
        "evidence": evidence,
        "history": [
            {
                **_material(
                    r,
                    (
                        "id",
                        "revision",
                        "operation",
                        "acceptance_state",
                        "previous_revision_id",
                        "reason_code",
                    ),
                ),
                "evidence": json.loads(r.evidence_json),
            }
            for r in _rows(session, HistoricalPortfolioFlowRevision)
            if r.flow_id == flow_id
        ],
    }


def _append(session, flow_id, current, evidence, operation, state, reason=None):
    row = HistoricalPortfolioFlowRevision(
        flow_id=flow_id,
        revision=current.revision + 1 if current else 1,
        previous_revision_id=current.id if current else None,
        operation=operation,
        acceptance_state=state,
        evidence_json=canonical(evidence),
        material_signature=digest(evidence),
        reason_code=reason,
        recorded_at=datetime.now(UTC),
    )
    session.add(row)
    return row


def apply_historical_portfolio_flow(session, intent, *, confirmation_digest, request_id):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    intent_digest = digest(intent.model_dump(mode="json"))
    try:
        session.execute(
            text("UPDATE historical_portfolio_flow_revisions SET revision = revision WHERE 0")
        )
        session.expire_all()
        receipt = session.scalar(
            select(HistoricalPortfolioFlowApply).where(
                HistoricalPortfolioFlowApply.request_id == request_id
            )
        )
        if receipt:
            if (
                receipt.intent_digest != intent_digest
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
            revision_id, action, replay = receipt.revision_id, receipt.result_action, True
        else:
            plan = _plan(session, intent)
            if plan["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError(";".join(plan["blockers"]))
            current = _latest(session, intent.flow_id)
            action = plan["candidate_action"]
            revision = (
                current
                if action == "noop"
                else _append(
                    session,
                    intent.flow_id,
                    current,
                    plan["evidence"],
                    intent.operation,
                    "revoked" if intent.operation == "revoke" else "accepted",
                    intent.reason_code,
                )
            )
            session.flush()
            revision_id = revision.id
            session.add(
                HistoricalPortfolioFlowApply(
                    request_id=request_id,
                    intent_digest=intent_digest,
                    confirmation_digest=confirmation_digest,
                    flow_id=intent.flow_id,
                    revision_id=revision_id,
                    result_action=action,
                    committed_at=datetime.now(UTC),
                )
            )
            session.flush()
            replay = False
        session.commit()
    except Exception:
        session.rollback()
        raise
    with Session(session.get_bind(), autoflush=False) as fresh:
        readback = read_historical_portfolio_flow(fresh, intent.flow_id)
    return {
        "request_id": request_id,
        "committed_revision_id": revision_id,
        "result_action": action,
        "replayed": replay,
        "readback": readback,
    }
