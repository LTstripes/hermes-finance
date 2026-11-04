"""One-time source custody-month evidence. Never financial authority or a raw cache."""

import hashlib
import json
from collections import OrderedDict
from datetime import UTC, date, datetime
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from time import monotonic

from sqlalchemy import func, select

from hermes_finance.database import coherent_read_operation
from hermes_finance.persistence import (
    SourceIntakeObservation,
    SourceIntakeRevision,
    SourceMoneyClassification,
    SourceReturnProof,
    SourceReturnProofDependency,
)
from hermes_finance.services import mybroker_identity, source_intake
from hermes_finance.source_proof_file import file_incarnation
from hermes_finance.statement_import import mybroker
from hermes_finance.statement_import import mybroker_return_structure as structure

VERSION = "source_return_custody_v1"
STRUCTURE_SEMANTICS = "source_custody_structure_v2"


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

# Exact recovered anchors only; all source/identity/journal guards run on every read.
_LEGACY_ANCHORS = OrderedDict()
_LEGACY_ANCHORS_LOCK = Lock()


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
    """Source structure only; financial readers validate their own operands.

    An ordinary release, catalogue update, new month or unrelated original is
    not a change to these immutable custody observations. Semantic changes must
    explicitly advance STRUCTURE_SEMANTICS and pass the semantic review guard.
    """
    connection = session.connection()
    path = connection.engine.url.database
    physical = file_incarnation(Path(path)) if path else None
    if not physical or connection.info.get("source_proof_incarnation") != physical:
        raise ProofError("source_return_proof_database_incarnation_unavailable")
    return mybroker.digest(
        {
            "version": VERSION,
            "code": STRUCTURE_SEMANTICS,
            "physical_database": physical,
            "sources": sources,
        }
    )


def _legacy_dependency(session, sources):
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


