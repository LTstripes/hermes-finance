"""Atomic source-only MyBroker Preview -> Apply and authoritative readback.

The append-only document ledger owns source occurrences. Economic identities
and their monotonic projections are reduced from that ledger, never from row
ordinals or financial payout tables. S1 does not attest portfolio completeness.
"""

from __future__ import annotations

import json
from collections import defaultdict
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
    MyBrokerDispositionApply,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.mybroker_dispositions import (
    counts,
    effective_bindings,
    impact,
    initial_accept,
    occurrence_evidence,
    resolve,
)
from hermes_finance.services.performance_availability import _membership_at
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


# The parser's core is immutable. These source fields may be absent in a
# narrower occurrence; two present values within one state must still agree.
# Pending dates are plans, so only settled observations enrich settled evidence.
ENRICHABLE_FIELDS = (
    "settlement_date",
    "depo_settlement_date",
    "settlement_time",
    "bank_commission",
    "accrued_interest",
)


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
    """Reduce a document set by source endpoints, independently of upload order."""
    ordered = sorted(
        documents, key=lambda d: (d["covered_to"], d["covered_from"], d["document_sha256"])
    )
    observations = defaultdict(list)
    document_identities = [{t["identity"] for t in d["trades"] if t["identity"]} for d in ordered]
    for index, document in enumerate(ordered):
        for trade in document["trades"]:
            if trade["identity"]:
                observations[trade["identity"]].append((index, trade))
    trades = {}
    conflicts = set()
    for identity, occurrences in sorted(observations.items()):
        identity_conflicts = set()
        if len({canonical(t["core"]) for _, t in occurrences}) != 1:
            identity_conflicts.add("immutable_trade_conflict")
        settled = [(i, t) for i, t in occurrences if t["state"] == "settled"]
        pending = [(i, t) for i, t in occurrences if t["state"] == "pending"]
        for index, trade in pending:
            origin = ordered[index]
            # Equal endpoints give no source order, even if covered_from differs.
            if any(ordered[i]["covered_to"] <= origin["covered_to"] for i, _ in settled):
                identity_conflicts.add("settled_to_pending_conflict")
            # Check absence against every overlapping document, including those
            # earlier in source chronology and those uploaded before this one.
            for other_index, other in enumerate(ordered):
                if (
                    other_index != index
                    and (
                        trade["core"]["source_account"] in other["source_accounts"]
                        or origin["filename_account"] == other["filename_account"]
                    )
                    and other["covered_from"]
                    <= trade["core"]["trade_time"][:10]
                    <= other["covered_to"]
                    and identity not in document_identities[other_index]
                ):
                    identity_conflicts.add("pending_disappeared")
        for state_occurrences in (pending, settled):
            for field in ENRICHABLE_FIELDS:
                if len({t[field] for _, t in state_occurrences if t[field] is not None}) > 1:
                    identity_conflicts.add("trade_material_conflict")
            # Visibility of a money row is occurrence lineage, but disagreement
            # between two present sets of legs of the same kind is material.
            for kind in ("settlement", "commission"):
                present = {
                    canonical(sorted(legs, key=canonical))
                    for _, t in state_occurrences
                    if (legs := [leg for leg in t.get("cash_legs", []) if leg["kind"] == kind])
                }
                if len(present) > 1:
                    identity_conflicts.add("trade_material_conflict")
        chosen = settled or pending
        chosen = sorted(chosen, key=lambda item: (item[0], canonical(item[1])))
        # Copy: projection enrichment must never rewrite occurrence lineage.
        result = json.loads(canonical(chosen[-1][1]))
        for field in ENRICHABLE_FIELDS:
            present = [t[field] for _, t in chosen if t[field] is not None]
            result[field] = present[-1] if present else None
        result["repo_observed"] = any(t["repo_observed"] for _, t in occurrences)
        result["cash_legs"] = []
        for kind in ("settlement", "commission"):
            present = [
                legs
                for _, t in chosen
                if (legs := [leg for leg in t.get("cash_legs", []) if leg["kind"] == kind])
            ]
            if present:
                result["cash_legs"].extend(json.loads(canonical(present[-1])))
        result["cash_legs"].sort(key=canonical)
        result["blockers"] = _cash_reasons(result) + sorted(identity_conflicts)
        result["cash_available"] = not result["blockers"]
        trades[identity] = result
        conflicts.update(identity_conflicts)
    return trades, sorted(conflicts)


