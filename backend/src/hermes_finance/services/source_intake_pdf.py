"""Non-economic PDF descriptors in the existing append-only intake journal."""

import hashlib
import json
from collections import Counter

from sqlalchemy import select

from hermes_finance.persistence import (
    AppliedStatementEvent,
    InvestmentCashFlow,
    SourceIntakeRevision,
)
from hermes_finance.services import source_intake
from hermes_finance.services.statement_import_apply import _linked_flow_matches_accepted
from hermes_finance.services.statement_import_preparation import (
    _account_views,
    _instrument_views,
    prepare_income_report_apply,
)
from hermes_finance.statement_import import preview_income_report
from hermes_finance.statement_import.dto import ReportStatus
from hermes_finance.statement_import.mybroker import MyBrokerError, digest

PDF_CONTRACT = "broker_income_pdf_v1"


def _descriptors(session):
    rows = session.scalars(
        select(SourceIntakeRevision)
        .where(
            SourceIntakeRevision.operation == "manifest",
            SourceIntakeRevision.original_id.is_(None),
        )
        .order_by(SourceIntakeRevision.seq)
    )
    for row in rows:
        payload = json.loads(row.payload_json)
        if "pdf_descriptor" not in payload:
            continue
        descriptor = payload["pdf_descriptor"]
        if (
            row.contract_version != source_intake.CONTRACT
            or row.confirmation_digest != digest(payload)
            or row.expected_predecessor_seq is not None
            or row.account_id is not None
            or row.reporting_month_id is not None
            or descriptor.get("contract") != PDF_CONTRACT
        ):
            raise MyBrokerError("source_intake_journal_invalid")
        yield row, descriptor


def _item(session, receipt, descriptor):
    # An exact document + unchanged live statement receipt proves acceptance.
    # No amount/date proximity or descriptor itself can establish money facts.
    accepted = []
    events = session.scalars(
        select(AppliedStatementEvent).where(
            AppliedStatementEvent.document_sha256 == descriptor["document_sha256"],
            AppliedStatementEvent.status == "active",
        )
    )
    for event in events:
        flow = session.get(InvestmentCashFlow, event.investment_cash_flow_id)
        if (
            flow is not None
            and flow.reporting_month_id == descriptor["month_id"]
            and _linked_flow_matches_accepted(session, event=event, flow=flow)
        ):
            accepted.append(event.material_fingerprint)
    expected = Counter(descriptor["row_fingerprints"])
    actual = Counter(accepted)
    complete = bool(expected) and actual == expected
    return {
        "intake_id": None,
        "receipt_seq": receipt.seq,
        "document_sha256": descriptor["document_sha256"],
        "filename_digest": descriptor["filename_digest"],
        "source_accounts": descriptor["source_accounts"],
        "account_id": None,
        "reporting_month_id": descriptor["month_id"],
        "covered_from": descriptor["covered_from"],
        "covered_to": descriptor["covered_to"],
        "period_basis": "payment_dates",
        "kind": "income_pdf",
        "slot": "pdf:" + digest(descriptor["source_accounts"]),
        "state": "financial_data_accepted" if complete else "needs_decision",
        "exceptions": [] if complete else ["statement_selection_required"],
        "row_count": sum(expected.values()),
        "accepted_count": sum((expected & actual).values()),
        "head_seq": receipt.seq,
        "request_ids": [receipt.request_id],
    }


def list_descriptors(session, month):
    return [
        _item(session, row, descriptor)
        for row, descriptor in _descriptors(session)
        if descriptor["month_id"] == month.id
        and month.period_start.isoformat() <= descriptor["covered_from"]
        and descriptor["covered_to"] <= month.period_end.isoformat()
    ]


def save_descriptor(session, month_id, document, filename, request_id):
    from hermes_finance.services.broker_sources import _month

    sha = hashlib.sha256(document).hexdigest()
    fingerprint = digest([PDF_CONTRACT, month_id, sha, len(document), digest(filename)])
    source_intake._reserve(session)
    try:
        month = _month(session, month_id, editable=True)
        source_intake._retry(session, request_id, fingerprint)
        for row, descriptor in _descriptors(session):
            if descriptor["document_sha256"] != sha:
                continue
            if descriptor["byte_length"] != len(document) or descriptor[
                "filename_digest"
            ] != digest(filename):
                raise MyBrokerError("source_intake_original_mismatch")
            if descriptor["month_id"] != month_id:
                raise MyBrokerError("source_intake_rebind_forbidden")
            if not (
                month.period_start.isoformat()
                <= descriptor["covered_from"]
                <= descriptor["covered_to"]
                <= month.period_end.isoformat()
            ):
                raise MyBrokerError("broker_source_period_mismatch")
            result = {"duplicate": True, "item": _item(session, row, descriptor)}
            session.rollback()
            return result
        preview = preview_income_report(
            document,
            hermes_accounts=_account_views(session),
            hermes_instruments=_instrument_views(session),
        )
        prepared = prepare_income_report_apply(session, document=document, account_mappings=())
        if preview.status != ReportStatus.APPLICABLE or prepared.status != ReportStatus.APPLICABLE:
            raise MyBrokerError("broker_source_pdf_unsupported")
        dates = [row.event_date for row in preview.rows]
        if not dates or any(day is None for day in dates):
            raise MyBrokerError("broker_source_pdf_period_unknown")
        if any(day < month.period_start or day > month.period_end for day in dates):
            raise MyBrokerError("broker_source_period_mismatch")
        descriptor = {
            "contract": PDF_CONTRACT,
            "month_id": month_id,
            "document_sha256": sha,
            "byte_length": len(document),
            "filename_digest": digest(filename),
            "source_accounts": sorted(
                {row.provider_account_ref for row in preview.rows if row.provider_account_ref}
            ),
            # The existing parser exposes payment dates, not a declared report range.
            "covered_from": min(dates).isoformat(),
            "covered_to": max(dates).isoformat(),
            "row_fingerprints": [row.material_fingerprint for row in prepared.rows],
        }
        payload = {"state": {}, "pdf_descriptor": descriptor}
        receipt = source_intake._append(
            session,
            request_id=request_id,
            fingerprint=fingerprint,
            operation="manifest",
            payload=payload,
        )
        result = {"duplicate": False, "item": _item(session, receipt, descriptor)}
        session.commit()
        return result
    except BaseException:
        session.rollback()
        raise
