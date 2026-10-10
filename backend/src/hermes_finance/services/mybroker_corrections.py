"""Append-only whole-batch Skip -> Map. Mapping is never financial acceptance."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import select, text

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Base,
    BrokerIdentityMapping,
    Instrument,
    MyBrokerCorrectionApply,
    MyBrokerCorrectionChange,
    MyBrokerCorrectionRevision,
    MyBrokerDispositionRevision,
    MyBrokerDispositionSet,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services.mybroker_dispositions import original_dispositions, source_fingerprint
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest

CONTRACT = "mybroker-skip-map-v1"
HISTORY = (MyBrokerCorrectionApply, MyBrokerCorrectionRevision, MyBrokerCorrectionChange)


def _rows(session, model):
    return list(session.scalars(select(model).execution_options(populate_existing=True)))


def _material(row):
    return {c.name: str(getattr(row, c.name)) for c in row.__table__.columns}


def _authority(session):
    """A source/registry change invalidates the whole reviewed union durably.

    Financial acceptances are deliberately separate: later S2/H1/H2 operations
    cannot retire the mapping that supplies their source support.
    """
    sources = sorted(_rows(session, MyBrokerImport), key=lambda r: r.id)
    return {
        "sources": [
            {
                "import_id": s.id,
                "source": source_fingerprint(s),
                "range": [str(s.covered_from), str(s.covered_to)],
                "dispositions": original_dispositions(session, s),
            }
            for s in sources
        ],
        "registry": sorted(
            (_material(r) for r in _rows(session, BrokerIdentityMapping)), key=canonical
        ),
        "targets": [
            [r.id, r.isin, r.instrument_type, r.currency]
            for r in sorted(_rows(session, Instrument), key=lambda r: r.id)
        ],
        "change_revision": max((r.id for r in _rows(session, MyBrokerCorrectionChange)), default=0),
    }


def current_corrections(session):
    revisions = sorted(_rows(session, MyBrokerCorrectionRevision), key=lambda r: r.id)
    if not revisions:
        return {}
    authority = digest(_authority(session))
    receipts = {r.request_id: r for r in _rows(session, MyBrokerCorrectionApply)}
    latest = {(r.import_id, r.isin): r for r in revisions}
    result = {}
    for key, row in latest.items():
        receipt = receipts.get(row.request_id)
        evidence = json.loads(receipt.evidence_json) if receipt else {}
        batch_ids = json.loads(receipt.revision_ids_json) if receipt else []
        # Superseding one member retires its old batch, never mixes generations.
        valid = evidence.get("authority_digest") == authority and all(
            any(r.id == i for r in latest.values()) for i in batch_ids
        )
        result[key] = {
            "revision_id": row.id,
            "revision": row.revision,
            "request_id": row.request_id,
            "predecessor_revision_id": row.predecessor_revision_id,
            "binding": json.loads(row.binding_json),
            "effective_state": "mapped" if valid else "retired",
            "blockers": [] if valid else ["correction_dependencies_changed"],
            "dependencies": {"accepted": evidence.get("authority_digest"), "current": authority},
        }
    return result


def _intent(decisions, owner_reviewed):
    if not owner_reviewed or not decisions or len(decisions) > 10000:
        raise MyBrokerError("correction_review_required")
    keys = [(d["import_id"], d["isin"]) for d in decisions]
    if len(set(keys)) != len(keys):
        raise MyBrokerError("correction_decision_duplicate")
    return {
        "contract": CONTRACT,
        "provider": PROVIDER,
        "owner_reviewed": True,
        "decisions": sorted(decisions, key=lambda d: (d["import_id"], d["isin"])),
    }


def _overlap(session, decisions, sources, blockers):
    """Close exact account/ISIN support, then retain reducer and Money guards."""
    from hermes_finance.services.mybroker_import import _reduce

    documents = [json.loads(s.normalized_json) for s in sources]
    selected = {(d["import_id"], d["isin"]): d for d in decisions}
    requested_isins = {d["isin"] for d in decisions}
    accounts = {}
    for source in sources:
        for item in original_dispositions(session, source):
            accounts[(source.id, item["isin"])] = {b["hermes_id"] for b in item["accounts"]}
    for key, decision in selected.items():
        for other, bound in accounts.items():
            if other[1] != key[1] or not (bound & accounts.get(key, set())):
                continue
            if other not in selected:
                blockers.add("correction_overlap_incomplete")
            elif selected[other]["hermes_id"] != decision["hermes_id"]:
                blockers.add("correction_overlap_target_conflict")
    targets = {d["isin"]: d["hermes_id"] for d in decisions}
    if any(len({d["hermes_id"] for d in decisions if d["isin"] == isin}) != 1 for isin in targets):
        blockers.add("correction_overlap_target_conflict")
    for source in sources:
        for binding in json.loads(source.mappings_json):
            if binding["kind"] == "instrument" and binding["identity"] in targets:
                matches = [
                    m
                    for m in _rows(session, BrokerIdentityMapping)
                    if m.provider == PROVIDER
                    and m.subject_kind == "instrument"
                    and m.provider_identity == binding["identity"]
                    and m.status == "effective"
                ]
                if (
                    len(matches) != 1
                    or matches[0].id != binding["mapping_id"]
                    or matches[0].hermes_target_id != binding["hermes_id"]
                    or binding["hermes_id"] != targets[binding["identity"]]
                ):
                    blockers.add("correction_overlap_target_conflict")
    projections, _ = _reduce(documents)
    affected = {i: p for i, p in projections.items() if p["core"]["isin"] in requested_isins}
    for trade in affected.values():
        blockers.update(
            set(trade["blockers"])
            & {
                "immutable_trade_conflict",
                "trade_material_conflict",
                "settled_to_pending_conflict",
                "pending_disappeared",
            }
        )
    links = {
        (t["core"]["source_account"], t["ids"][0])
        for doc in documents
        for t in doc["trades"]
        if t["core"]["isin"] in requested_isins and t["ids"]
    }
    leg_materials = defaultdict(set)
    for doc in documents:
        money = Counter()
        for leg in doc["money"]:
            link = (leg["source_account"], leg.get("primary_id"))
            if link not in links:
                continue
            identities = {
                t["identity"]
                for d in documents
                for t in d["trades"]
                if t["ids"] and (t["core"]["source_account"], t["ids"][0]) == link
            }
            # REPO/unsupported evidence is retained, never converted into cash.
            if len(identities) > 1:
                blockers.add("money_link_ambiguous")
            if leg["kind"] in ("settlement", "commission"):
                leg_materials[(*link, leg["kind"])].add(
                    canonical({k: leg[k] for k in ("kind", "date", "amount", "currency")})
                )
            money[canonical({k: v for k, v in leg.items() if k not in ("ordinal", "section")})] += 1
        if any(n > 1 for n in money.values()):
            blockers.add("correction_money_duplicate")
    if any(len(materials) > 1 for materials in leg_materials.values()):
        blockers.add("trade_material_conflict")


def _financial_dependencies(session):
    # Freeze existing source-dependent authorities and CLOSED facts in Preview.
    names = {
        "reporting_months",
        "position_snapshots",
        "investment_cash_flows",
        "executed_trades",
        "executed_trade_occurrences",
        "executed_trade_revisions",
        "external_flows",
        "cash_balances",
        "deposit_snapshots",
        "external_transfer_links",
        "external_transfer_reconciliation_evidence",
        "in_kind_movements",
        "cash_boundary_coverages",
        "in_kind_boundary_coverages",
        "class_no_crossing_coverages",
        "account_performance_scope_memberships",
        "observed_valuation_points",
    }
    tables = [
        t
        for t in Base.metadata.sorted_tables
        if t.name in names
        or t.name.startswith(
            (
                "historical_",
                "source_cash_coverage_",
            )
        )
    ]
    return {
        t.name: sorted(([str(v) for v in r] for r in session.execute(select(t))), key=canonical)
        for t in tables
    }


def _preview(session, decisions, owner_reviewed):
    intent = _intent(decisions, owner_reviewed)
    decisions = intent["decisions"]
    sources = sorted(_rows(session, MyBrokerImport), key=lambda r: r.id)
    by_id = {s.id: s for s in sources}
    current = current_corrections(session)
    blockers, reviewed = set(), []
    for decision in decisions:
        source = by_id.get(decision["import_id"])
        if source is None:
            blockers.add("import_not_found")
            continue
        document = json.loads(source.normalized_json)
        if (
            source.parser_version != "mybroker-s1-v2"
            or document["parser"] != source.parser_version
            or document["provider"] != PROVIDER
            or document["document_sha256"] != source.document_sha256
            or document["covered_from"] != str(source.covered_from)
            or document["covered_to"] != str(source.covered_to)
        ):
            blockers.add("source_integrity_or_version")
        item = next(
            (i for i in original_dispositions(session, source) if i["isin"] == decision["isin"]),
            None,
        )
        original = session.get(MyBrokerDispositionRevision, decision["original_revision_id"])
        marker = session.get(MyBrokerDispositionSet, source.id)
        prior = current.get((source.id, decision["isin"]))
        if (
            not item
            or not original
            or not marker
            or decision["document_sha256"] != source.document_sha256
            or marker.source_fingerprint != source_fingerprint(source)
            or original.import_id != source.id
            or original.isin != decision["isin"]
            or original.revision != 1
            or original.operation != "accept"
            or original.state != "accepted"
            or decision["isin"] not in json.loads(marker.skipped_isins_json)
            or any(
                b["kind"] == "instrument" and b["identity"] == decision["isin"]
                for b in json.loads(source.mappings_json)
            )
            or (
                item
                and json.loads(original.evidence_json)["source"]
                != {k: item[k] for k in json.loads(original.evidence_json)["source"]}
            )
        ):
            blockers.add("correction_original_evidence_invalid")
        if not item:
            continue
        if decision["expected_revision"] != item["revision"] or decision[
            "expected_correction_revision"
        ] != (prior["revision"] if prior else 0):
            blockers.add("disposition_revision_stale")
        predecessor = session.get(MyBrokerDispositionRevision, item["revision_id"])
        if (
            item["effective_state"] != "retired"
            or predecessor is None
            or predecessor.operation != "retire"
            or not predecessor.previous_revision_id
            or not item["dependencies"]["changes"]
            or (
                original
                and item["dependencies"]["changes"]
                == json.loads(original.evidence_json)["dependencies"]["changes"]
            )
        ):
            blockers.add("correction_predecessor_not_retired")
        if predecessor and predecessor.previous_revision_id:
            previous = session.get(MyBrokerDispositionRevision, predecessor.previous_revision_id)
            if (
                not previous
                or previous.state != "accepted"
                or previous.evidence_json != predecessor.evidence_json
            ):
                blockers.add("correction_retirement_untraceable")
        mapping = session.get(BrokerIdentityMapping, decision["mapping_id"])
        target = session.get(Instrument, decision["hermes_id"])
        matches = [
            m
            for m in _rows(session, BrokerIdentityMapping)
            if m.provider == PROVIDER
            and m.subject_kind == "instrument"
            and m.provider_identity == decision["isin"]
            and m.status == "effective"
        ]
        if (
            len(matches) != 1
            or not mapping
            or matches[0].id != mapping.id
            or mapping.hermes_target_id != decision["hermes_id"]
            or mapping.observed_isin != decision["isin"]
            or not target
            or target.isin != decision["isin"]
            or target.instrument_type != decision["reviewed_instrument_type"]
        ):
            blockers.add("correction_target_incompatible")
        currencies = {
            trade["core"]["currency"]
            for trade in document["trades"]
            if trade["core"]["isin"] == decision["isin"]
        }
        if target and currencies and currencies != {target.currency}:
            blockers.add("correction_target_incompatible")
        from hermes_finance.services.mybroker_dispositions import dependency_context

        if not dependency_context(session, source, decision["isin"])[1]:
            blockers.add("accepted_mapping_conflict")
        reviewed.append({"decision": decision, "disposition": item, "current_correction": prior})
    _overlap(session, decisions, sources, blockers)
    # Exclusions have no same-account lifetime irrelevance proof. CLOSED evidence
    # for affected accounts therefore always needs the existing explicit Reopen.
    affected_accounts = {b["hermes_id"] for r in reviewed for b in r["disposition"]["accounts"]}
    closed = {r.id for r in _rows(session, ReportingMonth) if r.status == "closed"}

    from hermes_finance.persistence import (
        CashBalance,
        ExternalFlow,
        InKindMovement,
        InvestmentCashFlow,
        PositionSnapshot,
    )

    if any(
        r.account_id in affected_accounts and r.reporting_month_id in closed
        for model in (PositionSnapshot, InvestmentCashFlow, ExternalFlow, CashBalance)
        for r in _rows(session, model)
    ) or any(
        r.reporting_month_id in closed
        and bool({r.source_account_id, r.destination_account_id} & affected_accounts)
        for r in _rows(session, InKindMovement)
    ):
        blockers.add("closed_reporting_month_requires_reopen")
    authority = _authority(session)
    evidence = {
        "authority_digest": digest(authority),
        "authority": authority,
        "financial": _financial_dependencies(session),
    }
    return {
        "intent": intent,
        "decisions": reviewed,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "evidence": evidence,
        "confirmation_digest": digest([intent, reviewed, evidence, sorted(blockers)]),
    }


def preview_corrections(session, *, decisions, owner_reviewed):
    with coherent_read_snapshot(session):
        return _preview(session, decisions, owner_reviewed)


def read_correction_batch(session, request_id):
    with coherent_read_snapshot(session):
        receipt = session.get(MyBrokerCorrectionApply, request_id, populate_existing=True)
        if receipt is None:
            raise MyBrokerError("correction_receipt_not_found")
        intent = json.loads(receipt.intent_json)
        current = current_corrections(session)
        sources = {s.id: s for s in _rows(session, MyBrokerImport)}
        from hermes_finance.services.mybroker_dispositions import resolve

        dispositions = [item for s in sources.values() for item in resolve(session, s)]
        return {
            "receipt": {
                "request_id": receipt.request_id,
                "intent": intent,
                "confirmation_digest": receipt.confirmation_digest,
                "committed_revision_ids": json.loads(receipt.revision_ids_json),
                "evidence": json.loads(receipt.evidence_json),
            },
            "current_corrections": [
                current.get((d["import_id"], d["isin"])) for d in intent["decisions"]
            ],
            "instrument_dispositions": dispositions,
            "unresolved_blockers": [
                {
                    "import_id": item["import_id"],
                    "isin": item["isin"],
                    "effective_state": item["effective_state"],
                    "reason": "mybroker_excluded_source_impact",
                }
                for item in dispositions
                if item["effective_state"] != "mapped"
            ],
        }


def apply_corrections(session, *, decisions, owner_reviewed, request_id, confirmation_digest):
    intent = _intent(decisions, owner_reviewed)
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    session.rollback()
    try:
        session.execute(text("UPDATE mybroker_imports SET id=id WHERE 0"))
        receipt = session.get(MyBrokerCorrectionApply, request_id)
        if receipt:
            if (
                receipt.intent_json != canonical(intent)
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
        else:
            view = _preview(session, decisions, owner_reviewed)
            if view["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("preview_stale")
            if not view["can_apply"]:
                raise MyBrokerError("correction_batch_blocked")
            # Receipt exists before its revisions; all are committed together.
            receipt = MyBrokerCorrectionApply(
                request_id=request_id,
                intent_json=canonical(intent),
                confirmation_digest=confirmation_digest,
                evidence_json=canonical(view["evidence"]),
                revision_ids_json="[]",
            )
            # Insert complete immutable receipt after revision IDs are allocated.
            # SQLite IDs are allocated under the writer reservation, no race.
            next_id = max((r.id for r in _rows(session, MyBrokerCorrectionRevision)), default=0) + 1
            rows, ids = [], []
            for reviewed in view["decisions"]:
                decision, prior = reviewed["decision"], reviewed["current_correction"]
                if (
                    prior
                    and prior["effective_state"] == "mapped"
                    and prior["binding"]
                    == {
                        "kind": "instrument",
                        "identity": decision["isin"],
                        "mapping_id": decision["mapping_id"],
                        "hermes_id": decision["hermes_id"],
                    }
                ):
                    ids.append(prior["revision_id"])
                    continue
                row = MyBrokerCorrectionRevision(
                    id=next_id,
                    import_id=decision["import_id"],
                    isin=decision["isin"],
                    revision=(prior["revision"] if prior else 0) + 1,
                    previous_revision_id=prior["revision_id"] if prior else None,
                    predecessor_revision_id=reviewed["disposition"]["revision_id"],
                    request_id=request_id,
                    binding_json=canonical(
                        {
                            "kind": "instrument",
                            "identity": decision["isin"],
                            "mapping_id": decision["mapping_id"],
                            "hermes_id": decision["hermes_id"],
                        }
                    ),
                    recorded_at=datetime.now(UTC),
                )
                rows.append(row)
                ids.append(next_id)
                next_id += 1
            receipt.revision_ids_json = canonical(ids)
            session.add(receipt)
            session.flush()
            session.add_all(rows)
            session.flush()
        session.commit()
    except Exception:
        session.rollback()
        raise
    return read_correction_batch(session, request_id)


def install_sql_guards(connection):
    for model in HISTORY:
        for operation in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {model.__tablename__}_{operation.lower()} BEFORE {operation} ON {model.__tablename__} BEGIN SELECT RAISE(ABORT, 'mybroker correction history is append-only'); END"
            )
    for table in ("mybroker_imports", "broker_identity_mappings", "accounts", "instruments"):
        columns = [r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        for operation in ("INSERT", "UPDATE", "DELETE"):
            when = f"WHEN {changed}" if operation == "UPDATE" else ""
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS correction_change_{table}_{operation.lower()} AFTER {operation} ON {table} {when} BEGIN INSERT INTO mybroker_correction_changes(id) VALUES(NULL); END"
            )
