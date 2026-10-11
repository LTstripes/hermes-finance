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
                            if row.role == "coupon"
                            else row.historical_owner_flow_id
                        ),
                        "row_fingerprint": row.source_fingerprint
                        if role == "trade"
                        else row.row_fingerprint,
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
