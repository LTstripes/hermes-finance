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
