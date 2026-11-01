"""Cross-writer occurrence mutex and immutable ownership, including old H2/S2."""

from sqlalchemy import select

from hermes_finance.persistence import (
    BrokerMoneyOccurrenceOwner,
    ExecutedTradeOccurrence,
    HistoricalOwnerFlowOccurrence,
)


def key(row):
    if isinstance(row, dict):
        return row["import_id"], row["section"], row["ordinal"]
    return row.import_id, row.section, row.ordinal


def owners(session, occurrences):
    from hermes_finance.database import snapshot_read_result

    return snapshot_read_result(
        session,
        "broker_money_occurrence_owners",
        tuple(sorted({key(o) for o in occurrences})),
        lambda: _owners(session, occurrences),
    )


def _owners(session, occurrences):
    keys = {key(o) for o in occurrences}
    result = []
    for model, role, field in (
        (BrokerMoneyOccurrenceOwner, None, None),
        (HistoricalOwnerFlowOccurrence, "account_funding", "flow_id"),
        (ExecutedTradeOccurrence, "trade", "trade_id"),
    ):
        for row in session.scalars(select(model)):
            if key(row) in keys:
                result.append(
                    {
                        "key": list(key(row)),
                        "role": role or row.role,
                        "target_id": getattr(row, field)
                        if field
                        else (
                            row.investment_cash_flow_id
                            if row.role in {"coupon", "dividend"}
                            else row.historical_owner_flow_id
                        ),
                        "row_fingerprint": row.source_fingerprint
                        if role == "trade"
                        else row.row_fingerprint,
                    }
                )
    # Typed account fees and equivalent NKD cohorts own source occurrences in
    # the existing append-only receipt journal, without fictitious trade edges.
    from hermes_finance.persistence import BrokerMonthApply
    from hermes_finance.services import broker_month_journal as journal

    for receipt in session.scalars(select(BrokerMonthApply)):
        if journal.kind(receipt) != journal.MONEY_V3:
            continue
        proof = journal.payload(receipt)
        for occurrence in proof["occurrences"]:
            if occurrence["role"] in {"account_fee", "broker_bonus"} and key(occurrence) in keys:
                result.append(
                    {
                        "key": list(key(occurrence)),
                        "role": occurrence["role"],
                        "target_id": occurrence["target_id"],
                        "row_fingerprint": occurrence["row_fingerprint"],
                    }
                )
        for group in proof.get("statement_groups", []):
            for occurrence in group["occurrences"]:
                if key(occurrence) in keys:
                    result.append(
                        {
                            "key": list(key(occurrence)),
                            "role": "trade_group",
                            "target_id": group["group_id"],
                            "row_fingerprint": occurrence["row_fingerprint"],
                        }
                    )
    return result


def conflicts(session, occurrences, role, target_id):
    found = owners(session, occurrences)
    fingerprints = {key(o): o["row_fingerprint"] for o in occurrences}
    return [
        o
        for o in found
        if (
            o["role"] != role
            or o["target_id"] != target_id
            or o["row_fingerprint"] != fingerprints[tuple(o["key"])]
        )
    ]
