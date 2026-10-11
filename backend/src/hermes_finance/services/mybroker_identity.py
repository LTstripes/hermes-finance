"""Original-bound identity planning and staging for the later broker-month writer.

No source or financial acceptance, no standalone Apply and no commit. The caller
owns the outer transaction and must roll it back if its later month work fails.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    Instrument,
    MyBrokerCorrectionChange,
    MyBrokerCorrectionRevision,
    MyBrokerDispositionChange,
    MyBrokerDispositionRevision,
    MyBrokerDispositionSet,
    MyBrokerImport,
)
from hermes_finance.services.broker_identity_mappings import confirm_mapping
from hermes_finance.services.mybroker_dispositions import effective_bindings, resolve
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, digest


def _revision(session: Session) -> str:
    # Include the existing monotonic change journal: A -> B -> A is stale too.
    # Full mapped catalogue fields are dependencies, including inactive identity.
    state = {}
    for model in (
        Account,
        Instrument,
        BrokerIdentityMapping,
        MyBrokerImport,
        MyBrokerDispositionSet,
        MyBrokerDispositionRevision,
        MyBrokerDispositionChange,
        MyBrokerCorrectionRevision,
        MyBrokerCorrectionChange,
    ):
        columns = list(model.__table__.columns)
        state[model.__tablename__] = [
            [str(value) if value is not None else None for value in row]
            for row in session.execute(select(*columns).order_by(*model.__table__.primary_key))
        ]
    return digest(state)


def _prepare(session: Session, evidence: dict, account_bindings: list[dict]) -> dict:
    conflicts = set(evidence["conflicts"])
    registry = list(
        session.scalars(
            select(BrokerIdentityMapping)
            .where(BrokerIdentityMapping.provider == PROVIDER)
            .order_by(BrokerIdentityMapping.id)
        )
    )
    requested = {}
    for item in account_bindings:
        alias, target = item["identity"], item["hermes_id"]
        if alias in requested:
            conflicts.add("duplicate_account_alias")
        if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
            conflicts.add("account_binding_invalid")
        requested[alias] = target
    if set(requested) - set(evidence["source_accounts"]):
        conflicts.add("account_alias_unobserved")
    accounts = []
    targets = {}
    for alias in evidence["source_accounts"]:
        history = [
            m for m in registry if m.subject_kind == "account" and m.provider_identity == alias
        ]
        effective = [m for m in history if m.status == "effective"]
        target_id = requested.get(alias)
        if len(effective) > 1:
            conflicts.add("account_mapping_conflict")
        elif effective:
            if target_id is not None and target_id != effective[0].hermes_target_id:
                conflicts.add("account_mapping_conflict")
            target_id = effective[0].hermes_target_id
        account = session.get(Account, target_id) if target_id else None
        if account is None or account.account_type not in {"brokerage", "iis"}:
            conflicts.add("account_binding_required")
        if any(m.status == "revoked" and m.hermes_target_id != target_id for m in history):
            conflicts.add("revoked_account_binding_conflict")
        targets[alias] = target_id
        accounts.append(
            {
                "identity": alias,
                "hermes_id": target_id,
                "mapping_id": effective[0].id if len(effective) == 1 else None,
                "action": "reuse" if len(effective) == 1 else "stage_create",
            }
        )
    # Filename and row code remain separately proved aliases, never suffix guesses.
    if any(
        targets.get(alias) != targets.get(evidence["filename_account"])
        for alias in evidence["row_accounts"]
    ):
        conflicts.add("source_account_conflict")
    position_aliases = set()
    for row in evidence["position_aliases"]:
        key = (targets.get(row["source_account"]), row["isin"])
        if key in position_aliases:
            conflicts.add("duplicate_position_alias")
        position_aliases.add(key)

    instruments = []
    evidence_gaps = []
    for observed in evidence["instruments"]:
        isin = observed["isin"]
        matches = list(
            session.scalars(
                select(Instrument).where(func.upper(func.trim(Instrument.isin)) == isin)
            )
        )
        history = [
            m for m in registry if m.subject_kind == "instrument" and m.provider_identity == isin
        ]
        effective = [m for m in history if m.status == "effective"]
        target = matches[0] if len(matches) == 1 else None
        if len(matches) > 1 or len(effective) > 1:
            conflicts.add("instrument_alias_conflict")
        if effective and (
            target is None
            or effective[0].hermes_target_id != target.id
            or effective[0].observed_isin not in (None, isin)
        ):
            conflicts.add("instrument_mapping_conflict")
        if target and (
            target.isin != isin
            or target.instrument_type != observed["instrument_type"]
            or (observed["currency"] is not None and target.currency != observed["currency"])
        ):
            conflicts.add("instrument_metadata_conflict")
        if any(
            m.status == "revoked"
            and (
                target is None
                or m.hermes_target_id != target.id
                or m.observed_isin not in (None, isin)
            )
            for m in history
        ):
            conflicts.add("revoked_instrument_binding_conflict")
        if target and any(
            m.subject_kind == "instrument"
            and m.status == "effective"
            and m.hermes_target_id == target.id
            and m.provider_identity != isin
            for m in registry
        ):
            conflicts.add("instrument_reverse_alias_conflict")
        if target and any(
            m.subject_kind == "instrument"
            and m.status == "revoked"
            and m.hermes_target_id == target.id
            and m.provider_identity != isin
            for m in registry
        ):
            conflicts.add("revoked_instrument_binding_conflict")
        gaps = list(observed["evidence_gaps"])
        if target is None and observed["currency"] is None:
            gaps.append("instrument_currency_unproven")
        if target and (not target.currency or not re.fullmatch(r"[A-Z]{3}", target.currency)):
            gaps.append("instrument_currency_unproven")
        evidence_gaps.extend({"isin": isin, "code": gap} for gap in gaps)
        instruments.append(
            {
                **observed,
                "currency": target.currency if target else observed["currency"],
                "currency_basis": "existing_catalogue" if target else observed["currency_basis"],
                "evidence_gaps": sorted(set(gaps)),
                "hermes_id": target.id if target else None,
                "action": "reuse" if target else "stage_create",
                "mapping_id": effective[0].id if len(effective) == 1 else None,
                "mapping_action": "reuse" if len(effective) == 1 else "stage_create",
                "nominal_value_kopecks": None,
                "ticker": None,
            }
        )

    # Legacy Skip/correction stays under its own lifecycle. A new original-bound
    # identity plan cannot turn any excluded occurrence into accepted authority.
    incoming = {row["isin"] for row in evidence["instruments"]}
    proposed_bindings = [
        {
            "kind": "account",
            "identity": p["identity"],
            "hermes_id": p["hermes_id"],
            "mapping_id": p["mapping_id"],
        }
        for p in accounts
    ] + [
        {
            "kind": "instrument",
            "identity": p["isin"],
            "hermes_id": p["hermes_id"],
            "mapping_id": p["mapping_id"],
        }
        for p in instruments
    ]
    for source in session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id)):
        document = json.loads(source.normalized_json)
        affected_accounts = {
            b["hermes_id"] for b in json.loads(source.mappings_json) if b["kind"] == "account"
        } & set(targets.values())
        if affected_accounts and any(
            i["isin"] in incoming and i["effective_state"] != "mapped"
            for i in resolve(session, source)
        ):
            conflicts.add("instrument_disposition_reconciliation_required")
        if source.document_sha256 == evidence["document_sha256"] and (
            source.parser_version != evidence["source_parser"]
            or document["covered_from"] != evidence["covered_from"]
            or document["covered_to"] != evidence["covered_to"]
            or document["filename_account"] != evidence["filename_account"]
        ):
            conflicts.add("accepted_source_conflict")
        if source.document_sha256 == evidence["document_sha256"] and sorted(
            effective_bindings(session, source), key=lambda b: (b["kind"], b["identity"])
        ) != sorted(proposed_bindings, key=lambda b: (b["kind"], b["identity"])):
            conflicts.add("accepted_mapping_conflict")
    revision = _revision(session)
    material = {
        "evidence": evidence,
        "accounts": accounts,
        "instruments": instruments,
        "revision": revision,
        "conflicts": sorted(conflicts),
        "evidence_gaps": evidence_gaps,
    }
    return {
        **material,
        "confirmation_digest": digest(material),
        "can_stage": not conflicts and not evidence_gaps,
        "can_apply": False,
    }


def preview_identity(
    session: Session, *, document: bytes, filename: str, account_bindings: list[dict]
) -> dict:
    from hermes_finance.statement_import.mybroker_identity import parse_identity

    evidence = parse_identity(document, filename)
    with coherent_read_snapshot(session):
        return _prepare(session, evidence, account_bindings)


def stage_identity(
    session: Session,
    *,
    document: bytes,
    filename: str,
    account_bindings: list[dict],
    confirmation_digest: str,
) -> dict:
    """Stage one batch inside the caller's SQLite transaction, never commit it.

    Call before staging the month. The no-op UPDATE reserves the same single
    writer for source revalidation, identity staging and the caller's later work.
    The savepoint rolls back the entire identity batch on any flush failure;
    the caller still owns rollback/commit of the outer source -> month batch.
    """
    from hermes_finance.statement_import.mybroker_identity import parse_identity

    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    if session.get_bind().dialect.name != "sqlite":
        raise MyBrokerError("sqlite_writer_required")
    evidence = parse_identity(document, filename)
    session.execute(
        update(MyBrokerImport).where(MyBrokerImport.id == -1).values(id=MyBrokerImport.id)
    )
    session.expire_all()
    plan = _prepare(session, evidence, account_bindings)
    if confirmation_digest != plan["confirmation_digest"]:
        raise MyBrokerError("identity_preview_stale")
    if not plan["can_stage"]:
        raise MyBrokerError("identity_batch_conflict")
    bindings = []
    with session.begin_nested():
        for proposal in plan["accounts"]:
            mapping = confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="account",
                provider_identity=proposal["identity"],
                hermes_target_id=proposal["hermes_id"],
                commit=False,
            )
            bindings.append(
                {
                    "kind": "account",
                    "identity": proposal["identity"],
                    "hermes_id": mapping.hermes_target_id,
                    "mapping_id": mapping.id,
                }
            )
        for proposal in plan["instruments"]:
            target_id = proposal["hermes_id"]
            if target_id is None:
                target = Instrument(
                    name=proposal["source_name"],
                    isin=proposal["isin"],
                    instrument_type=proposal["instrument_type"],
                    currency=proposal["currency"],
                    nominal_value_kopecks=None,
                    ticker=None,
                    moex_secid=None,
                )
                session.add(target)
                session.flush()
                target_id = target.id
            mapping = confirm_mapping(
                session,
                provider=PROVIDER,
                subject_kind="instrument",
                provider_identity=proposal["isin"],
                hermes_target_id=target_id,
                observed_isin=proposal["isin"],
                commit=False,
            )
            bindings.append(
                {
                    "kind": "instrument",
                    "identity": proposal["isin"],
                    "hermes_id": mapping.hermes_target_id,
                    "mapping_id": mapping.id,
                }
            )
    return {
        "mappings": bindings,
        "document_sha256": evidence["document_sha256"],
        "metadata_parser": evidence["metadata_parser"],
        "staged": True,
    }
