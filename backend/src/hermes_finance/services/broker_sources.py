"""Month intake facade over existing source readers/writers; no economic writes."""

import hashlib

from sqlalchemy import select

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.persistence import ReportingMonth, SourceIntakeOriginal
from hermes_finance.services import mybroker_import, source_intake, source_intake_pdf
from hermes_finance.statement_import.mybroker import MyBrokerError, digest
from hermes_finance.statement_import.mybroker_return_structure import source_return_blockers

# Parser limitations are retained as evidence. They are not a choice the Owner
# can confirm away, and must never be interpreted as a lost journal decision.
_STRUCTURE_CODES = {"4_Transfers_unsupported", "5_UFSR_unsupported", "unparsed_source_rows"}


def _review_issues(view, codes):
    """Describe only witnessed affected rows; this projection grants no authority."""
    issues = []
    located = set()
    for proposal in view["proposals"]:
        reasons = set(proposal.get("evidence_gaps", []))
        reasons.update(proposal.get("review_reasons", []))
        reasons.update(proposal["currency_assessment"]["reasons"])
        if proposal["isin"] in view["state"]["deferred_isins"]:
            reasons.add("source_intake_identity_deferred")
        for code in sorted(reasons.intersection(codes)):
            issues.append(
                {"code": code, "isin": proposal["isin"], "name": proposal.get("source_name")}
            )
            located.add(code)
    for section in ("trades", "money"):
        for row in view["document"][section]:
            reasons = set(row.get("blockers", []))
            if section == "money" and row["kind"] == "unsupported":
                reasons.add("money_semantics_unsupported")
            if section == "trades" and row.get("repo_observed"):
                reasons.add("repo_identity_unsupported")
            core = row.get("core", row)
            for code in sorted(reasons.intersection(codes)):
                issues.append(
                    {
                        "code": code,
                        "isin": core.get("isin"),
                        "name": next(
                            (
                                p.get("source_name")
                                for p in view["proposals"]
                                if p["isin"] == core.get("isin")
                            ),
                            None,
                        ),
                        "source_account": core.get("source_account"),
                        "date": core.get("trade_time", core.get("date")),
                        "quantity": core.get("quantity"),
                        "amount": core.get("trade_amount", core.get("amount")),
                        "currency": core.get("currency"),
                        "section": section,
                        "ordinal": row["ordinal"],
                    }
                )
                located.add(code)
    issues.extend({"code": code} for code in sorted(set(codes) - located))
    return issues


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
    # Reuse the existing exact inventory assessor. Unknown/opaque trees keep
    # their findings; recognized non-economic wrappers are information only.
    information = set(exceptions).intersection(_STRUCTURE_CODES) - source_return_blockers(view)
    decisions = sorted(set(exceptions) - information)
    # A previously linked receipt that no longer validates is a real changed
    # dependency, even when PENDING is the only remaining scope reason.
    if not view["finance_link"] and any(
        row["operation"] == "finance_link" for row in view["history"]
    ):
        decisions.append("source_intake_receipt_authority_changed")
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
        if decisions
        else ("financial_data_accepted" if view["finance_link"] else "file_saved"),
        "exceptions": exceptions,
        "review_issues": _review_issues(view, decisions),
        "information_codes": sorted(information),
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
