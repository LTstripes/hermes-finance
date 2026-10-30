"""One-time source custody-month evidence. Never financial authority or a raw cache."""

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from time import monotonic

from sqlalchemy import func, select

from hermes_finance.database import coherent_read_operation
from hermes_finance.persistence import (
    SourceIntakeRevision,
    SourceReturnProof,
    SourceReturnProofDependency,
)
from hermes_finance.services import mybroker_identity, source_intake
from hermes_finance.source_proof_file import file_incarnation
from hermes_finance.statement_import import mybroker
from hermes_finance.statement_import import mybroker_return_structure as structure

VERSION = "source_return_custody_v1"


class ProofError(ValueError):
    pass


class Forms:
    """Bounded, single-use server plans. Original bytes never enter this registry."""

    def __init__(self):
        self.lock = Lock()
        self.entries = {}

    def issue(self, epoch, plan):
        with self.lock:
            now = monotonic()
            self.entries = {k: v for k, v in self.entries.items() if v[0] > now}
            if len(self.entries) >= 128:
                self.entries.pop(next(iter(self.entries)))
            token = token_urlsafe(32)
            self.entries[token] = (now + 900, epoch, json.dumps(plan, sort_keys=True))
            return token

    def consume(self, token, epoch, expected_digest):
        with self.lock:
            entry = self.entries.pop(token, None)
        if entry is None or entry[0] <= monotonic() or entry[1] != epoch:
            raise ProofError("source_return_proof_form_expired")
        plan = json.loads(entry[2])
        if mybroker.digest(plan) != expected_digest:
            raise ProofError("source_return_proof_preview_changed")
        return plan


FORMS = Forms()


def _epoch(session):
    return session.info.get("source_intake_epoch", source_intake.PROCESS_EPOCH)


def _latest(session, source_account, native_scope=None):
    key = (
        SourceReturnProof.native_account == next(iter(native_scope))
        if native_scope is not None and len(native_scope) == 1
        else SourceReturnProof.source_account == source_account
    )
    return session.scalar(
        select(SourceReturnProof)
        .where(key, SourceReturnProof.proof_version == "source_return_custody_v1")
        .order_by(SourceReturnProof.id.desc())
        .limit(1)
    )


def _sources(selected, native_scope):
    if not selected or native_scope is None or len(native_scope) != 1:
        raise ProofError("source_return_proof_scope_ambiguous")
    from hermes_finance.services.source_monthly_returns import _native_scope

    sources = []
    for original, view, error in selected:
        if error or _native_scope(view["document"]) != native_scope:
            raise ProofError("source_return_proof_scope_ambiguous")
        sources.append(
            {
                "intake_id": original.id,
                "document_sha256": original.document_sha256,
                "manifest_digest": view["manifest_digest"],
                "parser": view["document"]["parser"],
                "generation": view["generation"],
                "head_seq": view["head_seq"],
                "native_account": next(iter(native_scope)),
            }
        )
    return sources


def _dependency(session, sources):
    connection = session.connection()
    path = connection.engine.url.database
    physical = file_incarnation(Path(path)) if path else None
    if not physical or connection.info.get("source_proof_incarnation") != physical:
        raise ProofError("source_return_proof_database_incarnation_unavailable")
    last = session.scalar(
        select(SourceReturnProofDependency)
        .order_by(SourceReturnProofDependency.seq.desc())
        .limit(1)
    )
    code = mybroker.digest(
        [
            hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for path in (structure.__file__, mybroker.__file__, __file__)
        ]
    )
    return mybroker.digest(
        {
            "version": VERSION,
            "code": code,
            "physical_database": physical,
            "sources": sources,
            "dependency": [last.seq, last.token] if last else None,
            "intake_tail": session.scalar(select(func.max(SourceIntakeRevision.seq))),
            "correction_identity_revision": mybroker_identity._revision(session),
        }
    )


def _status(row, state, reasons=(), currentness=None):
    return {
        "status": state,
        "proof_id": row.id if row else None,
        "version": row.proof_version if row else VERSION,
        "confirmed_at": row.confirmed_at.replace(tzinfo=UTC).isoformat() if row else None,
        "currentness": currentness,
        "reason_codes": list(reasons),
        "financial_authority": "none",
    }


def resolve_proof(session, source_account, selected, native_scope):
    """Latest proof only. A retired proof never falls back to an earlier record."""
    row = _latest(session, source_account, native_scope)
    if row is None:
        try:
            currentness = _dependency(session, _sources(selected, native_scope))
        except (ProofError, OSError):
            currentness = None
        return {}, _status(None, "absent", currentness=currentness)
    currentness = None
    try:
        sources = _sources(selected, native_scope)
        currentness = _dependency(session, sources)
        evidence = json.loads(row.evidence_json)
        if (
            row.proof_version != VERSION
            or evidence["sources"] != sources
            or row.dependency_digest != currentness
        ):
            raise ProofError("source_return_proof_dependencies_changed")
        dates = {}
        for entry in evidence["cancellations"]:
            if entry["intake_id"] not in {x["intake_id"] for x in sources}:
                raise ProofError("source_return_proof_invalid")
            months = tuple(date.fromisoformat(value) for value in entry["months"])
            if not months or any(day.day != 1 for day in months):
                raise ProofError("source_return_proof_invalid")
            dates[entry["intake_id"]] = months
        if not dates:
            raise ProofError("source_return_proof_invalid")
        return dates, _status(row, "current", currentness=currentness)
    except (ProofError, ValueError, KeyError, TypeError, OSError) as error:
        code = str(error) if isinstance(error, ProofError) else "source_return_proof_invalid"
        return {}, _status(row, "stale", (code,), currentness=currentness)


