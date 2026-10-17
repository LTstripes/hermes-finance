"""Known booked net payouts, never interval completeness or instrument return.

ICF owns economic identity. Money and typed statements only qualify that row.
All joins, absence sets and journals are read in one query-only snapshot.
"""

from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.domain import RubleAmount
from hermes_finance.persistence import (
    Account,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    BrokerIdentityMapping,
    BrokerMoneyOccurrenceOwner,
    BrokerMonthApply,
    Instrument,
    InvestmentCashFlow,
    MyBrokerCorrectionChange,
    MyBrokerCorrectionRevision,
    MyBrokerDispositionChange,
    MyBrokerDispositionRevision,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services.broker_money import material
from hermes_finance.services.mybroker_dispositions import effective_bindings, resolve
from hermes_finance.services.mybroker_import import _prepare
from hermes_finance.services.source_cash_coupons import authority
from hermes_finance.services.statement_import_apply import _linked_flow_matches_accepted
from hermes_finance.statement_import.dto import ALFA_DEPOSITORY_INCOME_PROVIDER
from hermes_finance.statement_import.mybroker import MyBrokerError, digest

METHOD = "known-booked-net-payouts"
VERSION = 1


def _money(value: int | None) -> str | None:
    return RubleAmount(value).to_api() if value is not None else None


def _rows(session, model):
    return list(session.scalars(select(model).order_by(*model.__table__.primary_key.columns)))


def _historical_identity(session, receipts, flow, instrument):
    """Frozen native month identity; never infer denomination from settlement RUB.

    A prior accepted identity remains usable for an exited holding. Current
    catalogue agreement prevents attributing a remapped instrument to that past.
    Money's explicit exact-RUB-bond acceptance is handled by its authority reader.
    Typed PDF alone contains settlement currency, not security denomination.
    """
    found = []
    for receipt in receipts:
        if receipt.account_id != flow.account_id or journal.kind(receipt) != journal.SOURCE:
            continue
        try:
            proof = json.loads(receipt.projection_json)
            identity = proof.get("instruments", {}).get(str(flow.instrument_id))
            source = session.get(MyBrokerImport, receipt.import_id)
            if source is None or proof["source_digest"] != digest(
                [source.normalized_json, source.mappings_json, source.parser_version]
            ):
                continue
            prepared = _prepare(session, json.loads(source.normalized_json))
            bindings = effective_bindings(session, source)
            if (
                prepared["conflicts"]
                or prepared["missing_mappings"]
                or prepared["mappings"] != bindings
                or any(
                    item["isin"] == instrument.isin and item["effective_state"] != "mapped"
                    for item in resolve(session, source)
                )
                or not any(
                    b["kind"] == "account" and b["hermes_id"] == flow.account_id for b in bindings
                )
                or not any(
                    b["kind"] == "instrument"
                    and b["hermes_id"] == flow.instrument_id
                    and b["identity"] == instrument.isin
                    for b in bindings
                )
            ):
                continue
        except (ValueError, TypeError, AttributeError, KeyError, MyBrokerError):
            continue
        if identity is not None:
            found.append((receipt, identity))
    expected = [instrument.isin, instrument.instrument_type, instrument.currency]
    return any(
        identity == expected and identity[1] in {"stock", "bond"} and identity[2] == "RUB"
        for _, identity in found
    )


@coherent_read_operation
def known_instrument_cash_income(
    session: Session, account_id: int, instrument_id: int, t0: date, t1: date
) -> dict:
    if t0 >= t1:
        raise ValueError("t0 must precede t1")
    account = session.get(Account, account_id)
    instrument = session.get(Instrument, instrument_id)
    if account is None or instrument is None:
        raise LookupError("account or instrument not found")

    # Bind complete absence/retirement/remapping journals too. The digest alone
    # leaves the process; normalized source text and receipt payloads never do.
    models = (
        InvestmentCashFlow,
        AppliedStatementEvent,
        AppliedStatementEventRevision,
        BrokerMoneyOccurrenceOwner,
        BrokerMonthApply,
        MyBrokerImport,
        MyBrokerCorrectionRevision,
        MyBrokerCorrectionChange,
        MyBrokerDispositionRevision,
        MyBrokerDispositionChange,
        BrokerIdentityMapping,
        ReportingMonth,
    )
    dependencies = {model.__tablename__: _rows(session, model) for model in models}
    receipts = dependencies[BrokerMonthApply.__tablename__]
    months = {m.id: m for m in dependencies[ReportingMonth.__tablename__]}
    # Only receipts whose reporting interval existed by the payout date can
    # establish historical identity (a later catalogue observation cannot).
    flows = [
        f
        for f in dependencies[InvestmentCashFlow.__tablename__]
        if f.account_id == account_id
        and f.instrument_id == instrument_id
        and f.flow_type in {"coupon", "dividend"}
        and t0 < f.event_date <= t1
    ]
    money_material, effective = {}, set()
    reader_reasons = []
    try:
        money_material, _, effective = authority(session, account_id, t0, t1, [])
    except (ValueError, TypeError, KeyError, AttributeError, MyBrokerError):
        reader_reasons.append("coupon_authority_unavailable")
    money_targets = {t["target_id"]: t for t in money_material.get("targets", [])}
    reader_reasons.extend(money_material.get("blockers", []))
    events = []
    totals = {"coupon": [], "dividend": []}
    for flow in flows:
        reasons = []
        month = months.get(flow.reporting_month_id)
        scope_ok = (
            account.account_type in {"brokerage", "iis"}
            and flow.currency == "RUB"
            and month is not None
            and month.period_start <= flow.event_date <= month.period_end
            and instrument.instrument_type
            == {"coupon": "bond", "dividend": "stock"}[flow.flow_type]
            and instrument.currency == "RUB"
        )
        if not scope_ok:
            reasons.append("payout_scope_unsupported")
        typed = [
            e
            for e in dependencies[AppliedStatementEvent.__tablename__]
            if e.investment_cash_flow_id == flow.id
        ]
        revisions = [
            r
            for r in dependencies[AppliedStatementEventRevision.__tablename__]
            if any(e.id == r.applied_statement_event_id for e in typed)
        ]
        latest = {
            e.id: next(
                (r for r in reversed(revisions) if r.applied_statement_event_id == e.id), None
            )
            for e in typed
        }
        valid_typed = []
        for event in typed:
            rev = latest[event.id]
            if (
                event.status == "active"
                and rev is not None
                and rev.revision_kind != "retract"
                and event.provider == ALFA_DEPOSITORY_INCOME_PROVIDER
                and event.account_id == rev.account_id == flow.account_id
                and event.instrument_id == rev.instrument_id == flow.instrument_id
                and event.event_kind == rev.event_kind == flow.flow_type
                and event.isin == rev.isin == instrument.isin
                and event.natural_identity == rev.natural_identity
                and event.material_fingerprint == rev.material_fingerprint
                and event.document_sha256 == rev.document_sha256
                and _linked_flow_matches_accepted(session, event=event, flow=flow)
            ):
                valid_typed.append(event)
            else:
                reasons.append("typed_statement_conflict")
        money_target = money_targets.get(flow.id)
        money_ok = flow.id in effective
        money_owned = bool(
            money_target and (money_target.get("receipt") or money_target.get("owners"))
        )
        if money_owned and not money_ok:
            reasons.extend(money_target.get("blockers", []))
        historical = money_ok or _historical_identity(
            session,
            [
                r
                for r in receipts
                if r.reporting_month_id in months
                and months[r.reporting_month_id].period_start <= flow.event_date
            ],
            flow,
            instrument,
        )
        if not historical:
            reasons.append("historical_instrument_identity_unknown")
        # Source-native rows cannot become manual merely because proof expired.
        manual = flow.source == "manual" and flow.amount_basis == "gross_components"
        journaled_scope = any(
            r.account_id == flow.account_id
            and r.reporting_month_id == flow.reporting_month_id
            and journal.kind(r) == journal.SOURCE
            for r in receipts
        )
        # Net-only source coupons require effective Money authority. A PDF is
        # corroboration and cannot restore a retired Money proof. Legacy typed
        # rows need an existing same-month mutation journal to supply ABA-safe
        # currentness; no new writer or inferred revision is introduced here.
        versioned = money_ok or (
            bool(valid_typed)
            and flow.amount_basis == "gross_components"
            and journaled_scope
            and not money_owned
        )
        if (valid_typed and not versioned) or (
            flow.amount_basis == "gross_components" and not journaled_scope and not money_ok
        ):
            reasons.append("canonical_revision_unavailable")
        if manual and not versioned:
            reasons.append("manual_revision_unavailable")
        if manual:
            proof_state = "manual_booked"
        elif versioned:
            proof_state = "source_accepted"
        elif money_owned:
            proof_state = "retired_or_unmatched"
        else:
            proof_state = "incomplete_unknown"
            reasons.append("payout_source_unproven")
        supported = (
            scope_ok and historical and "typed_statement_conflict" not in reasons and versioned
        )
        if not supported and proof_state == "source_accepted":
            proof_state = "incomplete_unknown"
        gross, tax, fee = (
            flow.gross_amount_kopecks,
            flow.tax_amount_kopecks,
            flow.commission_amount_kopecks,
        )
        if typed:
            # Even a linked-existing manual row stays manual, but PDF's unknown
            # tax must never be rendered as the legacy technical storage zero.
            accepted = [latest[e.id] for e in valid_typed]
            if accepted:
                gross = accepted[-1].gross_amount_kopecks
                tax = accepted[-1].tax_amount_kopecks if accepted[-1].tax_available else None
                fee = None
            else:
                gross = tax = fee = None
        if flow.currency != "RUB":
            gross = tax = fee = None
        if supported:
            totals[flow.flow_type].append(flow.net_amount_kopecks)
        events.append(
            {
                "cash_flow_id": flow.id,
                "kind": flow.flow_type,
                "date": flow.event_date.isoformat(),
                "booked_net": _money(flow.net_amount_kopecks) if flow.currency == "RUB" else None,
                "included_in_known_net": supported,
                "proof_state": proof_state,
                "currentness": "current" if supported else "unavailable",
                "gross": _money(gross),
                "tax": _money(tax),
                "fee": _money(fee),
                "tax_available": tax is not None,
                "receipt_ids": sorted(
                    ([money_target["receipt"]["request_id"]] if money_ok else [])
                    + [f"statement:{e.id}:revision:{latest[e.id].id}" for e in valid_typed]
                ),
                "provenance": (["manual"] if manual else [])
                + (["accepted_money_coupon"] if money_ok else [])
                + (["typed_depository"] if valid_typed else []),
                "reason_codes": sorted(set(reasons)),
            }
        )
    events.sort(key=lambda e: (e["date"], e["cash_flow_id"]))
    reasons = {
        "whole_interval_coverage_unknown",
        "full_instrument_return_unavailable",
        *reader_reasons,
    }
    if not events:
        reasons.add("no_observed_events")
    if any(not e["included_in_known_net"] for e in events):
        reasons.add("some_booked_rows_unproven")
    return {
        "method": METHOD,
        "version": VERSION,
        "account": {"id": account.id, "name": account.name},
        "instrument": {"id": instrument.id, "name": instrument.name},
        "t0": t0.isoformat(),
        "t1": t1.isoformat(),
        "currency": "RUB",
        "coverage": "unknown",
        "completeness": "unknown",
        "known_booked_net": {
            kind: _money(sum(values)) if values else None for kind, values in totals.items()
        },
        "event_count": len(events),
        "known_event_count": sum(e["included_in_known_net"] for e in events),
        "events": events,
        "reason_codes": sorted(reasons),
        "dependency_fingerprint": None
        if any(
            {"manual_revision_unavailable", "canonical_revision_unavailable"}.intersection(
                e["reason_codes"]
            )
            for e in events
        )
        else digest(
            {
                "method": METHOD,
                "version": VERSION,
                "scope": [account_id, instrument_id, str(t0), str(t1)],
                "account": material(account),
                "instrument": material(instrument),
                "dependencies": {
                    name: [material(r) for r in rows] for name, rows in dependencies.items()
                },
                "coupon_authority": money_material,
            }
        ),
    }
