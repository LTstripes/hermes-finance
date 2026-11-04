"""Read-only bridge to current, exact-original financial section/Money proof.

No classification, financial fact or receipt is written by a return reader.
"""

import json

from sqlalchemy import select

from hermes_finance.persistence import MyBrokerImport
from hermes_finance.services.mybroker_money_candidates import _original_equal
from hermes_finance.statement_import.mybroker import digest


def bound_import(session, view):
    source = session.scalar(
        select(MyBrokerImport).where(MyBrokerImport.document_sha256 == view["document_sha256"])
    )
    if source is None:
        return None
    document = view["document"]
    if (
        source.parser_version != document["parser"]
        or str(source.covered_from) != view["covered_from"]
        or str(source.covered_to) != view["covered_to"]
        # S1 enriches parsed facts with account/cash linkage. Compare the frozen
        # parser facts, as other exact-original readers do, rather than that enrichment.
        or not _original_equal(document, json.loads(source.normalized_json))
    ):
        return None
    return source


def effective_bonus(session, source, row):
    """Only the exact reviewed bonus occurrence, never a nearby or matching sum."""
    if source is None:
        return False
    from hermes_finance.services import broker_money as money

    target_id = f"{source.id}:{row['ordinal']}"
    entry = money.latest_proofs(session).get(("broker_bonus", target_id))
    if entry is None:
        return False
    receipt, proof, target = entry
    return any(
        occurrence["import_id"] == source.id
        and occurrence["section"] == "money"
        and occurrence["ordinal"] == row["ordinal"]
        and occurrence["row_fingerprint"] == digest(row)
        and occurrence["role"] == "broker_bonus"
        and occurrence["target_id"] == target_id
        for occurrence in proof["occurrences"]
    ) and not money.proof_blockers(session, receipt, proof, target)


def payout_source_unambiguous(views, view, event_date):
    """Only use a receipt directly when no other selected source covers the date."""
    day = str(event_date)
    covered = [v for v in views if v["covered_from"] <= day <= v["covered_to"]]
    return len(covered) == 1 and covered[0]["id"] == view["id"]


def effective_payout_instrument(session, view, row, saved, resolver):
    """Use an exact current Money receipt, without altering intake decisions."""
    from hermes_finance.statement_import.mybroker import MyBrokerError

    try:
        return _effective_payout_instrument(session, view, row, saved, resolver)
    except (MyBrokerError, ValueError, TypeError, KeyError, ArithmeticError):
        return None


def _effective_payout_instrument(session, view, row, saved, resolver):
    from hermes_finance.persistence import ReportingMonth
    from hermes_finance.services import broker_money as money
    from hermes_finance.services.broker_money_ownership import owners
    from hermes_finance.services.broker_statement_provisional import _minor
    from hermes_finance.services.source_money_classifications import source_reference

    role = saved.get("classification")
    if (
        role not in {"coupon", "dividend"}
        or saved.get("origin") != "default_rule"
        or saved.get("instrument_link_status") not in {None, "not_parsed", "unresolved_no_match"}
        or saved.get("instrument_id") is not None
        or saved.get("source_reference") != source_reference(view["id"], row)
    ):
        return None
    source = bound_import(session, view)
    if source is None:
        return None
    occurrence = {"import_id": source.id, "section": "money", "ordinal": row["ordinal"]}
    owned = owners(session, [occurrence])
    if len(owned) != 1:
        return None
    owner = owned[0]
    if owner["role"] != role or owner["row_fingerprint"] != digest(row):
        return None
    entry = money.latest_proofs(session).get((role, owner["target_id"]))
    if entry is None:
        return None
    receipt, proof, target = entry
    cohort = [
        o for o in proof["occurrences"] if (o["role"], o["target_id"]) == (role, owner["target_id"])
    ]
    if len(cohort) != 1 or any(cohort[0].get(k) != v for k, v in occurrence.items()):
        return None
    if cohort[0]["row_fingerprint"] != digest(row) or money.proof_blockers(
        session, receipt, proof, target
    ):
        return None
    facts = target.get("facts") or {}
    month = session.get(ReportingMonth, receipt.reporting_month_id)
    instrument_id = facts.get("instrument_id")
    instrument = resolver.instruments.get(int(instrument_id)) if instrument_id is not None else None
    expected_kind = "bond" if role == "coupon" else "stock"
    if (
        not instrument
        or not instrument.isin
        or instrument.instrument_type != expected_kind
        or instrument.currency != "RUB"
        or facts.get("flow_type") != role
        or facts.get("account_id") != str(receipt.account_id)
        or facts.get("reporting_month_id") != str(receipt.reporting_month_id)
        or facts.get("currency") != "RUB"
        or facts.get("event_date") != str(row.get("date"))
        or facts.get("net_amount_kopecks") != str(_minor(row.get("amount")))
        or month is None
        or not month.period_start.isoformat() <= str(row["date"]) <= month.period_end.isoformat()
    ):
        return None
    return instrument.isin


def apply_cash_gifts(session, view, rows):
    """Project only current exact cash gifts; never mutate saved source rows."""
    source = bound_import(session, view)
    captured = view["money_classifications"]
    raw = view["document"]["money"]
    if len(rows) != len(raw) or len(rows) != len(captured):
        return rows
    result = []
    for value, saved, original in zip(rows, captured, raw, strict=True):
        eligible = (
            saved["classification"] in {"unknown", "external_deposit"}
            and value["minor"] == saved["amount_kopecks"]
            and value["minor"] > 0
            and str(value["day"]) == str(saved["date"])
            and value["currency"] == saved["currency"] == "RUB"
            and effective_bonus(session, source, original)
        )
        result.append({**value, "classification": "external_gift"} if eligible else value)
    return result


def effective_section_blockers(session, source, codes):
    if source is None:
        return set(codes)
    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services.broker_sections import coverage_disposition

    accounts = set(
        session.scalars(
            select(BrokerMonthApply.account_id).where(BrokerMonthApply.import_id == source.id)
        )
    )
    if len(accounts) != 1:
        return set(codes)
    return set(coverage_disposition(session, source, accounts.pop(), codes)["effective_blockers"])
