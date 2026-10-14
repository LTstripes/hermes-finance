"""Reserved cross-writer checks and monotonic retirement of Money proof."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import event, inspect, select, text
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    Account,
    AppliedStatementEvent,
    AppliedStatementEventRevision,
    BrokerIdentityMapping,
    BrokerMoneyOccurrenceOwner,
    BrokerMonthApply,
    CashBalance,
    ExecutedTrade,
    ExecutedTradeOccurrence,
    ExecutedTradeRevision,
    ExternalFlow,
    HistoricalOwnerFlowOccurrence,
    HistoricalOwnerFlowRevision,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.broker_money_ownership import key, owners
from hermes_finance.statement_import.mybroker import MyBrokerError, canonical, digest

DEPENDENCY_CONTRACT = "broker_money_dependency_v1"


def next_journal_revision(session):
    """Reserved writer assigns order independent of wall-clock timestamps."""
    from hermes_finance.services import broker_month_journal as journal

    with session.no_autoflush:
        rows = list(session.scalars(select(BrokerMonthApply)))
        rows.extend(r for r in session.new if isinstance(r, BrokerMonthApply))
        return 1 + max(
            (
                journal.payload(r).get("journal_revision", 0)
                for r in rows
                if journal.kind(r) in {journal.MONEY, journal.DEPENDENCY}
            ),
            default=0,
        )


def _append_receipt(session, receipt, proof):
    token = digest([proof["contract_version"], uuid4().hex])
    session.add(
        BrokerMonthApply(
            request_id=token,
            request_fingerprint=token,
            confirmation_digest=token,
            reporting_month_id=receipt.reporting_month_id,
            account_id=receipt.account_id,
            import_id=receipt.import_id,
            projection_json=canonical(
                {**proof, "journal_revision": next_journal_revision(session)}
            ),
            accepted_at=datetime.now(UTC),
        )
    )


def _values(row, field):
    if not hasattr(row, field):
        return set()
    return {getattr(row, field), *inspect(row).attrs[field].history.deleted}


def _financial_scope(row, receipt, month):
    """Both old and new scope matter when a financial row changes month/account."""
    return receipt.account_id in _values(row, "account_id") and (
        receipt.reporting_month_id in _values(row, "reporting_month_id")
        or any(
            day is not None and month.period_start <= day <= month.period_end
            for day in _values(row, "event_date")
        )
    )


def _statement_affects(session, row, target):
    if target["role"] != "coupon":
        return False
    from hermes_finance.services.broker_money import (
        compatible_pdf_event,
        compatible_pdf_revision,
        material,
    )

    frozen_events = {e["id"] for e in target["statement_support"]["events"]}
    event_rows = (
        [row]
        if isinstance(row, AppliedStatementEvent)
        else [
            session.get(AppliedStatementEvent, event_id)
            for event_id in _values(row, "applied_statement_event_id")
            if event_id is not None
        ]
    )
    relevant = [
        event_row
        for event_row in event_rows
        if event_row is not None
        and (
            target["target_id"] in _values(event_row, "investment_cash_flow_id")
            or str(event_row.id) in frozen_events
        )
    ]
    if not relevant:
        return False
    event_row = relevant[0]
    marker = session.info.get("broker_money_pdf_link")
    if (
        row in session.new
        and marker
        and marker["target_id"] == target["target_id"]
        and marker["event_date"] == target["facts"]["event_date"]
        and marker["net_amount_kopecks"] == target["facts"]["net_amount_kopecks"]
        and str(event_row.id) not in frozen_events
    ):
        if isinstance(row, AppliedStatementEvent):
            if compatible_pdf_event(material(row), target["facts"]):
                return False
        elif not list(
            session.scalars(
                select(AppliedStatementEventRevision).where(
                    AppliedStatementEventRevision.applied_statement_event_id == event_row.id
                )
            )
        ) and compatible_pdf_revision(material(event_row), material(row), target["facts"]):
            return False
    # A changed/retracted event or any later revision is never additive,
    # including A -> B -> A after a compatible attachment.
    return True


def _before_flush(session, _context, _instances):
    if not inspect(session.connection()).has_table("broker_money_occurrence_owners"):
        return
    changes = [
        r
        for r in (*session.new, *session.dirty, *session.deleted)
        if r in session.new or r in session.deleted or session.is_modified(r)
    ]
    if not changes:
        return
    session.execute(text("UPDATE broker_money_occurrence_owners SET ordinal = ordinal WHERE 0"))
    with session.no_autoflush:
        links = list(session.scalars(select(BrokerMoneyOccurrenceOwner)))
        for row in (*session.dirty, *session.deleted):
            if (
                isinstance(row, ExecutedTradeOccurrence)
                and "money" in _values(row, "section")
                and (row in session.deleted or session.is_modified(row))
            ):
                raise MyBrokerError("money_ownership_is_permanent")
            if (
                isinstance(row, ExecutedTradeRevision)
                and (row in session.deleted or session.is_modified(row))
                and any(
                    "cash_reconciliation" in json.loads(value)
                    for value in _values(row, "evidence_json")
                    if value
                )
            ):
                raise MyBrokerError("trade_cash_revision_is_append_only")
            if isinstance(row, BrokerMoneyOccurrenceOwner) and (
                row in session.deleted or session.is_modified(row)
            ):
                raise MyBrokerError("money_ownership_is_permanent")
            if isinstance(row, InvestmentCashFlow) and any(
                o.investment_cash_flow_id == row.id for o in links
            ):
                if row in session.deleted or session.is_modified(row):
                    raise MyBrokerError("money_target_requires_source_revision")
            if isinstance(row, BrokerMonthApply) and (
                row in session.deleted or session.is_modified(row)
            ):
                old = inspect(row).attrs.projection_json.history.deleted
                initial_stage = list(old) == ["{}"]
                initial_stage |= bool(
                    session.info.get("broker_money_stage")
                    and session.info.get("broker_money_initial_receipt")
                    == (row.request_id, old[0] if len(old) == 1 else None)
                )
                if not initial_stage:
                    raise MyBrokerError("broker_month_receipt_is_append_only")
        new_occurrences = [
            r
            for r in session.new
            if isinstance(
                r,
                (
                    BrokerMoneyOccurrenceOwner,
                    HistoricalOwnerFlowOccurrence,
                    ExecutedTradeOccurrence,
                ),
            )
        ]
        for row in new_occurrences:
            if row.section != "money":
                continue
            role = (
                row.role
                if isinstance(row, BrokerMoneyOccurrenceOwner)
                else "account_funding"
                if isinstance(row, HistoricalOwnerFlowOccurrence)
                else "trade"
            )
            target_id = (
                (
                    row.investment_cash_flow_id
                    if row.role == "coupon"
                    else row.historical_owner_flow_id
                )
                if isinstance(row, BrokerMoneyOccurrenceOwner)
                else (
                    row.flow_id if isinstance(row, HistoricalOwnerFlowOccurrence) else row.trade_id
                )
            )
            for prior in owners(
                session,
                [{"import_id": row.import_id, "section": row.section, "ordinal": row.ordinal}],
            ):
                if prior["role"] != role or prior["target_id"] != target_id:
                    raise MyBrokerError("occurrence_already_owned")
            for other in new_occurrences:
                if other is row or key(other) != key(row):
                    continue
                if type(other) is type(row):
                    raise MyBrokerError("duplicate_occurrence_owner")
                # H2 and Money may stage the same funding link together, but a
                # coupon/trade owner cannot claim that occurrence in this flush.
                if not (
                    role == "account_funding"
                    and isinstance(
                        other, (HistoricalOwnerFlowOccurrence, BrokerMoneyOccurrenceOwner)
                    )
                    and getattr(other, "role", "account_funding") == "account_funding"
                    and (
                        other.flow_id
                        if isinstance(other, HistoricalOwnerFlowOccurrence)
                        else other.historical_owner_flow_id
                    )
                    == target_id
                    and other.row_fingerprint == row.row_fingerprint
                ):
                    raise MyBrokerError("occurrence_already_owned")
        # PDF/manual/forecast creation cannot bypass an existing Money owner by
        # minting an equal payout. Link-existing is the reviewed safe route.
        if not session.info.get("broker_money_stage"):
            from hermes_finance.services import broker_month_journal as journal

            for row in session.new:
                if not isinstance(row, InvestmentCashFlow):
                    continue
                for link in links:
                    if link.role != "coupon":
                        continue
                    target = session.get(InvestmentCashFlow, link.investment_cash_flow_id)
                    if target and (
                        target.account_id,
                        target.instrument_id,
                        target.flow_type,
                        target.event_date,
                        target.net_amount_kopecks,
                        target.currency,
                    ) == (
                        row.account_id,
                        row.instrument_id,
                        row.flow_type,
                        row.event_date,
                        row.net_amount_kopecks,
                        row.currency or "RUB",
                    ):
                        raise MyBrokerError("source_payout_requires_link_existing")
        # Legacy ICF/cash/catalogue have no revision journal. Retain a dependency token
        # for source-owned scopes even before the first Money acceptance, so an
        # edit A -> B -> A cannot revive a previously reviewed confirmation.
        if not session.info.get("broker_money_stage"):
            identity_changed = any(isinstance(r, (Account, Instrument)) for r in changes)
            for receipt in session.scalars(select(BrokerMonthApply)):
                # Zero-write Preview can select a bond absent from end holdings;
                # catalogue dependencies are therefore account-wide, as in the
                # existing identity revision hash. Tokens do not block v1 Close.
                if journal.kind(receipt) != journal.SOURCE:
                    continue
                month = session.get(ReportingMonth, receipt.reporting_month_id)
                month_geometry_changed = any(
                    isinstance(r, ReportingMonth)
                    and r.id == receipt.reporting_month_id
                    and any(
                        inspect(r).attrs[f].history.has_changes()
                        for f in ("year", "month", "snapshot_date", "period_start", "period_end")
                    )
                    for r in changes
                )
                if (
                    not identity_changed
                    and not month_geometry_changed
                    and not any(
                        isinstance(
                            r, (InvestmentCashFlow, CashBalance, PositionSnapshot, ExternalFlow)
                        )
                        and _financial_scope(r, receipt, month)
                        for r in changes
                    )
                ):
                    continue
                _append_receipt(
                    session,
                    receipt,
                    {
                        "contract_version": DEPENDENCY_CONTRACT,
                        "base_request_id": receipt.request_id,
                        "reason_code": "financial_dependency_changed",
                    },
                )
        from hermes_finance.services.broker_money import latest_proofs

        grouped = {}
        for receipt, proof, target in latest_proofs(session).values():
            if proof["operation"] == "retire":
                continue
            month = session.get(ReportingMonth, receipt.reporting_month_id)
            instruments = (
                {int(target["facts"]["instrument_id"])}
                if target["role"] in ("coupon", "trade") and target["facts"]
                else set()
            )
            source_ids = {s["import_id"] for s in proof["sources"]}
            funding_ids = {target["target_id"]} if target["role"] == "account_funding" else set()

            def affects(row):
                if isinstance(row, ReportingMonth):
                    return (
                        target["role"] == "trade"
                        and row.id == receipt.reporting_month_id
                        and "closed" in inspect(row).attrs.status.history.deleted
                    )
                if isinstance(row, ExecutedTrade):
                    return target["role"] == "trade" and row.id == target["target_id"]
                if isinstance(row, ExecutedTradeRevision):
                    return (
                        target["role"] == "trade"
                        and row.trade_id == target["target_id"]
                        and not session.info.get("broker_money_stage")
                    )
                if (
                    session.info.get("broker_money_stage")
                    and isinstance(row, InvestmentCashFlow)
                    and row in session.new
                ):
                    # The reserved, revalidated batch may add an independently
                    # proved payout without invalidating unchanged prior payouts.
                    return False
                if isinstance(row, Account):
                    return row.id == receipt.account_id
                if isinstance(row, Instrument):
                    return row.id in instruments
                if isinstance(row, BrokerIdentityMapping):
                    return receipt.account_id in _values(row, "hermes_account_id") or bool(
                        instruments.intersection(_values(row, "hermes_instrument_id"))
                    )
                if isinstance(row, MyBrokerImport):
                    if row.id in source_ids:
                        return True
                    return (
                        row.covered_from <= month.period_end
                        and row.covered_to >= month.period_start
                        and any(
                            b["kind"] == "account" and b["hermes_id"] == receipt.account_id
                            for b in json.loads(row.mappings_json)
                        )
                    )
                if isinstance(row, HistoricalOwnerFlowRevision):
                    return row.flow_id in funding_ids
                if isinstance(row, (AppliedStatementEvent, AppliedStatementEventRevision)):
                    return _statement_affects(session, row, target)
                if isinstance(
                    row,
                    (
                        ExternalFlow,
                        CashBalance,
                        PositionSnapshot,
                        InvestmentCashFlow,
                    ),
                ):
                    return _financial_scope(row, receipt, month)
                return False

            if not any(affects(r) for r in changes):
                continue
            if receipt.request_id not in grouped:
                grouped[receipt.request_id] = (receipt, proof, [])
            grouped[receipt.request_id][2].append(target)
        for receipt, proof, affected_targets in grouped.values():
            retired = {
                **proof,
                "targets": affected_targets,
                "occurrences": [
                    o
                    for o in proof["occurrences"]
                    if any(
                        (o["role"], o["target_id"]) == (t["role"], t["target_id"])
                        for t in affected_targets
                    )
                ],
                "operation": "retire",
                "previous_request_id": receipt.request_id,
                "reason_code": "dependency_changed",
            }
            _append_receipt(session, receipt, retired)


def install_hooks():
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
