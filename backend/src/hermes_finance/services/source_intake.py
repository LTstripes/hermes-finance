"""Durable zero-economic original/observation/review journal (#889 slice one).

No raw-file cache, S1 acceptance, metadata creation or financial write lives here.
The strict writer remains the sole financial path. Links verify its own authority,
not aggregate readiness (which includes this journal and would be circular).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import uuid4
from xml.etree import ElementTree as ET

from sqlalchemy import event, select, text

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Account,
    Base,
    BrokerIdentityMapping,
    BrokerMonthApply,
    MyBrokerImport,
    ReportingMonth,
    SourceIntakeObservation,
    SourceIntakeOriginal,
    SourceIntakeRevision,
)
from hermes_finance.services import mybroker_identity, mybroker_import
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical, digest
from hermes_finance.statement_import.mybroker_identity import parse_identity

CONTRACT = "source_intake_v1"
PROCESS_EPOCH = uuid4().hex
PENDING = "source_intake_pending"
TABLES = (SourceIntakeOriginal, SourceIntakeObservation, SourceIntakeRevision)


def _rows(session, model):
    return list(session.scalars(select(model).order_by(*model.__table__.primary_key)))


def _events(session, original_id):
    rows = list(
        session.scalars(
            select(SourceIntakeRevision)
            .where(SourceIntakeRevision.original_id == original_id)
            .order_by(SourceIntakeRevision.seq)
        )
    )
    previous = None
    for row in rows:
        if (
            row.contract_version != CONTRACT
            or row.expected_predecessor_seq != previous
            or row.operation not in {"manifest", "decision", "finance_link"}
        ):
            raise MyBrokerError("source_intake_journal_invalid")
        payload = json.loads(row.payload_json)
        if not isinstance(payload, dict) or "state" not in payload:
            raise MyBrokerError("source_intake_journal_invalid")
        previous = row.seq
    if not rows or rows[0].operation != "manifest":
        raise MyBrokerError("source_intake_journal_invalid")
    return rows


def _policy(session):
    rows = list(
        session.scalars(
            select(SourceIntakeRevision)
            .where(SourceIntakeRevision.operation == "policy")
            .order_by(SourceIntakeRevision.seq)
        )
    )
    predecessor = None
    for row in rows:
        payload = json.loads(row.payload_json)
        if (
            row.expected_predecessor_seq != predecessor
            or payload.get("currency") != "RUB"
            or type(payload.get("enabled")) is not bool
            or row.original_id is not None
        ):
            raise MyBrokerError("source_intake_policy_invalid")
        predecessor = row.seq
    return rows[-1] if rows else None


def _append(
    session,
    *,
    request_id,
    fingerprint,
    operation,
    payload,
    original=None,
    account_id=None,
    month_id=None,
    predecessor=None,
    confirmation=None,
):
    row = SourceIntakeRevision(
        request_id=request_id,
        request_fingerprint=fingerprint,
        contract_version=CONTRACT,
        operation=operation,
        original_id=original.id if original else None,
        account_id=account_id,
        reporting_month_id=month_id,
        expected_predecessor_seq=predecessor,
        confirmation_digest=confirmation or digest(payload),
        payload_json=canonical(payload),
        reviewer="owner_local",
        accepted_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def _reserve(session):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    session.rollback()
    session.execute(text("UPDATE source_intake_revisions SET seq=seq WHERE 0"))
    session.expire_all()


def _retry(session, request_id, fingerprint):
    row = session.scalar(
        select(SourceIntakeRevision).where(SourceIntakeRevision.request_id == request_id)
    )
    if row and row.request_fingerprint != fingerprint:
        raise MyBrokerError("source_intake_idempotency_conflict")
    return row


def _binding(session, source, account_id, month_id):
    if (account_id is None) != (month_id is None):
        raise MyBrokerError("source_intake_scope_required")
    if account_id is None:
        return
    month = session.get(ReportingMonth, month_id, populate_existing=True)
    account = session.get(Account, account_id, populate_existing=True)
    if (
        not month
        or month.status != "draft"
        or month.snapshot_date != month.period_end
        or (month.period_start.isoformat(), month.period_end.isoformat())
        != (source["covered_from"], source["covered_to"])
    ):
        raise MyBrokerError("source_intake_editable_period_required")
    if (
        not account
        or account.status != "active"
        or account.account_type not in {"brokerage", "iis"}
    ):
        raise MyBrokerError("source_intake_account_invalid")
    # Explicit review can bind unbound aliases, but cannot steal/revive an alias.
    for alias in source["source_accounts"]:
        mappings = list(
            session.scalars(
                select(BrokerIdentityMapping).where(
                    BrokerIdentityMapping.provider == source["provider"],
                    BrokerIdentityMapping.subject_kind == "account",
                    BrokerIdentityMapping.provider_identity == alias,
                )
            )
        )
        effective = [m for m in mappings if m.status == "effective"]
        if (
            len(effective) > 1
            or any(m.hermes_target_id != account_id for m in effective)
            or (not effective and any(m.status == "revoked" for m in mappings))
        ):
            raise MyBrokerError("source_intake_account_binding_conflict")


def _manifest(session, document, filename):
    source = mybroker_import.parse_import_original(session, document, filename)
    evidence = parse_identity(document, filename, incomplete_draft=True)
    observations = []
    for section, rows in (
        ("positions", source["positions"]),
        ("rub_money", source["rub_money"]),
        ("money", source["money"]),
        ("trades", source["trades"]),
    ):
        for ordinal, facts in enumerate(rows):
            observations.append((section, ordinal, f"s1/{section}/{ordinal}", "recognized", facts))
    # A bounded structural inventory records every node, including unknown attrs,
    # without storing XML/text/narrative or interpreting zeros as no economics.
    root = ET.fromstring(document.decode("utf-8-sig"))
    stack = [(root, "0", 0)]
    while stack:
        node, locator, depth = stack.pop()
        if depth > 64 or len(observations) >= 50000 or len(node.attrib) > 128:
            raise MyBrokerError("source_intake_inventory_limit")
        attributes = [
            {"name": key, "value_digest": digest(value)}
            for key, value in sorted(node.attrib.items())
        ]
        if len(str(node.tag)) > 256 or any(len(a["name"]) > 256 for a in attributes):
            raise MyBrokerError("source_intake_inventory_limit")
        # These are source references only, especially repo_no != economic ID #2.
        refs = {
            k: v
            for k, v in node.attrib.items()
            if k in {"repo_no", "trade_no", "isin_reg", "ISIN1", "acc_code"}
        }
        if any(len(v) > 256 for v in refs.values()):
            raise MyBrokerError("source_intake_inventory_limit")
        facts = {
            "tag": node.tag,
            "attributes": attributes,
            "text_digest": digest(node.text),
            "tail_digest": digest(node.tail),
            "child_count": len(node),
            "native_references": refs,
            "financial_authority": "none",
        }
        observations.append(("structure", len(observations), locator, "opaque_inventory", facts))
        stack.extend(
            (child, f"{locator}/{index}", depth + 1)
            for index, child in reversed(list(enumerate(node)))
        )
    material = {
        "contract_version": CONTRACT,
        "generation": 1,
        "source": source,
        "identity_evidence": evidence,
        "inventory_count": len(observations),
        "observations_digest": digest(observations),
    }
    return material, observations


def _verify_original(original, document, filename):
    if (
        hashlib.sha256(document).hexdigest() != original.document_sha256
        or digest(filename) != original.filename_digest
        or len(document) != original.byte_length
    ):
        raise MyBrokerError("source_intake_original_mismatch")


def _currency_evidence(evidence, prior=None):
    from hermes_finance.services.public_security_registry import current_denomination_observation

    result = dict(prior or {})
    for instrument in evidence["instruments"]:
        observation = current_denomination_observation(
            instrument["isin"], instrument["instrument_type"]
        )
        if observation is not None:
            result[instrument["isin"]] = observation
    return result


def save_intake(
    session, *, document, filename, request_id, account_id=None, reporting_month_id=None
):
    fingerprint = digest(
        [
            CONTRACT,
            "save",
            hashlib.sha256(document).hexdigest(),
            digest(filename),
            account_id,
            reporting_month_id,
        ]
    )
    _reserve(session)
    try:
        retry = _retry(session, request_id, fingerprint)
        if retry:
            intake_id = retry.original_id
        else:
            material, observations = _manifest(session, document, filename)
            evidence = material["identity_evidence"]
            _binding(session, evidence, account_id, reporting_month_id)
            original = session.scalar(
                select(SourceIntakeOriginal).where(
                    SourceIntakeOriginal.document_sha256 == material["source"]["document_sha256"]
                )
            )
            if original:
                _verify_original(original, document, filename)
                events = _events(session, original.id)
                state = json.loads(events[-1].payload_json)["state"]
                if (state["account_id"], state["reporting_month_id"]) != (
                    account_id,
                    reporting_month_id,
                ):
                    raise MyBrokerError("source_intake_rebind_forbidden")
                # Same original, different request: a journal command, not new occurrences.
                operation = "decision"
                predecessor = events[-1].seq
                payload = {"state": state, "no_change": True}
            else:
                original = SourceIntakeOriginal(
                    document_sha256=material["source"]["document_sha256"],
                    byte_length=len(document),
                    filename_digest=digest(filename),
                    provider=evidence["provider"],
                    covered_from=date.fromisoformat(evidence["covered_from"]),
                    covered_to=date.fromisoformat(evidence["covered_to"]),
                    native_accounts_json=canonical(evidence["source_accounts"]),
                    captured_at=datetime.now(UTC),
                )
                session.add(original)
                session.flush()
                for section, ordinal, locator, row_class, facts in observations:
                    session.add(
                        SourceIntakeObservation(
                            original_id=original.id,
                            generation=1,
                            section=section,
                            ordinal=ordinal,
                            locator=locator,
                            row_class=row_class,
                            row_fingerprint=digest(facts),
                            facts_json=canonical(facts),
                        )
                    )
                policy = _policy(session)
                if policy is None:
                    policy = _append(
                        session,
                        request_id=uuid4().hex,
                        fingerprint=digest(["RUB", True]),
                        operation="policy",
                        payload={"enabled": True, "currency": "RUB"},
                    )
                state = {
                    "account_id": account_id,
                    "reporting_month_id": reporting_month_id,
                    "policy_revision": policy.seq,
                    "default_enabled": json.loads(policy.payload_json)["enabled"],
                    "account_currency": None,
                    "overrides": {},
                    "instrument_decisions": [],
                    "deferred_isins": [],
                    "currency_evidence": _currency_evidence(evidence),
                }
                operation, predecessor = "manifest", None
                payload = {"state": state, "manifest": material}
            row = _append(
                session,
                request_id=request_id,
                fingerprint=fingerprint,
                operation=operation,
                payload=payload,
                original=original,
                account_id=account_id,
                month_id=reporting_month_id,
                predecessor=predecessor,
            )
            intake_id = original.id
            session.commit()
            return {
                "intake_id": intake_id,
                "request_id": request_id,
                "head_seq": row.seq,
                "duplicate": False,
            }
        session.rollback()
        return {
            "intake_id": intake_id,
            "request_id": request_id,
            "head_seq": retry.seq,
            "duplicate": True,
        }
    except BaseException:
        session.rollback()
        raise


def _scope_revision(session, account_id, month_id, instrument_ids, mapping_ids):
    result = []
    month = session.get(ReportingMonth, month_id)
    for row in session.scalars(
        select(SourceIntakeRevision).where(SourceIntakeRevision.operation == "dependency")
    ):
        p = json.loads(row.payload_json)
        if (
            (p["table"] == "accounts" and p["id"] == account_id)
            or (p["table"] == "instruments" and p["id"] in instrument_ids)
            or (p["table"] == "broker_identity_mappings" and p["id"] in mapping_ids)
            or any(
                scope["account_id"] == account_id
                and (
                    scope["month_id"] == month_id
                    or (
                        scope["event_date"] is not None
                        and str(month.period_start) <= scope["event_date"] <= str(month.period_end)
                    )
                )
                for scope in p.get("financial_scopes", [])
            )
        ):
            result.append(row.seq)
    return result


def _journal_identity(session, evidence, state):
    bindings = (
        [
            {"identity": alias, "hermes_id": state["account_id"]}
            for alias in evidence["source_accounts"]
        ]
        if state["account_id"]
        else []
    )
    identity = mybroker_identity._prepare(
        session, evidence, bindings, state["instrument_decisions"], source_intake=True
    )
    reasons = set(identity["conflicts"])
    reasons.update(gap["code"] for gap in identity["evidence_gaps"])
    if state["deferred_isins"]:
        reasons.add("source_intake_identity_deferred")
    return identity, reasons


def _link_authority(session, original, state, request_id):
    from hermes_finance.services import broker_month_journal as journal
    from hermes_finance.services import broker_months

    receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
    if (
        not receipt
        or journal.kind(receipt) != journal.SOURCE
        or (receipt.account_id, receipt.reporting_month_id)
        != (state["account_id"], state["reporting_month_id"])
    ):
        raise MyBrokerError("source_intake_strict_source_receipt_required")
    source = session.get(MyBrokerImport, receipt.import_id, populate_existing=True)
    if (
        not source
        or source.document_sha256 != original.document_sha256
        or (source.covered_from, source.covered_to) != (original.covered_from, original.covered_to)
    ):
        raise MyBrokerError("source_intake_receipt_original_mismatch")
    accepted = journal.payload(receipt)
    manifest = json.loads(_events(session, original.id)[0].payload_json)["manifest"]
    identity, identity_reasons = _journal_identity(session, manifest["identity_evidence"], state)
    bindings = [
        {
            "kind": "account",
            "identity": p["identity"],
            "hermes_id": p["hermes_id"],
            "mapping_id": p["mapping_id"],
        }
        for p in identity["accounts"]
    ] + [
        {
            "kind": "instrument",
            "identity": p["isin"],
            "hermes_id": p["hermes_id"],
            "mapping_id": p["mapping_id"],
        }
        for p in identity["instruments"]
    ]
    instruments = {
        str(p["hermes_id"]): [p["isin"], p["instrument_type"], p["currency"]]
        for p in identity["instruments"]
    }
    # A receipt affirms its frozen S1 bindings, never an incompatible later Owner
    # proposal or a deferred obligation. Recheck on both reserved linking and GET.
    if identity_reasons or (
        sorted(bindings, key=lambda b: (b["kind"], b["identity"]))
        != sorted(json.loads(source.mappings_json), key=lambda b: (b["kind"], b["identity"]))
        or instruments != accepted["instruments"]
    ):
        raise MyBrokerError("source_intake_identity_review_required")
    # Validate the receipt itself, deliberately excluding aggregate intake blockers.
    if (
        broker_months._projection(session, receipt) != accepted["projection_digest"]
        or digest([source.normalized_json, source.mappings_json, source.parser_version])
        != accepted["source_digest"]
    ):
        raise MyBrokerError("source_intake_receipt_authority_changed")
    reasons = broker_months._readiness(session, receipt)
    integrity = {
        "source_projection_changed",
        "source_authority_changed",
        "accepted_mapping_changed",
        "account_binding_changed",
        "instrument_metadata_changed",
        "broker_month_receipt_invalid",
        "canonical_trade_projection_changed",
        "canonical_trade_authority_unavailable",
        "source_disposition_changed",
        "accepted_mapping_conflict",
        "accepted_parser_version_conflict",
        "document_coverage_conflict",
        "overlapping_endpoint_conflict",
        "immutable_trade_conflict",
        "trade_material_conflict",
        "money_link_ambiguous",
        "instrument_disposition_reconciliation_required",
    }
    if integrity.intersection(reasons):
        raise MyBrokerError("source_intake_receipt_authority_changed")
    signature = digest(
        [
            receipt.projection_json,
            source.normalized_json,
            source.mappings_json,
            _scope_revision(
                session,
                receipt.account_id,
                receipt.reporting_month_id,
                {int(k) for k in accepted["instruments"]},
                {b["mapping_id"] for b in json.loads(source.mappings_json)},
            ),
            reasons,
        ]
    )
    return {
        "request_id": request_id,
        "signature": signature,
        "blockers": reasons,
        "import_id": source.id,
    }


def _assessment(proposal, state, head_seq, override_revision):
    from hermes_finance.services.public_security_registry import current_denomination_observation

    observed = proposal.get("currency")
    origin = proposal.get("currency_basis", "unproven")
    override = state["overrides"].get(proposal["isin"]) or state["account_currency"]
    proven = origin == "official_FACEUNIT"
    basis = "official_proven" if proven else "existing_catalogue" if observed else "unknown"
    effective = observed
    reasons = list(proposal.get("review_reasons", []))
    saved = state.get("currency_evidence", {}).get(proposal["isin"])
    observed_denomination = observed if proven else None
    if saved:
        current = current_denomination_observation(proposal["isin"], proposal["instrument_type"])
        observed_denomination = saved["currency"]
        if current is None or current["proof_id"] != saved["proof_id"]:
            # Retain the known explicit denomination; expiry is never a RUB fallback.
            observed = saved["currency"]
            effective, basis, proven = observed, "unknown", False
            reasons.append("source_intake_public_proof_stale")
        elif observed and observed != saved["currency"]:
            effective, basis = None, "conflict"
            reasons.append("source_intake_currency_conflict")
        else:
            observed = saved["currency"]
            effective, basis, proven = observed, "official_proven", True
    if override:
        if observed and override != observed:
            basis = "conflict"
            reasons.append("source_intake_currency_conflict")
        elif not observed:
            effective, basis = override, "owner_selected"
    elif observed is None and state["default_enabled"]:
        effective, basis = "RUB", "owner_default_rub"
    if effective is not None and effective != "RUB":
        reasons.append("source_intake_currency_unsupported")
    return {
        "observed_denomination": observed_denomination,
        "effective_currency": effective,
        "basis": basis,
        "denomination_proven": proven,
        "provisional": basis in {"owner_selected", "owner_default_rub", "unknown", "conflict"},
        "policy_revision": state["policy_revision"],
        "override_revision": override_revision if override else None,
        "assessment_revision": head_seq,
        "proof_ref": saved or proposal.get("official_proof"),
        "reasons": sorted(set(reasons)),
    }


def _view(session, original):
    _policy(session)
    events = _events(session, original.id)
    manifest = json.loads(events[0].payload_json)["manifest"]
    state = json.loads(events[-1].payload_json)["state"]
    observations = list(
        session.scalars(
            select(SourceIntakeObservation)
            .where(SourceIntakeObservation.original_id == original.id)
            .order_by(SourceIntakeObservation.id)
        )
    )
    inventory = [
        (o.section, o.ordinal, o.locator, o.row_class, json.loads(o.facts_json))
        for o in observations
    ]
    if (
        len(inventory) != manifest["inventory_count"]
        or digest(inventory) != manifest["observations_digest"]
        or any(digest(json.loads(o.facts_json)) != o.row_fingerprint for o in observations)
    ):
        raise MyBrokerError("source_intake_inventory_invalid")
    evidence = manifest["identity_evidence"]
    identity, identity_reasons = _journal_identity(session, evidence, state)
    decision_seq = next(
        (
            r.seq
            for r in reversed(events)
            if r.operation == "decision" and not json.loads(r.payload_json).get("no_change")
        ),
        events[0].seq,
    )
    proposals = [
        {**p, "currency_assessment": _assessment(p, state, events[-1].seq, decision_seq)}
        for p in identity["instruments"]
    ]
    link = None
    for row in reversed(events):
        if row.operation == "decision" and not json.loads(row.payload_json).get("no_change"):
            break
        if row.operation == "finance_link":
            stored = json.loads(row.payload_json)["link"]
            try:
                current = _link_authority(session, original, state, stored["request_id"])
                if current["signature"] == stored["signature"]:
                    link = current
            except MyBrokerError:
                pass
            break
    reasons = set(link["blockers"] if link else [PENDING])
    reasons.update(identity_reasons)
    if link is None:
        source = manifest["source"]
        reasons.update(source["syntax_blockers"])
        reasons.update(source["endpoint_blockers"])
        reasons.update(source["endpoint_conflicts"])
    if any(p["currency_assessment"]["basis"] == "conflict" for p in proposals):
        reasons.add("source_intake_currency_conflict")
    for proposal in proposals:
        reasons.update(
            code
            for code in proposal["currency_assessment"]["reasons"]
            if code.startswith("source_intake_")
        )
    if {"source_intake_currency_conflict", "source_intake_public_proof_stale"}.intersection(
        reasons
    ):
        link = None
        reasons.add(PENDING)
    return {
        "contract_version": CONTRACT,
        "id": original.id,
        "document_sha256": original.document_sha256,
        "generation": manifest["generation"],
        "head_seq": events[-1].seq,
        "manifest_digest": digest(manifest),
        "covered_from": original.covered_from.isoformat(),
        "covered_to": original.covered_to.isoformat(),
        "state": state,
        "original_required": True,
        "document": manifest["source"],
        "proposals": proposals,
        "observations": [
            {
                "id": o.id,
                "section": o.section,
                "ordinal": o.ordinal,
                "locator": o.locator,
                "row_class": o.row_class,
                "row_fingerprint": o.row_fingerprint,
                "facts": json.loads(o.facts_json),
            }
            for o in observations
        ],
        "exceptions": sorted(reasons),
        "financial_authority": "none",
        "finance_link": link,
        "bookkeeping_ready": bool(link) and not reasons,
        "can_close": bool(link) and not reasons,
        "history": [
            {
                "seq": r.seq,
                "operation": r.operation,
                "request_id": r.request_id,
                "reviewer": r.reviewer,
            }
            for r in events
        ],
    }


def read_intake(session, intake_id):
    with coherent_read_snapshot(session):
        original = session.get(SourceIntakeOriginal, intake_id)
        if not original:
            raise MyBrokerError("source_intake_not_found")
        return _view(session, original)


def list_intakes(session, month_id=None, include_unbound=False):
    with coherent_read_snapshot(session):
        views = [_view(session, row) for row in _rows(session, SourceIntakeOriginal)]
        return [
            v
            for v in views
            if month_id is None
            or v["state"]["reporting_month_id"] == month_id
            or (include_unbound and v["state"]["reporting_month_id"] is None)
        ]


def _review(session, intake_id, document, filename, intent):
    original = session.get(SourceIntakeOriginal, intake_id, populate_existing=True)
    if not original:
        raise MyBrokerError("source_intake_not_found")
    _verify_original(original, document, filename)
    view = _view(session, original)
    if intent.expected_head_seq != view["head_seq"]:
        raise MyBrokerError("source_intake_preview_stale")
    manifest, observations = _manifest(session, document, filename)
    if digest(manifest) != view["manifest_digest"]:
        raise MyBrokerError("source_intake_parser_revision_changed")
    state = view["state"]
    account_id = intent.account_id if intent.account_id is not None else state["account_id"]
    month_id = (
        intent.reporting_month_id
        if intent.reporting_month_id is not None
        else state["reporting_month_id"]
    )
    if state["account_id"] is not None and (account_id, month_id) != (
        state["account_id"],
        state["reporting_month_id"],
    ):
        raise MyBrokerError("source_intake_rebind_forbidden")
    _binding(session, manifest["identity_evidence"], account_id, month_id)
    valid_isins = {p["isin"] for p in view["proposals"]}
    overrides = {o.isin: o.currency for o in intent.overrides if o.currency is not None}
    if (
        len({o.isin for o in intent.overrides}) != len(intent.overrides)
        or set(overrides) - valid_isins
        or set(intent.deferred_isins) - valid_isins
        or len({d.isin for d in intent.instrument_decisions}) != len(intent.instrument_decisions)
        or {d.isin for d in intent.instrument_decisions} - valid_isins
    ):
        raise MyBrokerError("source_intake_decision_invalid")
    new_state = {
        **state,
        "account_id": account_id,
        "reporting_month_id": month_id,
        "default_enabled": intent.default_enabled,
        "account_currency": intent.account_currency,
        "overrides": overrides,
        "deferred_isins": sorted(set(intent.deferred_isins)),
        "instrument_decisions": [d.model_dump() for d in intent.instrument_decisions],
        "currency_evidence": _currency_evidence(
            manifest["identity_evidence"], state.get("currency_evidence")
        ),
    }
    link = (
        _link_authority(session, original, new_state, intent.finance_request_id)
        if intent.finance_request_id
        else None
    )
    if link and (
        new_state != state
        or any(p["currency_assessment"]["basis"] == "conflict" for p in view["proposals"])
    ):
        raise MyBrokerError("source_intake_link_review_required")
    plan = {
        "contract_version": CONTRACT,
        "intake_id": intake_id,
        "expected_head_seq": view["head_seq"],
        "state": new_state,
        "link": link,
        "manifest_digest": view["manifest_digest"],
        "dependency_digest": mybroker_identity._revision(session),
        "policy_head": _policy(session).seq if _policy(session) else None,
        "epoch": session.info.get("source_intake_epoch", PROCESS_EPOCH),
        "financial_effects": 0,
        "current_assessments_digest": digest(view["proposals"]),
    }
    return {**plan, "confirmation_digest": digest(plan)}


def preview_review(session, intake_id, document, filename, intent):
    with coherent_read_snapshot(session):
        return _review(session, intake_id, document, filename, intent)


def apply_review(
    session,
    intake_id,
    document,
    filename,
    intent,
    request_id,
    confirmation_digest,
    *,
    finance_link=False,
):
    fingerprint = digest(
        [
            intake_id,
            intent.model_dump(),
            confirmation_digest,
            finance_link,
            hashlib.sha256(document).hexdigest(),
            digest(filename),
        ]
    )
    _reserve(session)
    try:
        retry = _retry(session, request_id, fingerprint)
        if retry:
            session.rollback()
            return {
                "intake_id": intake_id,
                "head_seq": retry.seq,
                "request_id": request_id,
                "duplicate": True,
            }
        plan = _review(session, intake_id, document, filename, intent)
        if plan["confirmation_digest"] != confirmation_digest:
            raise MyBrokerError("source_intake_preview_stale")
        if finance_link != bool(plan["link"]):
            raise MyBrokerError("source_intake_command_invalid")
        policy = _policy(session)
        state = plan["state"]
        if (
            not finance_link
            and json.loads(policy.payload_json)["enabled"] != state["default_enabled"]
        ):
            policy = _append(
                session,
                request_id=uuid4().hex,
                fingerprint=digest(state["default_enabled"]),
                operation="policy",
                payload={"enabled": state["default_enabled"], "currency": "RUB"},
                predecessor=policy.seq,
            )
        if not finance_link:
            state["policy_revision"] = policy.seq
        row = _append(
            session,
            request_id=request_id,
            fingerprint=fingerprint,
            operation="finance_link" if finance_link else "decision",
            payload={"state": state, **({"link": plan["link"]} if finance_link else {})},
            original=session.get(SourceIntakeOriginal, intake_id),
            account_id=state["account_id"],
            month_id=state["reporting_month_id"],
            predecessor=intent.expected_head_seq,
            confirmation=confirmation_digest,
        )
        session.commit()
        return {
            "intake_id": intake_id,
            "head_seq": row.seq,
            "request_id": request_id,
            "duplicate": False,
        }
    except BaseException:
        session.rollback()
        raise


def scoped_status(session, month_id, account_id=None):
    """One resolver used by Close, completeness and actual-return consumers."""
    ids = set(
        session.scalars(
            select(SourceIntakeRevision.original_id).where(
                SourceIntakeRevision.reporting_month_id == month_id,
                *(
                    [SourceIntakeRevision.account_id == account_id]
                    if account_id is not None
                    else []
                ),
            )
        )
    )
    reasons, accounts, heads = set(), set(), []
    for intake_id in sorted(ids):
        try:
            view = _view(session, session.get(SourceIntakeOriginal, intake_id))
            reasons.update(view["exceptions"])
            heads.append([intake_id, view["head_seq"], view["finance_link"], view["exceptions"]])
            if view["exceptions"]:
                accounts.add(view["state"]["account_id"])
        except (MyBrokerError, ValueError, KeyError, TypeError):
            reasons.add("source_intake_journal_invalid")
    return {
        "status": "partial" if reasons else "complete",
        "intake_count": len(ids),
        "revision_digest": digest(heads),
        "reason_codes": sorted(reasons),
        "account_ids": sorted(a for a in accounts if a is not None),
    }


def interval_blockers(session, start_date, end_date, account_ids):
    reasons = set()
    for month in session.scalars(
        select(ReportingMonth).where(
            ReportingMonth.period_start <= end_date, ReportingMonth.period_end >= start_date
        )
    ):
        for account_id in account_ids:
            reasons.update(scoped_status(session, month.id, account_id)["reason_codes"])
    return sorted(reasons)


def require_unbound_month(session, month_id):
    if (
        session.scalar(
            select(SourceIntakeRevision.seq)
            .where(SourceIntakeRevision.reporting_month_id == month_id)
            .limit(1)
        )
        is not None
    ):
        raise ValueError("source_intake_bound_month_immutable")


def install_sql_guards(connection):
    for model in TABLES:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {model.__tablename__}_{operation.lower()} "
                f"BEFORE {operation} ON {model.__tablename__} BEGIN SELECT RAISE(ABORT, 'source intake is append-only'); END"
            )
    for table in (
        "accounts",
        "instruments",
        "broker_identity_mappings",
        "position_snapshots",
        "cash_balances",
        "investment_cash_flows",
        "external_flows",
    ):
        columns = [row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        for operation in ("INSERT", "UPDATE", "DELETE"):
            alias = "OLD" if operation == "DELETE" else "NEW"
            present = "EXISTS (SELECT 1 FROM source_intake_originals)"
            when = f"WHEN {present} AND ({changed})" if operation == "UPDATE" else f"WHEN {present}"
            scopes = []
            if "reporting_month_id" in columns and "account_id" in columns:
                # Retain BOTH endpoints of a move/delete/recreate. These tokens
                # never revive when financial values return to their old state.
                for scope_alias in ["OLD", "NEW"] if operation == "UPDATE" else [alias]:
                    day = f"{scope_alias}.event_date" if "event_date" in columns else "NULL"
                    scopes.append(
                        f"json_object('account_id',{scope_alias}.account_id,"
                        f"'month_id',{scope_alias}.reporting_month_id,'event_date',{day})"
                    )
            payload = f"json_object('table','{table}','id',{alias}.id"
            if scopes:
                payload += f",'financial_scopes',json_array({','.join(scopes)})"
            payload += ")"
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS intake_dependency_{table}_{operation.lower()} "
                f"AFTER {operation} ON {table} {when} BEGIN INSERT INTO source_intake_revisions "
                "(request_id,request_fingerprint,contract_version,operation,confirmation_digest,payload_json,reviewer,accepted_at) "
                f"VALUES(lower(hex(randomblob(32))),'{64 * '0'}','{CONTRACT}','dependency','{64 * '0'}',"
                f"{payload},'system',CURRENT_TIMESTAMP); END"
            )


def _after_create(_metadata, connection, **_kwargs):
    install_sql_guards(connection)


def install_hooks():
    if not event.contains(Base.metadata, "after_create", _after_create):
        event.listen(Base.metadata, "after_create", _after_create)