def _cash_reasons(trade: dict) -> list[str]:
    legs = trade["cash_legs"]
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
    return reasons


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
            if len(matches) == 1 and matches[0] is not None and trade["identity"] == matches[0]:
                trade["cash_legs"].append(
                    {key: row[key] for key in ("kind", "date", "amount", "currency")}
                )
    for trade in document["trades"]:
        trade["cash_legs"].sort(key=canonical)
        reasons = _cash_reasons(trade)
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


def _historical_bound_accounts(
    session: Session, bindings: list[dict], start: date, end: date
) -> tuple[int, ...]:
    rows = defaultdict(list)
    targets = {b["hermes_id"] for b in bindings if b["kind"] == "account"}
    for row in session.scalars(
        select(AccountPerformanceScopeMembership).where(
            AccountPerformanceScopeMembership.account_id.in_(targets)
        )
    ):
        rows[row.account_id].append(row)
    return tuple(
        account
        for account in sorted(targets)
        if _membership_at(rows[account], start) is True
        and _membership_at(rows[account], end) is True
    )


def _source_affects_interval(
    document: dict,
    bindings: list[dict],
    account_ids: tuple[int, ...],
    start: date,
    end: date,
    trades: dict[str, dict],
    skipped_isins: tuple[str, ...] = (),
) -> bool:
    # No source event-C1 exists in S1. An in-universe source event can affect any
    # class; neither today's catalogue nor a snapshot labels that trade's C1.
    accounts = {
        b["identity"] for b in bindings if b["kind"] == "account" and b["hermes_id"] in account_ids
    }
    if not accounts:
        return False
    # Excluded inventory/activity has no accepted lifetime proof in bounded v1.
    if any(
        p["isin"] in skipped_isins and p["source_account"] in accounts
        for p in document["positions"]
    ) or any(
        t["core"]["isin"] in skipped_isins and t["core"]["source_account"] in accounts
        for t in document["trades"]
    ):
        return True
    start_day, end_day = start.isoformat(), end.isoformat()
    relevant_trades = [t for t in document["trades"] if t["core"]["source_account"] in accounts]
    if document["covered_to"] >= start_day and document["covered_from"] <= end_day:
        if (
            relevant_trades
            or any(m["source_account"] in accounts for m in document["money"])
            or document["syntax_blockers"]
            or any(
                p["source_account"] in accounts
                and Decimal(p["actual_quantity"]) != Decimal(p["forward_quantity"])
                for p in document["positions"]
            )
        ):
            return True
    return any(
        _crosses_cutoff(projection := trades.get(t["identity"], t), start_day, end_day)
        or (
            t["core"]["trade_time"][:10] <= end_day
            and set(projection.get("blockers", [])).intersection(
                {
                    "immutable_trade_conflict",
                    "trade_material_conflict",
                    "pending_disappeared",
                    "settled_to_pending_conflict",
                }
            )
        )
        for t in relevant_trades
    )


