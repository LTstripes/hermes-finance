"""Scoped payout dependency generations in the existing reserved receipt journal."""

import json
from datetime import UTC, datetime
from itertools import product
from uuid import uuid4

from sqlalchemy import event, insert, inspect, select, update
from sqlalchemy.orm import Session

from hermes_finance.actual_payout_schema import ECF_MATERIAL
from hermes_finance.persistence import (
    Account,
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    BrokerIdentityMapping,
    BrokerMonthApply,
    ExpectedCashFlow,
    Instrument,
    InstrumentMarketMapping,
    InvestmentCashFlow,
    MyBrokerCorrectionRevision,
    MyBrokerDispositionRevision,
    MyBrokerImport,
    ReportingMonth,
    SecurityRegIsinMapping,
)
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services.broker_money_lifecycle import (
    _append_receipt,
    _values,
    next_journal_revision,
)
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical, digest


def _material_change(session, row):
    if row in session.new or row in session.deleted:
        return True
    fields = (
        ECF_MATERIAL
        if isinstance(row, ExpectedCashFlow)
        else tuple(c.key for c in row.__table__.columns)
    )
    return any(inspect(row).attrs[f].history.has_changes() for f in fields)


def _forecast_affects(session, row, actual, links):
    if isinstance(row, AppliedPayoutRevision):
        row = session.get(AppliedProviderPayout, row.applied_payout_id)
        if row is None:
            return False
    kind = "event_kind" if isinstance(row, AppliedProviderPayout) else "flow_type"
    if actual.account_id not in _values(row, "account_id") or actual.instrument_id not in _values(
        row, "instrument_id"
    ):
        return False
    if actual.flow_type not in _values(row, kind):
        return False
    if any(
        (
            link.applied_payout_id
            if isinstance(row, AppliedProviderPayout)
            else link.expected_cash_flow_id
        )
        == row.id
        for link in links
    ):
        return True
    if isinstance(row, AppliedProviderPayout):
        # A new/deleted projection of an already reviewed canonical event is
        # relevant even outside the conservative date candidate window.
        keys = {
            digest(["actual-provider-event-v1", *values])
            for values in product(
                *(
                    _values(row, field)
                    for field in (
                        "account_id",
                        "instrument_id",
                        "provider",
                        "provider_instrument_uid",
                        "event_kind",
                        "identity_key",
                    )
                )
            )
        }
        if any(link.provider_event_key in keys for link in links):
            return True
    from hermes_finance.services.actual_payouts import _future_bounds

    for month_id in _values(row, "reporting_month_id"):
        month = session.get(ReportingMonth, month_id) if month_id else None
        if month is None:
            continue
        start, end = _future_bounds(month)
        if any(
            day and start <= day < end and abs((day - actual.event_date).days) <= 3
            for day in _values(
                row, "payment_date" if isinstance(row, AppliedProviderPayout) else "expected_date"
            )
        ):
            return True
    return False


def _affects(session, row, actual, base, links):
    if isinstance(row, (AppliedProviderPayout, AppliedPayoutRevision, ExpectedCashFlow)):
        return _forecast_affects(session, row, actual, links)
    if isinstance(row, Account):
        return row.id == actual.account_id
    if isinstance(row, Instrument):
        return row.id == actual.instrument_id
    if isinstance(row, InstrumentMarketMapping):
        return actual.instrument_id in _values(row, "instrument_id")
    if isinstance(row, BrokerIdentityMapping):
        return actual.account_id in _values(
            row, "hermes_account_id"
        ) or actual.instrument_id in _values(row, "hermes_instrument_id")
    if isinstance(row, SecurityRegIsinMapping):
        instrument = session.get(Instrument, actual.instrument_id)
        return instrument.isin in _values(row, "isin")
    if isinstance(row, InvestmentCashFlow):
        return row.id == actual.id
    if isinstance(row, ReportingMonth):
        ids = {actual.reporting_month_id}
        # Include possible explicit selections before the first link exists.
        # The resulting generation token is filtered to the reviewed month set.
        for model in (AppliedProviderPayout, ExpectedCashFlow):
            kind = model.event_kind if model is AppliedProviderPayout else model.flow_type
            ids.update(
                session.scalars(
                    select(model.reporting_month_id).where(
                        model.account_id == actual.account_id,
                        model.instrument_id == actual.instrument_id,
                        kind == actual.flow_type,
                    )
                )
            )
        for link in links:
            for model, ident in (
                (AppliedProviderPayout, link.applied_payout_id),
                (ExpectedCashFlow, link.expected_cash_flow_id),
            ):
                forecast = session.get(model, ident) if ident else None
                if forecast:
                    ids.add(forecast.reporting_month_id)
        if row.id not in ids:
            return False
        # Normal Close preserves the accepted proof. Reopen always changes its generation.
        return (
            "closed" in inspect(row).attrs.status.history.deleted
            or (row.status == "draft" and inspect(row).attrs.updated_at.history.has_changes())
            or any(
                inspect(row).attrs[f].history.has_changes()
                for f in ("year", "month", "snapshot_date", "period_start", "period_end")
            )
        )
    if isinstance(row, MyBrokerImport):
        month = session.get(ReportingMonth, actual.reporting_month_id)
        return row.id == base.import_id or (
            row.covered_from <= month.period_end
            and row.covered_to >= month.period_start
            and any(
                b["kind"] == "account" and b["hermes_id"] == actual.account_id
                for b in json.loads(row.mappings_json)
            )
        )
    if isinstance(row, (MyBrokerCorrectionRevision, MyBrokerDispositionRevision)):
        source = session.get(MyBrokerImport, row.import_id)
        return source is not None and _affects(session, source, actual, base, links)
    if isinstance(row, BrokerMonthApply) and journal.kind(row) in journal.MONEY_KINDS:
        return any(
            t.get("role") == actual.flow_type and t.get("target_id") == actual.id
            for t in journal.payload(row).get("targets", [])
        )
    return False


