"""Atomic source-only MyBroker Preview -> Apply and authoritative readback.

The append-only document ledger owns source occurrences. Economic identities
and their monotonic projections are reduced from that ledger, never from row
ordinals or financial payout tables. S1 does not attest portfolio completeness.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    Account,
    AccountPerformanceScopeMembership,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    BrokerIdentityMapping,
    ClassNoCrossingCoverage,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.statement_import.mybroker import (
    PARSER,
    PROVIDER,
    MyBrokerError,
    canonical,
    digest,
    parse_mybroker,
)


def _imports(session: Session) -> list[MyBrokerImport]:
    return list(session.scalars(select(MyBrokerImport).order_by(MyBrokerImport.id)))


def _material(trade: dict) -> dict:
    return {
        key: value
        for key, value in trade.items()
        if key not in {"section", "ordinal", "cash_available", "blockers"}
    }


def _crosses_cutoff(trade: dict, start: str, end: str) -> bool:
    traded = trade["core"]["trade_time"][:10]
    if traded > end:
        return False
    if trade["state"] == "pending":
        return True
    return any(
        traded <= cutoff
        and any(
            trade[field] is None or trade[field] > cutoff
            for field in ("settlement_date", "depo_settlement_date")
        )
        for cutoff in (start, end)
    )


def _reduce(documents: list[dict]) -> tuple[dict[str, dict], list[str]]:
    trades = {}
    origins = {}
    conflicts = []
    for document in documents:
        current = {}
        for trade in document["trades"]:
            if trade["identity"] is None:
                continue
            identity = trade["identity"]
            previous = current.get(identity) or trades.get(identity)
            if previous is not None:
                if previous["core"] != trade["core"]:
                    conflicts.append("immutable_trade_conflict")
                elif previous["state"] == "settled" and trade["state"] == "pending":
                    conflicts.append("settled_to_pending_conflict")
                elif previous["state"] == trade["state"] and _material(previous) != _material(
                    trade
                ):
                    conflicts.append("trade_material_conflict")
            current[identity] = trade
        # Pending disappearance is evaluated per account and confirmed report range.
        accounts = set(document["source_accounts"])
        for identity, previous in trades.items():
            if (
                previous["state"] == "pending"
                and (
                    previous["core"]["source_account"] in accounts
                    or origins[identity] == document["filename_account"]
                )
                and document["covered_from"]
                <= previous["core"]["trade_time"][:10]
                <= document["covered_to"]
                and identity not in current
            ):
                conflicts.append("pending_disappeared")
        trades.update(current)
        origins.update({identity: document["filename_account"] for identity in current})
    return trades, sorted(set(conflicts))


def _attach_cash(document: dict, prior: dict[str, dict]) -> list[str]:
    blockers = []
    candidates = dict(prior)
    candidates.update({t["identity"]: t for t in document["trades"] if t["identity"]})
    incomplete = [t for t in document["trades"] if not t["identity"] and t["ids"]]
    for trade in document["trades"]:
        trade["cash_legs"] = []
    for row in document["money"]:
        if row["kind"] == "unsupported":
            blockers.append("money_semantics_unsupported")
            continue
        matches = [
            identity
            for identity, trade in candidates.items()
            if trade["core"]["source_account"] == row["source_account"]
            and trade["ids"][0] == row["primary_id"]
        ]
        matches.extend(
            None
            for trade in incomplete
            if trade["core"]["source_account"] == row["source_account"]
            and trade["ids"][0] == row["primary_id"]
        )
        row["trade_identity"] = matches[0] if len(matches) == 1 else None
        if len(matches) != 1:
            blockers.append("money_link_ambiguous" if matches else "money_link_missing")
        elif matches[0] is None:
            blockers.append("money_link_incomplete_identity")
        for trade in document["trades"]:
            if len(matches) == 1 and trade["identity"] == matches[0]:
                trade["cash_legs"].append(
                    {key: row[key] for key in ("kind", "date", "amount", "currency")}
                )
    for trade in document["trades"]:
        legs = trade["cash_legs"]
        legs.sort(key=canonical)
        reasons = []
        if trade["identity"] is None:
            reasons.append("trade_ids_incomplete")
        if trade["state"] == "pending":
            reasons.append("pending_not_cash")
        settlement = [leg for leg in legs if leg["kind"] == "settlement"]
        commission = [leg for leg in legs if leg["kind"] == "commission"]
        if len(settlement) != 1:
            reasons.append("settlement_cash_missing_or_ambiguous")
        else:
            qty = Decimal(trade["core"]["quantity"])
            cash = Decimal(settlement[0]["amount"])
            if qty * cash >= 0:
                reasons.append("trade_cash_direction_conflict")
            if (
                settlement[0]["currency"] != trade["core"]["currency"]
                or settlement[0]["date"] != trade["settlement_date"]
            ):
                reasons.append("settlement_cash_conflict")
        # No commission embedding convention was supplied. Preserve, never count twice.
        if trade["bank_commission"] is None:
            reasons.append("commission_missing")
        elif commission or Decimal(trade["bank_commission"]):
            reasons.append("commission_basis_unresolved")
        if trade["repo_observed"]:
            reasons.append("repo_semantics_unsupported")
        if trade["core"]["currency"] != "RUB":
            reasons.append("currency_unsupported")
        trade["cash_available"] = not reasons
        trade["blockers"] = reasons
        blockers.extend(reasons)
    return blockers


def _state(session: Session) -> tuple[dict, list[BrokerIdentityMapping]]:
    mappings = list(
        session.scalars(
            select(BrokerIdentityMapping)
            .where(BrokerIdentityMapping.provider == PROVIDER)
            .order_by(BrokerIdentityMapping.id)
        )
    )
    # Bind reconciliation to the authoritative facts and all mapping lifecycle revisions.
    state = {
        "mappings": [
            [
                m.id,
                m.subject_kind,
                m.provider_identity,
                m.hermes_target_id,
                m.status,
                m.observed_isin,
                str(m.revoked_at),
                m.predecessor_mapping_id,
                m.successor_mapping_id,
            ]
            for m in mappings
        ]
    }
    for model, fields in (
        (Account, ("id", "account_type", "status", "include_in_returns")),
        (Instrument, ("id", "isin")),
        (ReportingMonth, ("id", "status", "snapshot_date")),
        (
            PositionSnapshot,
            (
                "id",
                "reporting_month_id",
                "account_id",
                "instrument_id",
                "quantity",
                "historical_instrument_type",
                "market_value_kopecks",
            ),
        ),
        (
            InvestmentCashFlow,
            (
                "id",
                "reporting_month_id",
                "account_id",
                "instrument_id",
                "event_date",
                "gross_amount_kopecks",
                "tax_amount_kopecks",
                "commission_amount_kopecks",
                "net_amount_kopecks",
                "flow_type",
                "currency",
                "source",
            ),
        ),
        (
            AppliedStatementEvent,
            ("id", "status", "material_fingerprint", "investment_cash_flow_id", "document_sha256"),
        ),
        (AppliedStatementEventRevision, ("id", "applied_statement_event_id", "revision_kind")),
        (
            AccountPerformanceScopeMembership,
            ("id", "account_id", "effective_from", "effective_to", "include_in_returns"),
        ),
        (
            ClassNoCrossingCoverage,
            (
                "id",
                "covered_from",
                "covered_to",
                "coverage_state",
                "revision",
                "material_signature",
            ),
        ),
        (MyBrokerImport, ("id", "document_sha256", "confirmation_digest")),
    ):
        state[model.__tablename__] = [
            [str(getattr(row, field)) for field in fields]
            for row in session.scalars(select(model).order_by(model.id))
        ]
    return state, mappings


def _prepare(session: Session, document: dict) -> dict:
    state, registry = _state(session)
    accounts = sorted(
        {document["filename_account"]}
        | {p["source_account"] for p in document["positions"]}
        | {t["core"]["source_account"] for t in document["trades"]}
        | {m["source_account"] for m in document["money"]}
    )
    # Filename identity and acc_code require separate explicit mappings; no suffix
    # guessing. This also lets a quiet report retain confirmed source-only coverage.
    document["source_accounts"] = accounts
    instruments = sorted(
        {p["isin"] for p in document["positions"]} | {t["core"]["isin"] for t in document["trades"]}
    )
    bindings = []
    missing = []
    for kind, identities in (("account", accounts), ("instrument", instruments)):
        for identity in identities:
            matches = [
                m
                for m in registry
                if m.status == "effective"
                and m.subject_kind == kind
                and m.provider_identity == identity
            ]
            if len(matches) == 1:
                mapping = matches[0]
                if kind == "instrument":
                    target = session.get(Instrument, mapping.hermes_target_id)
                    if target is None or target.isin not in (None, identity):
                        missing.append({"kind": kind, "identity": identity})
                        continue
                bindings.append(
                    {
                        "kind": kind,
                        "identity": identity,
                        "mapping_id": mapping.id,
                        "hermes_id": mapping.hermes_target_id,
                    }
                )
            else:
                missing.append({"kind": kind, "identity": identity})
    imports = _imports(session)
    prior_documents = [json.loads(row.normalized_json) for row in imports]
    prior, _ = _reduce(prior_documents)
    blockers = list(document["syntax_blockers"])
    blockers.extend(_attach_cash(document, prior))
    if not accounts:
        blockers.append("source_account_unobserved")
    if any(
        Decimal(p["actual_quantity"]) != Decimal(p["forward_quantity"])
        for p in document["positions"]
    ):
        blockers.append("endpoint_unsettled")
    same = next(
        (row for row in imports if row.document_sha256 == document["document_sha256"]), None
    )
    conflicts = []
    if same:
        old = json.loads(same.normalized_json)
        if any(
            old[key] != document[key]
            for key in ("covered_from", "covered_to", "filename_account", "parser")
        ):
            conflicts.append("document_coverage_conflict")
        if json.loads(same.mappings_json) != bindings:
            conflicts.append("accepted_mapping_conflict")
    else:
        _, conflicts = _reduce(prior_documents + [document])
        # A new second native ID must not make an already accepted primary-only
        # cash linkage ambiguous. Revalidate stored links against the full union.
        union = dict(prior)
        union.update({t["identity"]: t for t in document["trades"] if t["identity"]})
        for previous_document in prior_documents:
            for money in previous_document["money"]:
                if (
                    money.get("trade_identity")
                    and sum(
                        trade["core"]["source_account"] == money["source_account"]
                        and trade["ids"][0] == money["primary_id"]
                        for trade in union.values()
                    )
                    > 1
                ):
                    conflicts.append("money_link_ambiguous")
    if "money_link_ambiguous" in blockers:
        conflicts.append("money_link_ambiguous")
    # Unknown historical class prevents safe narrowing of contradictory evidence.
    material = bool(document["trades"] or document["money"] or blockers)
    if not same and material:
        complete = session.scalars(
            select(ClassNoCrossingCoverage).where(
                ClassNoCrossingCoverage.coverage_state == "complete"
            )
        )
        if any(
            (
                coverage.covered_to.isoformat() >= document["covered_from"]
                and coverage.covered_from.isoformat() <= document["covered_to"]
            )
            or any(
                _crosses_cutoff(
                    t, coverage.covered_from.isoformat(), coverage.covered_to.isoformat()
                )
                for t in document["trades"]
            )
            for coverage in complete
        ):
            conflicts.append("accepted_class_coverage_requires_reconciliation")
    account_targets = {b["identity"]: b["hermes_id"] for b in bindings if b["kind"] == "account"}
    instrument_targets = {
        b["identity"]: b["hermes_id"] for b in bindings if b["kind"] == "instrument"
    }
    for position in document["positions"]:
        accepted = session.scalars(
            select(PositionSnapshot)
            .join(ReportingMonth)
            .where(
                ReportingMonth.snapshot_date == date.fromisoformat(document["covered_to"]),
                PositionSnapshot.account_id == account_targets.get(position["source_account"], -1),
                PositionSnapshot.instrument_id == instrument_targets.get(position["isin"], -1),
            )
        )
        if any(row.quantity != Decimal(position["actual_quantity"]) for row in accepted):
            conflicts.append("accepted_endpoint_quantity_conflict")
    confirmation = digest({"document": document, "bindings": bindings, "state": state})
    return {
        "document": document,
        "mappings": bindings,
        "missing_mappings": missing,
        "conflicts": sorted(set(conflicts)),
        "blockers": sorted(set(blockers)),
        "confirmation_digest": confirmation,
        "already_imported": same.id if same else None,
        "coverage_state": "unknown",
        "can_apply": not missing and not conflicts,
    }


def preview_mybroker(session: Session, *, document: bytes, filename: str) -> dict:
    parsed = parse_mybroker(document, filename)
    with coherent_read_snapshot(session):
        return _prepare(session, parsed)


def read_mybroker_import(session: Session, import_id: int) -> dict:
    with coherent_read_snapshot(session):
        row = session.get(MyBrokerImport, import_id, populate_existing=True)
        if row is None:
            raise MyBrokerError("import_not_found")
        return {
            "import_id": row.id,
            "document": json.loads(row.normalized_json),
            "mappings": json.loads(row.mappings_json),
            "coverage_state": "unknown",
            "confirmation_digest": row.confirmation_digest,
        }


def apply_mybroker(
    session: Session,
    *,
    document: bytes,
    filename: str,
    confirmation_digest: str,
    confirmed_range: tuple[str, str],
    confirmed_mappings: list[dict],
) -> dict:
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    parsed = parse_mybroker(document, filename)  # authoritative bytes, never browser rows
    session.rollback()
    try:
        # A no-op UPDATE reserves SQLite's single writer even when the ledger is empty.
        # Hold it through authoritative planning and commit; Close/remap cannot interleave.
        session.execute(
            update(MyBrokerImport).where(MyBrokerImport.id == -1).values(id=MyBrokerImport.id)
        )
        session.expire_all()
        preview = _prepare(session, parsed)
        if (
            confirmation_digest != preview["confirmation_digest"]
            or list(confirmed_range) != [parsed["covered_from"], parsed["covered_to"]]
            or confirmed_mappings != preview["mappings"]
        ):
            raise MyBrokerError("preview_stale")
        if not preview["can_apply"]:
            raise MyBrokerError("reconciliation_required")
        import_id = preview["already_imported"]
        if import_id is None:
            row = MyBrokerImport(
                document_sha256=parsed["document_sha256"],
                covered_from=date.fromisoformat(parsed["covered_from"]),
                covered_to=date.fromisoformat(parsed["covered_to"]),
                parser_version=PARSER,
                confirmation_digest=confirmation_digest,
                normalized_json=canonical(parsed),
                mappings_json=canonical(preview["mappings"]),
                accepted_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            import_id = row.id
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {
        **read_mybroker_import(session, import_id),
        "duplicate": preview["already_imported"] is not None,
    }


def read_mybroker_lineage(session: Session) -> dict:
    with coherent_read_snapshot(session):
        rows = _imports(session)
        documents = [json.loads(row.normalized_json) for row in rows]
        trades, conflicts = _reduce(documents)
        ranges = []
        for row, document in zip(rows, documents, strict=True):
            for mapping in json.loads(row.mappings_json):
                if mapping["kind"] == "account":
                    ranges.append(
                        {
                            "import_id": row.id,
                            "source_account": mapping["identity"],
                            "hermes_account_id": mapping["hermes_id"],
                            "covered_from": document["covered_from"],
                            "covered_to": document["covered_to"],
                        }
                    )
    return {
        "provider": PROVIDER,
        "trades": list(trades.values()),
        "source_ranges": ranges,
        "conflicts": conflicts,
        "coverage_state": "unknown",
    }


def unresolved_class_source_ids(
    session: Session, account_ids: tuple[int, ...], start: date, end: date
) -> list[int]:
    """S1 has no event-C1: source evidence cannot silently support no-crossing.

    Use accepted explicit account bindings and the caller's historical universe,
    never current flags/catalogue class. Quiet reports do not prove inventory zero.
    """
    ids = set()
    rows = _imports(session)
    documents = [json.loads(row.normalized_json) for row in rows]
    trades, _ = _reduce(documents)
    for row, document in zip(rows, documents, strict=True):
        bindings = json.loads(row.mappings_json)
        if not any(b["kind"] == "account" and b["hermes_id"] in account_ids for b in bindings):
            continue
        if (
            row.covered_to >= start
            and row.covered_from <= end
            and (
                document["trades"]
                or document["money"]
                or document["syntax_blockers"]
                or any(
                    Decimal(p["actual_quantity"]) != Decimal(p["forward_quantity"])
                    for p in document["positions"]
                )
            )
        ):
            ids.add(row.id)
        # A pending identity survives its report range until an explicit settled
        # occurrence resolves it. Planned dates never prove settlement. Also
        # inspect actual settlement/depo cutoffs of settled source occurrences.
        for occurrence in document["trades"]:
            identity = occurrence["identity"]
            trade = trades.get(identity) if identity else occurrence
            if _crosses_cutoff(trade, start.isoformat(), end.isoformat()):
                ids.add(row.id)
    return sorted(ids)