def _prepare(
    session: Session,
    document: dict,
    skipped_isins: tuple[str, ...] = (),
    owner_reviewed: bool = False,
) -> dict:
    state, registry = _state(session)
    accounts = sorted(
        {document["filename_account"]}
        | {p["source_account"] for p in document["positions"]}
        | {r["source_account"] for r in document["rub_money"]}
        | {t["core"]["source_account"] for t in document["trades"]}
        | {m["source_account"] for m in document["money"]}
    )
    # Filename identity and acc_code require separate explicit mappings; no suffix
    # guessing. This also lets a quiet report retain confirmed source-only coverage.
    document["source_accounts"] = accounts
    instruments = sorted(
        {p["isin"] for p in document["positions"]} | {t["core"]["isin"] for t in document["trades"]}
    )
    if len(set(skipped_isins)) != len(skipped_isins) or set(skipped_isins) - set(instruments):
        raise MyBrokerError("instrument_decision_invalid")
    if skipped_isins and not owner_reviewed:
        raise MyBrokerError("skip_owner_review_required")
    bindings = []
    missing = []
    decision_conflicts = []
    reconciliation_instruments = {}
    for kind, identities in (("account", accounts), ("instrument", instruments)):
        for identity in identities:
            matches = [
                m
                for m in registry
                if m.status == "effective"
                and m.subject_kind == kind
                and m.provider_identity == identity
            ]
            if kind == "instrument" and identity in skipped_isins:
                if len(matches) > 1:
                    decision_conflicts.append("accepted_mapping_conflict")
                if len(matches) == 1:
                    target = session.get(Instrument, matches[0].hermes_target_id)
                    if target is None or target.isin not in (None, identity):
                        decision_conflicts.append("accepted_mapping_conflict")
                    else:
                        reconciliation_instruments[identity] = target.id
                continue
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
    blockers.extend(document["endpoint_blockers"])
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
    conflicts = list(document["endpoint_conflicts"]) + decision_conflicts
    # An overlapping occurrence is not a correction route. Keep both source
    # acceptance and downstream projection closed to mixed economic support.
    incoming_trades = {
        t["identity"]: t["core"]["isin"] in skipped_isins
        for t in document["trades"]
        if t["identity"]
    }

    def position_support(doc, exclusions):
        support = {}
        for p in doc["positions"]:
            days = [doc["covered_to"]]
            if (
                p.get("beginning_actual_quantity") is not None
                or p.get("beginning_value") is not None
            ):
                days.append(date.fromisoformat(doc["covered_from"]).toordinal() - 1)
            for day in days:
                cutoff = date.fromordinal(day).isoformat() if isinstance(day, int) else day
                support[p["source_account"], p["isin"], cutoff] = p["isin"] in exclusions
        return support

    incoming_positions = position_support(document, skipped_isins)
    for source, previous_document in zip(imports, prior_documents, strict=True):
        excluded = {i["isin"] for i in resolve(session, source) if i["effective_state"] != "mapped"}
        if any(
            t["identity"] in incoming_trades
            and incoming_trades[t["identity"]] != (t["core"]["isin"] in excluded)
            for t in previous_document["trades"]
            if t["identity"]
        ) or any(
            key in incoming_positions and incoming_positions[key] != skipped
            for key, skipped in position_support(previous_document, excluded).items()
        ):
            conflicts.append("instrument_disposition_reconciliation_required")
    reduced, reduction_conflicts = _reduce(prior_documents + [document])
    if same:
        accepted_skips = sorted(i["isin"] for i in resolve(session, same))
        if accepted_skips != sorted(skipped_isins):
            conflicts.append("instrument_disposition_reconciliation_required")
        elif any(i["effective_state"] != "accepted" for i in resolve(session, same)):
            conflicts.append("instrument_disposition_reconciliation_required")
        old = json.loads(same.normalized_json)
        # A changed parser shape cannot silently reinterpret an accepted document.
        if old["parser"] != document["parser"]:
            conflicts.append("accepted_parser_version_conflict")
        if any(
            old[key] != document[key] for key in ("covered_from", "covered_to", "filename_account")
        ):
            conflicts.append("document_coverage_conflict")
        if json.loads(same.mappings_json) != bindings:
            conflicts.append("accepted_mapping_conflict")
    else:
        conflicts.extend(reduction_conflicts)
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
    if not same:
        complete = session.scalars(
            select(ClassNoCrossingCoverage).where(
                ClassNoCrossingCoverage.coverage_state == "complete"
            )
        )
        if any(
            _source_affects_interval(
                document,
                bindings,
                _historical_bound_accounts(
                    session, bindings, coverage.covered_from, coverage.covered_to
                ),
                coverage.covered_from,
                coverage.covered_to,
                reduced,
                skipped_isins,
            )
            for coverage in complete
        ):
            conflicts.append("accepted_class_coverage_requires_reconciliation")
    account_targets = {b["identity"]: b["hermes_id"] for b in bindings if b["kind"] == "account"}
    instrument_targets = {
        b["identity"]: b["hermes_id"] for b in bindings if b["kind"] == "instrument"
    }
    # Skip removes projection authority, never existing reconciliation guards.
    instrument_targets.update(reconciliation_instruments)
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
    # Preserve exact legacy confirmation material when there are no exclusions.
    material = {"document": document, "bindings": bindings, "state": state}
    decisions = [occurrence_evidence(document, bindings, isin) for isin in sorted(skipped_isins)]
    existing_impact = impact(session, [b["hermes_id"] for b in bindings if b["kind"] == "account"])
    if decisions or existing_impact:
        material["instrument_dispositions"] = decisions
        material["disposition_state"] = existing_impact
    confirmation = digest(material)
    return {
        "document": document,
        "mappings": bindings,
        "missing_mappings": missing,
        "instrument_choices": [
            {
                "isin": isin,
                "choice": "skip"
                if isin in skipped_isins
                else "map"
                if any(b["kind"] == "instrument" and b["identity"] == isin for b in bindings)
                else "undecided",
            }
            for isin in instruments
        ],
        "instrument_dispositions": decisions,
        "counts": counts(document, bindings, skipped_isins),
        "conflicts": sorted(set(conflicts)),
        "blockers": sorted(set(blockers)),
        "confirmation_digest": confirmation,
        "already_imported": same.id if same else None,
        "coverage_state": "unknown",
        "can_apply": not missing and not conflicts,
    }