def _compatible_source_only_dependency(session, sources, expected, confirmed_at, anchors=None):
    """Reproduce a previous digest across source-irrelevant financial changes.

    This attests only stored custody-month evidence, never a financial result.
    Every original, manifest, identity, parser, physical database and other
    intervening dependency still has to match exactly.
    """
    from hermes_finance.services.source_custody_compat import (
        CURRENT_CUSTODY_CODE_SHA256,
        LEGACY_CUSTODY_CODE_SHA256,
        PREVIOUS_CUSTODY_CODE_SHA256,
    )

    current_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if current_hash != CURRENT_CUSTODY_CODE_SHA256:
        return False
    path = session.connection().engine.url.database
    physical = file_incarnation(Path(path)) if path else None
    if not physical or session.connection().info.get("source_proof_incarnation") != physical:
        return False
    source_ids = {item["intake_id"] for item in sources}
    # A classification moved away from a bound immutable observation must not
    # masquerade as an unrelated source. Missing/deleted rows remain barriers.
    observations = list(
        session.scalars(
            select(SourceIntakeObservation).where(
                SourceIntakeObservation.original_id.in_(source_ids),
                SourceIntakeObservation.section == "money",
                SourceIntakeObservation.row_class == "recognized",
            )
        )
    )
    classes = list(session.scalars(select(SourceMoneyClassification)))
    by_observation = {row.observation_id: row for row in classes}
    if any(
        o.id not in by_observation or by_observation[o.id].intake_id != o.original_id
        for o in observations
    ):
        return False
    foreign_observations = {
        row.id: row
        for row in session.scalars(
            select(SourceIntakeObservation).where(
                SourceIntakeObservation.id.in_([row.observation_id for row in classes])
            )
        )
    }
    unrelated_money = {
        row.id
        for row in classes
        if row.intake_id not in source_ids
        and (observation := foreign_observations.get(row.observation_id)) is not None
        and observation.original_id == row.intake_id
    }
    deps = iter(
        session.scalars(
            select(SourceReturnProofDependency).order_by(SourceReturnProofDependency.seq.desc())
        ).yield_per(128)
    )
    entry = next(deps, None)
    dep_candidates = [[entry.seq, entry.token] if entry else None]
    while entry is not None:
        bits = entry.token.split(":")
        if (
            len(bits) != 3
            or not bits[1].isdigit()
            or not (bits[0] == "p" or bits[0] == "m" and int(bits[1]) in unrelated_money)
        ):
            break
        entry = next(deps, None)
        dep_candidates.append([entry.seq, entry.token] if entry else None)
    tails = iter(
        session.execute(
            select(
                SourceIntakeRevision.seq,
                SourceIntakeRevision.operation,
                SourceIntakeRevision.payload_json,
                SourceIntakeRevision.accepted_at,
                SourceIntakeRevision.original_id,
            ).order_by(SourceIntakeRevision.seq.desc())
        ).yield_per(128)
    )
    entry = next(tails, None)
    tail_candidates = [(entry.seq, entry.accepted_at) if entry else (None, None)]
    validated_journals = set()
    while entry is not None:
        payload = json.loads(entry.payload_json)
        irrelevant_finance = (
            entry.operation == "dependency"
            and isinstance(payload, dict)
            and payload.get("table")
            in {"position_snapshots", "cash_balances", "investment_cash_flows", "external_flows"}
        )
        unrelated_source = (
            entry.original_id is not None
            and entry.original_id not in source_ids
            and entry.operation in {"manifest", "decision", "finance_link"}
        )
        if unrelated_source and entry.original_id not in validated_journals:
            source_intake._events(session, entry.original_id)
            validated_journals.add(entry.original_id)
        if not (irrelevant_finance or unrelated_source):
            break
        entry = next(tails, None)
        tail_candidates.append((entry.seq, entry.accepted_at) if entry else (None, None))
    # A proof cannot predate the source heads it attests.
    floor = max((item["head_seq"] for item in sources), default=0)
    tail_candidates = [(seq, at) for seq, at in tail_candidates if (seq or 0) >= floor]
    # Timestamps only prioritize candidates; digest equality remains the sole
    # authority, including when clocks moved backwards or several share a second.
    when = confirmed_at.replace(tzinfo=None) if confirmed_at else None
    if when:
        tail_candidates.sort(
            key=lambda item: (
                item[1] is None or item[1].replace(tzinfo=None) > when,
                -(item[0] or 0),
            )
        )
    common_hashes = [
        hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in (structure.__file__, mybroker.__file__)
    ]
    base = {
        "version": VERSION,
        "physical_database": physical,
        "sources": sources,
        "correction_identity_revision": mybroker_identity._revision(session),
    }
    codes = [
        mybroker.digest([*common_hashes, own_hash])
        for own_hash in (current_hash, PREVIOUS_CUSTODY_CODE_SHA256, LEGACY_CUSTODY_CODE_SHA256)
    ]
    # The canonical JSON suffix (mostly immutable sources) is identical for
    # every pair. Encode it once, never serialize the whole source inventory
    # D*T times. This remains exactly mybroker.digest, not a weaker checksum.
    suffix = (
        b","
        + mybroker.canonical(
            {k: v for k, v in base.items() if k not in {"version", "correction_identity_revision"}}
        ).encode()[1:-1]
    )
    suffix += b',"version":' + mybroker.canonical(VERSION).encode() + b"}"
    tails = {tail for tail, _ in tail_candidates}
    dependencies = {mybroker.canonical(dep) for dep in dep_candidates}
    key = (
        physical,
        expected,
        mybroker.digest(sources),
        base["correction_identity_revision"],
        tuple(codes),
    )
    with _LEGACY_ANCHORS_LOCK:
        cached = _LEGACY_ANCHORS.get(key)
    preferred = [value for value in (anchors, cached) if isinstance(value, dict)]

    def matches(code, dependency, tail):
        prefix = {
            "code": code,
            "correction_identity_revision": base["correction_identity_revision"],
            "dependency": dependency,
            "intake_tail": tail,
        }
        return (
            hashlib.sha256(mybroker.canonical(prefix).encode()[:-1] + suffix).hexdigest()
            == expected
        )

    found = None
    for candidate in preferred:
        code, dependency, tail = (candidate.get(k) for k in ("code", "dependency", "intake_tail"))
        if (
            code in codes
            and tail in tails
            and mybroker.canonical(dependency) in dependencies
            and matches(code, dependency, tail)
        ):
            found = candidate
            break
    if found is None:
        # Hash the long common suffix in C; small per-pair serialization only.
        for tail, _ in tail_candidates:
            for dependency in dep_candidates:
                for code in codes:
                    if matches(code, dependency, tail):
                        found = {"code": code, "dependency": dependency, "intake_tail": tail}
                        break
                if found is not None:
                    break
            if found is not None:
                break
    if found is None:
        return False
    with _LEGACY_ANCHORS_LOCK:
        _LEGACY_ANCHORS[key] = found
        _LEGACY_ANCHORS.move_to_end(key)
        while len(_LEGACY_ANCHORS) > 128:
            _LEGACY_ANCHORS.popitem(last=False)
    return True


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
    from hermes_finance.database import snapshot_read_result

    row = _latest(session, source_account, native_scope)
    if row is None:
        try:
            currentness = _dependency(session, _sources(selected, native_scope))
        except (ProofError, OSError):
            currentness = None
        return {}, _status(None, "absent", currentness=currentness)
    currentness = None
    try:
        evidence = json.loads(row.evidence_json)
        bound_ids = {item["intake_id"] for item in evidence["sources"]}
        sources = _sources([item for item in selected if item[0].id in bound_ids], native_scope)
        currentness = _dependency(session, sources)
        if (
            row.proof_version != VERSION
            or evidence.get("dependency_kind") not in {None, STRUCTURE_SEMANTICS}
            or evidence["sources"] != sources
            or (
                row.dependency_digest != currentness
                and (
                    evidence.get("dependency_kind") is not None
                    or not snapshot_read_result(
                        session,
                        "source_custody_compatible_dependency",
                        (row.id, row.dependency_digest, mybroker.digest(sources)),
                        lambda: _compatible_source_only_dependency(
                            session,
                            sources,
                            row.dependency_digest,
                            row.confirmed_at,
                            evidence.get("anchors"),
                        ),
                    )
                )
            )
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
        "dependency_kind": STRUCTURE_SEMANTICS,
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
                {
                    "sources": sources,
                    "cancellations": plan["cancellations"],
                    "dependency_kind": plan.get("dependency_kind"),
                },
                sort_keys=True,
            ),
            confirmed_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        return {**proof_request_status(session, request_id), "replay": False}
    except BaseException:
        session.rollback()
        raise
