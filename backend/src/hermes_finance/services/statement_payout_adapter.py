"""Read exact XML/PDF facts into the existing, 1.9.0-readable Money v2 intent.

No writer or new receipt type. Source acceptance and explicit reviewed identity
bindings precede the ordinary Money Preview/Apply transaction.
"""

import hashlib
import json

from sqlalchemy import select

from hermes_finance.domain.broker_money import MoneyIntentV2
from hermes_finance.persistence import (
    BrokerMonthApply,
    Instrument,
    MyBrokerImport,
    SecurityRegIsinMapping,
)
from hermes_finance.services import broker_money, mybroker_import
from hermes_finance.services.source_report_preview import _money, _payout_links
from hermes_finance.statement_import.extract import extract_pdf_text_layer
from hermes_finance.statement_import.investment_report import parse_investment_report
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def read_payout_facts(session, originals, pdf):
    """Zero-write exact account/kind/date/net groups, using the accepted reader."""
    documents = [
        mybroker_import.parse_import_original(session, raw, name) for name, raw in originals
    ]
    if len({d["document_sha256"] for d in documents}) != len(documents):
        raise MyBrokerError("duplicate_original")
    report = parse_investment_report(
        extract_pdf_text_layer(pdf), {d["filename_account"] for d in documents}
    )
    if any(
        (d["covered_from"], d["covered_to"]) != (str(report.start), str(report.end))
        for d in documents
    ):
        raise MyBrokerError("payout_pdf_period_mismatch")
    rows = {
        d["document_sha256"]: _money(d, raw)
        for d, (_, raw) in zip(documents, originals, strict=True)
    }
    links, issues = _payout_links(documents, rows, report)
    if issues or report.instrument_issues:
        raise MyBrokerError("payout_pdf_xml_identity_review_required")
    facts, mappings = [], []
    for document in documents:
        for row in rows[document["document_sha256"]]:
            if row["classification"] not in {"coupon", "dividend"}:
                continue
            linked = links.get(row["ref"])
            if linked is None or row["minor"] is None or row["minor"] <= 0:
                raise MyBrokerError("payout_original_identity_unresolved")
            isin, registration = linked
            instruments = list(session.scalars(select(Instrument).where(Instrument.isin == isin)))
            if (
                len(instruments) != 1
                or not instruments[0].is_active
                or instruments[0].currency != "RUB"
                or instruments[0].instrument_type
                != ("stock" if row["classification"] == "dividend" else "bond")
            ):
                raise MyBrokerError("payout_catalogue_identity_review_required")
            fact = {
                "document_sha256": document["document_sha256"],
                "source_account": document["filename_account"],
                "ordinal": row["ordinal"],
                "kind": row["classification"],
                "instrument_id": instruments[0].id,
                "isin": isin,
                "registration": registration,
                "net_kopecks": row["minor"],
                "date": row["date"],
                "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
            }
            facts.append(fact)
            if fact["kind"] == "dividend":
                mapping = session.scalar(
                    select(SecurityRegIsinMapping).where(
                        SecurityRegIsinMapping.reg_number == registration
                    )
                )
                if mapping is not None and mapping.isin != isin:
                    raise MyBrokerError("payout_registration_mapping_conflict")
                if mapping is None and {"reg_number": registration, "isin": isin} not in mappings:
                    mappings.append({"reg_number": registration, "isin": isin})
    return {
        "facts": facts,
        "missing_registration_mappings": mappings,
        "source_hashes": [d["document_sha256"] for d in documents],
        "pdf_sha256": hashlib.sha256(pdf).hexdigest(),
    }


def reviewed_payout_intent(session, *, base_request_id, originals, facts, review_reference):
    """Build normal v2 claims only after the caller's exact facts were reviewed.

    Existing Money guards still check complete union, multiplicity, identity,
    legacy overlaps, fiscal unknowns and all dependency changes at Apply.
    """
    base = session.get(BrokerMonthApply, base_request_id)
    if base is None:
        raise MyBrokerError("existing_source_draft_required")
    source = session.get(MyBrokerImport, base.import_id)
    document = json.loads(source.normalized_json)
    selected = [f for f in facts if f["document_sha256"] == source.document_sha256]
    if not selected:
        raise MyBrokerError("reviewed_payout_facts_required")
    decisions = []
    for fact in selected:
        row = next((r for r in document["money"] if r["ordinal"] == fact["ordinal"]), None)
        instrument = session.get(Instrument, fact["instrument_id"])
        if (
            row is None
            or instrument is None
            or instrument.isin != fact["isin"]
            or row["date"] != fact["date"]
            or broker_money.broker_months._minor(row["amount"]) != fact["net_kopecks"]
        ):
            raise MyBrokerError("reviewed_payout_facts_changed")
        decisions.append(
            {
                "role": fact["kind"],
                "instrument_id": fact["instrument_id"],
                "seed": {"import_id": source.id, "section": "money", "ordinal": fact["ordinal"]},
            }
        )
    intent = MoneyIntentV2(
        contract_version="broker_money_v2",
        base_request_id=base_request_id,
        reporting_month_id=base.reporting_month_id,
        account_id=base.account_id,
        money_decisions=decisions,
    )
    initial = broker_money.preview_money(session, intent, originals)
    if len(initial["decisions"]) != len(decisions):
        raise MyBrokerError("reviewed_payout_occurrence_set_changed")
    for decision, planned, fact in zip(decisions, initial["decisions"], selected, strict=True):
        if (
            planned["observation"]["amount_minor"] != fact["net_kopecks"]
            or planned["observation"]["date"] != fact["date"]
        ):
            raise MyBrokerError("reviewed_payout_facts_changed")
        claims = {
            "reference": digest([review_reference, fact]),
            "review_context_digest": planned["review_context_digest"],
            "complete_occurrence_set_is_one_event": True,
        }
        if fact["kind"] == "dividend":
            claims.update(
                independent_net_basis_reference=fact["pdf_sha256"],
                actual_ordinary_stock_dividend=True,
                exact_row_stock_link=True,
                posted_amount_is_final_net_credit=True,
                withholding_is_embedded_not_additional_cash_leg=True,
            )
            decision["dividend_claims"] = claims
        else:
            claims.update(actual_coupon_payment=True, exact_row_instrument_link=True)
            decision["coupon_claims"] = claims
    intent = MoneyIntentV2.model_validate({**intent.model_dump(), "money_decisions": decisions})
    plan = broker_money.preview_money(session, intent, originals)
    if not plan["can_apply"]:
        raise MyBrokerError("reviewed_payout_money_blocked:" + ",".join(plan["blockers"]))
    return intent, plan