def _require_editable_history(session, link):
    receipt = session.get(BrokerMonthApply, link.accepted_request_id)
    if receipt is None:
        raise MyBrokerError("payout_history_receipt_missing")
    ids = {receipt.reporting_month_id}
    proof = journal.payload(receipt)
    ids.update(ref["reporting_month_id"] for ref in proof.get("paid_forecasts", []))
    for candidate in proof.get("dependency", {}).get("candidates", []):
        facts = candidate["facts"]
        if (candidate["kind"] == "app" and str(link.applied_payout_id) == facts["id"]) or (
            candidate["kind"] == "ecf" and str(link.expected_cash_flow_id) == facts["id"]
        ):
            if facts.get("reporting_month_id"):
                ids.add(int(facts["reporting_month_id"]))
    if any(
        (month := session.get(ReportingMonth, ident)) is None or month.status != "draft"
        for ident in ids
    ):
        raise MyBrokerError("payout_involved_scope_requires_reopen")


def _retire(session, base, link):
    _require_editable_history(session, link)
    request = digest([journal.PAYOUT, "dependency-retirement", uuid4().hex])
    proof = {
        "contract_version": journal.PAYOUT,
        "operation": "retire",
        "base_request_id": base.request_id,
        "journal_revision": next_journal_revision(session),
        "reason_code": "payout_dependency_changed",
        "targets": [
            {"relation_id": link.id, "investment_cash_flow_id": link.investment_cash_flow_id}
        ],
    }
    # The typed receipt must precede the guarded one-time stamp, in this transaction.
    session.execute(
        insert(BrokerMonthApply).values(
            request_id=request,
            request_fingerprint=request,
            confirmation_digest=request,
            reporting_month_id=base.reporting_month_id,
            account_id=base.account_id,
            import_id=base.import_id,
            projection_json=canonical(proof),
            accepted_at=datetime.now(UTC),
        )
    )
    session.execute(
        update(AppliedPayoutReconciliation)
        .where(AppliedPayoutReconciliation.id == link.id)
        .values(retired_request_id=request)
    )


def _before_flush(session, _context, _instances):
    changes = [
        r for r in (*session.new, *session.dirty, *session.deleted) if _material_change(session, r)
    ]
    if not changes or not inspect(session.connection()).has_table("applied_payout_reconciliations"):
        return
    with session.no_autoflush:
        bases = [
            r
            for r in session.scalars(select(BrokerMonthApply))
            if journal.kind(r) == journal.SOURCE
        ]
        if not bases:
            return
        session.execute(
            update(BrokerMonthApply)
            .where(BrokerMonthApply.request_id == "")
            .values(request_id=BrokerMonthApply.request_id)
        )
        for base in bases:
            affected = []
            changed_month_ids = set()
            has_material_change = False
            actuals = session.scalars(
                select(InvestmentCashFlow).where(
                    InvestmentCashFlow.account_id == base.account_id,
                    InvestmentCashFlow.reporting_month_id == base.reporting_month_id,
                    InvestmentCashFlow.flow_type.in_(("coupon", "dividend")),
                )
            )
            for actual in actuals:
                links = list(
                    session.scalars(
                        select(AppliedPayoutReconciliation).where(
                            AppliedPayoutReconciliation.investment_cash_flow_id == actual.id
                        )
                    )
                )
                relevant = [r for r in changes if _affects(session, r, actual, base, links)]
                if not relevant:
                    continue
                affected.append(actual.id)
                # Reopen leaves the historical row immutable and stale until reviewed.
                material = [r for r in relevant if not isinstance(r, ReportingMonth)]
                changed_month_ids.update(r.id for r in relevant if isinstance(r, ReportingMonth))
                has_material_change = has_material_change or bool(material)
                if material:
                    for link in links:
                        _require_editable_history(session, link)
                        if link.retired_request_id is None:
                            _retire(session, base, link)
            if affected:
                _append_receipt(
                    session,
                    base,
                    {
                        "contract_version": journal.PAYOUT_DEPENDENCY,
                        "base_request_id": base.request_id,
                        "reason_code": "payout_dependency_changed",
                        "investment_cash_flow_ids": sorted(affected),
                        **(
                            {"changed_reporting_month_ids": sorted(changed_month_ids)}
                            if not has_material_change
                            else {}
                        ),
                    },
                )


def install_hooks():
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
