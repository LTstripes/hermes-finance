"""Two persisted EOD observations, not a security performance calculation.

The existing source receipt owns native projection/identity, PositionSnapshot
owns observed value. Payouts use #858 unchanged in the same committed snapshot.
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
    BrokerIdentityMapping,
    BrokerMonthApply,
    Instrument,
    MyBrokerCorrectionChange,
    MyBrokerCorrectionRevision,
    MyBrokerDispositionChange,
    MyBrokerDispositionRevision,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services import broker_months
from hermes_finance.services.broker_money import material
from hermes_finance.services.instrument_cash_income import (
    _historical_identity,
    known_instrument_cash_income,
)
from hermes_finance.services.mybroker_corrections import _source_integrity
from hermes_finance.services.mybroker_dispositions import accepted_account_binding
from hermes_finance.statement_import.mybroker import MyBrokerError, digest

METHOD = "persisted-instrument-eod-pair"
VERSION = 1


def _rows(session, model, *conditions):
    return list(
        session.scalars(
            select(model).where(*conditions).order_by(*model.__table__.primary_key.columns)
        )
    )


def _inventory(session, account, instrument, t0, t1):
    positions = _rows(
        session,
        PositionSnapshot,
        PositionSnapshot.account_id == account.id,
        PositionSnapshot.instrument_id == instrument.id,
    )
    receipts = _rows(session, BrokerMonthApply, BrokerMonthApply.account_id == account.id)
    mappings = _rows(session, BrokerIdentityMapping)
    aliases = {
        m.provider_identity
        for m in mappings
        if m.subject_kind == "account" and m.hermes_account_id == account.id
    }
    retained = {p.source_import_id for p in positions} | {r.import_id for r in receipts}
    sources = []
    for source in _rows(session, MyBrokerImport):
        # Retain original aliases and receipt IDs after revoke/remap/deletion.
        # Only relevant originals are hashed; unrelated account text is absent.
        try:
            bindings = json.loads(source.mappings_json)
            belongs = any(
                b["kind"] == "account"
                and (b["hermes_id"] == account.id or b["identity"] in aliases)
                for b in bindings
            )
            doc = json.loads(source.normalized_json)
            belongs |= doc.get("filename_account") in aliases
        except (ValueError, TypeError, KeyError, AttributeError):
            belongs = source.id in retained
        if source.id in retained or (
            belongs and source.covered_from <= t1 and source.covered_to >= t0
        ):
            sources.append(source)
    source_ids = {s.id for s in sources}
    scoped_mappings = [
        m
        for m in mappings
        if (m.subject_kind == "account" and m.provider_identity in aliases)
        or (
            m.subject_kind == "instrument"
            and (m.hermes_instrument_id == instrument.id or m.provider_identity == instrument.isin)
        )
    ]
    history = {}
    for model in (
        MyBrokerCorrectionRevision,
        MyBrokerDispositionRevision,
        MyBrokerDispositionChange,
    ):
        history[model.__tablename__] = [
            material(r) for r in _rows(session, model, model.import_id.in_(source_ids))
        ]
    # Existing correction authority has a global monotonic generation, including
    # SQL source/registry/catalogue ABA. Bind the counter, not unrelated originals.
    changes = _rows(session, MyBrokerCorrectionChange)
    history["correction_generation"] = changes[-1].id if changes else 0
    months = {m.id: m for m in _rows(session, ReportingMonth)}
    scoped_months = [
        m
        for m in months.values()
        if m.snapshot_date in {t0, t1} or m.id in {p.reporting_month_id for p in positions}
    ]
    # The authority checks the whole native account/month projection. Bind its
    # current readback too, including cash/other securities, without importing
    # unrelated accounts' original source text into this dependency token.
    native_readbacks = [
        [r.request_id, broker_months._projection(session, r)]
        for r in receipts
        if journal.kind(r) == journal.SOURCE
        and r.reporting_month_id in months
        and months[r.reporting_month_id].snapshot_date in {t0, t1}
    ]
    signature = digest(
        {
            "method": METHOD,
            "version": VERSION,
            "scope": [account.id, instrument.id, str(t0), str(t1)],
            "account": material(account),
            "instrument": material(instrument),
            "positions": [material(p) for p in positions],
            "months": [material(m) for m in scoped_months],
            "receipts": [material(r) for r in receipts],
            "native_readbacks": native_readbacks,
            "sources": [[s.id, digest(material(s))] for s in sources],
            "mappings": [material(m) for m in scoped_mappings],
            "history": history,
        }
    )
    return positions, receipts, months, signature, history["correction_generation"]


def _boundary(
    session, account, instrument, day, positions, receipts, months, signature, generation
):
    reasons = set()
    candidates = [
        p
        for p in positions
        if p.price_date == day
        or (p.reporting_month_id in months and months[p.reporting_month_id].snapshot_date == day)
    ]
    exact_months = [m for m in months.values() if m.snapshot_date == day]
    row = candidates[0] if len(candidates) == 1 else None
    scope_receipts = [
        r
        for r in receipts
        if r.reporting_month_id in {m.id for m in exact_months}
        and journal.kind(r) == journal.SOURCE
    ]
    if account.account_type not in {"brokerage", "iis"}:
        reasons.add("brokerage_or_iis_required")
    if len(exact_months) > 1 or len(candidates) > 1:
        reasons.add("ambiguous_eod_period")
    if not candidates:
        reasons.add("exact_eod_position_missing")
    if row is not None:
        month = months.get(row.reporting_month_id)
        if month is None or row.archived_from_period is not None:
            reasons.add("archived_position_unavailable")
        elif month.snapshot_date != day or row.price_date != day or month.period_end != day:
            reasons.add("exact_eod_date_mismatch")
        if row.price_source != "broker_statement_native" or row.native_contract_version != 1:
            reasons.add("native_position_authority_unavailable")
        if row.historical_instrument_type not in {"stock", "bond"}:
            reasons.add("historical_identity_unknown")
        if row.quantity is None or not row.quantity.is_finite() or row.quantity <= 0:
            reasons.add("zero_inventory_entitlement_unproven")
        if type(row.market_value_kopecks) is not int or row.market_value_kopecks < 0:
            reasons.add("observed_value_unavailable")
    accepted = []
    identity = None
    if row is not None and not reasons:
        for receipt in scope_receipts:
            proof = journal.payload(receipt)
            if receipt.import_id != row.source_import_id or row.id not in proof["position_ids"]:
                continue
            try:
                source = session.get(MyBrokerImport, receipt.import_id)
                document = json.loads(source.normalized_json) if source else {}
                frozen = proof["instruments"].get(str(instrument.id))
                if not source or not _source_integrity(source, document):
                    reasons.add("source_evidence_invalid")
                    continue
                reasons.update(broker_months._overlap(session, document, account.id))
                if not _historical_identity(session, [receipt], row, instrument):
                    reasons.add("historical_identity_or_mapping_changed")
                    continue
                if frozen != [instrument.isin, row.historical_instrument_type, "RUB"]:
                    reasons.add("historical_identity_or_mapping_changed")
                    continue
                if broker_months._projection(session, receipt) != proof["projection_digest"]:
                    reasons.add("native_projection_changed")
                if (
                    source.covered_to != day
                    or document.get("endpoint_basis", {}).get("ending_value") != "covered_to_eod"
                ):
                    reasons.add("source_eod_date_mismatch")
                original_rows = [p for p in document["positions"] if p["isin"] == frozen[0]]
                if len(original_rows) != 1:
                    reasons.add("source_position_conflict")
                    continue
                original = original_rows[0]
                binding = accepted_account_binding(session, source, original["source_account"])
                if binding is None or binding["hermes_id"] != account.id:
                    reasons.add("source_account_mismatch")
                if row.source_row_key != digest(
                    ["mybroker-native-position-v1", account.id, frozen[0], day.isoformat()]
                ):
                    reasons.add("source_row_identity_mismatch")
                if (
                    Decimal(original["actual_quantity"]) != row.quantity
                    or broker_months._minor(original["ending_value"]) != row.market_value_kopecks
                ):
                    reasons.add("source_position_value_mismatch")
                identity = {
                    "isin": frozen[0],
                    "instrument_type": frozen[1],
                    "denomination": frozen[2],
                }
                accepted.append(receipt.request_id)
            except (
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                MyBrokerError,
                DecimalException,
            ):
                reasons.add("source_reader_unavailable")
        if not accepted:
            reasons.add("native_receipt_unavailable")
    if not scope_receipts:
        reasons.add("revision_journal_unavailable")
    current = row is not None and not reasons
    return {
        "date": day.isoformat(),
        "account_id": account.id,
        "instrument_id": instrument.id,
        "availability": "available" if current else "unavailable",
        "quantity": format(row.quantity.normalize(), "f") if current else None,
        "market_value": RubleAmount(row.market_value_kopecks).to_api() if current else None,
        "currency": "RUB",
        "historical_identity": identity if current else None,
        "bond_nkd_basis": row.bond_nkd_basis if current else None,
        "price_date": row.price_date.isoformat() if row else None,
        "position_id": row.id if row else None,
        "price_source": row.price_source if row else None,
        "source_import_id": row.source_import_id if row else None,
        "source_row_key": row.source_row_key if row else None,
        "receipt_ids": sorted(accepted),
        "revision_generation": generation if scope_receipts else None,
        "proof_state": "source_accepted" if current else "unavailable",
        "currentness": "current" if current else "unavailable",
        "dependency_fingerprint": digest([signature, str(day)]) if scope_receipts else None,
        "reason_codes": sorted(reasons),
    }


def compare_observations(opening, closing):
    """Compare economic value basis only; never infer unchanged units/activity."""
    reasons = {"full_instrument_return_unavailable", "interval_activity_unknown"}
    comparable = None
    difference = None
    if opening["availability"] == closing["availability"] == "available":
        a, b = opening["historical_identity"], closing["historical_identity"]
        if a != b:
            comparable = False
            reasons.add("boundary_identity_incomparable")
        elif "unknown" in {opening["bond_nkd_basis"], closing["bond_nkd_basis"]}:
            reasons.add("bond_nkd_basis_unknown")
        elif opening["bond_nkd_basis"] != closing["bond_nkd_basis"]:
            comparable = False
            reasons.add("bond_nkd_basis_incomparable")
        else:
            comparable = True
            difference = RubleAmount(
                RubleAmount.from_api(closing["market_value"]).kopecks
                - RubleAmount.from_api(opening["market_value"]).kopecks
            )
        if opening["quantity"] != closing["quantity"]:
            reasons.add("quantity_changed_not_profit")
    else:
        reasons.add("boundary_observation_unavailable")
    return comparable, difference.to_api() if difference is not None else None, sorted(reasons)


@coherent_read_operation
def instrument_eod_observations(session, account_id: int, instrument_id: int, t0: date, t1: date):
    if t0 >= t1:
        raise ValueError("t0 must precede t1")
    account, instrument = session.get(Account, account_id), session.get(Instrument, instrument_id)
    if account is None or instrument is None:
        raise LookupError("account or instrument not found")
    positions, receipts, months, signature, generation = _inventory(
        session, account, instrument, t0, t1
    )
    opening = _boundary(
        session, account, instrument, t0, positions, receipts, months, signature, generation
    )
    closing = _boundary(
        session, account, instrument, t1, positions, receipts, months, signature, generation
    )
    comparable, difference, reasons = compare_observations(opening, closing)
    payouts = known_instrument_cash_income(session, account_id, instrument_id, t0, t1)
    return {
        "method": METHOD,
        "version": VERSION,
        "account": {"id": account.id, "name": account.name},
        "instrument": {"id": instrument.id, "name": instrument.name},
        "t0": str(t0),
        "t1": str(t1),
        "currency": "RUB",
        "opening": opening,
        "closing": closing,
        "comparable": comparable,
        "observed_position_value_difference": difference,
        "reason_codes": reasons,
        "valuation_dependency_fingerprint": signature
        if all(b["dependency_fingerprint"] for b in (opening, closing))
        else None,
        "dependency_fingerprint": digest([signature, payouts["dependency_fingerprint"]])
        if all(b["dependency_fingerprint"] for b in (opening, closing))
        and payouts["dependency_fingerprint"]
        else None,
        "known_payouts": payouts,
    }
