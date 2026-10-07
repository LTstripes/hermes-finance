"""Bounded H2-A1 source-backed account cash, independent of monthly facts."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain.historical_owner_flows import CLAIMS, OwnerFlowIntent
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
    ReportingMonth,
)
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest
from hermes_finance.statement_import.mybroker import decimal as source_decimal

CONTRACT = "h2-a1-owner-rub-v1"
MAX_MINOR = 2**63 - 1


def _rows(session, model):
    return list(session.scalars(select(model).order_by(model.id)))


def _material(row, fields=None):
    return {name: str(getattr(row, name)) for name in (fields or row.__table__.columns.keys())}


def _latest(session, flow_id):
    return session.scalar(
        select(HistoricalOwnerFlowRevision)
        .where(HistoricalOwnerFlowRevision.flow_id == flow_id)
        .order_by(HistoricalOwnerFlowRevision.revision.desc())
        .limit(1)
    )


def _money_core(account_id, row, blockers):
    try:
        day = date.fromisoformat(row["date"])
        if (
            row["date"] != day.isoformat()
            or not isinstance(row["amount"], str)
            or source_decimal(row["amount"]) != row["amount"]
        ):
            raise ValueError("noncanonical_source_money")
        value = Decimal(row["amount"])
        if not value.is_finite():
            raise InvalidOperation
        with localcontext() as context:
            context.prec = max(32, len(value.as_tuple().digits) + 4)
            minor = abs(value) * 100
            if minor != minor.to_integral_value():
                blockers.add("fractional_kopeck")
            if minor == 0 or minor > MAX_MINOR:
                blockers.add("amount_out_of_bounds")
            if row["currency"] != "RUB":
                blockers.add("source_currency_unsupported")
            if blockers:
                return None
            return {
                "account_id": account_id,
                "event_date": day.isoformat(),
                "currency": "RUB",
                "signed_source_amount": row["amount"],
                "direction": "contribution" if value > 0 else "withdrawal",
                "boundary_amount_kopecks": int(minor),
            }
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError, MyBrokerError):
        blockers.add("source_money_invalid")
        return None


def _core(flow):
    return {
        "account_id": flow.account_id,
        "event_date": flow.event_date.isoformat(),
        "currency": flow.currency,
        "signed_source_amount": flow.signed_source_amount,
        "direction": flow.direction,
        "boundary_amount_kopecks": flow.boundary_amount_kopecks,
    }


def _binding(session, source, alias, account_id, registry, blockers):
    accepted = [
        b
        for b in json.loads(source.mappings_json)
        if b["kind"] == "account" and b["identity"] == alias
    ]
    active = [
        m
        for m in registry
        if m.provider == PROVIDER
        and m.subject_kind == "account"
        and m.provider_identity == alias
        and m.status == "effective"
    ]
    if (
        len(accepted) != 1
        or len(active) != 1
        or accepted[0]["mapping_id"] != active[0].id
        or accepted[0]["hermes_id"] != account_id
        or active[0].hermes_account_id != account_id
    ):
        blockers.add("accepted_mapping_changed")
    return {
        "alias": alias,
        "accepted": accepted,
        "active": [_material(m) for m in active],
    }


def _build(session, intent):
    """Discover all accepted reports covering the source date for this account.

    Equality only discovers a cohort to review. It never establishes identity.
    The entire scoped inventory and inclusive report ranges are digest-bound.
    """
    blockers = set()
    selected = session.get(MyBrokerImport, intent.seed.import_id)
    if selected is None:
        raise MyBrokerError("source_import_not_found")
    try:
        document = json.loads(selected.normalized_json)
        seeds = [r for r in document["money"] if r["ordinal"] == intent.seed.ordinal]
        if len(seeds) != 1 or seeds[0].get("section") != "money":
            raise MyBrokerError("source_occurrence_not_found")
        seed = seeds[0]
        core = _money_core(intent.account_id, seed, blockers)
        if core is None:
            # Inspection still returns source financial observations on rejection.
            return (
                {"intent": intent.model_dump(mode="json"), "core": None, "seed": seed},
                sorted(blockers),
                None,
                None,
            )
        day = date.fromisoformat(core["event_date"])
        if seed.get("kind") != "unsupported" or seed.get("primary_id") is not None:
            blockers.add("source_trade_linkage_unsupported")
        if not selected.covered_from <= day <= selected.covered_to:
            blockers.add("source_date_out_of_range")
        registry = _rows(session, BrokerIdentityMapping)
        active_aliases = {
            m.provider_identity
            for m in registry
            if m.provider == PROVIDER
            and m.subject_kind == "account"
            and m.status == "effective"
            and m.hermes_account_id == intent.account_id
        }
        account = session.get(Account, intent.account_id)
        if account is None or account.account_type != "brokerage":
            blockers.add("brokerage_account_required")
        sources, occurrences, bindings = [], [], []
        for source in _rows(session, MyBrokerImport):
            accepted = json.loads(source.mappings_json)
            aliases = {
                b["identity"]
                for b in accepted
                if b["kind"] == "account" and b["hermes_id"] == intent.account_id
            } | active_aliases.intersection(
                b["identity"] for b in accepted if b["kind"] == "account"
            )
            if source.id != selected.id and (
                not aliases or not source.covered_from <= day <= source.covered_to
            ):
                continue
            other = json.loads(source.normalized_json)
            if (
                source.parser_version != "mybroker-s1-v2"
                or other["parser"] != source.parser_version
                or other["provider"] != PROVIDER
                or other["document_sha256"] != source.document_sha256
                or other["covered_from"] != source.covered_from.isoformat()
                or other["covered_to"] != source.covered_to.isoformat()
            ):
                blockers.add("source_integrity_or_version")
            blockers.update(other["syntax_blockers"])
            money = [r for r in other["money"] if r["source_account"] in aliases]
            if source.id == selected.id and seed["source_account"] not in aliases:
                blockers.add("selected_account_mapping_mismatch")
            needed = {other["filename_account"]} | {r["source_account"] for r in money}
            for alias in sorted(needed):
                bindings.append(
                    {
                        "import_id": source.id,
                        **_binding(session, source, alias, intent.account_id, registry, blockers),
                    }
                )
            candidates = [
                r
                for r in money
                if all(
                    r.get(f) == seed.get(f)
                    for f in ("source_account", "date", "amount", "currency")
                )
            ]
            if not candidates:
                blockers.add("overlapping_source_event_missing")
            if len(candidates) > 1:
                blockers.add("same_report_multiplicity")
            for r in candidates:
                if r.get("kind") != "unsupported" or r.get("primary_id") is not None:
                    blockers.add("source_trade_linkage_unsupported")
                occurrences.append(
                    {
                        "import_id": source.id,
                        "section": "money",
                        "ordinal": r["ordinal"],
                        "row_fingerprint": digest(r),
                        "provider": other["provider"],
                        "document_sha256": source.document_sha256,
                        "parser": source.parser_version,
                        "source_account": r["source_account"],
                        "date": r["date"],
                        "signed_amount": r["amount"],
                        "currency": r["currency"],
                    }
                )
            sources.append(
                {
                    "import_id": source.id,
                    "material": _material(source),
                    "money_inventory": money,
                }
            )
        membership = [
            _material(m)
            for m in _rows(session, AccountPerformanceScopeMembership)
            if m.account_id == intent.account_id
            and m.effective_from <= day
            and (m.effective_to is None or m.effective_to >= day)
        ]
        legacy_rows = [
            f
            for f in _rows(session, ExternalFlow)
            if f.account_id == intent.account_id and f.event_date == day
        ]
        legacy = [_material(f) for f in legacy_rows]
        links = [
            _material(t)
            for t in _rows(session, ExternalTransferLink)
            if t.id in {f.transfer_link_id for f in legacy_rows}
        ]
        coverage = [
            _material(c)
            for c in _rows(session, CashBoundaryCoverage)
            if c.account_id == intent.account_id and c.covered_from <= day <= c.covered_to
        ]
        if legacy:
            blockers.add("legacy_flow_or_transfer_overlap")
        if any(c["coverage_state"] == "complete" for c in coverage):
            blockers.add("legacy_complete_coverage_not_source_reconciled")
        dependencies = {
            "sources": sources,
            "bindings": bindings,
            "membership": membership,
            "account": _material(account, ("id", "account_type")) if account else None,
            "legacy_flows": legacy,
            "transfer_links": links,
            "cash_coverage": coverage,
        }
        source_set = digest({"core": core, "sources": sources, "occurrences": occurrences})
        review_context = digest({"contract": CONTRACT, "core": core, "dependencies": dependencies})
        claims = intent.claims
        if claims is None:
            blockers.add("owner_cash_claims_missing")
        else:
            if (
                claims.source_set_fingerprint != source_set
                or claims.review_context_digest != review_context
            ):
                blockers.add("claim_binding_mismatch")
            if claims.direction != core["direction"]:
                blockers.add("attested_direction_mismatch")
            for name in CLAIMS:
                if not getattr(claims, name):
                    blockers.add(name + "_unconfirmed")
        evidence = {
            "contract_version": CONTRACT,
            "intent": intent.model_dump(mode="json"),
            "core": core,
            "occurrences": occurrences,
            "dependencies": dependencies,
            "source_set_fingerprint": source_set,
            "review_context_digest": review_context,
            "claims": claims.model_dump(mode="json") if claims else None,
        }
        return evidence, sorted(blockers), source_set, review_context
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as error:
        raise MyBrokerError("source_envelope_invalid") from error


def _support(evidence):
    return {k: v for k, v in evidence.items() if k != "intent"}


def _ownership(session, occurrences):
    keys = {(o["import_id"], o["section"], o["ordinal"]) for o in occurrences}
    return [
        _material(o)
        for o in _rows(session, HistoricalOwnerFlowOccurrence)
        if (o.import_id, o.section, o.ordinal) in keys
    ]


def _withdrawal_context(session, flow, evidence):
    """Bind live dependencies without requiring positive/valid source support.

    Retired/revoked flows can acquire new evidence without another revision.
    Include their current account/date union and retained frozen dependencies;
    malformed source metadata stays opaque and cannot prevent withdrawal.
    """
    account_id, day = flow.account_id, flow.event_date
    deps = evidence["dependencies"]
    registry = _rows(session, BrokerIdentityMapping)
    aliases = {b["alias"] for b in deps["bindings"]} | {
        m.provider_identity
        for m in registry
        if m.provider == PROVIDER
        and m.subject_kind == "account"
        and m.status == "effective"
        and m.hermes_account_id == account_id
    }
    mapping_ids = {a["mapping_id"] for b in deps["bindings"] for a in b["accepted"]}
    source_ids = {s["import_id"] for s in deps["sources"]}
    sources = []
    for source in _rows(session, MyBrokerImport):
        relevant = source.id in source_ids
        if source.covered_from <= day <= source.covered_to:
            try:
                relevant |= any(
                    b["kind"] == "account"
                    and (b["hermes_id"] == account_id or b["identity"] in aliases)
                    for b in json.loads(source.mappings_json)
                )
            except (ValueError, TypeError, KeyError):
                relevant = True
        if relevant:
            sources.append(_material(source))
    legacy = [
        f
        for f in _rows(session, ExternalFlow)
        if f.account_id == account_id
        and f.event_date == day
        or any(f.id == int(old["id"]) for old in deps["legacy_flows"])
    ]
    links = {f.transfer_link_id for f in legacy} | {int(t["id"]) for t in deps["transfer_links"]}
    account = session.get(Account, account_id)
    return {
        "sources": sources,
        "mappings": [
            _material(m)
            for m in registry
            if m.id in mapping_ids
            or m.provider == PROVIDER
            and m.subject_kind == "account"
            and (m.provider_identity in aliases or m.hermes_account_id == account_id)
        ],
        "membership": [
            _material(m)
            for m in _rows(session, AccountPerformanceScopeMembership)
            if m.account_id == account_id
            and m.effective_from <= day
            and (m.effective_to is None or m.effective_to >= day)
            or any(m.id == int(old["id"]) for old in deps["membership"])
        ],
        "account": _material(account, ("id", "account_type")) if account else None,
        "legacy_flows": [_material(f) for f in legacy],
        "transfer_links": [
            _material(t) for t in _rows(session, ExternalTransferLink) if t.id in links
        ],
        "cash_coverage": [
            _material(c)
            for c in _rows(session, CashBoundaryCoverage)
            if c.account_id == account_id
            and c.covered_from <= day <= c.covered_to
            or any(c.id == int(old["id"]) for old in deps["cash_coverage"])
        ],
        "occurrence_owners": [
            _material(o)
            for o in _rows(session, HistoricalOwnerFlowOccurrence)
            if o.flow_id == flow.id
        ],
    }


def _plan(session, intent):
    flow = session.get(HistoricalOwnerFlow, intent.flow_id) if intent.flow_id else None
    current = _latest(session, intent.flow_id) if flow else None
    blockers = set()
    if intent.flow_id and current is None:
        blockers.add("flow_not_found")
    if current and current.revision != intent.expected_revision:
        blockers.add("stale_flow_revision")
    source_set = review_context = withdrawal_context = None
    if intent.operation == "revoke":
        evidence = json.loads(current.evidence_json) if current else None
        withdrawal_context = _withdrawal_context(session, flow, evidence) if evidence else None
        owners = withdrawal_context["occurrence_owners"] if withdrawal_context else []
        action = "noop" if current and current.acceptance_state == "revoked" else "revoked"
    else:
        evidence, reasons, source_set, review_context = _build(session, intent)
        blockers.update(reasons)
        owners = _ownership(session, evidence.get("occurrences", []))
        if any(o["flow_id"] != intent.flow_id for o in owners):
            blockers.add("occurrence_already_owned")
        action = "created"
        if flow:
            if _core(flow) != evidence["core"]:
                blockers.add("changed_core_unsupported")
            old = json.loads(current.evidence_json)
            if any(o not in evidence.get("occurrences", []) for o in old["occurrences"]):
                blockers.add("owned_occurrence_disappeared_or_changed")
            identical = _support(old) == _support(evidence)
            action = (
                "noop"
                if current.acceptance_state == "accepted" and identical
                else {
                    "accept": "noop",
                    "corroborate": "corroborated",
                    "reaffirm": "reaffirmed",
                }[intent.operation]
            )
            if intent.operation == "accept" and not (
                current.acceptance_state == "accepted" and identical
            ):
                blockers.add("reviewed_reaffirmation_required")
            if intent.operation == "corroborate" and current.acceptance_state == "revoked":
                blockers.add("reviewed_reaffirmation_required")
        elif evidence["core"]:
            # Equal account/date/currency/signed-amount cores form a comparison
            # cohort, never an economic ID. Distinct same-day cores remain eligible.
            for other in _rows(session, HistoricalOwnerFlow):
                if _core(other) == evidence["core"]:
                    blockers.add("existing_event_reconciliation_required")
    day = evidence["core"]["event_date"] if evidence and evidence.get("core") else None
    months = [
        _material(m)
        for m in _rows(session, ReportingMonth)
        if day and m.period_start.isoformat() <= day <= m.period_end.isoformat()
    ]
    # Calendar overlap alone neither writes nor edits a CLOSED financial fact.
    result = {
        "flow_id": intent.flow_id,
        "expected_revision": intent.expected_revision,
        "evidence": evidence,
        "source_set_fingerprint": source_set,
        "review_context_digest": review_context,
        "withdrawal_context": withdrawal_context,
        "missing_claims": [
            n for n in CLAIMS if intent.claims is None or not getattr(intent.claims, n)
        ]
        if intent.operation != "revoke"
        else [],
        "occurrence_owners": owners,
        "target": _material(current) if current else None,
        "month_states": months,
        "candidate_action": action,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "account_scope": "unknown",
        "portfolio_scope": "unknown",
        "cash_coverage": "unknown",
    }
    result["confirmation_digest"] = digest(
        {"contract": CONTRACT, "intent": intent.model_dump(mode="json"), "plan": result}
    )
    return result


@coherent_read_operation
def preview_historical_owner_flow(session: Session, intent: OwnerFlowIntent):
    return _plan(session, intent)


@coherent_read_operation
def read_historical_owner_flow(session: Session, flow_id: str):
    flow = session.get(HistoricalOwnerFlow, flow_id)
    current = _latest(session, flow_id)
    if flow is None or current is None:
        raise MyBrokerError("flow_not_found")
    evidence = json.loads(current.evidence_json)
    state, blockers = current.acceptance_state, []
    try:
        frozen = OwnerFlowIntent.model_validate(evidence["intent"])
        if evidence["contract_version"] != CONTRACT or frozen.claims is None:
            raise ValueError("invalid_acceptance")
        rebuilt, reasons, _, _ = _build(session, frozen)
        blockers.extend(reasons)
        if (
            digest(_support(evidence)) != current.material_signature
            or _core(flow) != evidence["core"]
            or _support(rebuilt) != _support(evidence)
        ):
            blockers.append("frozen_dependency_changed")
        owned = _ownership(session, evidence["occurrences"])
        if len(owned) != len(evidence["occurrences"]) or any(
            o["flow_id"] != flow_id or o["row_fingerprint"] != r["row_fingerprint"]
            for r in evidence["occurrences"]
            for o in owned
            if (int(o["import_id"]), int(o["ordinal"])) == (r["import_id"], r["ordinal"])
        ):
            blockers.append("occurrence_ownership_changed")
    except (ValueError, KeyError, TypeError, MyBrokerError):
        blockers.append("accepted_envelope_invalid")
    if state == "accepted" and blockers:
        state = "invalidated"
    effective = state == "accepted"
    history = [r for r in _rows(session, HistoricalOwnerFlowRevision) if r.flow_id == flow_id]
    return {
        "flow_id": flow_id,
        "core": _core(flow),
        "revision_id": current.id,
        "revision": current.revision,
        "acceptance_state": current.acceptance_state,
        "effective_state": state,
        "blockers": sorted(set(blockers)),
        "authority_kind": "owner_attested_source_row",
        "boundary_amount_kopecks": flow.boundary_amount_kopecks if effective else None,
        "account_scope": {
            "status": "authoritative" if effective else "unknown",
            "classification": "external_" + flow.direction if effective else None,
        },
        "portfolio_scope": {"status": "unknown", "classification": None},
        "cash_coverage": "unknown",
        "evidence": evidence,
        "owned_occurrences": [
            _material(o)
            for o in _rows(session, HistoricalOwnerFlowOccurrence)
            if o.flow_id == flow_id
        ],
        "history": [
            {
                "id": r.id,
                "revision": r.revision,
                "operation": r.operation,
                "acceptance_state": r.acceptance_state,
                "previous_revision_id": r.previous_revision_id,
                "reason_code": r.reason_code,
            }
            for r in history
        ],
    }


def _append(session, flow_id, current, evidence, operation, state, reason=None):
    row = HistoricalOwnerFlowRevision(
        flow_id=flow_id,
        revision=current.revision + 1 if current else 1,
        previous_revision_id=current.id if current else None,
        operation=operation,
        acceptance_state=state,
        evidence_json=canonical(evidence),
        material_signature=digest(_support(evidence)),
        reason_code=reason,
        recorded_at=datetime.now(UTC),
    )
    session.add(row)
    return row


def apply_historical_owner_flow(session, intent, *, confirmation_digest, request_id):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    intent_digest = digest(intent.model_dump(mode="json"))
    try:
        # Reserve SQLite's writer before any authoritative read, even for a replay.
        session.execute(
            text("UPDATE historical_owner_flow_revisions SET revision = revision WHERE 0")
        )
        session.expire_all()
        receipt = session.scalar(
            select(HistoricalOwnerFlowApply).where(
                HistoricalOwnerFlowApply.request_id == request_id
            )
        )
        if receipt:
            if (
                receipt.intent_digest != intent_digest
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
            flow_id, revision_id, action, replay = (
                receipt.flow_id,
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
            action, evidence = plan["candidate_action"], plan["evidence"]
            flow_id = intent.flow_id or uuid4().hex
            if not intent.flow_id:
                core = evidence["core"]
                session.add(
                    HistoricalOwnerFlow(
                        id=flow_id,
                        **{
                            **core,
                            "event_date": date.fromisoformat(core["event_date"]),
                        },
                    )
                )
                session.flush()
            current = _latest(session, flow_id)
            if action == "noop":
                revision = current
            else:
                if intent.operation != "revoke":
                    for occurrence in evidence["occurrences"]:
                        if not _ownership(session, [occurrence]):
                            session.add(
                                HistoricalOwnerFlowOccurrence(
                                    flow_id=flow_id,
                                    **{
                                        k: occurrence[k]
                                        for k in (
                                            "import_id",
                                            "section",
                                            "ordinal",
                                            "row_fingerprint",
                                        )
                                    },
                                )
                            )
                revision = _append(
                    session,
                    flow_id,
                    current,
                    evidence,
                    intent.operation,
                    "revoked" if intent.operation == "revoke" else "accepted",
                    intent.reason_code,
                )
                session.flush()
            revision_id = revision.id
            session.add(
                HistoricalOwnerFlowApply(
                    request_id=request_id,
                    intent_digest=intent_digest,
                    confirmation_digest=confirmation_digest,
                    flow_id=flow_id,
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
        readback = read_historical_owner_flow(fresh, flow_id)
    return {
        "request_id": request_id,
        "committed_revision_id": revision_id,
        "result_action": action,
        "replayed": replay,
        "readback": readback,
    }
