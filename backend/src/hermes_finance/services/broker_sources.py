"""Month intake facade over existing source readers/writers; no economic writes."""

import hashlib

from sqlalchemy import select

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import ReportingMonth, SourceIntakeOriginal
from hermes_finance.services import mybroker_import, source_intake, source_intake_pdf
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def _month(session, month_id, *, editable=False):
    month = session.get(ReportingMonth, month_id, populate_existing=True)
    if month is None:
        raise MyBrokerError("reporting_month_not_found")
    if editable and month.status != "draft":
        raise MyBrokerError("reporting_month_closed")
    return month


def _item(view, filename_digest=None):
    document = view["document"]
    # Native row identities are independent of the filename alias. The stored
    # parser document does not carry the identity planner's source_accounts.
    accounts = sorted(
        {
            row["source_account"]
            for row in document["positions"] + document["rub_money"] + document["money"]
        }
        | {row["core"]["source_account"] for row in document["trades"]}
    )
    if not accounts and view["document"].get("filename_account"):
        accounts = [view["document"]["filename_account"]]
    exceptions = [code for code in view["exceptions"] if code != source_intake.PENDING]
    return {
        "intake_id": view["id"],
        "document_sha256": view["document_sha256"],
        "filename_digest": filename_digest,
        "source_accounts": accounts,
        "account_id": view["state"]["account_id"],
        "reporting_month_id": view["state"]["reporting_month_id"],
        "covered_from": view["covered_from"],
        "covered_to": view["covered_to"],
        "kind": "mybroker_xml",
        "slot": "xml:" + digest(accounts),
        "state": "needs_decision"
        if exceptions
        else ("financial_data_accepted" if view["finance_link"] else "file_saved"),
        "exceptions": exceptions,
        "head_seq": view["head_seq"],
        "request_ids": [row["request_id"] for row in view["history"]],
    }


def read_sources(session, month_id):
    with coherent_read_snapshot(session):
        month = _month(session, month_id)
        views = source_intake.list_intakes(session, month_id, include_unbound=True)
        items = [
            _item(view, session.get(SourceIntakeOriginal, view["id"]).filename_digest)
            for view in views
            if (
                view["covered_from"] == month.period_start.isoformat()
                and view["covered_to"] == month.period_end.isoformat()
            )
        ]
        items.extend(source_intake_pdf.list_descriptors(session, month))
        count = sum(item["state"] == "needs_decision" for item in items)
        return {
            "reporting_month_id": month_id,
            "items": items,
            "confirmation_count": count,
            "status": "needs_confirmation" if count else "ok" if items else "empty",
            "severity": "warning" if count else None,
            "financial_effects": 0,
        }


def save_xml(session, month_id, document, filename, request_id):
    # Detection and period authority belong to the existing parser, including
    # its frozen parser selection for already accepted documents.
    month = _month(session, month_id, editable=True)
    parsed = mybroker_import.parse_import_original(session, document, filename)
    if (parsed["covered_from"], parsed["covered_to"]) != (
        month.period_start.isoformat(),
        month.period_end.isoformat(),
    ):
        raise MyBrokerError("broker_source_period_mismatch")
    original = session.scalar(
        select(SourceIntakeOriginal).where(
            SourceIntakeOriginal.document_sha256 == hashlib.sha256(document).hexdigest()
        )
    )
    account_id = bound_month = None
    if original is not None:
        # Hash discovers a candidate only. Existing filename/length identity,
        # journal integrity and attachment still must independently agree.
        source_intake._verify_original(original, document, filename)
        view = source_intake.read_intake(session, original.id)
        account_id = view["state"]["account_id"]
        bound_month = view["state"]["reporting_month_id"]
        if bound_month is not None and bound_month != month_id:
            raise MyBrokerError("source_intake_rebind_forbidden")
        # Ordinary duplicate upload never appends a no-op decision or refreshes
        # classifications. This also preserves a decision made after Save.
        return {"duplicate": True, "item": _item(view, digest(filename))}
    ack = source_intake.save_intake(
        session,
        document=document,
        filename=filename,
        request_id=request_id,
        account_id=account_id,
        reporting_month_id=bound_month,
        expected_month_id=month_id,
    )
    return {
        "duplicate": ack["duplicate"],
        "item": _item(source_intake.read_intake(session, ack["intake_id"]), digest(filename)),
    }
