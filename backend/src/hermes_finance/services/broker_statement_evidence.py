"""Enrich an existing SOURCE with original-bound trade/fee proof, never reimport it."""

import hashlib

from sqlalchemy import update

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import BrokerMonthApply, ReportingMonth
from hermes_finance.services import broker_money
from hermes_finance.services import broker_month_journal as journal
from hermes_finance.services.broker_statement_money import plan_statement_money
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def _plan(session, base_request_id, original, broker_bonuses=()):
    base = session.get(BrokerMonthApply, base_request_id, populate_existing=True)
    if base is None or journal.kind(base) != journal.SOURCE:
        raise MyBrokerError("existing_source_draft_required")
    month = session.get(ReportingMonth, base.reporting_month_id, populate_existing=True)
    if month is None or month.status != "draft":
        raise MyBrokerError("reporting_month_closed")
    # Payouts already have separate v1/v2 ownership. This operation cannot add,
    # reaffirm, replace or reclassify a payout or an Owner capital event.
    intent, plan = plan_statement_money(
        session, base, original, payouts=[], broker_bonuses=broker_bonuses
    )
    if not plan["decisions"]:
        raise MyBrokerError("statement_trade_or_account_fee_required")
    return base, intent, plan


def preview_statement_evidence(session, base_request_id, original, *, broker_bonuses=()):
    with coherent_read_snapshot(session):
        _, intent, plan = _plan(session, base_request_id, original, broker_bonuses)
        return {"intent": intent.model_dump(mode="json"), **plan}


def apply_statement_evidence(
    session, base_request_id, original, *, request_id, confirmation_digest, broker_bonuses=()
):
    if session.new or session.dirty or session.deleted:
        raise MyBrokerError("clean_session_required")
    filename, raw = original
    from hermes_finance.domain.broker_money import BrokerBonusReview

    reviews = [
        r if isinstance(r, BrokerBonusReview) else BrokerBonusReview.model_validate(r)
        for r in broker_bonuses
    ]
    fingerprint_parts = [
        base_request_id,
        filename,
        hashlib.sha256(raw).hexdigest(),
        confirmation_digest,
    ]
    if reviews:
        fingerprint_parts.append([r.model_dump(mode="json") for r in reviews])
    fingerprint = digest(fingerprint_parts)
    session.rollback()
    try:
        session.execute(
            update(BrokerMonthApply).where(BrokerMonthApply.request_id == "").values(request_id="")
        )
        session.expire_all()
        receipt = session.get(BrokerMonthApply, request_id, populate_existing=True)
        replay = receipt is not None
        if receipt:
            if (
                receipt.request_fingerprint != fingerprint
                or journal.kind(receipt) != journal.MONEY_V3
            ):
                raise MyBrokerError("idempotency_conflict")
            session.rollback()
        else:
            base, intent, plan = _plan(session, base_request_id, original, reviews)
            if confirmation_digest != plan["confirmation_digest"]:
                raise MyBrokerError("statement_evidence_preview_stale")
            broker_money.stage_money(
                session,
                intent,
                plan,
                base,
                request_id=request_id,
                fingerprint=fingerprint,
                confirmation_digest=confirmation_digest,
            )
            session.commit()
    except BaseException:
        session.info.pop("broker_money_stage", None)
        session.info.pop("broker_money_initial_receipt", None)
        session.rollback()
        raise
    return {**broker_money.read_money(session, request_id), "duplicate": replay}