@coherent_read_operation
def preview_proof(session, *, source_account, documents, expected_sources):
    from hermes_finance.services.source_monthly_returns import (
        _selected_sources,
        verified_originals,
    )

    selected, originals = verified_originals(
        session,
        source_account=source_account,
        documents=documents,
        expected_sources=expected_sources,
    )
    _, native_scope = _selected_sources(session, source_account)
    sources = _sources(selected, native_scope)
    cancellations = []
    for row, view, _ in selected:
        dates = structure.original_cancellation_dates(view, originals[row.id][0])
        if dates is not None:
            cancellations.append(
                {
                    "intake_id": row.id,
                    "months": sorted({day.replace(day=1).isoformat() for day in dates}),
                }
            )
        elif {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"}.intersection(
            structure.source_return_blockers(view)
        ):
            raise ProofError("source_return_proof_unsupported_structure")
    if not cancellations:
        raise ProofError("source_return_proof_not_needed")
    latest = _latest(session, source_account, native_scope)
    plan = {
        "version": VERSION,
        "source_account": source_account,
        "sources": sources,
        "cancellations": cancellations,
        "dependency_digest": _dependency(session, sources),
        "predecessor_id": latest.id if latest else None,
    }
    return {
        "preview_digest": mybroker.digest(plan),
        "form_token": FORMS.issue(_epoch(session), plan),
        "source_account": source_account,
        "version": VERSION,
        "source_count": len(sources),
        "cancellation_months": sorted(
            {month for entry in cancellations for month in entry["months"]}
        ),
        "table_deltas": {"source_return_proofs": 1, "source_return_proof_dependencies": 0},
        "other_table_deltas": 0,
        "trigger_deltas": 0,
        "financial_effects": 0,
        "financial_authority": "none",
    }


def _ack(session, row, replay):
    from hermes_finance.services.source_monthly_returns import _selected_sources

    selected, native = _selected_sources(session, row.source_account)
    _, current = resolve_proof(session, row.source_account, selected, native)
    if current["proof_id"] != row.id:
        current = _status(row, "stale", ("source_return_proof_superseded",))
    return {
        "request_id": row.request_id,
        "source_account": row.source_account,
        "proof": current,
        "replay": replay,
    }


@coherent_read_operation
def proof_request_status(session, request_id):
    row = session.scalar(
        select(SourceReturnProof).where(SourceReturnProof.request_id == request_id)
    )
    if row is None:
        raise ProofError("source_return_proof_request_not_found")
    return _ack(session, row, True)


def confirm_proof(session, *, source_account, form_token, preview_digest, request_id):
    """Reserve before revalidation; append exactly one source-only proof."""
    fingerprint = mybroker.digest([source_account, form_token, preview_digest])
    source_intake._reserve(session)
    try:
        session.expire_all()
        retry = session.scalar(
            select(SourceReturnProof).where(SourceReturnProof.request_id == request_id)
        )
        if retry:
            if retry.request_fingerprint != fingerprint:
                raise ProofError("source_return_proof_request_conflict")
            session.rollback()
            return proof_request_status(session, request_id)
        plan = FORMS.consume(form_token, _epoch(session), preview_digest)
        from hermes_finance.services.source_monthly_returns import _selected_sources

        # Same V1 view builder under the held SQLite writer reservation; a
        # separate committed-read wrapper must not commit/release that writer.
        selected, native = _selected_sources(session, source_account, reserved=True)
        sources = _sources(selected, native)
        latest = _latest(session, source_account, native)
        if (
            plan["source_account"] != source_account
            or plan["version"] != VERSION
            or plan["sources"] != sources
            or plan["dependency_digest"] != _dependency(session, sources)
            or plan["predecessor_id"] != (latest.id if latest else None)
        ):
            raise ProofError("source_return_proof_dependencies_changed")
        row = SourceReturnProof(
            source_account=source_account,
            native_account=next(iter(native)),
            request_id=request_id,
            request_fingerprint=fingerprint,
            proof_version=VERSION,
            dependency_digest=plan["dependency_digest"],
            evidence_json=json.dumps(
                {"sources": sources, "cancellations": plan["cancellations"]}, sort_keys=True
            ),
            confirmed_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        return {**proof_request_status(session, request_id), "replay": False}
    except BaseException:
        session.rollback()
        raise