def preview_mybroker(
    session: Session,
    *,
    document: bytes,
    filename: str,
    skipped_isins: tuple[str, ...] = (),
    owner_reviewed: bool = False,
) -> dict:
    parsed = parse_mybroker(document, filename)
    with coherent_read_snapshot(session):
        return _prepare(session, parsed, skipped_isins, owner_reviewed)


def read_mybroker_import(session: Session, import_id: int) -> dict:
    with coherent_read_snapshot(session):
        row = session.get(MyBrokerImport, import_id, populate_existing=True)
        if row is None:
            raise MyBrokerError("import_not_found")
        dispositions = resolve(session, row)
        document = json.loads(row.normalized_json)
        instruments = sorted(
            {p["isin"] for p in document["positions"]}
            | {t["core"]["isin"] for t in document["trades"]}
        )
        return {
            "instrument_dispositions": dispositions,
            "instrument_choices": [
                {
                    "isin": isin,
                    "choice": "skip" if any(i["isin"] == isin for i in dispositions) else "map",
                }
                for isin in instruments
            ],
            "counts": counts(
                document,
                effective_bindings(session, row),
                [i for i in dispositions if i["effective_state"] != "mapped"],
            ),
            "import_id": row.id,
            "document": json.loads(row.normalized_json),
            "mappings": json.loads(row.mappings_json),
            **(
                {"effective_mappings": effective_bindings(session, row)}
                if any("correction" in i for i in dispositions)
                else {}
            ),
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
    skipped_isins: tuple[str, ...] = (),
    owner_reviewed: bool = False,
    request_id: str | None = None,
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
        intent_digest = digest(
            [
                parsed["document_sha256"],
                [parsed["covered_from"], parsed["covered_to"], parsed["filename_account"]],
                list(confirmed_range),
                confirmed_mappings,
                sorted(skipped_isins),
                owner_reviewed,
            ]
        )
        if skipped_isins and not request_id:
            raise MyBrokerError("skip_request_id_required")
        receipt = session.get(MyBrokerDispositionApply, request_id) if request_id else None
        if receipt:
            if (
                receipt.intent_digest != intent_digest
                or receipt.confirmation_digest != confirmation_digest
            ):
                raise MyBrokerError("idempotency_conflict")
            session.rollback()
            return {
                **read_mybroker_import(session, receipt.import_id),
                "duplicate": True,
                "committed_revision_ids": json.loads(receipt.revision_ids_json),
            }
        preview = _prepare(session, parsed, skipped_isins, owner_reviewed)
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
            if skipped_isins:
                revision_ids = initial_accept(session, row, skipped_isins, confirmation_digest)
        if skipped_isins:
            if preview["already_imported"] is not None:
                revision_ids = [
                    i["revision_id"]
                    for i in resolve(session, session.get(MyBrokerImport, import_id))
                ]
            session.add(
                MyBrokerDispositionApply(
                    request_id=request_id,
                    import_id=import_id,
                    intent_digest=intent_digest,
                    confirmation_digest=confirmation_digest,
                    revision_ids_json=canonical(revision_ids),
                )
            )
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
            "instrument_dispositions": [i for row in rows for i in resolve(session, row)],
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
    ids = {i["import_id"] for i in impact(session, account_ids)}
    rows = _imports(session)
    documents = [json.loads(row.normalized_json) for row in rows]
    trades, _ = _reduce(documents)
    for row, document in zip(rows, documents, strict=True):
        bindings = json.loads(row.mappings_json)
        if _source_affects_interval(document, bindings, account_ids, start, end, trades):
            ids.add(row.id)
    return sorted(ids)
