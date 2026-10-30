"""Bounded Owner gold evidence, independent of broker trades and monthly books.

Amounts exclude separately charged fees. Unknown fees withhold results; tax is
not supplied by this source. Valuation always reads the existing saved snapshot.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from hermes_finance.database import coherent_read_operation
from hermes_finance.persistence import (
    Account,
    ClassNoCrossingCoverage,
    Instrument,
    OwnerManualGoldHistory,
    OwnerManualGoldHistoryApply,
    OwnerManualGoldHistoryRevision,
    PositionSnapshot,
    ReportingMonth,
)

VERSION = "owner_manual_gold_history_v1"
SOURCE = "owner_manual_gold_history"
DECIMAL = r"^(0|[1-9][0-9]{0,11})(\.[0-9]{1,6})?$"
MONEY = r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,2})?$"
KEY = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"


class GoldHistoryError(ValueError):
    pass


class GoldEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=KEY)
    event_date: date
    side: Literal["BUY", "SELL"]
    grams: str = Field(pattern=DECIMAL)
    amount_basis: Literal["actual", "derived_unit_price"]
    amount_rub: str | None = Field(default=None, pattern=MONEY)
    unit_price_rub: str | None = Field(default=None, pattern=MONEY)
    fee_state: Literal["known_zero", "known", "unknown"]
    fee_rub: str | None = Field(default=None, pattern=MONEY)

    @model_validator(mode="after")
    def consistent(self):
        if Decimal(self.grams) <= 0:
            raise ValueError("grams must be positive")
        if self.amount_basis == "actual":
            if self.amount_rub is None or self.unit_price_rub is not None:
                raise ValueError("actual amount requires only amount_rub")
        elif self.unit_price_rub is None or self.amount_rub is not None:
            raise ValueError("derived amount requires only unit_price_rub")
        if self.fee_state == "unknown" and self.fee_rub is not None:
            raise ValueError("unknown fee must not carry an amount")
        if self.fee_state == "known_zero" and self.fee_rub not in (None, "0", "0.0", "0.00"):
            raise ValueError("known_zero fee must be zero")
        if self.fee_state == "known" and self.fee_rub is None:
            raise ValueError("known fee requires fee_rub")
        return self


class GoldHistoryIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["owner_manual_gold_history_v1"] = VERSION
    account_id: int = Field(gt=0, strict=True)
    instrument_id: int = Field(gt=0, strict=True)
    expected_revision: int = Field(ge=0, strict=True)
    covered_from: date
    covered_to: date
    complete: StrictBool
    zero_start: StrictBool
    current_quantity: str = Field(pattern=DECIMAL)
    current_quantity_date: date
    provenance_reference: str = Field(min_length=1, max_length=128)
    change_reason: str | None = Field(default=None, min_length=1, max_length=500)
    events: list[GoldEvent] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def bounded(self):
        if self.covered_from > self.covered_to or self.current_quantity_date != self.covered_to:
            raise ValueError("quantity date must equal the ordered scope ending date")
        if not self.provenance_reference.strip():
            raise ValueError("provenance_reference must not be blank")
        if len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("event IDs must be unique within the history")
        if any(not self.covered_from <= e.event_date <= self.covered_to for e in self.events):
            raise ValueError("all events must be within the declared scope")
        return self


class GoldHistoryConfirmation(GoldHistoryIntent):
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(pattern=KEY)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value):
    return sha256(_canonical(value).encode()).hexdigest()


def _decimal(value):
    return format(Decimal(value).normalize(), "f")


def _minor(value):
    with localcontext() as ctx:
        ctx.prec = 80
        result = int((Decimal(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    if abs(result) > 2**63 - 1:
        raise GoldHistoryError("money_out_of_range")
    return result


def _intent(value):
    if isinstance(value, GoldHistoryConfirmation):
        return GoldHistoryIntent.model_validate(
            value.model_dump(exclude={"confirmation_digest", "request_id"})
        )
    return (
        value if isinstance(value, GoldHistoryIntent) else GoldHistoryIntent.model_validate(value)
    )


def _declaration(intent):
    data = intent.model_dump(mode="json", exclude={"expected_revision"})
    data["current_quantity"] = _decimal(data["current_quantity"])
    data["provenance_reference"] = data["provenance_reference"].strip()
    events = []
    for event in intent.events:
        with localcontext() as ctx:
            ctx.prec = 80
            amount = (
                _minor(event.amount_rub)
                if event.amount_basis == "actual"
                else _minor(Decimal(event.grams) * Decimal(event.unit_price_rub))
            )
        fee = None if event.fee_state == "unknown" else _minor(event.fee_rub or "0")
        events.append(
            dict(
                event_id=event.event_id,
                event_date=event.event_date.isoformat(),
                side=event.side,
                grams=_decimal(event.grams),
                amount_basis=event.amount_basis,
                amount_kopecks=str(amount),
                unit_price_rub=event.unit_price_rub,
                fee_state=event.fee_state,
                separate_fee_kopecks=None if fee is None else str(fee),
            )
        )
    data["events"] = sorted(events, key=lambda e: (e["event_date"], e["event_id"]))
    return data


def _columns(row):
    return {c.name: getattr(row, c.name) for c in row.__table__.columns} if row else None


def _history(session, account_id, instrument_id):
    return session.scalar(
        select(OwnerManualGoldHistory).where(
            OwnerManualGoldHistory.account_id == account_id,
            OwnerManualGoldHistory.instrument_id == instrument_id,
        )
    )


def _revisions(session, history_id):
    return list(
        session.scalars(
            select(OwnerManualGoldHistoryRevision)
            .where(OwnerManualGoldHistoryRevision.history_id == history_id)
            .order_by(OwnerManualGoldHistoryRevision.revision)
        )
    )


def _scope(session, account_id, instrument_id):
    account = session.get(Account, account_id, populate_existing=True)
    instrument = session.get(Instrument, instrument_id, populate_existing=True)
    if account is None or instrument is None:
        raise GoldHistoryError("account_or_instrument_not_found")
    if instrument.instrument_type != "gold" or instrument.currency != "RUB":
        raise GoldHistoryError("rub_gold_instrument_required")
    rows = session.execute(
        select(PositionSnapshot, ReportingMonth)
        .join(ReportingMonth, ReportingMonth.id == PositionSnapshot.reporting_month_id)
        .where(
            PositionSnapshot.account_id == account_id,
            PositionSnapshot.instrument_id == instrument_id,
        )
        .order_by(ReportingMonth.snapshot_date, PositionSnapshot.id)
    ).all()
    return account, instrument, rows


def _binding(account, instrument):
    return {
        "account_id": account.id,
        "instrument_id": instrument.id,
        "instrument_type": instrument.instrument_type,
        "currency": instrument.currency,
        "isin": instrument.isin,
    }


def _valuation(declaration, rows):
    start, end = (date.fromisoformat(declaration[key]) for key in ("covered_from", "covered_to"))
    selected = sorted(
        ((p, m) for p, m in rows if start <= p.price_date <= end),
        key=lambda pair: (pair[0].price_date, pair[1].snapshot_date, pair[0].id),
    )
    if not selected:
        return None
    position, month = selected[-1]
    return dict(
        snapshot_id=position.id,
        date=position.price_date.isoformat(),
        snapshot_date=month.snapshot_date.isoformat(),
        month_status=month.status,
        provisional=month.status != "closed",
        price_date=position.price_date.isoformat(),
        quantity=_decimal(position.quantity),
        market_value_kopecks=str(position.market_value_kopecks),
        price_source=position.price_source,
    )


def _result(declaration, valuation):
    all_events = declaration["events"]
    reasons = set()
    with localcontext() as ctx:
        ctx.prec = 80
        declared_quantity = sum(
            (Decimal(e["grams"]) * (1 if e["side"] == "BUY" else -1) for e in all_events),
            Decimal(0),
        )
        daily = defaultdict(Decimal)
        for event in all_events:
            daily[event["event_date"]] += Decimal(event["grams"]) * (
                1 if event["side"] == "BUY" else -1
            )
        running = Decimal(0)
        for day in sorted(daily):
            running += daily[day]
            if running < 0:
                reasons.add("gold_negative_running_quantity")
    if not declaration["complete"]:
        reasons.add("gold_trade_history_incomplete")
    if not declaration["zero_start"]:
        reasons.add("gold_zero_start_unproven")
    if declared_quantity != Decimal(declaration["current_quantity"]):
        reasons.add("gold_quantity_mismatch")

    # A later completeness declaration can support an earlier saved valuation.
    # Its exact event prefix supplies grams and cash at the actual quote date;
    # snapshot holding quantity and quote date must describe that same prefix.
    zero_holding = declared_quantity == 0 and Decimal(declaration["current_quantity"]) == 0
    as_of = declaration["covered_to"] if zero_holding or valuation is None else valuation["date"]
    events = [event for event in all_events if event["event_date"] <= as_of]
    buys = sum(int(e["amount_kopecks"]) for e in events if e["side"] == "BUY")
    sales = sum(int(e["amount_kopecks"]) for e in events if e["side"] == "SELL")
    sale_events = [e for e in events if e["side"] == "SELL"]
    sale_fees_known = all(e["separate_fee_kopecks"] is not None for e in sale_events)
    fees_known = all(e["separate_fee_kopecks"] is not None for e in events)
    fees = sum(int(e["separate_fee_kopecks"]) for e in events) if fees_known else None
    with localcontext() as ctx:
        ctx.prec = 80
        quantity = sum(
            (Decimal(e["grams"]) * (1 if e["side"] == "BUY" else -1) for e in events), Decimal(0)
        )
    if not fees_known:
        reasons.add("gold_separate_fees_unknown")
    prefix_available = declaration["covered_from"] <= as_of <= declaration["covered_to"]
    if not prefix_available:
        reasons.add("gold_valuation_outside_complete_scope")
    trade_reasons = set(reasons)
    valuation_reasons = set()
    value = None
    if zero_holding:
        value = 0  # Affirmative zero grams needs no invented quote.
    elif valuation is not None:
        if not prefix_available:
            valuation_reasons.add("gold_valuation_outside_complete_scope")
        elif Decimal(valuation["quantity"]) != quantity:
            valuation_reasons.add("gold_snapshot_quantity_mismatch")
        else:
            value = int(valuation["market_value_kopecks"])
        if valuation["price_date"] > valuation["snapshot_date"]:
            valuation_reasons.add("gold_future_price_date")
    else:
        valuation_reasons.add("gold_saved_valuation_unavailable")
    reasons.update(valuation_reasons)
    total = value + sales - buys - fees if not reasons and value is not None else None
    realized = unrealized = remaining_cost = None
    decomposition_reasons = []
    purchases = [e for e in events if e["side"] == "BUY"]
    if not trade_reasons:
        if not events:
            realized, remaining_cost = 0, 0
            if value is not None and not valuation_reasons:
                unrealized = value
        elif len(purchases) == 1:
            purchase = purchases[0]
            with localcontext() as ctx:
                ctx.prec = 80
                purchased = Decimal(purchase["grams"])
                sold = purchased - quantity
                purchase_cost = int(purchase["amount_kopecks"]) + int(
                    purchase["separate_fee_kopecks"]
                )
                sold_cost = int(
                    (Decimal(purchase_cost) * sold / purchased).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
            sale_fees = sum(int(e["separate_fee_kopecks"]) for e in events if e["side"] == "SELL")
            remaining_cost = purchase_cost - sold_cost
            realized = sales - sale_fees - sold_cost
            if value is not None and not valuation_reasons:
                unrealized = value - remaining_cost
        else:
            decomposition_reasons.append("gold_cost_allocation_unproven")

    def money(value):
        return None if value is None else str(value)

    return dict(
        total_result_kopecks=money(total),
        realized_result_kopecks=money(realized),
        unrealized_result_kopecks=money(unrealized),
        remaining_cost_kopecks=money(remaining_cost),
        buy_amount_kopecks=str(buys) if prefix_available else None,
        sale_amount_kopecks=str(sales) if prefix_available else None,
        separate_fees_kopecks=money(fees) if prefix_available else None,
        net_sales_kopecks=money(
            sales - sum(int(e["separate_fee_kopecks"]) for e in sale_events)
            if sale_fees_known and prefix_available
            else None
        ),
        calculated_quantity=_decimal(quantity) if prefix_available else None,
        declared_calculated_quantity=_decimal(declared_quantity),
        valuation_kopecks=money(value),
        as_of_date=as_of,
        valuation_date=as_of if zero_holding or valuation is not None else None,
        valuation_basis=(
            "owner_declared_zero_quantity"
            if zero_holding
            else "saved_snapshot_quote"
            if valuation is not None
            else None
        ),
        valuation_provisional=(
            valuation["provisional"] if valuation is not None and not zero_holding else None
        ),
        period={"covered_from": declaration["covered_from"], "covered_to": as_of},
        amount_basis="derived" if any(e["amount_basis"] != "actual" for e in events) else "actual",
        tax_treatment="not_provided",
        method="owner_gold_complete_from_zero",
        reason_codes=sorted(reasons),
        total_reason_codes=sorted(reasons),
        realized_reason_codes=sorted(trade_reasons | set(decomposition_reasons)),
        unrealized_reason_codes=sorted(
            trade_reasons | valuation_reasons | set(decomposition_reasons)
        ),
        decomposition_reason_codes=decomposition_reasons,
    )


def _plan(session, intent):
    account, instrument, rows = _scope(session, intent.account_id, intent.instrument_id)
    history = _history(session, account.id, instrument.id)
    revisions = _revisions(session, history.id) if history else []
    latest = revisions[-1] if revisions else None
    if intent.expected_revision != (latest.revision if latest else 0):
        raise GoldHistoryError("gold_revision_conflict")
    declaration = _declaration(intent)
    prior = json.loads(latest.declaration_json) if latest else None
    changed = declaration != prior
    if latest and changed and not (intent.change_reason and intent.change_reason.strip()):
        raise GoldHistoryError("gold_correction_reason_required")
    valuation = _valuation(declaration, rows)
    coverages = list(
        session.scalars(
            select(ClassNoCrossingCoverage)
            .where(ClassNoCrossingCoverage.asset_class == "gold")
            .order_by(ClassNoCrossingCoverage.id)
        )
    )
    dependencies = dict(
        account=_columns(account),
        instrument=_columns(instrument),
        snapshots=[[_columns(p), _columns(m)] for p, m in rows],
        revisions=[_columns(r) for r in revisions],
        gold_coverages=[_columns(c) for c in coverages],
    )
    return dict(
        contract_version=VERSION,
        source_kind=SOURCE,
        authority="owner_attestation",
        history_id=history.id if history else None,
        expected_revision=intent.expected_revision,
        action="create" if not latest else "revise" if changed else "noop",
        declaration=declaration,
        valuation=valuation,
        result=_result(declaration, valuation),
        bindings=_binding(account, instrument),
        confirmation_digest=_digest(
            dict(intent=intent.model_dump(mode="json"), dependencies=dependencies)
        ),
        can_apply=True,
    )


@coherent_read_operation
def preview_gold_history(session: Session, intent: GoldHistoryIntent | dict):
    return _plan(session, _intent(intent))


def _read(session, history, *, include_events=True):
    revisions = _revisions(session, history.id)
    latest = revisions[-1]
    declaration = json.loads(latest.declaration_json)
    reasons = []
    valuation = None
    try:
        account, instrument, rows = _scope(session, history.account_id, history.instrument_id)
        if json.loads(latest.bindings_json) != _binding(account, instrument):
            reasons.append("gold_catalogue_binding_changed")
        valuation = _valuation(declaration, rows)
    except GoldHistoryError as error:
        reasons.append(str(error))
    result = _result(declaration, valuation)
    if reasons:
        for key in (
            "total_result_kopecks",
            "realized_result_kopecks",
            "unrealized_result_kopecks",
            "remaining_cost_kopecks",
        ):
            result[key] = None
        result["reason_codes"] = sorted(set(result["reason_codes"] + reasons))
        for key in ("total_reason_codes", "realized_reason_codes", "unrealized_reason_codes"):
            result[key] = sorted(set(result[key] + reasons))
    return dict(
        contract_version=VERSION,
        source_kind=SOURCE,
        authority="owner_attestation",
        history_id=history.id,
        revision=latest.revision,
        account_id=history.account_id,
        instrument_id=history.instrument_id,
        currentness="current" if not reasons else "dependency_changed",
        declaration=declaration if include_events else dict(declaration, events=[]),
        events=declaration["events"] if include_events else [],
        events_loaded=include_events,
        valuation=valuation,
        result=result,
        reason_codes=sorted(set(reasons + result["reason_codes"])),
        revisions=[
            dict(
                revision=r.revision,
                declaration=json.loads(r.declaration_json),
                accepted_at=r.accepted_at.isoformat(),
            )
            for r in revisions
            if include_events
        ],
    )


@coherent_read_operation
def read_gold_history(session: Session, history_id: int):
    history = session.get(OwnerManualGoldHistory, history_id, populate_existing=True)
    if history is None:
        raise GoldHistoryError("gold_history_not_found")
    return _read(session, history)


@coherent_read_operation
def read_gold_histories(
    session: Session, *, account_id=None, instrument_id=None, include_events=True
):
    query = select(OwnerManualGoldHistory).order_by(OwnerManualGoldHistory.id)
    if account_id is not None:
        query = query.where(OwnerManualGoldHistory.account_id == account_id)
    if instrument_id is not None:
        query = query.where(OwnerManualGoldHistory.instrument_id == instrument_id)
    return [_read(session, h, include_events=include_events) for h in session.scalars(query)]


@coherent_read_operation
def read_gold_history_receipt(session: Session, request_id: str):
    receipt = session.scalar(
        select(OwnerManualGoldHistoryApply).where(
            OwnerManualGoldHistoryApply.request_id == request_id
        )
    )
    if receipt is None:
        raise GoldHistoryError("gold_request_not_found")
    revision = session.get(OwnerManualGoldHistoryRevision, receipt.revision_id)
    return dict(
        contract_version=VERSION,
        request_id=request_id,
        accepted_revision=revision.revision,
        history=_read(session, session.get(OwnerManualGoldHistory, revision.history_id)),
    )


def gold_crossing_evidence(session, accounts, start, end):
    """Current crossings and retained revision material have distinct meanings.

    A reviewed correction can remove an erroneous crossing. All revisions stay
    bound to the prior affected interval, so no old no-crossing claim revives.
    """
    material, crossings = [], []
    for history in session.scalars(
        select(OwnerManualGoldHistory)
        .where(OwnerManualGoldHistory.account_id.in_(accounts))
        .order_by(OwnerManualGoldHistory.id)
    ):
        revisions = _revisions(session, history.id)
        relevant = False
        for revision in revisions:
            events = [
                e["event_id"]
                for e in json.loads(revision.declaration_json)["events"]
                if start <= date.fromisoformat(e["event_date"]) <= end
            ]
            relevant |= bool(events)
            if revision is revisions[-1] and events:
                crossings.append((history.id, revision.revision, events))
        if relevant:
            material.extend((history.id, r.revision, r.material_fingerprint) for r in revisions)
    return {"material": material, "crossings": crossings}


def _invalidate_coverages(session, declarations):
    dates = {date.fromisoformat(e["event_date"]) for d in declarations for e in d["events"]}
    for coverage in session.scalars(
        select(ClassNoCrossingCoverage).where(
            ClassNoCrossingCoverage.asset_class == "gold",
            ClassNoCrossingCoverage.coverage_state == "complete",
        )
    ):
        if any(coverage.covered_from <= day <= coverage.covered_to for day in dates):
            coverage.coverage_state = "unknown"
            coverage.material_signature = None
            coverage.revision += 1


def apply_gold_history(session: Session, confirmation: GoldHistoryConfirmation | dict):
    request = (
        confirmation
        if isinstance(confirmation, GoldHistoryConfirmation)
        else GoldHistoryConfirmation.model_validate(confirmation)
    )
    intent = _intent(request)
    if session.new or session.dirty or session.deleted:
        raise GoldHistoryError("session_has_pending_changes")
    fingerprint = _digest(request.model_dump(mode="json"))
    session.rollback()
    try:
        session.execute(
            update(OwnerManualGoldHistory)
            .where(OwnerManualGoldHistory.id == -1)
            .values(id=OwnerManualGoldHistory.id)
        )
        session.expire_all()
        receipt = session.scalar(
            select(OwnerManualGoldHistoryApply).where(
                OwnerManualGoldHistoryApply.request_id == request.request_id
            )
        )
        duplicate = receipt is not None
        if receipt:
            if receipt.request_fingerprint != fingerprint:
                raise GoldHistoryError("idempotency_conflict")
            accepted = session.get(OwnerManualGoldHistoryRevision, receipt.revision_id)
        else:
            plan = _plan(session, intent)
            if plan["confirmation_digest"] != request.confirmation_digest:
                raise GoldHistoryError("gold_preview_stale")
            history = _history(session, intent.account_id, intent.instrument_id)
            now = datetime.now(UTC)
            if history is None:
                history = OwnerManualGoldHistory(
                    account_id=intent.account_id, instrument_id=intent.instrument_id, created_at=now
                )
                session.add(history)
                session.flush()
            revisions = _revisions(session, history.id)
            if plan["action"] == "noop":
                accepted = revisions[-1]
            else:
                accepted = OwnerManualGoldHistoryRevision(
                    history_id=history.id,
                    revision=intent.expected_revision + 1,
                    contract_version=VERSION,
                    declaration_json=_canonical(plan["declaration"]),
                    bindings_json=_canonical(plan["bindings"]),
                    material_fingerprint=_digest(plan["declaration"]),
                    confirmation_digest=request.confirmation_digest,
                    accepted_at=now,
                )
                session.add(accepted)
                session.flush()
                declarations = [plan["declaration"]]
                if revisions:
                    declarations.append(json.loads(revisions[-1].declaration_json))
                _invalidate_coverages(session, declarations)
            receipt = OwnerManualGoldHistoryApply(
                request_id=request.request_id,
                request_fingerprint=fingerprint,
                revision_id=accepted.id,
                accepted_at=now,
            )
            session.add(receipt)
            session.flush()
        history_id, revision = accepted.history_id, accepted.revision
        session.commit()
    except Exception:
        session.rollback()
        raise
    return dict(
        contract_version=VERSION,
        request_id=request.request_id,
        duplicate=duplicate,
        accepted_revision=revision,
        history=read_gold_history(session, history_id),
    )
