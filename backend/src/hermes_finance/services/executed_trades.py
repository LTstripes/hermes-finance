"""S2-A source -> canonical execution. No financial projections or S2-B writes.

Only accepted S1 occurrences are candidates. Every Preview, Apply and read uses
the full source union; accepted bindings/core are frozen, never last-upload-wins.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import (
    ClassNoCrossingCoverage,
    ExecutedTrade,
    ExecutedTradeApply,
    ExecutedTradeOccurrence,
    ExecutedTradeRevision,
    Instrument,
)
from hermes_finance.services.mybroker_import import (
    _historical_bound_accounts,
    _imports,
    _reduce,
    _source_affects_interval,
    _state,
)
from hermes_finance.statement_import.mybroker import PROVIDER, MyBrokerError, canonical, digest


def _minor(value: str) -> int:
    # S1 permits 48-digit exact decimals. Avoid ambient Decimal precision loss.
    with localcontext() as context:
        context.prec = 100
        amount = int((Decimal(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if abs(amount) > 2**63 - 1:
        raise MyBrokerError("money_out_of_range")
    return amount


def _rows(session: Session, model) -> list:
    return list(session.scalars(select(model).order_by(model.id)))


def _context(session: Session) -> dict:
    imports = _imports(session)
    documents = [json.loads(row.normalized_json) for row in imports]
    projections, _ = _reduce(documents)
    state, registry = _state(session)
    state["source_material"] = [
        [row.id, row.parser_version, row.normalized_json, row.mappings_json] for row in imports
    ]
    for model in (ExecutedTrade, ExecutedTradeOccurrence, ExecutedTradeRevision):
        state[model.__tablename__] = [
            [str(getattr(row, column.name)) for column in model.__table__.columns]
            for row in _rows(session, model)
        ]
    return {
        "imports": imports,
        "documents": documents,
        "projections": projections,
        "state": state,
        "registry": registry,
        "trades": {t.source_identity: t for t in _rows(session, ExecutedTrade)},
        "revisions": _rows(session, ExecutedTradeRevision),
        "occurrences": _rows(session, ExecutedTradeOccurrence),
    }


def _latest(context: dict, trade_id: int) -> ExecutedTradeRevision | None:
    return max(
        (r for r in context["revisions"] if r.trade_id == trade_id),
        key=lambda r: r.revision,
        default=None,
    )


def _candidate(session: Session, context: dict, identity: str) -> dict:
    source = context["projections"].get(identity)
    if source is None:
        raise MyBrokerError("source_trade_not_found")
    conflicts = set(source["blockers"]) & {
        "immutable_trade_conflict",
        "trade_material_conflict",
        "settled_to_pending_conflict",
        "pending_disappeared",
    }
    occurrences = []
    bindings = []
    money = defaultdict(list)
    for row, document in zip(context["imports"], context["documents"], strict=True):
        matching = [t for t in document["trades"] if t["identity"] == identity]
        for trade in matching:
            occurrences.append(
                {
                    "import_id": row.id,
                    "section": trade["section"],
                    "ordinal": trade["ordinal"],
                    "source_fingerprint": digest(trade),
                    "document_sha256": row.document_sha256,
                    "parser": row.parser_version,
                    "covered_from": document["covered_from"],
                    "covered_to": document["covered_to"],
                }
            )
        if matching:
            required = [
                ("account", source["core"]["source_account"]),
                ("instrument", source["core"]["isin"]),
            ]
            stored = json.loads(row.mappings_json)
            selected = [b for b in stored if (b["kind"], b["identity"]) in required]
            if len(selected) != 2:
                conflicts.add("accepted_mapping_conflict")
            bindings.append(sorted(selected, key=canonical))
        for leg in document["money"]:
            if leg.get("trade_identity") != identity:
                continue
            # Revalidate primary-only linkage against the entire accepted union,
            # including incomplete identities; stored linkage is never authority.
            candidates = {
                t["identity"]
                for d in context["documents"]
                for t in d["trades"]
                if t["core"]["source_account"] == leg["source_account"]
                and t["ids"]
                and t["ids"][0] == leg["primary_id"]
            }
            if candidates != {identity}:
                conflicts.add("money_link_ambiguous")
            if leg["kind"] in ("settlement", "commission"):
                material = {k: leg[k] for k in ("kind", "date", "amount", "currency")}
                money[canonical(material)].append(
                    {
                        "import_id": row.id,
                        "ordinal": leg["ordinal"],
                        "source_fingerprint": digest(leg),
                    }
                )
    if len({canonical(b) for b in bindings}) != 1:
        conflicts.add("accepted_mapping_conflict")
    accepted_bindings = bindings[0] if bindings else []
    for binding in accepted_bindings:
        current = [
            m
            for m in context["registry"]
            if m.status == "effective"
            and m.subject_kind == binding["kind"]
            and m.provider_identity == binding["identity"]
        ]
        if (
            len(current) != 1
            or current[0].id != binding["mapping_id"]
            or (current[0].hermes_target_id != binding["hermes_id"])
        ):
            conflicts.add("accepted_mapping_conflict")
        if binding["kind"] == "instrument":
            target = session.get(Instrument, binding["hermes_id"])
            if target is None or target.isin not in (None, binding["identity"]):
                conflicts.add("accepted_mapping_conflict")
    prior = context["trades"].get(identity)
    latest = _latest(context, prior.id) if prior else None
    if prior:
        if prior.core_json != canonical(source["core"]):
            conflicts.add("immutable_trade_conflict")
        if prior.bindings_json != canonical(accepted_bindings):
            conflicts.add("accepted_mapping_conflict")
        if latest is None or latest.acceptance_state != "active":
            conflicts.add("reconciliation_required")
    actual = source["state"] == "settled"
    legs = []
    leg_groups = defaultdict(list)
    for material, provenance in sorted(money.items()):
        leg = json.loads(material)
        leg_groups[leg["kind"]].append(leg)
        signed = Decimal(leg["amount"])
        legs.append(
            {
                "role": leg["kind"],
                "source_account": source["core"]["source_account"],
                "effective_date": leg["date"],
                "currency": leg["currency"],
                "amount_minor": abs(_minor(leg["amount"])) if leg["currency"] == "RUB" else None,
                "direction": ("debit" if signed < 0 else "credit") if signed else None,
                "source_amount": leg["amount"],
                "occurrences": provenance,
            }
        )
    settlement_reasons = []
    if not actual:
        settlement_reasons.append("pending_not_cash")
    if not actual or not source["settlement_date"] or not source["depo_settlement_date"]:
        settlement_reasons.append("actual_settlement_missing")
    settlements = leg_groups["settlement"]
    if len(settlements) != 1:
        settlement_reasons.append("settlement_cash_missing_or_ambiguous")
        if len(settlements) > 1:
            conflicts.add("trade_material_conflict")
    else:
        leg = settlements[0]
        qty, amount = Decimal(source["core"]["quantity"]), Decimal(leg["amount"])
        if not qty or not amount or (qty > 0) == (amount > 0):
            settlement_reasons.append("trade_cash_direction_conflict")
        if leg["currency"] != source["core"]["currency"] or (
            leg["date"] != source["settlement_date"]
        ):
            settlement_reasons.append("settlement_cash_conflict")
        if amount.copy_abs() != Decimal(source["core"]["trade_amount"]).copy_abs():
            settlement_reasons.append("settlement_principal_unresolved")
    commission = source["bank_commission"] if actual else None
    fee_basis = (
        "zero"
        if commission is not None and Decimal(commission) == 0 and (not leg_groups["commission"])
        else "unknown"
    )
    if len(leg_groups["commission"]) > 1:
        conflicts.add("trade_material_conflict")
    # S2-A cannot accept nonzero separation/embedding or event-C1: S2-B owns
    # explicit reconciliation. Fields stay distinct and auditable in evidence.
    evidence = {
        "lifecycle": source["state"],
        "fee_basis": fee_basis,
        "event_c1": None,
        "settlement_date": source["settlement_date"] if actual else None,
        "depo_settlement_date": source["depo_settlement_date"] if actual else None,
        "settlement_time": source["settlement_time"] if actual else None,
        "planned_dates": {k: source[k] for k in ("settlement_date", "depo_settlement_date")}
        if not actual
        else None,
        "bank_commission": commission,
        "bank_commission_minor": _minor(commission)
        if commission is not None and source["core"]["currency"] == "RUB"
        else None,
        "accrued_interest": source["accrued_interest"],
        "cash_legs": legs if actual else [],
        "occurrences": occurrences,
        "trade_amount_minor": _minor(source["core"]["trade_amount"])
        if source["core"]["currency"] == "RUB"
        else None,
        "readiness": {
            "settlement": sorted(set(settlement_reasons)),
            "commission": [] if fee_basis == "zero" else ["commission_basis_unresolved"],
            "c1": ["event_c1_missing"],
            "coverage": ["coverage_unknown"],
            "unsupported": sorted(
                set(source["blockers"]) & {"currency_unsupported", "repo_semantics_unsupported"}
            ),
        },
    }
    if latest:
        old = json.loads(latest.evidence_json)
        if old["lifecycle"] == "settled" and not actual:
            conflicts.add("settled_to_pending_conflict")
        if old["lifecycle"] == evidence["lifecycle"]:
            old_legs = {
                (leg["role"], leg["effective_date"], leg["currency"], leg["source_amount"])
                for leg in old["cash_legs"]
            }
            new_legs = {
                (leg["role"], leg["effective_date"], leg["currency"], leg["source_amount"])
                for leg in evidence["cash_legs"]
            }
            if not old_legs.issubset(new_legs):
                conflicts.add("trade_material_conflict")
            for field in (
                "settlement_date",
                "depo_settlement_date",
                "settlement_time",
                "bank_commission",
                "accrued_interest",
            ):
                if old[field] is not None and evidence[field] != old[field]:
                    conflicts.add("trade_material_conflict")
        if latest.event_c1_json is not None or latest.fee_basis in ("separate", "embedded"):
            conflicts.add("reconciliation_required")
    for coverage in session.scalars(
        select(ClassNoCrossingCoverage).where(ClassNoCrossingCoverage.coverage_state == "complete")
    ):
        accounts = _historical_bound_accounts(
            session, accepted_bindings, coverage.covered_from, coverage.covered_to
        )
        if any(
            _source_affects_interval(
                d,
                accepted_bindings,
                accounts,
                coverage.covered_from,
                coverage.covered_to,
                context["projections"],
            )
            for d in context["documents"]
            if any(t["identity"] == identity for t in d["trades"])
        ):
            conflicts.add("accepted_class_coverage_requires_reconciliation")
    material = digest({"core": source["core"], "bindings": accepted_bindings, "evidence": evidence})
    return {
        "source_identity": identity,
        "trade_id": prior.id if prior else None,
        "revision": latest.revision if latest else None,
        "core": source["core"],
        "ids": source["ids"],
        "bindings": accepted_bindings,
        "evidence": evidence,
        "material_fingerprint": material,
        "conflicts": sorted(conflicts),
        "can_apply": not conflicts,
        "action": "create"
        if prior is None
        else ("noop" if latest and latest.material_fingerprint == material else "enrich"),
        "financial_ready": False,
        "coverage_state": "unknown",
    }


def _plan(session: Session, identities: list[str]) -> dict:
    if not identities or len(identities) > 1000 or len(set(identities)) != len(identities):
        raise MyBrokerError("selection_invalid")
    context = _context(session)
    candidates = [_candidate(session, context, identity) for identity in sorted(identities)]
    return {
        "candidates": candidates,
        "can_apply": all(t["can_apply"] for t in candidates),
        "confirmation_digest": digest({"selection": candidates, "state": context["state"]}),
        "coverage_state": "unknown",
        "financial_ready": False,
    }


def preview_executed_trades(session: Session, identities: list[str]) -> dict:
    with coherent_read_snapshot(session):
        return _plan(session, identities)


def _read(session: Session, context: dict, trade: ExecutedTrade) -> dict:
    latest = _latest(context, trade.id)
    if latest is None:
        raise MyBrokerError("trade_revision_missing")
    try:
        current = _candidate(session, context, trade.source_identity)
        conflicts = current["conflicts"]
        if latest.material_fingerprint != current["material_fingerprint"]:
            conflicts = sorted(set(conflicts) | {"source_enrichment_not_accepted"})
    except MyBrokerError as error:
        conflicts = [str(error)]
    return {
        "trade_id": trade.id,
        "source_identity": trade.source_identity,
        "provider": trade.provider,
        "source_account": trade.source_account,
        "ids": [trade.primary_id, trade.secondary_id],
        "core": json.loads(trade.core_json),
        "account_id": trade.account_id,
        "instrument_id": trade.instrument_id,
        "bindings": json.loads(trade.bindings_json),
        "revision": latest.revision,
        "acceptance_state": latest.acceptance_state,
        "evidence": json.loads(latest.evidence_json),
        "conflicts": conflicts,
        "financial_ready": False,
        "coverage_state": "unknown",
        "revisions": [
            {
                "revision": r.revision,
                "material_fingerprint": r.material_fingerprint,
                "confirmation_digest": r.confirmation_digest,
                "accepted_at": r.accepted_at.isoformat(),
                "evidence": json.loads(r.evidence_json),
            }
            for r in context["revisions"]
            if r.trade_id == trade.id
        ],
    }


def read_executed_trades(session: Session, trade_ids: list[int] | None = None) -> dict:
    with coherent_read_snapshot(session):
        context = _context(session)
        trades = sorted(context["trades"].values(), key=lambda t: t.id)
        if trade_ids is not None:
            trades = [t for t in trades if t.id in trade_ids]
            if len(trades) != len(set(trade_ids)):
                raise MyBrokerError("trade_not_found")
        return {
            "trades": [_read(session, context, trade) for trade in trades],
            "coverage_state": "unknown",
            "financial_ready": False,
        }


def apply_executed_trades(
    session: Session, *, identities: list[str], confirmation_digest: str, request_id: str
) -> dict:
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("session_has_pending_changes")
    if not request_id or len(request_id) > 64:
        raise MyBrokerError("request_id_invalid")
    fingerprint = digest({"identities": sorted(identities), "confirmation": confirmation_digest})
    session.rollback()
    try:
        session.execute(
            update(ExecutedTrade).where(ExecutedTrade.id == -1).values(id=ExecutedTrade.id)
        )
        session.expire_all()
        receipt = session.scalar(
            select(ExecutedTradeApply).where(ExecutedTradeApply.request_id == request_id)
        )
        duplicate = receipt is not None
        if receipt:
            if receipt.request_fingerprint != fingerprint:
                raise MyBrokerError("idempotency_conflict")
            trade_ids = json.loads(receipt.trade_ids_json)
        else:
            plan = _plan(session, identities)
            if confirmation_digest != plan["confirmation_digest"]:
                raise MyBrokerError("preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError("reconciliation_required")
            trade_ids = []
            now = datetime.now(UTC)
            for candidate in plan["candidates"]:
                trade = (
                    session.get(ExecutedTrade, candidate["trade_id"])
                    if candidate["trade_id"]
                    else None
                )
                if trade is None:
                    binding = {b["kind"]: b["hermes_id"] for b in candidate["bindings"]}
                    trade = ExecutedTrade(
                        provider=PROVIDER,
                        source_account=candidate["core"]["source_account"],
                        primary_id=candidate["ids"][0],
                        secondary_id=candidate["ids"][1],
                        source_identity=candidate["source_identity"],
                        account_id=binding["account"],
                        instrument_id=binding["instrument"],
                        core_json=canonical(candidate["core"]),
                        bindings_json=canonical(candidate["bindings"]),
                        accepted_at=now,
                    )
                    session.add(trade)
                    session.flush()
                trade_ids.append(trade.id)
                if candidate["action"] != "noop":
                    evidence = candidate["evidence"]
                    session.add(
                        ExecutedTradeRevision(
                            trade_id=trade.id,
                            revision=(candidate["revision"] or 0) + 1,
                            lifecycle=evidence["lifecycle"],
                            acceptance_state="active",
                            fee_basis=evidence["fee_basis"],
                            event_c1_json=None,
                            evidence_json=canonical(evidence),
                            material_fingerprint=candidate["material_fingerprint"],
                            confirmation_digest=confirmation_digest,
                            accepted_at=now,
                        )
                    )
                    for occurrence in evidence["occurrences"]:
                        exists = session.scalar(
                            select(ExecutedTradeOccurrence.id).where(
                                ExecutedTradeOccurrence.import_id == occurrence["import_id"],
                                ExecutedTradeOccurrence.section == occurrence["section"],
                                ExecutedTradeOccurrence.ordinal == occurrence["ordinal"],
                            )
                        )
                        if exists is None:
                            session.add(
                                ExecutedTradeOccurrence(
                                    trade_id=trade.id,
                                    import_id=occurrence["import_id"],
                                    section=occurrence["section"],
                                    ordinal=occurrence["ordinal"],
                                    source_fingerprint=occurrence["source_fingerprint"],
                                )
                            )
            session.add(
                ExecutedTradeApply(
                    request_id=request_id,
                    request_fingerprint=fingerprint,
                    trade_ids_json=canonical(trade_ids),
                    accepted_at=now,
                )
            )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {
        **read_executed_trades(session, trade_ids),
        "duplicate": duplicate,
        "request_id": request_id,
    }


def unresolved_execution_ids(
    session: Session, accounts: tuple[int, ...], start: date, end: date
) -> list[int]:
    """Canonical accepted/disputed truth blocks no-crossing independently of S1.

    NULL event-C1 potentially affects every security class. Missing source support
    never restores completeness. Frozen historical account bindings remain used.
    """
    trades = list(
        session.scalars(select(ExecutedTrade).where(ExecutedTrade.account_id.in_(accounts)))
    )
    if not trades:
        return []
    ids = []
    context = _context(session)
    for trade in trades:
        core = json.loads(trade.core_json)
        traded = date.fromisoformat(core["trade_time"][:10])
        revisions = list(
            session.scalars(
                select(ExecutedTradeRevision)
                .where(ExecutedTradeRevision.trade_id == trade.id)
                .order_by(ExecutedTradeRevision.revision)
            )
        )
        if traded > end:
            continue
        try:
            current = _candidate(session, context, trade.source_identity)
            if current["conflicts"]:
                ids.append(trade.id)
                continue
        except MyBrokerError:
            ids.append(trade.id)
            continue
        if not revisions:
            ids.append(trade.id)
            continue
        evidence = current["evidence"]
        dates = [evidence.get("settlement_date"), evidence.get("depo_settlement_date")]
        dates.extend(leg["effective_date"] for leg in evidence["cash_legs"])
        if (
            traded >= start
            or evidence["lifecycle"] == "pending"
            or any(day is None or day >= start.isoformat() for day in dates)
        ):
            ids.append(trade.id)
    return ids
