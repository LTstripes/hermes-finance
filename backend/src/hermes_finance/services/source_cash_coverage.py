"""Source-bound acceptance for CashBoundaryCoverage, never another cash ledger.

The directed dependency is S1 -> effective H2-A1 revision -> cash coverage.
No coverage operation accepts, reaffirms or revives a flow.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import InvalidOperation

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.historical_owner_flows import (
    COMPATIBLE_FLOW_CONTRACT,
    SOURCE_CASH_PROVENANCE,
)
from hermes_finance.domain.source_cash_coverage import CLAIMS, SourceCashIntent
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
    InKindBoundaryCoverage,
    InKindMovement,
    InvestmentCashFlow,
    MyBrokerImport,
    SourceCashCoverageApply,
    SourceCashCoverageRevision,
)
from hermes_finance.services.cash_boundary_coverage import closed_month_for_cash_boundary_interval
from hermes_finance.services.historical_owner_flows import (
    _binding,
    _material,
    _read_historical_owner_flow,
    _rows,
)
from hermes_finance.services.mybroker_dispositions import REASON, excluded_trade, impact
from hermes_finance.services.mybroker_import import _reduce
from hermes_finance.services.performance_availability import _history_covers_interval
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest

CONTRACT = "h2-a2-source-cash-rub-v1"
# These accounting limitations do not contradict exact non-owner linkage.
# Keep them in linked_trade evidence; every other (including future) blocker
# still prevents excluding Money from Owner boundary crossings.
_NON_OWNER_TRADE_CASH_LIMITATIONS = frozenset({"commission_basis_unresolved", "commission_missing"})


def latest(session, coverage_id):
    return session.scalar(
        select(SourceCashCoverageRevision)
        .where(SourceCashCoverageRevision.coverage_id == coverage_id)
        .order_by(SourceCashCoverageRevision.revision.desc())
        .limit(1)
    )


def _overlap(start, end, a, b):
    return start <= b and (end is None or end >= a)


def _union_and_gaps(ranges, start, end):
    union = []
    for a, b in sorted(ranges):
        if union and (union[-1][1] == date.max or a <= union[-1][1] + timedelta(days=1)):
            union[-1][1] = max(union[-1][1], b)
        else:
            union.append([a, b])
    gaps, cursor = [], start
    for a, b in union:
        if cursor < a:
            gaps.append([cursor, a - timedelta(days=1)])
        if b >= end:
            cursor = None
            break
        cursor = b + timedelta(days=1)
    if cursor is not None and cursor <= end:
        gaps.append([cursor, end])
    return (
        [[a.isoformat(), b.isoformat()] for a, b in union],
        [[a.isoformat(), b.isoformat()] for a, b in gaps],
    )


def inventory(session, account_id, a, b, *, retained=None):
    """Discover the full inventory, including absence sets and ineffective history.

    Raw accepted material is always bound. Invalid envelopes stay disclosed and
    blocked; they cannot make a previously relevant report disappear on revoke.
    """
    retained = retained or {}
    start = a + timedelta(days=1)
    blockers = set()
    account = session.get(Account, account_id)
    if account is None or account.account_type != "brokerage":
        blockers.add("brokerage_account_required")
    registry = _rows(session, BrokerIdentityMapping)
    aliases = {
        m.provider_identity
        for m in registry
        if m.provider == PROVIDER
        and m.subject_kind == "account"
        and m.hermes_account_id == account_id
    } | set(retained.get("aliases", []))
    flows = [
        f
        for f in _rows(session, HistoricalOwnerFlow)
        if f.account_id == account_id and a < f.event_date <= b
    ]
    owners = _rows(session, HistoricalOwnerFlowOccurrence)
    needed_sources = {o.import_id for o in owners if o.flow_id in {f.id for f in flows}}
    needed_sources.update(s["import_id"] for s in retained.get("sources", []))
    source_rows = _rows(session, MyBrokerImport)
    if needed_sources - {s.id for s in source_rows}:
        blockers.add("retained_source_missing")
    # Accepted original aliases survive mapping withdrawal/remap. Discover the
    # union first, independently of source upload order and current bindings.
    for source in source_rows:
        try:
            aliases.update(
                m["identity"]
                for m in json.loads(source.mappings_json)
                if m["kind"] == "account" and m["hermes_id"] == account_id
            )
        except (ValueError, TypeError, KeyError):
            pass
    trade_links = set()
    for source in source_rows:
        try:
            mappings = json.loads(source.mappings_json)
            document = json.loads(source.normalized_json)
            relevant = any(m["kind"] == "account" and m["identity"] in aliases for m in mappings)
            if (
                source.id in needed_sources
                or relevant
                and _overlap(source.covered_from, source.covered_to, start, b)
            ):
                for money in document["money"]:
                    if (
                        money["source_account"] in aliases
                        and a.isoformat() < money["date"] <= b.isoformat()
                        and money["kind"] in ("settlement", "commission")
                    ):
                        trade_links.add((money["source_account"], money["primary_id"]))
        except (ValueError, TypeError, KeyError):
            continue
    # Follow accepted native linkage across source chronology, even when the
    # supporting trade report's confirmed range lies outside this window.
    for source in source_rows:
        try:
            document = json.loads(source.normalized_json)
            if any(
                (t["core"]["source_account"], t["ids"][0]) in trade_links
                for t in document["trades"]
                if t["ids"]
            ):
                needed_sources.add(source.id)
        except (ValueError, TypeError, KeyError):
            if _overlap(source.covered_from, source.covered_to, start, b):
                needed_sources.add(source.id)
    sources, bindings, documents, ranges, scoped_money = [], [], [], [], []
    for source in source_rows:
        intersects = _overlap(source.covered_from, source.covered_to, start, b)
        try:
            accepted = json.loads(source.mappings_json)
            relevant_aliases = {
                m["identity"]
                for m in accepted
                if m["kind"] == "account"
                and (m["hermes_id"] == account_id or m["identity"] in aliases)
            }
            try:
                observed = json.loads(source.normalized_json)
                relevant_aliases.update(aliases.intersection(observed["source_accounts"]))
            except (ValueError, KeyError, TypeError):
                pass
        except (ValueError, TypeError, KeyError):
            accepted, relevant_aliases = [], set()
            if intersects or source.id in needed_sources:
                blockers.add("source_account_attribution_invalid")
                relevant_aliases = aliases
        if source.id not in needed_sources and not (intersects and relevant_aliases):
            continue
        item = {
            "import_id": source.id,
            "material": _material(
                source,
                (
                    "id",
                    "document_sha256",
                    "covered_from",
                    "covered_to",
                    "parser_version",
                    "confirmation_digest",
                    "mappings_json",
                    "accepted_at",
                ),
            ),
            "normalized_content_fingerprint": digest(source.normalized_json),
            "full_range": [source.covered_from.isoformat(), source.covered_to.isoformat()],
            "clipped_range": [
                max(start, source.covered_from).isoformat(),
                min(b, source.covered_to).isoformat(),
            ]
            if intersects
            else None,
        }
        sources.append(item)
        if intersects:
            ranges.append((max(start, source.covered_from), min(b, source.covered_to)))
        try:
            document = json.loads(source.normalized_json)
            if (
                source.parser_version != "mybroker-s1-v2"
                or document["parser"] != source.parser_version
                or document["provider"] != PROVIDER
                or document["document_sha256"] != source.document_sha256
                or document["covered_from"] != source.covered_from.isoformat()
                or document["covered_to"] != source.covered_to.isoformat()
            ):
                blockers.add("source_integrity_or_version")
            # Opaque sections cannot be scoped more finely than the full range.
            if intersects:
                blockers.update(document["syntax_blockers"])
                if "position_row_unclassified" in document["endpoint_blockers"]:
                    blockers.add("source_cash_scope_uninterpretable")
            item["section_inventory"] = document["section_inventory"]
            needed = relevant_aliases | {document["filename_account"]}
            for alias in sorted(needed):
                bindings.append(
                    {
                        "import_id": source.id,
                        **_binding(session, source, alias, account_id, registry, blockers),
                    }
                )
            item["aliases"] = sorted(relevant_aliases)
            documents.append(document)
            for row in document["money"]:
                if row["source_account"] not in relevant_aliases:
                    continue
                day = date.fromisoformat(row["date"])
                if not source.covered_from <= day <= source.covered_to:
                    blockers.add("source_date_out_of_range")
                if a < day <= b:
                    scoped_money.append((source.id, row))
                    if row["currency"] != "RUB":
                        blockers.add("source_currency_unsupported")
        except (ValueError, KeyError, TypeError):
            blockers.add("source_envelope_invalid")
    source_union, gaps = _union_and_gaps(ranges, start, b)
    if gaps:
        blockers.add("source_range_gap")
    # Bind current and historical lifecycle rows for every relevant alias and
    # accepted mapping ID, including instrument support used by trade exclusions.
    accepted_ids = set()
    identities = set()
    for item in sources:
        try:
            for m in json.loads(item["material"]["mappings_json"]):
                accepted_ids.add(m["mapping_id"])
                identities.add((m["kind"], m["identity"]))
                matches = [
                    r
                    for r in registry
                    if r.id == m["mapping_id"]
                    and r.provider == PROVIDER
                    and r.subject_kind == m["kind"]
                    and r.provider_identity == m["identity"]
                    and r.hermes_target_id == m["hermes_id"]
                    and r.status == "effective"
                ]
                if len(matches) != 1:
                    blockers.add("accepted_mapping_changed")
        except (ValueError, KeyError, TypeError):
            blockers.add("source_account_attribution_invalid")
    mappings = [
        m
        for m in registry
        if m.id in accepted_ids
        or m.provider == PROVIDER
        and (
            (m.subject_kind, m.provider_identity) in identities
            or m.subject_kind == "account"
            and (m.hermes_account_id == account_id or m.provider_identity in aliases)
        )
    ]
    for m in mappings:
        if m.id in accepted_ids and m.status != "effective":
            blockers.add("accepted_mapping_changed")
    membership = sorted(
        [
            m
            for m in _rows(session, AccountPerformanceScopeMembership)
            if m.account_id == account_id and _overlap(m.effective_from, m.effective_to, a, b)
        ],
        key=lambda m: (m.effective_from, m.id),
    )
    if not _history_covers_interval(membership, start_date=a, end_date=b) or any(
        not m.include_in_returns for m in membership
    ):
        blockers.add("historical_membership_not_continuously_included")
    flow_inventory, effective_ids = [], set()
    for flow in flows:
        try:
            view = _read_historical_owner_flow(session, flow.id)
            if view["effective_state"] != "accepted":
                blockers.add("historical_flow_not_effective")
            elif view["evidence"]["contract_version"] != COMPATIBLE_FLOW_CONTRACT:
                blockers.add("reviewed_flow_compatibility_required")
            else:
                effective_ids.add(flow.id)
            # Bind the acceptance identity/core/owners, not a duplicate of every
            # source document inside every flow's full API envelope.
            flow_inventory.append(
                {
                    "material": _material(flow),
                    "flow_id": view["flow_id"],
                    "revision_id": view["revision_id"],
                    "revision": view["revision"],
                    "material_signature": view["material_signature"],
                    "contract_version": view["evidence"]["contract_version"],
                    "frozen_core": view["evidence"]["core"],
                    "acceptance_state": view["acceptance_state"],
                    "effective_state": view["effective_state"],
                    "blockers": view["blockers"],
                    "owned_occurrences": view["owned_occurrences"],
                    "history": view["history"],
                }
            )
        except MyBrokerError:
            blockers.add("historical_flow_revision_missing")
            flow_inventory.append({"material": _material(flow), "readback": None})
    try:
        trades, _ = _reduce(documents)
    except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError):
        trades = {}
        blockers.add("source_trade_envelope_invalid")
    dispositions = []
    for import_id, row in scoped_money:
        occurrence = {
            "import_id": import_id,
            "section": "money",
            "ordinal": row["ordinal"],
            "row_fingerprint": digest(row),
            "row": row,
        }
        owned = [
            o
            for o in owners
            if (o.import_id, o.section, o.ordinal) == (import_id, "money", row["ordinal"])
        ]
        occurrence["owners"] = [_material(o) for o in owned]
        occurrence["disposition"] = "unresolved"
        if (
            len(owned) == 1
            and owned[0].flow_id in effective_ids
            and owned[0].row_fingerprint == digest(row)
        ):
            occurrence["disposition"] = "effective_owner_flow"
        elif not owned and row["kind"] in ("settlement", "commission"):
            identity = row.get("trade_identity")
            trade = trades.get(identity)
            matches = [
                t
                for t in trades.values()
                if t["core"]["source_account"] == row["source_account"]
                and t["ids"][0] == row["primary_id"]
            ]
            leg = {k: row[k] for k in ("kind", "date", "amount", "currency")}
            occurrence["linked_trade"] = trade
            if (
                trade
                and not excluded_trade(session, identity)
                and len(matches) == 1
                and trade["state"] == "settled"
                and not (set(trade["blockers"]) - _NON_OWNER_TRADE_CASH_LIMITATIONS)
                and leg in trade["cash_legs"]
            ):
                occurrence["disposition"] = "accepted_non_owner_trade_cash"
        if occurrence["disposition"] == "unresolved":
            blockers.add("money_disposition_unresolved")
        dispositions.append(occurrence)
    legacy = [
        f
        for f in _rows(session, ExternalFlow)
        if f.account_id == account_id and a < f.event_date <= b
    ]
    link_ids = {f.transfer_link_id for f in legacy if f.transfer_link_id is not None}
    linked_legs = [f for f in _rows(session, ExternalFlow) if f.transfer_link_id in link_ids]
    links = [t for t in _rows(session, ExternalTransferLink) if t.id in link_ids]
    reconciliation = [
        t
        for t in _rows(session, ExternalTransferReconciliationEvidence)
        if t.transfer_link_id in link_ids
    ]
    legacy_cash = [
        f
        for f in _rows(session, InvestmentCashFlow)
        if f.account_id == account_id and a < f.event_date <= b
    ]
    if legacy or legacy_cash:
        blockers.add("legacy_cash_or_transfer_overlap")
    in_kind = [
        m
        for m in _rows(session, InKindMovement)
        if account_id in (m.source_account_id, m.destination_account_id) and a < m.event_date <= b
    ]
    in_kind_coverage = [
        c
        for c in _rows(session, InKindBoundaryCoverage)
        if c.account_id == account_id and _overlap(c.covered_from, c.covered_to, start, b)
    ]
    if in_kind:
        blockers.add("in_kind_boundary_exposure")
    # Exact identity is the one canonical target, which is never its own input.
    coverage = [
        c
        for c in _rows(session, CashBoundaryCoverage)
        if c.account_id == account_id
        and _overlap(c.covered_from, c.covered_to, start, b)
        and (c.covered_from, c.covered_to) != (start, b)
    ]
    if coverage:
        blockers.add("overlapping_cash_coverage")
    exclusions = impact(session, (account_id,))
    if exclusions:
        blockers.add(REASON)
    result = {
        "account": _material(account, ("id", "account_type")) if account else None,
        "aliases": sorted(aliases),
        "sources": sources,
        "bindings": bindings,
        "mappings": [_material(m) for m in mappings],
        "source_range_union": source_union,
        "source_gaps": gaps,
        "membership": [_material(m) for m in membership],
        "flows": flow_inventory,
        "effective_flow_ids": sorted(effective_ids),
        "money_dispositions": dispositions,
        "trade_links": [list(link) for link in sorted(trade_links)],
        "legacy_flows": [_material(f) for f in legacy],
        "linked_legs": [_material(f) for f in linked_legs],
        "legacy_cash": [_material(f) for f in legacy_cash],
        "transfer_links": [_material(t) for t in links],
        "transfer_reconciliation": [_material(t) for t in reconciliation],
        "in_kind_movements": [_material(m) for m in in_kind],
        "in_kind_coverage": [_material(c) for c in in_kind_coverage],
        "competing_coverage": [_material(c) for c in coverage],
        "blockers": sorted(blockers),
    }
    if exclusions:
        result["instrument_dispositions"] = exclusions
    return result


def _support(evidence):
    return {k: v for k, v in evidence.items() if k != "intent"}


def _evidence(session, intent, account_id, a, b, *, retained=None):
    deps = inventory(session, account_id, a, b, retained=retained)
    identity = {
        "account_id": account_id,
        "scope": "account",
        "currency": "RUB",
        "opening_date": a.isoformat(),
        "closing_date": b.isoformat(),
        "covered_from": (a + timedelta(days=1)).isoformat(),
        "covered_to": b.isoformat(),
    }
    context = digest({"contract_version": CONTRACT, "identity": identity, "dependencies": deps})
    return {
        "contract_version": CONTRACT,
        "identity": identity,
        "dependencies": deps,
        "review_context_digest": context,
        "claims": intent.claims.model_dump(mode="json") if intent.claims else None,
        "intent": intent.model_dump(mode="json"),
    }


def _plan(session, intent):
    blockers = set()
    row = session.get(CashBoundaryCoverage, intent.coverage_id) if intent.coverage_id else None
    if intent.coverage_id and row is None:
        raise MyBrokerError("coverage_not_found")
    if intent.operation == "revoke":
        account_id, a, b = row.account_id, row.covered_from - timedelta(days=1), row.covered_to
    else:
        account_id, a, b = intent.account_id, intent.opening_date, intent.closing_date
        if row and (row.account_id, row.covered_from, row.covered_to) != (
            account_id,
            a + timedelta(days=1),
            b,
        ):
            blockers.add("coverage_identity_immutable")
        if row is None:
            row = session.scalar(
                select(CashBoundaryCoverage).where(
                    CashBoundaryCoverage.account_id == account_id,
                    CashBoundaryCoverage.covered_from == a + timedelta(days=1),
                    CashBoundaryCoverage.covered_to == b,
                )
            )
    current = latest(session, row.id) if row else None
    if intent.coverage_id and intent.expected_revision != (current.revision if current else 0):
        blockers.add("stale_coverage_revision")
    if intent.operation == "revoke" and current is None:
        blockers.add("source_coverage_revision_required")
    if (
        closed_month_for_cash_boundary_interval(
            session, covered_from=a + timedelta(days=1), covered_to=b
        )
        is not None
    ):
        blockers.add("closed_reporting_month_requires_reopen")
    old = json.loads(current.evidence_json) if current else None
    if intent.operation == "revoke":
        from hermes_finance.services.source_cash_coverage_lifecycle import DEPENDENCIES, _affects

        # Bind conflicts without parsing positive support: corrupt evidence
        # cannot prevent explicit withdrawal of its assertion.
        context = {
            model.__tablename__: [
                _material(r)
                for r in _rows(session, model)
                if (isinstance(r, Account) and r.id == account_id)
                or old
                and _affects(session, r, row, old)
            ]
            for model in DEPENDENCIES
        }
        evidence = {"frozen_assertion": old, "withdrawal_context": context}
        action = "noop" if current and current.acceptance_state == "revoked" else "revoked"
    else:
        evidence = _evidence(
            session, intent, account_id, a, b, retained=old["dependencies"] if old else None
        )
        blockers.update(evidence["dependencies"]["blockers"])
        claims = intent.claims
        if claims is None:
            blockers.add("owner_cash_coverage_claims_missing")
        else:
            if claims.review_context_digest != evidence["review_context_digest"]:
                blockers.add("claim_binding_mismatch")
            for name in CLAIMS:
                if not getattr(claims, name):
                    blockers.add(name + "_unconfirmed")
            if (
                not evidence["dependencies"]["effective_flow_ids"]
                and not claims.zero_owner_cash_crossings
            ):
                blockers.add("zero_owner_cash_crossings_unconfirmed")
            if evidence["dependencies"]["effective_flow_ids"] and claims.zero_owner_cash_crossings:
                blockers.add("zero_owner_cash_crossings_conflicts")
        identical = (
            current
            and current.acceptance_state == "accepted"
            and row.coverage_state == "complete"
            and row.provenance_kind == SOURCE_CASH_PROVENANCE
            and _support(old) == _support(evidence)
        )
        if row and not identical and intent.operation != "reaffirm":
            blockers.add("reviewed_reaffirmation_required")
        action = "noop" if identical else "reaffirmed" if row else "created"
    result = {
        "coverage_id": row.id if row else None,
        "target_revision": _material(current) if current else None,
        "evidence": evidence,
        "review_context_digest": evidence.get("review_context_digest"),
        "candidate_action": action,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "portfolio_scope": "unknown",
    }
    result["confirmation_digest"] = digest(
        {"contract": CONTRACT, "intent": intent.model_dump(mode="json"), "plan": result}
    )
    return result


@coherent_read_operation
def preview_source_cash_coverage(session, intent):
    return _plan(session, intent)


@coherent_read_operation
def read_source_cash_coverage(session, coverage_id):
    row = session.get(CashBoundaryCoverage, coverage_id)
    if row is None:
        raise MyBrokerError("coverage_not_found")
    current = latest(session, coverage_id)
    blockers, evidence, state = [], None, "unbound"
    if current:
        state = current.acceptance_state
        try:
            evidence = json.loads(current.evidence_json)
            identity = evidence["identity"]
            frozen = SourceCashIntent.model_validate(evidence["intent"])
            # Withdrawal revisions keep the last positive assertion's envelope.
            rebuilt = _evidence(
                session,
                frozen,
                identity["account_id"],
                date.fromisoformat(identity["opening_date"]),
                date.fromisoformat(identity["closing_date"]),
                retained=evidence["dependencies"],
            )
            if (
                evidence["contract_version"] != CONTRACT
                or frozen.claims is None
                or digest(_support(evidence)) != current.material_signature
                or _support(rebuilt) != _support(evidence)
                or (row.account_id, row.covered_from.isoformat(), row.covered_to.isoformat())
                != (identity["account_id"], identity["covered_from"], identity["covered_to"])
                or row.provenance_kind != SOURCE_CASH_PROVENANCE
                or row.coverage_state != "complete"
                or row.provenance_reference != frozen.claims.reference
            ):
                blockers.append("frozen_dependency_changed")
            blockers.extend(rebuilt["dependencies"]["blockers"])
            if frozen.claims.review_context_digest != rebuilt["review_context_digest"]:
                blockers.append("claim_binding_mismatch")
            if any(not getattr(frozen.claims, name) for name in CLAIMS):
                blockers.append("owner_cash_coverage_claims_missing")
            if (
                not rebuilt["dependencies"]["effective_flow_ids"]
                and not frozen.claims.zero_owner_cash_crossings
            ):
                blockers.append("zero_owner_cash_crossings_unconfirmed")
        except (ValueError, TypeError, KeyError, MyBrokerError):
            blockers.append("accepted_envelope_invalid")
    else:
        blockers.append("source_coverage_revision_missing")
    if state == "accepted" and blockers:
        state = "invalidated"
    effective = state == "accepted"
    history = [
        r for r in _rows(session, SourceCashCoverageRevision) if r.coverage_id == coverage_id
    ]
    return {
        "coverage_id": coverage_id,
        "revision_id": current.id if current else None,
        "revision": current.revision if current else 0,
        "acceptance_state": current.acceptance_state if current else "unbound",
        "effective_state": state,
        "coverage_state": "complete" if effective else "unknown",
        "blockers": sorted(set(blockers)),
        "evidence": evidence,
        "portfolio_scope": "unknown",
        "history": [
            {
                "id": r.id,
                "revision": r.revision,
                "operation": r.operation,
                "acceptance_state": r.acceptance_state,
                "previous_revision_id": r.previous_revision_id,
                "reason_code": r.reason_code,
                "previous_projection": json.loads(r.previous_projection_json),
            }
            for r in history
        ],
    }


def append_revision(session, row, current, evidence, operation, state, previous, reason=None):
    revision = SourceCashCoverageRevision(
        coverage_id=row.id,
        revision=current.revision + 1 if current else 1,
        previous_revision_id=current.id if current else None,
        operation=operation,
        acceptance_state=state,
        evidence_json=canonical(evidence),
        material_signature=digest(_support(evidence)),
        previous_projection_json=canonical(previous),
        reason_code=reason,
        recorded_at=datetime.now(UTC),
    )
    session.add(revision)
    return revision


def apply_source_cash_coverage(session, intent, *, confirmation_digest, request_id):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    intent_digest = digest(intent.model_dump(mode="json"))
    try:
        session.execute(
            text("UPDATE source_cash_coverage_revisions SET revision = revision WHERE 0")
        )
        session.expire_all()
        receipt = session.scalar(
            select(SourceCashCoverageApply).where(SourceCashCoverageApply.request_id == request_id)
        )
        if receipt:
            if (
                receipt.intent_digest != intent_digest
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
            coverage_id, revision_id, action, replay = (
                receipt.coverage_id,
                receipt.revision_id,
                receipt.result_action,
                True,
            )
        else:
            plan = _plan(session, intent)
            if plan["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError(";".join(plan["blockers"]))
            row = (
                session.get(CashBoundaryCoverage, plan["coverage_id"])
                if plan["coverage_id"]
                else None
            )
            previous = _material(row) if row else None
            evidence, action = plan["evidence"], plan["candidate_action"]
            # This exemption is bounded to the projection owned by this write;
            # all dependency writers still run normal transactional retirement.
            session.info["source_cash_projection_write"] = row.id if row else "new"
            if row is None:
                identity = evidence["identity"]
                row = CashBoundaryCoverage(
                    account_id=identity["account_id"],
                    covered_from=date.fromisoformat(identity["covered_from"]),
                    covered_to=date.fromisoformat(identity["covered_to"]),
                    coverage_state="complete",
                    provenance_kind=SOURCE_CASH_PROVENANCE,
                    provenance_reference=intent.claims.reference,
                )
                session.add(row)
                session.flush()
            current = latest(session, row.id)
            if action == "noop":
                revision = current
            else:
                if intent.operation == "revoke":
                    evidence = json.loads(current.evidence_json)
                row.coverage_state = "unknown" if intent.operation == "revoke" else "complete"
                row.provenance_kind = SOURCE_CASH_PROVENANCE
                if intent.claims:
                    row.provenance_reference = intent.claims.reference
                revision = append_revision(
                    session,
                    row,
                    current,
                    evidence,
                    intent.operation,
                    "revoked" if intent.operation == "revoke" else "accepted",
                    previous,
                    intent.reason_code,
                )
                session.flush()
            coverage_id, revision_id = row.id, revision.id
            session.add(
                SourceCashCoverageApply(
                    request_id=request_id,
                    intent_digest=intent_digest,
                    confirmation_digest=confirmation_digest,
                    coverage_id=coverage_id,
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
    finally:
        session.info.pop("source_cash_projection_write", None)
    with Session(session.get_bind(), autoflush=False) as fresh:
        readback = read_source_cash_coverage(fresh, coverage_id)
    return {
        "request_id": request_id,
        "committed_revision_id": revision_id,
        "result_action": action,
        "replayed": replay,
        "readback": readback,
    }
