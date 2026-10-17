"""Bounded canonical executions and independently effective Money legs.

No inventory completeness, cost basis, cash aggregation or financial writes.
The digest describes this snapshot; it is deliberately not a reusable token:
S2-only inventory/absence has no complete monotonic journal.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, DecimalException

from sqlalchemy import select

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import (
    Account,
    BrokerMoneyOccurrenceOwner,
    BrokerMonthApply,
    Instrument,
    MyBrokerCorrectionChange,
    MyBrokerCorrectionRevision,
    MyBrokerDispositionChange,
    MyBrokerDispositionRevision,
    ReportingMonth,
)
from hermes_finance.services import executed_trades as executions
from hermes_finance.services.broker_money import latest_proofs, material, proof_blockers
from hermes_finance.services.broker_trade_money import effective_proof, is_stock_proof
from hermes_finance.services.instrument_cash_income import _historical_identity
from hermes_finance.statement_import.mybroker import MyBrokerError, digest

METHOD = "known-instrument-trades"
VERSION = 1
CAPACITY = 250


def _day(value):
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def _inside(day, t0, t1):
    return t0.isoformat() < day <= t1.isoformat() if day is not None else None


def _dates(core, evidence):
    return [
        _day(core.get("trade_time")),
        _day(evidence.get("settlement_date")),
        _day(evidence.get("depo_settlement_date")),
        *[_day(v) for v in (evidence.get("planned_dates") or {}).values()],
        *[_day(leg.get("effective_date")) for leg in evidence.get("cash_legs", [])],
    ]


def _event(session, context, trade, receipts, instrument, latest_money, t0, t1):
    reasons = set()
    try:
        row = executions._read(session, context, trade)
        reasons.update(row["conflicts"])
        core, evidence = row["core"], row["evidence"]
        revision = row["revision"]
        if row["acceptance_state"] != "active":
            reasons.add("execution_revision_inactive")
    except (MyBrokerError, KeyError, ValueError, TypeError):
        core, evidence = json.loads(trade.core_json), {}
        revision = None
        reasons.add("execution_reader_unavailable")
    current = not reasons
    if core.get("isin") != instrument.isin or core.get("currency") != "RUB":
        reasons.add("execution_identity_or_currency_conflict")
        current = False
    day = _day(core.get("trade_time"))
    if day is None:
        reasons.add("execution_date_unavailable")
    try:
        quantity = Decimal(core["quantity"])
        valid_quantity = quantity.is_finite() and quantity != 0
    except (KeyError, ValueError, TypeError, DecimalException):
        quantity, valid_quantity = None, False
    if not valid_quantity:
        reasons.add("execution_side_unavailable")
    cash_reasons = set(reasons)
    entry = latest_money.get(("trade", trade.id))
    try:
        proof = effective_proof(session, trade.source_identity)
        if entry:
            cash_reasons.update(proof_blockers(session, *entry))
    except (MyBrokerError, ValueError, TypeError, KeyError, AttributeError):
        proof = None
        cash_reasons.add("money_reader_unavailable")
    if not proof:
        cash_reasons.add("effective_money_proof_unavailable")
    if not current or evidence.get("lifecycle") != "settled":
        cash_reasons.add("current_settled_rub_execution_required")
    if not valid_quantity or quantity <= 0:
        cash_reasons.add("sell_cash_authority_unsupported")
    if proof and (
        proof.get("source_identity") != trade.source_identity
        or proof.get("native_ids") != [trade.primary_id, trade.secondary_id]
        or (is_stock_proof(proof) and instrument.instrument_type != "stock")
        or (not is_stock_proof(proof) and instrument.instrument_type != "bond")
    ):
        cash_reasons.add("cash_proof_identity_conflict")
    historical_receipts = []
    for receipt in receipts:
        month = session.get(ReportingMonth, receipt.reporting_month_id)
        if day is not None and month is not None and month.period_start.isoformat() <= day:
            historical_receipts.append(receipt)
    # SOURCE identity cannot be projected backward from a later catalogue.
    # An independently accepted, effective narrow Money BUY proof is itself
    # the existing exact-RUB-stock/bond link; S2-only observations have no such authority.
    historical = _historical_identity(session, historical_receipts, trade, instrument)
    historical |= bool(
        proof
        and entry
        and current
        and valid_quantity
        and quantity > 0
        and instrument.currency == "RUB"
        and not cash_reasons
        and evidence.get("lifecycle") == "settled"
    )
    if not historical:
        reasons.add("historical_rub_identity_unproven")
        cash_reasons.add("historical_rub_identity_unproven")
    legs = []
    for role in ("settlement", "paid_nkd", "commission"):
        blockers = set(cash_reasons)
        candidates = [leg for leg in evidence.get("cash_legs", []) if leg["role"] == role]
        signed = proof.get("signed_minor", {}).get(role) if proof else None
        if signed is None or len(candidates) != 1:
            blockers.add("role_cash_authority_unavailable")
        accepted = not blockers
        leg = candidates[0] if len(candidates) == 1 else None
        legs.append(
            {
                "role": role,
                "proof_class": "effective_cash_leg_authority" if accepted else "unavailable",
                "signed_rub": RubleAmount(int(signed)).to_api() if accepted else None,
                "signed_kopecks": signed if accepted else None,
                "effective_date": leg["effective_date"] if leg else None,
                "in_interval": _inside(leg["effective_date"], t0, t1) if leg else None,
                "basis": proof["claims"]["native_total_basis"] if accepted else None,
                "receipt_id": entry[0].request_id if accepted else None,
                "occurrences": [
                    {
                        "import_id": p["import_id"],
                        "section": "money",
                        "ordinal": p["ordinal"],
                        "row_fingerprint": p["source_fingerprint"],
                    }
                    for p in leg["occurrences"]
                ]
                if accepted
                else [],
                "reason_codes": sorted(blockers) if blockers else ["effective_money_role_proof"],
            }
        )
    return {
        "trade_id": trade.id,
        "account_id": trade.account_id,
        "instrument_id": trade.instrument_id,
        "source_identity": trade.source_identity,
        "native_ids": [trade.primary_id, trade.secondary_id],
        "proof_class": "observed_native_execution",
        "revision": revision,
        "currentness": "current" if current else "unavailable",
        "historical_identity": {
            "isin": instrument.isin,
            "instrument_type": instrument.instrument_type,
            "denomination": "RUB",
        }
        if historical
        else None,
        "side": ("BUY" if quantity > 0 else "SELL") if valid_quantity else None,
        "signed_quantity": format(quantity, "f") if valid_quantity else None,
        "execution_date": day,
        "execution_in_interval": _inside(day, t0, t1),
        "settlement_date": evidence.get("settlement_date"),
        "settlement_in_interval": _inside(evidence.get("settlement_date"), t0, t1),
        "depository_date": evidence.get("depo_settlement_date"),
        "depository_in_interval": _inside(evidence.get("depo_settlement_date"), t0, t1),
        "planned_settlement_date": (evidence.get("planned_dates") or {}).get("settlement_date"),
        "lifecycle": evidence.get("lifecycle"),
        "source_occurrences": [
            {
                "import_id": p["import_id"],
                "section": p["section"],
                "ordinal": p["ordinal"],
                "row_fingerprint": p["source_fingerprint"],
            }
            for p in evidence.get("occurrences", [])
        ],
        "cash_legs": legs,
        "reason_codes": sorted(reasons),
    }


@coherent_read_operation
def known_instrument_trades(session, account_id: int, instrument_id: int, t0: date, t1: date):
    if t0 >= t1:
        raise ValueError("invalid_interval")
    account = session.get(Account, account_id)
    instrument = session.get(Instrument, instrument_id)
    if account is None or instrument is None:
        raise LookupError("account_or_instrument_not_found")
    if account.account_type not in {"brokerage", "iis"}:
        raise ValueError("brokerage_or_iis_required")
    context = executions._context(session)
    trades = [
        t
        for t in context["trades"].values()
        if t.account_id == account_id and t.instrument_id == instrument_id
    ]
    reasons = {
        "trade_history_completeness_unknown",
        "financial_coverage_unknown",
        "full_instrument_return_unavailable",
        "inventory_revision_journal_unavailable",
    }
    selected = []
    for trade in trades:
        core = json.loads(trade.core_json)
        revision = executions._latest(context, trade.id)
        evidence = json.loads(revision.evidence_json) if revision else {}
        days = _dates(core, evidence)
        source = context["projections"].get(trade.source_identity)
        if source:
            days += [source.get("settlement_date"), source.get("depo_settlement_date")]
        if any(_inside(day, t0, t1) for day in days) or days[0] is None:
            selected.append(trade)
    scoped_sources = []
    aliases = {
        b["identity"]
        for source in context["imports"]
        for b in json.loads(source.mappings_json)
        if b["kind"] == "account" and b["hermes_id"] == account_id
    }
    trade_ids = {t.id for t in trades}
    retained_source_ids = {o.import_id for o in context["occurrences"] if o.trade_id in trade_ids}
    for source, document in zip(context["imports"], context["documents"], strict=True):
        bindings = json.loads(source.mappings_json)
        if source.id not in retained_source_ids and not any(
            b["kind"] == "account" and (b["hermes_id"] == account_id or b["identity"] in aliases)
            for b in bindings
        ):
            continue
        if source.id not in retained_source_ids and (
            source.covered_from > t1 or source.covered_to <= t0
        ):
            continue
        scoped_sources.append(source)
        reasons.update(document.get("syntax_blockers", []))
        reasons.update(document.get("blockers", []))
        if any(
            r.get("source_account") in aliases and r.get("kind") == "unsupported"
            for r in document.get("money", [])
        ):
            reasons.add("unsupported_money_rows")
        if any(
            t["core"]["isin"] == instrument.isin and t.get("identity") not in context["trades"]
            for t in document["trades"]
        ):
            reasons.add("unaccepted_native_execution_rows")
    if not scoped_sources:
        reasons.add("source_inventory_gap")
    capacity = len(selected) > CAPACITY
    receipts = list(
        session.scalars(select(BrokerMonthApply).where(BrokerMonthApply.account_id == account_id))
    )
    latest_money = latest_proofs(session)
    events = (
        []
        if capacity
        else [
            _event(session, context, trade, receipts, instrument, latest_money, t0, t1)
            for trade in sorted(selected, key=lambda t: t.id)
        ]
    )
    if capacity:
        reasons.add("capacity_exceeded")
    elif not events:
        reasons.add("no_known_trades_not_zero_activity")
    generation = session.scalar(
        select(MyBrokerCorrectionChange.id).order_by(MyBrokerCorrectionChange.id.desc()).limit(1)
    )
    source_ids = {s.id for s in scoped_sources}
    history = {
        model.__tablename__: [
            material(r)
            for r in session.scalars(
                select(model).where(model.import_id.in_(source_ids)).order_by(model.id)
            )
        ]
        for model in (
            MyBrokerCorrectionRevision,
            MyBrokerDispositionRevision,
            MyBrokerDispositionChange,
            BrokerMoneyOccurrenceOwner,
        )
    }
    signature = digest(
        {
            "method": METHOD,
            "version": VERSION,
            "scope": [account_id, instrument_id, str(t0), str(t1)],
            "account": material(account),
            "instrument": material(instrument),
            "sources": [[s.id, digest(material(s))] for s in scoped_sources],
            "receipts": [material(r) for r in receipts],
            "trades": [material(t) for t in trades],
            "revisions": [
                material(r) for r in context["revisions"] if r.trade_id in {t.id for t in trades}
            ],
            "correction_generation": generation,
            "history": history,
            "occurrences": [material(o) for o in context["occurrences"] if o.trade_id in trade_ids],
            "events": events,
            "absence_reasons": sorted(reasons),
        }
    )
    return {
        "method": METHOD,
        "version": VERSION,
        "account": {"id": account.id, "name": account.name},
        "instrument": {"id": instrument.id, "name": instrument.name},
        "t0": str(t0),
        "t1": str(t1),
        "currency": "RUB",
        "trade_history_completeness": "unknown",
        "financial_coverage": "unknown",
        "status": "capacity_exceeded" if capacity else "available",
        "capacity": CAPACITY,
        "known_count": None if capacity else len(events),
        "events": events,
        "dependency_digest": signature,
        "dependency_fingerprint": None,
        "currentness": "unavailable",
        "reason_codes": sorted(reasons),
    }
