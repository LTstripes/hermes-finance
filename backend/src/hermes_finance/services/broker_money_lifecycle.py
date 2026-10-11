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
    ExecutedTradeOccurrence,
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
    with session.no_autoflush:
        rows = list(session.scalars(select(BrokerMonthApply)))
        rows.extend(r for r in session.new if isinstance(r, BrokerMonthApply))
        return 1 + max(
            (json.loads(r.projection_json).get("journal_revision", 0) for r in rows),
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
            affected_accounts = {
                r.account_id
                for r in changes
                if isinstance(r, (InvestmentCashFlow, CashBalance, PositionSnapshot, ExternalFlow))
            }
            identity_changed = any(isinstance(r, (Account, Instrument)) for r in changes)
            for receipt in session.scalars(select(BrokerMonthApply)):
                # Zero-write Preview can select a bond absent from end holdings;
                # catalogue dependencies are therefore account-wide, as in the
                # existing identity revision hash. Tokens do not block v1 Close.
                if not identity_changed and receipt.account_id not in affected_accounts:
                    continue
                if "projection_digest" not in json.loads(receipt.projection_json):
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
        for receipt, proof, _target in latest_proofs(session).values():
            if proof["operation"] == "retire":
                continue
            grouped[receipt.request_id] = (receipt, proof)
        for receipt, proof in grouped.values():
            instruments = {
                int(t["facts"]["instrument_id"])
                for t in proof["targets"]
                if t["role"] == "coupon" and t["facts"]
            }
            source_ids = {s["import_id"] for s in proof["sources"]}
            funding_ids = {
                t["target_id"] for t in proof["targets"] if t["role"] == "account_funding"
            }

            def affects(row):
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
                    return (
                        row.hermes_account_id == receipt.account_id
                        or row.hermes_instrument_id in instruments
                    )
                if isinstance(row, MyBrokerImport):
                    if row.id in source_ids:
                        return True
                    month = session.get(ReportingMonth, receipt.reporting_month_id)
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
                if isinstance(
                    row,
                    (
                        ExternalFlow,
                        AppliedStatementEvent,
                        AppliedStatementEventRevision,
                        CashBalance,
                        PositionSnapshot,
                        InvestmentCashFlow,
                    ),
                ):
                    return getattr(row, "account_id", None) == receipt.account_id
                return False

            if not any(affects(r) for r in changes):
                continue
            retired = {
                **proof,
                "operation": "retire",
                "previous_request_id": receipt.request_id,
                "reason_code": "dependency_changed",
            }
            _append_receipt(session, receipt, retired)


def install_hooks():
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
