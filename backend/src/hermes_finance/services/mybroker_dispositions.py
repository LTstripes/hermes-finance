"""Revision-bound source exclusions. No date expiry or financial authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import event, select, text

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Account,
    Base,
    BrokerIdentityMapping,
    MyBrokerDispositionApply,
    MyBrokerDispositionChange,
    MyBrokerDispositionRevision,
    MyBrokerDispositionSet,
    MyBrokerImport,
)
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest

REASON = "mybroker_excluded_source_impact"
CONTRACT = "mybroker-instrument-skip-v1"
TABLES = (
    MyBrokerDispositionSet,
    MyBrokerDispositionRevision,
    MyBrokerDispositionApply,
    MyBrokerDispositionChange,
)


def source_fingerprint(source):
    return digest(
        [
            source.document_sha256,
            source.parser_version,
            source.normalized_json,
            source.mappings_json,
        ]
    )


def occurrence_evidence(document, bindings, isin):
    positions = [p for p in document["positions"] if p["isin"] == isin]
    trades = [t for t in document["trades"] if t["core"]["isin"] == isin]
    accounts = {p["source_account"] for p in positions} | {
        t["core"]["source_account"] for t in trades
    }
    # An opaque section cannot be attributed more narrowly than the bound document.
    if document["syntax_blockers"]:
        accounts.update(b["identity"] for b in bindings if b["kind"] == "account")
    links = {(t["core"]["source_account"], t["ids"][0]) for t in trades if t["ids"]}
    money = [m for m in document["money"] if (m["source_account"], m.get("primary_id")) in links]
    return {
        "contract": CONTRACT,
        "isin": isin,
        "owner_reviewed": True,
        "accounts": [b for b in bindings if b["kind"] == "account" and b["identity"] in accounts],
        "occurrences": [
            {"section": r["section"], "ordinal": r["ordinal"], "fingerprint": digest(r)}
            for r in positions + trades + money
        ],
        "trade_identities": sorted(t["identity"] for t in trades if t["identity"]),
        "money_links": sorted([a, i] for a, i in links),
        "source_set_fingerprint": digest([document, bindings, isin]),
    }


def counts(document, bindings, skips):
    return {
        "mapped": sum(b["kind"] == "instrument" for b in bindings),
        "skipped": len(skips),
        "unsupported": sum(m["kind"] == "unsupported" for m in document["money"])
        + sum(t["repo_observed"] or t["identity"] is None for t in document["trades"])
        + len(document["syntax_blockers"]),
    }


def dependency_context(session, source, isin):
    bindings = json.loads(source.mappings_json)
    identities = {("account", b["identity"]) for b in bindings if b["kind"] == "account"} | {
        ("instrument", isin)
    }
    registry = list(
        session.scalars(
            select(BrokerIdentityMapping)
            .where(BrokerIdentityMapping.provider == PROVIDER)
            .order_by(BrokerIdentityMapping.id)
        )
    )
    material = [
        [
            str(getattr(m, field))
            for field in (
                "id",
                "subject_kind",
                "provider_identity",
                "hermes_target_id",
                "status",
                "observed_isin",
                "revoked_at",
                "predecessor_mapping_id",
                "successor_mapping_id",
            )
        ]
        for m in registry
        if (m.subject_kind, m.provider_identity) in identities
    ]
    valid = all(
        any(
            m.id == b["mapping_id"]
            and m.status == "effective"
            and m.subject_kind == "account"
            and m.provider_identity == b["identity"]
            and m.hermes_target_id == b["hermes_id"]
            for m in registry
        )
        and session.get(Account, b["hermes_id"]) is not None
        for b in bindings
        if b["kind"] == "account"
    )
    changes = list(
        session.scalars(
            select(MyBrokerDispositionChange.id)
            .where(MyBrokerDispositionChange.import_id == source.id)
            .order_by(MyBrokerDispositionChange.id)
        )
    )
    return {"source": source_fingerprint(source), "registry": material, "changes": changes}, valid


def resolve(session, source):
    """Permanent impacted identities survive revoke, retirement and missing support."""
    document, bindings = json.loads(source.normalized_json), json.loads(source.mappings_json)
    mapped = {b["identity"] for b in bindings if b["kind"] == "instrument"}
    needed = {p["isin"] for p in document["positions"]} | {
        t["core"]["isin"] for t in document["trades"]
    }
    marker = session.get(MyBrokerDispositionSet, source.id, populate_existing=True)
    manifest = set(json.loads(marker.skipped_isins_json)) if marker else set()
    # Missing initial extension never converts an unmapped accepted row into legacy.
    retained = list(
        session.scalars(
            select(MyBrokerDispositionRevision)
            .where(MyBrokerDispositionRevision.import_id == source.id)
            .order_by(MyBrokerDispositionRevision.revision)
        )
    )
    excluded = manifest | (needed - mapped) | {r.isin for r in retained}
    result = []
    for isin in sorted(excluded):
        revisions = list(
            session.scalars(
                select(MyBrokerDispositionRevision)
                .where(
                    MyBrokerDispositionRevision.import_id == source.id,
                    MyBrokerDispositionRevision.isin == isin,
                )
                .order_by(MyBrokerDispositionRevision.revision)
                .execution_options(populate_existing=True)
            )
        )
        current = revisions[-1] if revisions else None
        expected = occurrence_evidence(document, bindings, isin)
        original = next(
            (json.loads(r.evidence_json)["source"] for r in retained if r.isin == isin), expected
        )
        retained_accounts = {canonical(b): b for b in original["accounts"] + expected["accounts"]}
        retained_identities = sorted(
            set(original["trade_identities"]) | set(expected["trade_identities"])
        )
        context, valid = dependency_context(session, source, isin)
        state = "invalid"
        if current and marker and marker.source_fingerprint == source_fingerprint(source):
            evidence = json.loads(current.evidence_json)
            if evidence.get("source") == expected:
                state = current.state
                if state == "accepted" and (not valid or evidence.get("dependencies") != context):
                    state = "retired"
        result.append(
            {
                **expected,
                "accounts": list(retained_accounts.values()),
                "trade_identities": retained_identities,
                "import_id": source.id,
                "revision_id": current.id if current else None,
                "revision": current.revision if current else 0,
                "effective_state": state,
                "history": [
                    {
                        "revision_id": r.id,
                        "revision": r.revision,
                        "state": r.state,
                        "operation": r.operation,
                    }
                    for r in revisions
                ],
                "dependencies": context,
            }
        )
    return result


def impact(session, account_ids):
    requested = set(account_ids)
    items = []
    if not requested:
        return items
    for source in session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id)):
        for item in resolve(session, source):
            if any(b["hermes_id"] in requested for b in item["accounts"]):
                items.append(item)
    return items


def excluded_trade(session, identity):
    return any(
        identity in item["trade_identities"]
        for source in session.scalars(select(MyBrokerImport))
        for item in resolve(session, source)
    )


def append_revision(session, source, isin, operation, state, confirmation, current=None):
    context, valid = dependency_context(session, source, isin)
    if state == "accepted" and not valid:
        raise MyBrokerError("accepted_mapping_conflict")
    row = MyBrokerDispositionRevision(
        import_id=source.id,
        isin=isin,
        revision=current.revision + 1 if current else 1,
        previous_revision_id=current.id if current else None,
        operation=operation,
        state=state,
        evidence_json=canonical(
            {
                "source": occurrence_evidence(
                    json.loads(source.normalized_json), json.loads(source.mappings_json), isin
                ),
                "dependencies": context,
            }
        ),
        confirmation_digest=confirmation,
        recorded_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row


def initial_accept(session, source, skips, confirmation):
    session.add(
        MyBrokerDispositionSet(
            import_id=source.id,
            skipped_isins_json=canonical(sorted(skips)),
            source_fingerprint=source_fingerprint(source),
        )
    )
    session.flush()
    return [
        append_revision(session, source, isin, "accept", "accepted", confirmation).id
        for isin in sorted(skips)
    ]


def lifecycle_preview(session, *, import_id, isin, operation, expected_revision):
    if operation not in ("revoke", "reaffirm"):
        raise MyBrokerError("reconciliation_required")
    source = session.get(MyBrokerImport, import_id)
    if source is None:
        raise MyBrokerError("import_not_found")
    items = [i for i in resolve(session, source) if i["isin"] == isin]
    if len(items) != 1 or not items[0]["revision_id"]:
        raise MyBrokerError("reconciliation_required")
    item = items[0]
    context, valid = dependency_context(session, source, isin)
    intent = {
        "import_id": import_id,
        "isin": isin,
        "operation": operation,
        "expected_revision": expected_revision,
    }
    blockers = []
    marker = session.get(MyBrokerDispositionSet, source.id)
    original = session.scalar(
        select(MyBrokerDispositionRevision)
        .where(
            MyBrokerDispositionRevision.import_id == source.id,
            MyBrokerDispositionRevision.isin == isin,
        )
        .order_by(MyBrokerDispositionRevision.revision)
        .limit(1)
    )
    if operation == "reaffirm" and (
        marker is None
        or marker.source_fingerprint != source_fingerprint(source)
        or json.loads(original.evidence_json)["source"]
        != occurrence_evidence(
            json.loads(source.normalized_json), json.loads(source.mappings_json), isin
        )
    ):
        blockers.append("instrument_disposition_reconciliation_required")
    if expected_revision != item["revision"]:
        blockers.append("disposition_revision_stale")
    if operation == "reaffirm" and not valid:
        blockers.append("accepted_mapping_conflict")
    return {
        "intent": intent,
        "disposition": item,
        "blockers": blockers,
        "can_apply": not blockers,
        "confirmation_digest": digest([intent, item, context]),
    }


def apply_lifecycle(session, *, request_id, confirmation_digest, **intent):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    session.rollback()
    try:
        session.execute(text("UPDATE mybroker_imports SET id=id WHERE 0"))
        receipt = session.get(MyBrokerDispositionApply, request_id)
        intent_digest = digest(intent)
        if receipt:
            if (
                receipt.intent_digest != intent_digest
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
            source = session.get(MyBrokerImport, receipt.import_id)
            result = {
                "committed_revision_ids": json.loads(receipt.revision_ids_json),
                "dispositions": resolve(session, source),
            }
        else:
            view = lifecycle_preview(session, **intent)
            if view["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("preview_stale")
            if not view["can_apply"]:
                raise MyBrokerError("reconciliation_required")
            source = session.get(MyBrokerImport, intent["import_id"])
            current = session.get(MyBrokerDispositionRevision, view["disposition"]["revision_id"])
            state = "revoked" if intent["operation"] == "revoke" else "accepted"
            if current.state == state and view["disposition"]["effective_state"] == state:
                row = current
            else:
                row = append_revision(
                    session,
                    source,
                    intent["isin"],
                    intent["operation"],
                    state,
                    confirmation_digest,
                    current,
                )
            session.add(
                MyBrokerDispositionApply(
                    request_id=request_id,
                    import_id=source.id,
                    intent_digest=intent_digest,
                    confirmation_digest=confirmation_digest,
                    revision_ids_json=canonical([row.id]),
                )
            )
            session.flush()
            result = {"committed_revision_ids": [row.id]}
        session.commit()
    except Exception:
        session.rollback()
        raise
    with coherent_read_snapshot(session):
        result["dispositions"] = resolve(
            session, session.get(MyBrokerImport, intent["import_id"], populate_existing=True)
        )
    return result


def install_sql_guards(connection):
    """Identical SQL guards for migrations and synthetic metadata databases."""
    for model in TABLES:
        table = model.__tablename__
        for op in ("UPDATE", "DELETE"):
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS {table}_{op.lower()} BEFORE {op} ON {table} BEGIN SELECT RAISE(ABORT, 'mybroker disposition history is append-only'); END"
            )
    for table in ("broker_identity_mappings", "accounts", "mybroker_imports"):
        columns = [r[1] for r in connection.exec_driver_sql(f"PRAGMA table_info({table})")]
        changed = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in columns)
        for op, aliases in (("INSERT", ("NEW",)), ("UPDATE", ("OLD", "NEW")), ("DELETE", ("OLD",))):
            statements = []
            for alias in aliases:
                if table == "broker_identity_mappings":
                    condition = f"{alias}.provider = 'alfa_mybroker' AND (({alias}.subject_kind='instrument' AND EXISTS (SELECT 1 FROM json_each(s.skipped_isins_json) WHERE value={alias}.provider_identity)) OR ({alias}.subject_kind='account' AND EXISTS (SELECT 1 FROM json_each(i.mappings_json) b WHERE json_extract(b.value,'$.kind')='account' AND json_extract(b.value,'$.identity')={alias}.provider_identity)))"
                elif table == "accounts":
                    condition = f"EXISTS (SELECT 1 FROM json_each(i.mappings_json) b WHERE json_extract(b.value,'$.kind')='account' AND json_extract(b.value,'$.hermes_id')={alias}.id)"
                else:
                    condition = f"i.id={alias}.id"
                affected = f"SELECT s.import_id FROM mybroker_disposition_sets s JOIN mybroker_imports i ON i.id=s.import_id WHERE {condition}"
                statements.append(
                    f"INSERT INTO mybroker_disposition_changes(import_id) {affected};"
                )
                statements.append(
                    f"INSERT INTO mybroker_disposition_revisions(import_id,isin,revision,previous_revision_id,operation,state,evidence_json,confirmation_digest,recorded_at) SELECT r.import_id,r.isin,r.revision+1,r.id,'retire','retired',r.evidence_json,r.confirmation_digest,CURRENT_TIMESTAMP FROM mybroker_disposition_revisions r WHERE r.import_id IN ({affected}) AND r.state='accepted' AND r.revision=(SELECT MAX(x.revision) FROM mybroker_disposition_revisions x WHERE x.import_id=r.import_id AND x.isin=r.isin);"
                )
            when = f"WHEN {changed}" if op == "UPDATE" else ""
            connection.exec_driver_sql(
                f"CREATE TRIGGER IF NOT EXISTS skip_change_{table}_{op.lower()} AFTER {op} ON {table} {when} BEGIN {' '.join(statements)} END"
            )


def _after_create(_metadata, connection, **_kwargs):
    install_sql_guards(connection)


def install_hooks():
    if not event.contains(Base.metadata, "after_create", _after_create):
        event.listen(Base.metadata, "after_create", _after_create)
