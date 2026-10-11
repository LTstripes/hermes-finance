"""One reviewed Money extension of an existing source-owned DRAFT.

Economic facts live only in ICF/H2/canonical trade revisions. This module stages permanent links and
versioned proofs in the existing month receipt journal under one reserved writer.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import RubleAmount
from hermes_finance.domain.broker_money import MoneyIntent
from hermes_finance.domain.historical_owner_flows import OwnerFlowIntent
from hermes_finance.persistence import (
    Account,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    BrokerMoneyOccurrenceOwner,
    BrokerMonthApply,
    ExecutedTrade,
    ExecutedTradeOccurrence,
    ExecutedTradeRevision,
    HistoricalOwnerFlow,
    HistoricalOwnerFlowApply,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_months
from hermes_finance.services import historical_owner_flows as h2
from hermes_finance.services.broker_money_ownership import conflicts, key, owners
from hermes_finance.services.mybroker_dispositions import accepted_account_binding, resolve
from hermes_finance.services.mybroker_money_candidates import (
    ADAPTER,
    _narratives,
    _read_money_candidates,
)
from hermes_finance.services.source_native import stage_native_payout
from hermes_finance.statement_import.mybroker import (
    MyBrokerError,
    canonical,
    digest,
)

CONTRACT = "broker_money_v1"


def material(row):
    return (
        {
            c.name: str(getattr(row, c.name)) if getattr(row, c.name) is not None else None
            for c in row.__table__.columns
        }
        if row is not None
        else None
    )


def receipts(session):
    result = [
        (r, json.loads(r.projection_json))
        for r in session.scalars(
            select(BrokerMonthApply).order_by(
                BrokerMonthApply.accepted_at, BrokerMonthApply.request_id
            )
        )
        if json.loads(r.projection_json).get("contract_version") == CONTRACT
    ]
    return sorted(
        result,
        key=lambda item: (
            item[1].get("journal_revision", 0),
            item[0].accepted_at,
            item[0].request_id,
        ),
    )


def target_key(target):
    return target["role"], target["target_id"]


def latest_proofs(session):
    latest = {}
    for receipt, proof in receipts(session):
        for target in proof["targets"]:
            latest[target_key(target)] = (receipt, proof, target)
    return latest


def _target(session, role, target_id):
    if role == "trade":
        trade = session.get(ExecutedTrade, target_id, populate_existing=True)
        revision = session.scalar(
            select(ExecutedTradeRevision)
            .where(ExecutedTradeRevision.trade_id == target_id)
            .order_by(ExecutedTradeRevision.revision.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return {
            "role": role,
            "target_id": target_id,
            "facts": material(trade),
            "trade_revision": material(revision),
            "cash_proof": json.loads(revision.evidence_json).get("cash_reconciliation")
            if revision
            else None,
        }
    if role == "coupon":
        row = session.get(InvestmentCashFlow, target_id, populate_existing=True)
        events = [
            event
            for event in broker_months._rows(session, AppliedStatementEvent)
            if event.investment_cash_flow_id == target_id
        ]
        event_ids = {event.id for event in events}
        revisions = [
            revision
            for revision in broker_months._rows(session, AppliedStatementEventRevision)
            if revision.applied_statement_event_id in event_ids
        ]
        latest = {revision.applied_statement_event_id: revision for revision in revisions}
        components = {
            field: str(getattr(row, field)) if row and getattr(row, field) is not None else None
            for field in ("gross_amount_kopecks", "tax_amount_kopecks", "commission_amount_kopecks")
        }
        if any(
            event.link_mode == "statement_created"
            and event.id in latest
            and not latest[event.id].tax_available
            for event in events
        ):
            # Legacy PDF stores technical zero in ICF; provenance retains the
            # actual unavailable tax. Preserve the row and expose honest meaning.
            components["tax_amount_kopecks"] = None
        return {
            "role": role,
            "target_id": target_id,
            "facts": material(row),
            "components": components,
            "statement_support": {
                "events": [material(event) for event in events],
                "revisions": [material(revision) for revision in revisions],
            },
        }
    row = session.get(HistoricalOwnerFlow, target_id, populate_existing=True)
    readback = h2._read_historical_owner_flow(session, target_id) if row else None
    return {"role": role, "target_id": target_id, "facts": material(row), "h2": readback}


def compatible_pdf_event(event, facts):
    return bool(
        facts
        and event["provider"] == "alfa_depository_income_report"
        and event["link_mode"] == "linked_existing"
        and event["status"] == "active"
        and event["retracted_at"] is None
        and event["investment_cash_flow_id"] == facts["id"]
        and all(
            event[field] == facts[flow_field]
            for field, flow_field in (
                ("account_id", "account_id"),
                ("instrument_id", "instrument_id"),
                ("event_kind", "flow_type"),
            )
        )
    )


def compatible_pdf_revision(event, revision, facts):
    """Only the first accepted LINK_EXISTING supports an additive attachment.

    Missing ICF fiscal components remain missing; every known financial value and
    the complete event/revision identity must agree. Later edits are not additive.
    """
    if not compatible_pdf_event(event, facts) or revision["revision_kind"] != "link_existing":
        return False
    if revision["applied_statement_event_id"] != event["id"] or any(
        revision[field] != event[field]
        for field in (
            "document_sha256",
            "natural_identity",
            "material_fingerprint",
            "account_id",
            "instrument_id",
            "event_kind",
            "isin",
            "record_date",
        )
    ):
        return False
    if (
        any(
            revision[field] != facts[flow_field]
            for field, flow_field in (
                ("event_date", "event_date"),
                ("net_amount_kopecks", "net_amount_kopecks"),
                ("net_currency", "currency"),
            )
        )
        or revision["gross_currency"] != facts["currency"]
    ):
        return False
    if facts["amount_basis"] == "broker_statement_net_v1":
        return all(
            facts[field] is None or facts[field] == revision[field]
            for field in ("gross_amount_kopecks", "tax_amount_kopecks")
        ) and facts["commission_amount_kopecks"] in (None, "0")
    expected_tax = revision["tax_amount_kopecks"] if revision["tax_available"] == "True" else "0"
    return (
        facts["gross_amount_kopecks"] == revision["gross_amount_kopecks"]
        and facts["tax_amount_kopecks"] == expected_tax
        and facts["commission_amount_kopecks"] == "0"
    )


def compatible_target_readback(accepted, current):
    if accepted["role"] != "coupon":
        return accepted == current
    if {k: v for k, v in accepted.items() if k != "statement_support"} != {
        k: v for k, v in current.items() if k != "statement_support"
    }:
        return False
    old, new = accepted["statement_support"], current["statement_support"]
    for section in ("events", "revisions"):
        by_id = {row["id"]: row for row in new[section]}
        if any(by_id.get(row["id"]) != row for row in old[section]):
            return False
    old_ids = {event["id"] for event in old["events"]}
    # Existing support is immutable, including its full revision history.
    if any(
        revision["applied_statement_event_id"] in old_ids and revision not in old["revisions"]
        for revision in new["revisions"]
    ):
        return False
    for event in new["events"]:
        if event["id"] in old_ids:
            continue
        revisions = [r for r in new["revisions"] if r["applied_statement_event_id"] == event["id"]]
        if len(revisions) != 1 or not compatible_pdf_revision(
            event, revisions[0], current["facts"]
        ):
            return False
    return True


def _dependencies(session):
    return digest(
        {
            "month": broker_months._dependencies(session),
            **{
                model.__tablename__: [material(r) for r in broker_months._rows(session, model)]
                for model in (
                    BrokerMoneyOccurrenceOwner,
                    HistoricalOwnerFlow,
                    HistoricalOwnerFlowOccurrence,
                    HistoricalOwnerFlowRevision,
                    HistoricalOwnerFlowApply,
                    AppliedStatementEvent,
                    AppliedStatementEventRevision,
                )
            },
        }
    )


def _sources(session, intent):
    month = session.get(ReportingMonth, intent.reporting_month_id)
    result = []
    for source in broker_months._rows(session, MyBrokerImport):
        if source.covered_from > month.period_end or source.covered_to < month.period_start:
            continue
        recorded = json.loads(source.mappings_json)
        if any(b["kind"] == "account" and b["hermes_id"] == intent.account_id for b in recorded):
            result.append(source)
    return result


def _union(session, intent, originals):
    by_hash = {}
    for filename, document in originals:
        sha = hashlib.sha256(document).hexdigest()
        if sha in by_hash:
            raise MyBrokerError("duplicate_original")
        by_hash[sha] = (filename, document)
    inventory, sources, blockers = [], [], set()
    for source in _sources(session, intent):
        entry = {"import_id": source.id, "source": material(source)}
        sources.append(entry)
        if source.document_sha256 not in by_hash:
            blockers.add("overlapping_original_required")
            entry["original_required"] = True
            continue
        filename, document = by_hash.pop(source.document_sha256)
        diagnostic = _read_money_candidates(
            session,
            import_id=source.id,
            document=document,
            filename=filename,
            account_id=intent.account_id,
        )
        stored = json.loads(source.normalized_json)
        entry["adapter"] = ADAPTER
        entry["dispositions"] = resolve(session, source)
        if entry["dispositions"]:
            blockers.add("source_disposition_changed")
        for observation, row, (operation, narrative, _) in zip(
            diagnostic.observations, stored["money"], _narratives(document), strict=True
        ):
            if not stored["covered_from"] <= row["date"] <= stored["covered_to"]:
                blockers.add("posted_date_outside_range")
            for alias in (stored["filename_account"], row["source_account"]):
                binding = accepted_account_binding(session, source, alias)
                if binding is None or binding["hermes_id"] != intent.account_id:
                    blockers.add("source_mapping_unavailable")
            # Narrative distinguishes observations for specific review; it is
            # never the server-assigned canonical payment identity.
            inventory.append(
                {
                    **asdict(observation),
                    "description": narrative,
                    "narrative_digest": digest([operation, narrative]),
                    "row": row,
                }
            )
    if by_hash:
        blockers.add("original_not_in_accepted_source_union")
    return inventory, sources, blockers


def _cohort(inventory, seed, sources, blockers):
    selected = [o for o in inventory if key(o["occurrence"]) == key(seed.model_dump())]
    if len(selected) != 1:
        blockers.add("source_occurrence_not_found")
        return None, []
    observation = selected[0]

    def signature(o):
        return o["date"], o["signed_amount"], o["currency"], o["narrative_digest"]

    cohort = [o for o in inventory if signature(o) == signature(observation)]
    # Complete relevant source union is disclosed. Review cannot waive missing
    # or indistinguishable multiplicity in any report covering the event date.
    for source in sources:
        if (
            source["source"]["covered_from"]
            <= observation["date"]
            <= source["source"]["covered_to"]
        ):
            count = sum(o["occurrence"]["import_id"] == source["import_id"] for o in cohort)
            if count == 0:
                blockers.add("overlapping_source_event_missing")
            if count > 1:
                blockers.add("same_report_multiplicity")
    return observation, [o["occurrence"] for o in cohort]


def _coupon(session, intent, decision, observation, occurrences, context, blockers):
    instrument = session.get(Instrument, decision.instrument_id) if decision.instrument_id else None
    if instrument is None or instrument.instrument_type != "bond" or instrument.currency != "RUB":
        blockers.add("exact_rub_bond_link_required")
    found = owners(session, occurrences)
    owned = {o["target_id"] for o in found if o["role"] == "coupon"}
    target_id = decision.investment_cash_flow_id
    if owned:
        if len(owned) != 1 or (target_id is not None and target_id not in owned):
            blockers.add("target_reassignment_unsupported")
        else:
            target_id = next(iter(owned))
    if conflicts(session, occurrences, "coupon", target_id):
        blockers.add("occurrence_already_owned")
    target = session.get(InvestmentCashFlow, target_id) if target_id else None
    if target:
        from hermes_finance.services.statement_import_apply import _linked_flow_matches_accepted

        for event in broker_months._rows(session, AppliedStatementEvent):
            if event.investment_cash_flow_id == target_id and (
                event.status != "active"
                or not _linked_flow_matches_accepted(session, event=event, flow=target)
            ):
                blockers.add("typed_statement_payout_conflict")
    if target_id and (
        target is None
        or (
            target.reporting_month_id,
            target.account_id,
            target.instrument_id,
            target.flow_type,
            target.event_date.isoformat(),
            target.currency,
            target.net_amount_kopecks,
        )
        != (
            intent.reporting_month_id,
            intent.account_id,
            decision.instrument_id,
            "coupon",
            observation["date"],
            "RUB",
            observation["amount_minor"],
        )
    ):
        blockers.add("existing_payout_facts_conflict")
    competing = [
        material(f)
        for f in broker_months._rows(session, InvestmentCashFlow)
        if f.account_id == intent.account_id
        and f.event_date.isoformat() == observation["date"]
        and f.flow_type == "coupon"
        and f.net_amount_kopecks == observation["amount_minor"]
        and f.instrument_id == decision.instrument_id
        and f.id != target_id
        and not any(
            o.role == "coupon"
            and o.investment_cash_flow_id == f.id
            and key(o) not in set(map(key, occurrences))
            for o in broker_months._rows(session, BrokerMoneyOccurrenceOwner)
        )
    ]
    if competing:
        blockers.add("legacy_payout_overlap")
    previous = latest_proofs(session).get(("coupon", target_id))
    selected_keys = set(map(key, occurrences))
    target_owners = {
        key(owner)
        for owner in broker_months._rows(session, BrokerMoneyOccurrenceOwner)
        if owner.role == "coupon" and owner.investment_cash_flow_id == target_id
    }
    if target_owners - selected_keys:
        # A canonical payout cannot absorb a distinguishable second event,
        # even when financial fields match and new claims are supplied.
        blockers.add("existing_payout_occurrence_set_conflict")
    proven_reuse = (
        previous is not None
        and previous[1]["operation"] != "retire"
        and decision.operation == "accept"
        and selected_keys == target_owners
        and selected_keys
        == {
            key(o)
            for o in previous[1]["occurrences"]
            if o["role"] == "coupon" and o["target_id"] == target_id
        }
    )
    reviewed = digest(
        [context, "coupon", occurrences, material(instrument), material(target), competing]
    )
    if not proven_reuse:
        claims = decision.coupon_claims
        if claims is None or claims.review_context_digest != reviewed:
            blockers.add("coupon_claim_binding_required")
        if claims is None or not all(
            (
                claims.actual_coupon_payment,
                claims.exact_row_instrument_link,
                claims.complete_occurrence_set_is_one_event,
            )
        ):
            blockers.add("specific_coupon_claims_required")
        if target and not owned and (claims is None or not claims.existing_target_is_same_payment):
            blockers.add("same_payment_link_claim_required")
    if previous and previous[1]["operation"] == "retire" and decision.operation != "reaffirm":
        blockers.add("reviewed_reaffirmation_required")
    return {
        "target_id": target_id,
        "instrument_id": decision.instrument_id,
        "target": material(target),
        "competing_payouts": competing,
        "review_context_digest": reviewed,
        "action": "reuse" if proven_reuse else ("link_existing" if target else "create"),
    }


def _funding(session, intent, decision, occurrences, blockers):
    found = owners(session, occurrences)
    ids = {o["target_id"] for o in found if o["role"] == "account_funding"}
    requested = decision.owner_flow_intent
    if requested is not None and requested.evidence_version != h2.COMPATIBLE_FLOW_CONTRACT:
        blockers.add("money_h2_v2_required")
        return {"target_id": requested.flow_id, "action": "blocked", "h2_plan": None}
    if ids and len(ids) == 1 and requested is None:
        flow_id = next(iter(ids))
        read = h2._read_historical_owner_flow(session, flow_id)
        if conflicts(session, occurrences, "account_funding", flow_id):
            blockers.add("occurrence_already_owned")
        previous = latest_proofs(session).get(("account_funding", flow_id))
        if previous and previous[1]["operation"] == "retire" and decision.operation != "reaffirm":
            blockers.add("reviewed_reaffirmation_required")
        if (
            read["effective_state"] == "accepted"
            and read["evidence"]["contract_version"] == h2.COMPATIBLE_FLOW_CONTRACT
        ):
            return {"target_id": flow_id, "action": "reuse", "h2_readback": read, "h2_plan": None}
        requested = OwnerFlowIntent(
            evidence_version="h2-a1-owner-rub-v2",
            account_id=intent.account_id,
            seed=decision.seed,
            flow_id=flow_id,
            expected_revision=read["revision"],
            operation=decision.operation,
        )
    requested = requested or OwnerFlowIntent(
        evidence_version="h2-a1-owner-rub-v2", account_id=intent.account_id, seed=decision.seed
    )
    if (
        requested.operation == "revoke"
        or requested.account_id != intent.account_id
        or requested.seed != decision.seed
    ):
        blockers.add("owner_flow_intent_scope_mismatch")
        return {"target_id": None, "action": "blocked", "h2_plan": None}
    plan = h2._plan(session, requested)
    blockers.update(plan["blockers"])
    if set(map(key, plan["evidence"].get("occurrences", []))) != set(map(key, occurrences)):
        blockers.add("owner_flow_occurrence_set_conflict")
    if requested.claims and requested.claims.direction != "contribution":
        blockers.add("incoming_account_cash_required")
    if conflicts(session, occurrences, "account_funding", requested.flow_id):
        blockers.add("occurrence_already_owned")
    return {
        "target_id": requested.flow_id,
        "action": plan["candidate_action"],
        "owner_flow_intent": requested.model_dump(mode="json"),
        "h2_plan": plan,
    }


def _plan(session, intent, originals):
    base = session.get(BrokerMonthApply, intent.base_request_id, populate_existing=True)
    if (
        base is None
        or "projection_digest" not in json.loads(base.projection_json)
        or (base.reporting_month_id, base.account_id)
        != (intent.reporting_month_id, intent.account_id)
    ):
        raise MyBrokerError("existing_source_draft_required")
    month = session.get(ReportingMonth, intent.reporting_month_id, populate_existing=True)
    account = session.get(Account, intent.account_id, populate_existing=True)
    blockers = set()
    if month.status != "draft":
        blockers.add("reporting_month_closed")
    if account is None or account.status != "active" or account.account_type != "brokerage":
        blockers.add("active_brokerage_account_required")
    if (
        broker_months._projection(session, base)
        != json.loads(base.projection_json)["projection_digest"]
    ):
        blockers.add("source_projection_changed")
    inventory, sources, union_blockers = _union(session, intent, originals)
    blockers.update(union_blockers)
    if base.import_id not in {s["import_id"] for s in sources}:
        blockers.add("base_source_missing")
    dependencies = _dependencies(session)
    plans, selected, selected_targets = [], set(), set()
    for decision in intent.money_decisions:
        reasons = set(union_blockers)
        observation, occurrences = _cohort(inventory, decision.seed, sources, reasons)
        if observation is None:
            blockers.update(reasons)
            continue
        if (
            not month.period_start.isoformat()
            <= observation["date"]
            <= month.period_end.isoformat()
        ):
            reasons.add("money_outside_selected_month")
        expected = {
            "coupon": "coupon_paid_candidate",
            "account_funding": "account_cash_in_candidate",
            "trade": "trade_paid_nkd_candidate",
        }[decision.role]
        if (
            observation["candidate_kind"] != expected
            or observation["amount_minor"] is None
            or (
                observation["amount_minor"] >= 0
                if decision.role == "trade"
                else observation["amount_minor"] <= 0
            )
        ):
            reasons.add("money_semantics_not_supported")
        occurrence_keys = set(map(key, occurrences))
        if selected.intersection(occurrence_keys):
            reasons.add("duplicate_decision_occurrence")
        selected.update(occurrence_keys)
        if decision.role == "trade":
            from hermes_finance.services.broker_trade_money import plan_trade

            target_plan = plan_trade(
                session,
                intent,
                decision,
                observation,
                occurrences,
                inventory,
                dependencies,
                reasons,
            )
            occurrences = target_plan.get("occurrences", occurrences)
            extra = set(map(key, occurrences)) - occurrence_keys
            if selected.intersection(extra):
                reasons.add("duplicate_decision_occurrence")
            selected.update(extra)
        elif decision.role == "coupon":
            target_plan = _coupon(
                session, intent, decision, observation, occurrences, dependencies, reasons
            )
        else:
            target_plan = _funding(session, intent, decision, occurrences, reasons)
        target_identity = (decision.role, target_plan["target_id"])
        if target_plan["target_id"] is not None:
            if target_identity in selected_targets:
                reasons.add("duplicate_decision_target")
            selected_targets.add(target_identity)
        plans.append(
            {
                "decision": decision.model_dump(mode="json"),
                "observation": observation,
                "occurrences": occurrences,
                **target_plan,
                "blockers": sorted(reasons),
            }
        )
        blockers.update(reasons)
    if not intent.money_decisions:
        blockers.add("money_decisions_required")
    exceptions = broker_months._account_readiness(
        session, intent.reporting_month_id, intent.account_id
    )
    plan = {
        "contract_version": CONTRACT,
        "base_request_id": intent.base_request_id,
        "reporting_month_id": intent.reporting_month_id,
        "account_id": intent.account_id,
        "inventory": inventory,
        "sources": sources,
        "decisions": plans,
        "trade_choices": [
            {
                "trade_id": t.id,
                "ids": [t.primary_id, t.secondary_id],
                "source_identity": t.source_identity,
                "instrument_id": t.instrument_id,
                "core": json.loads(t.core_json),
                "revision": _target(session, "trade", t.id)["trade_revision"],
            }
            for t in broker_months._rows(session, ExecutedTrade)
            if t.account_id == intent.account_id
            and month.period_start.isoformat()
            <= json.loads(t.core_json)["trade_time"][:10]
            <= month.period_end.isoformat()
        ],
        "expected_effects": {
            "new_coupon_facts": sum(
                p["decision"]["role"] == "coupon" and p["target_id"] is None for p in plans
            ),
            "new_account_flow_facts": sum(
                p["decision"]["role"] == "account_funding" and p["action"] == "created"
                for p in plans
            ),
            "new_external_flows": 0,
            "cash_increment_minor": "0",
            "selected_coupon_net_minor": str(
                sum(
                    p["observation"]["amount_minor"]
                    for p in plans
                    if p["decision"]["role"] == "coupon"
                )
            )
            if all(p["observation"]["amount_minor"] is not None for p in plans)
            else None,
        },
        "dependencies": dependencies,
        "blockers": sorted(blockers),
        "can_apply": not blockers,
        "exceptions": exceptions,
        "bookkeeping_ready": not exceptions,
        "portfolio_scope": "unknown",
        "coverage_state": "unknown",
        "exact_return_ready": False,
    }
    plan["confirmation_digest"] = digest([intent.model_dump(mode="json"), plan])
    return plan


def preview_money(session, intent, originals):
    with coherent_read_snapshot(session):
        return _plan(session, intent, originals)


def effective_occurrence(session, source_id, row):
    owner = session.scalar(
        select(BrokerMoneyOccurrenceOwner).where(
            BrokerMoneyOccurrenceOwner.import_id == source_id,
            BrokerMoneyOccurrenceOwner.section == "money",
            BrokerMoneyOccurrenceOwner.ordinal == row["ordinal"],
        )
    )
    if owner is None:
        trade_owner = session.scalar(
            select(ExecutedTradeOccurrence).where(
                ExecutedTradeOccurrence.import_id == source_id,
                ExecutedTradeOccurrence.section == "money",
                ExecutedTradeOccurrence.ordinal == row["ordinal"],
            )
        )
        if trade_owner is None or trade_owner.source_fingerprint != digest(row):
            return False
        latest = latest_proofs(session).get(("trade", trade_owner.trade_id))
        return latest is not None and not proof_blockers(session, *latest)
    if owner.row_fingerprint != digest(row):
        return False
    target_id = (
        owner.investment_cash_flow_id if owner.role == "coupon" else owner.historical_owner_flow_id
    )
    latest = latest_proofs(session).get((owner.role, target_id))
    return latest is not None and not proof_blockers(session, latest[0], latest[1], latest[2])


def proof_blockers(session, receipt, proof, target):
    blockers = set()
    if proof["operation"] == "retire":
        blockers.add("money_review_retired")
    current = _target(session, target["role"], target["target_id"])
    if not compatible_target_readback(target, current):
        blockers.add("money_target_revision_changed")
    if target["role"] == "account_funding" and (
        current.get("h2") is None
        or current["h2"]["effective_state"] != "accepted"
        or current["h2"]["evidence"]["contract_version"] != h2.COMPATIBLE_FLOW_CONTRACT
    ):
        blockers.add("h2_authority_unavailable")
    for source_snapshot in proof["sources"]:
        source = session.get(MyBrokerImport, source_snapshot["import_id"], populate_existing=True)
        if material(source) != source_snapshot["source"]:
            blockers.add("money_source_changed")
    source_ids = {
        s.id
        for s in _sources(
            session,
            MoneyIntent(
                contract_version=CONTRACT,
                base_request_id=proof["base_request_id"],
                reporting_month_id=receipt.reporting_month_id,
                account_id=receipt.account_id,
            ),
        )
    }
    if source_ids != {s["import_id"] for s in proof["sources"]}:
        blockers.add("money_source_union_changed")
    for occurrence in proof["occurrences"]:
        source = session.get(MyBrokerImport, occurrence["import_id"])
        row = (
            next(
                (
                    r
                    for r in json.loads(source.normalized_json)["money"]
                    if r["ordinal"] == occurrence["ordinal"]
                ),
                None,
            )
            if source
            else None
        )
        if (
            row is None
            or digest(row) != occurrence["row_fingerprint"]
            or conflicts(session, [occurrence], occurrence["role"], occurrence["target_id"])
        ):
            blockers.add("money_ownership_changed")
        if occurrence["role"] == "trade" and not any(
            owner["role"] == "trade"
            and owner["target_id"] == occurrence["target_id"]
            and owner["row_fingerprint"] == occurrence["row_fingerprint"]
            for owner in owners(session, [occurrence])
        ):
            blockers.add("money_ownership_changed")
        if source and any(
            accepted_account_binding(session, source, alias) is None
            or accepted_account_binding(session, source, alias)["hermes_id"] != receipt.account_id
            for alias in (
                json.loads(source.normalized_json)["filename_account"],
                row["source_account"] if row else "",
            )
        ):
            blockers.add("money_mapping_changed")
    return sorted(blockers)


def owned_payout_ids(session, month_id, account_id):
    return {
        target_id
        for (role, target_id), (receipt, proof, target) in latest_proofs(session).items()
        if role == "coupon"
        and receipt.reporting_month_id == month_id
        and receipt.account_id == account_id
        and not proof_blockers(session, receipt, proof, target)
    }


def read_money(session, request_id):
    with coherent_read_snapshot(session):
        receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
        if receipt is None:
            raise MyBrokerError("broker_month_not_found")
        proof = json.loads(receipt.projection_json)
        if proof.get("contract_version") != CONTRACT:
            raise MyBrokerError("money_receipt_required")
        latest = latest_proofs(session)
        targets, blockers = [], set()
        current_targets = []
        for current_receipt, current_proof, target in latest.values():
            if (
                current_receipt.reporting_month_id == receipt.reporting_month_id
                and current_receipt.account_id == receipt.account_id
                and current_proof["base_request_id"] == proof["base_request_id"]
            ):
                reasons = proof_blockers(session, current_receipt, current_proof, target)
                current_targets.append(
                    {
                        **_target(session, target["role"], target["target_id"]),
                        "effective": not reasons,
                        "exceptions": reasons,
                        "current_request_id": current_receipt.request_id,
                    }
                )
        for accepted in proof["targets"]:
            current_receipt, current_proof, target = latest[target_key(accepted)]
            reasons = proof_blockers(session, current_receipt, current_proof, target)
            blockers.update(reasons)
            targets.append(
                {
                    **_target(session, accepted["role"], accepted["target_id"]),
                    "effective": not reasons,
                    "exceptions": reasons,
                    "current_request_id": current_receipt.request_id,
                }
            )
        blockers.update(
            broker_months._account_readiness(
                session, receipt.reporting_month_id, receipt.account_id
            )
        )
        return {
            "contract_version": CONTRACT,
            "request_id": request_id,
            "base_request_id": proof["base_request_id"],
            "reporting_month_id": receipt.reporting_month_id,
            "account_id": receipt.account_id,
            "import_id": receipt.import_id,
            "confirmation_digest": receipt.confirmation_digest,
            "status": session.get(ReportingMonth, receipt.reporting_month_id).status,
            "accepted": proof,
            "targets": targets,
            "current_targets": current_targets,
            "exceptions": sorted(blockers),
            "bookkeeping_ready": not blockers,
            "portfolio_scope": "unknown",
            "coverage_state": "unknown",
            "exact_return_ready": False,
        }


def apply_money(session, intent, originals, *, confirmation_digest, request_id):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    fingerprint = digest(
        [
            intent.model_dump(mode="json"),
            confirmation_digest,
            sorted(
                [filename, hashlib.sha256(document).hexdigest()] for filename, document in originals
            ),
        ]
    )
    session.rollback()
    try:
        session.execute(
            update(BrokerMonthApply)
            .where(BrokerMonthApply.request_id == "")
            .values(request_id=BrokerMonthApply.request_id)
        )
        session.expire_all()
        receipt = session.get(BrokerMonthApply, request_id)
        replay = receipt is not None
        if receipt:
            if receipt.request_fingerprint != fingerprint:
                raise MyBrokerError("idempotency_conflict")
            session.rollback()
        else:
            plan = _plan(session, intent, originals)
            if plan["confirmation_digest"] != confirmation_digest:
                raise MyBrokerError("money_preview_stale")
            if not plan["can_apply"]:
                raise MyBrokerError(";".join(plan["blockers"]))
            base = session.get(BrokerMonthApply, intent.base_request_id)
            receipt = BrokerMonthApply(
                request_id=request_id,
                request_fingerprint=fingerprint,
                confirmation_digest=confirmation_digest,
                reporting_month_id=intent.reporting_month_id,
                account_id=intent.account_id,
                import_id=base.import_id,
                projection_json="{}",
                accepted_at=datetime.now(UTC),
            )
            session.info["broker_money_stage"] = True
            session.add(receipt)
            session.flush()
            target_refs, occurrence_refs = [], []
            for index, decision in enumerate(plan["decisions"]):
                role, target_id = decision["decision"]["role"], decision["target_id"]
                if role == "coupon" and target_id is None:
                    row = stage_native_payout(
                        session,
                        reporting_month_id=intent.reporting_month_id,
                        account_id=intent.account_id,
                        instrument_id=decision["instrument_id"],
                        flow_type="coupon",
                        event_date=date.fromisoformat(decision["observation"]["date"]),
                        net_amount=RubleAmount(decision["observation"]["amount_minor"]),
                        source_import_id=decision["observation"]["occurrence"]["import_id"],
                        source_row_key=digest([CONTRACT, "payment", uuid4().hex]),
                    )
                    target_id = row.id
                elif role == "account_funding" and decision["h2_plan"] is not None:
                    owner_intent = OwnerFlowIntent.model_validate(decision["owner_flow_intent"])
                    target_id, _, _ = h2.stage_historical_owner_flow(
                        session,
                        owner_intent,
                        decision["h2_plan"],
                        confirmation_digest=decision["h2_plan"]["confirmation_digest"],
                        request_id=digest([CONTRACT, request_id, index]),
                    )
                elif role == "trade":
                    from hermes_finance.services.executed_trades import stage_executed_trades

                    stage_executed_trades(
                        session,
                        {"can_apply": True, "candidates": [decision["candidate"]]},
                        confirmation_digest=confirmation_digest,
                        request_id=digest([CONTRACT, request_id, "trade", index]),
                    )
                target_refs.append((role, target_id))
                for occurrence in decision["occurrences"]:
                    if conflicts(session, [occurrence], role, target_id):
                        raise MyBrokerError("occurrence_already_owned")
                    if role == "trade":
                        exists = session.scalar(
                            select(ExecutedTradeOccurrence.id).where(
                                ExecutedTradeOccurrence.import_id == occurrence["import_id"],
                                ExecutedTradeOccurrence.section == "money",
                                ExecutedTradeOccurrence.ordinal == occurrence["ordinal"],
                            )
                        )
                        if exists is None:
                            session.add(
                                ExecutedTradeOccurrence(
                                    trade_id=target_id,
                                    import_id=occurrence["import_id"],
                                    section="money",
                                    ordinal=occurrence["ordinal"],
                                    source_fingerprint=occurrence["row_fingerprint"],
                                )
                            )
                        occurrence_refs.append({**occurrence, "role": role, "target_id": target_id})
                        continue
                    existing = session.scalar(
                        select(BrokerMoneyOccurrenceOwner).where(
                            BrokerMoneyOccurrenceOwner.import_id == occurrence["import_id"],
                            BrokerMoneyOccurrenceOwner.section == "money",
                            BrokerMoneyOccurrenceOwner.ordinal == occurrence["ordinal"],
                        )
                    )
                    if existing is None:
                        session.add(
                            BrokerMoneyOccurrenceOwner(
                                **occurrence,
                                role=role,
                                investment_cash_flow_id=target_id if role == "coupon" else None,
                                historical_owner_flow_id=target_id
                                if role == "account_funding"
                                else None,
                                accepted_request_id=request_id,
                            )
                        )
                    occurrence_refs.append({**occurrence, "role": role, "target_id": target_id})
            session.flush()
            proof = {
                "contract_version": CONTRACT,
                "base_request_id": intent.base_request_id,
                "operation": "reaffirm"
                if any(d.operation == "reaffirm" for d in intent.money_decisions)
                else "accept",
                "sources": plan["sources"],
                "occurrences": occurrence_refs,
                "targets": [_target(session, role, target_id) for role, target_id in target_refs],
                "decisions": [d.model_dump(mode="json") for d in intent.money_decisions],
            }
            from hermes_finance.services.broker_money_lifecycle import next_journal_revision

            proof["journal_revision"] = next_journal_revision(session)
            receipt.accepted_at = datetime.now(UTC)
            receipt.projection_json = canonical(proof)
            session.flush()
            session.info.pop("broker_money_stage", None)
            session.commit()
    except BaseException:
        session.info.pop("broker_money_stage", None)
        session.rollback()
        raise
    with Session(session.get_bind(), autoflush=False) as fresh:
        return {**read_money(fresh, request_id), "duplicate": replay}
