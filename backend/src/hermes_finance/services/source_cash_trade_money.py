"""Query-only H2-A2 v4 adapter over independently reviewed trade Money authority.

The canonical Money proof owns financial meaning. This adapter only proves the
role of one exact source occurrence and freezes its complete current dependency
set; it neither infers linkage nor creates economic facts.
"""

import json
from decimal import DecimalException

from sqlalchemy import select

from hermes_finance.persistence import (
    BrokerMonthApply,
    ExecutedTrade,
    ExecutedTradeOccurrence,
    Instrument,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_money as money
from hermes_finance.services import broker_trade_money as cash
from hermes_finance.services import executed_trades as trades
from hermes_finance.services.broker_money_ownership import key, owners
from hermes_finance.services.historical_owner_flows import _rows
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def authority(session, account_id, a, b, scoped_money, *, retained=None):
    scoped_keys = {(sid, "money", row["ordinal"]) for sid, row in scoped_money}
    permanent = _rows(session, ExecutedTradeOccurrence)
    relevant = [o for o in permanent if key(o) in scoped_keys]
    target_ids = {o.trade_id for o in relevant} | {
        t["target_id"] for t in (retained or {}).get("targets", [])
    }
    targets, accepted = [], {}
    result = {
        "targets": targets,
        "owners": [money.material(o) for o in relevant],
        "scoped_owners": owners(
            session,
            [
                {"import_id": sid, "section": "money", "ordinal": row["ordinal"]}
                for sid, row in scoped_money
            ],
        ),
        "journal": [],
        "blockers": [],
    }
    try:
        # The canonical journal intentionally ignores unknown envelope kinds.
        # A relevant malformed/newer typed receipt must not expose an older
        # good proof through that filtering. Freeze the raw scoped journal too.
        raw_journal = []
        invalid_journal = False
        source_ids = {sid for sid, _ in scoped_money}
        retained_requests = {r["request_id"] for r in (retained or {}).get("raw_journal", [])}
        for receipt in session.scalars(
            select(BrokerMonthApply).order_by(BrokerMonthApply.request_id)
        ):
            month = session.get(ReportingMonth, receipt.reporting_month_id)
            scoped = (
                receipt.account_id == account_id
                and receipt.import_id in source_ids
                and month is not None
                and month.period_start <= b
                and month.period_end > a
            )
            retained_receipt = receipt.request_id in retained_requests
            try:
                payload = json.loads(receipt.projection_json)
                from hermes_finance.services import broker_month_journal as journal_types

                kind = journal_types.kind(receipt)
                relevant_receipt = (
                    retained_receipt
                    or any(
                        t.get("role") == "trade" and t.get("target_id") in target_ids
                        for t in payload.get("targets", [])
                    )
                    or any(key(o) in scoped_keys for o in payload.get("occurrences", []))
                    or scoped
                    and kind == "invalid"
                )
                if not relevant_receipt:
                    continue
                if kind in (journal_types.SOURCE, journal_types.SECTIONS, journal_types.DEPENDENCY):
                    if not retained_receipt:
                        continue
                raw_journal.append(money.material(receipt))
                if kind != money.CONTRACT:
                    invalid_journal = True
            except (ValueError, TypeError, KeyError, AttributeError):
                if scoped or retained_receipt:
                    invalid_journal = True
                    raw_journal.append(money.material(receipt))
        result["raw_journal"] = raw_journal
        if invalid_journal or retained_requests - {r["request_id"] for r in raw_journal}:
            result["blockers"] = ["paid_nkd_money_journal_invalid"]
            return result, accepted
        journal = money.receipts(session)
        # Preserve relevant targets even if permanent ownership disappeared.
        for receipt, proof in journal:
            if receipt.account_id == account_id:
                target_ids.update(
                    o["target_id"]
                    for o in proof["occurrences"]
                    if o["role"] == "trade" and key(o) in scoped_keys
                )
        result["journal"] = [
            money.material(receipt)
            for receipt, proof in journal
            if any(t["role"] == "trade" and t["target_id"] in target_ids for t in proof["targets"])
        ]
        latest = money.latest_proofs(session)
        context = trades._context(session) if target_ids else None
    except (ValueError, TypeError, KeyError, MyBrokerError, DecimalException):
        result["blockers"] = ["paid_nkd_money_journal_invalid"]
        return result, accepted
    for target_id in sorted(target_ids):
        item = {"target_id": target_id}
        targets.append(item)
        blockers = set()
        cohort = []
        target_owners = [o for o in permanent if o.trade_id == target_id]
        item["owners"] = [money.material(o) for o in target_owners]
        entry = latest.get(("trade", target_id))
        item["receipt"] = money.material(entry[0]) if entry else None
        try:
            trade = session.get(ExecutedTrade, target_id)
            current = money._target(session, "trade", target_id)
            item["current_target"] = current
            if entry is None or trade is None:
                blockers.add("paid_nkd_money_proof_missing")
            else:
                receipt, proof, frozen = entry
                target_heads = [
                    p
                    for _, p in journal
                    if any(
                        t["role"] == "trade" and t["target_id"] == target_id for t in p["targets"]
                    )
                ]
                revisions = [p.get("journal_revision") for p in target_heads]
                if (
                    any(type(n) is not int or n <= 0 for n in revisions)
                    or len(revisions) != len(set(revisions))
                    or sum(
                        t["role"] == "trade" and t["target_id"] == target_id
                        for t in proof["targets"]
                    )
                    != 1
                ):
                    blockers.add("paid_nkd_money_journal_fork")
                blockers.update(money.proof_blockers(session, *entry))
                view = trades._read(session, context, trade)
                item["canonical_trade"] = view
                blockers.update(view["conflicts"])
                source = context["projections"][trade.source_identity]
                item["current_source"] = source
                # Full canonical source union is validated above; retain every
                # supporting original, including out-of-window trade reports.
                source_ids = (
                    {
                        s["import_id"]
                        for t in (retained or {}).get("targets", [])
                        if t["target_id"] == target_id
                        for s in t.get("sources", [])
                    }
                    | {
                        s.id
                        for s in context["imports"]
                        if any(
                            t["identity"] == trade.source_identity
                            for t in json.loads(s.normalized_json)["trades"]
                        )
                    }
                    | {o.import_id for o in target_owners}
                )
                item["sources"] = [
                    {"import_id": sid, "material": money.material(session.get(MyBrokerImport, sid))}
                    for sid in sorted(source_ids)
                ]
                instrument = session.get(Instrument, trade.instrument_id)
                item["instrument"] = money.material(instrument)
                month = session.get(ReportingMonth, receipt.reporting_month_id)
                item["month_geometry"] = (
                    {
                        k: str(getattr(month, k))
                        for k in (
                            "id",
                            "year",
                            "month",
                            "snapshot_date",
                            "period_start",
                            "period_end",
                        )
                    }
                    if month
                    else None
                )
                cp = frozen.get("cash_proof")
                if (
                    not cp
                    or cash.is_stock_proof(cp)
                    or cash.effective_proof(session, trade.source_identity) != cp
                    or current["cash_proof"] != cp
                    or view["evidence"].get("cash_reconciliation") != cp
                ):
                    blockers.add("paid_nkd_exact_proof_required")
                if (
                    trade.account_id != account_id
                    or receipt.account_id != account_id
                    or view["acceptance_state"] != "active"
                    or view["evidence"]["lifecycle"] != "settled"
                    or instrument is None
                    or instrument.instrument_type != "bond"
                    or instrument.currency != "RUB"
                    or month is None
                    or not source["settlement_date"]
                    or not a.isoformat() < source["settlement_date"] <= b.isoformat()
                    or not month.period_start.isoformat()
                    <= source["settlement_date"]
                    <= month.period_end.isoformat()
                ):
                    blockers.add("paid_nkd_scope_conflict")
                cohort = [
                    o
                    for o in proof["occurrences"]
                    if (o["role"], o["target_id"]) == ("trade", target_id)
                ]
                keys = [key(o) for o in cohort]
                if (
                    len(keys) != 3
                    or len(set(keys)) != 3
                    or set(keys) != {key(o) for o in target_owners if o.section == "money"}
                    or len({o["import_id"] for o in cohort}) != 1
                ):
                    blockers.add("paid_nkd_occurrence_set_conflict")
                groups, leg_refs = {}, {}
                for leg in view["evidence"]["cash_legs"]:
                    role = leg["role"]
                    if role not in ("settlement", "commission", "paid_nkd"):
                        blockers.add("paid_nkd_unexpected_cash_role")
                        continue
                    groups.setdefault(role, []).append(
                        {
                            "amount": leg["source_amount"],
                            "date": leg["effective_date"],
                            "currency": leg["currency"],
                        }
                    )
                    refs = leg["occurrences"]
                    if len(refs) != 1 or leg["observed_multiplicity"] != 1:
                        blockers.add("paid_nkd_overlapping_sources")
                    for ref in refs:
                        k = (ref["import_id"], "money", ref["ordinal"])
                        if k in leg_refs:
                            blockers.add("paid_nkd_duplicate_role")
                        leg_refs[k] = (role, ref["source_fingerprint"])
                if set(leg_refs) != set(keys):
                    blockers.add("paid_nkd_proof_role_conflict")
                if cp:
                    if (
                        len(view["ids"]) != 2
                        or not all(view["ids"])
                        or cp["native_ids"] != view["ids"]
                        or source["ids"] != view["ids"]
                        or cp["source_identity"] != trade.source_identity
                        or cp["claims"]["native_total_basis"]
                        not in ("includes_paid_nkd", "excludes_paid_nkd")
                        or not cp["claims"].get("review_context_digest")
                        or cp.get("nkd_leg") not in view["evidence"]["cash_legs"]
                    ):
                        blockers.add("paid_nkd_native_proof_conflict")
                    blockers.update(cash.cash_reasons(source, groups, cp))
                for occurrence in cohort:
                    original = session.get(MyBrokerImport, occurrence["import_id"])
                    rows = (
                        [
                            r
                            for r in json.loads(original.normalized_json)["money"]
                            if r["ordinal"] == occurrence["ordinal"]
                        ]
                        if original
                        else []
                    )
                    found = owners(session, [occurrence])
                    role, fingerprint = leg_refs.get(key(occurrence), (None, None))
                    if (
                        occurrence["section"] != "money"
                        or len(rows) != 1
                        or len(found) != 1
                        or found[0]["role"] != "trade"
                        or found[0]["target_id"] != target_id
                        or found[0]["row_fingerprint"] != occurrence["row_fingerprint"]
                        or fingerprint != occurrence["row_fingerprint"]
                        or digest(rows[0]) != fingerprint
                    ):
                        blockers.add("paid_nkd_ownership_conflict")
                    if len(rows) == 1:
                        row = rows[0]
                        if (
                            row["source_account"] != trade.source_account
                            or row["date"] != source["settlement_date"]
                            or row["currency"] != "RUB"
                            or not original.covered_from.isoformat()
                            <= row["date"]
                            <= original.covered_to.isoformat()
                            or role not in groups
                            or {
                                "amount": row["amount"],
                                "date": row["date"],
                                "currency": row["currency"],
                            }
                            not in groups.get(role, [])
                            or not money.effective_occurrence(session, original.id, row)
                        ):
                            blockers.add("paid_nkd_source_facts_conflict")
                if not blockers:
                    accepted.update(
                        (k, target_id)
                        for k, (role, _) in leg_refs.items()
                        if role == "paid_nkd" and k in scoped_keys
                    )
        except (ValueError, TypeError, KeyError, AttributeError, MyBrokerError, DecimalException):
            blockers.add("paid_nkd_evidence_invalid")
        item["cohort_owners"] = owners(session, cohort)
        item["blockers"] = sorted(blockers)
    return result, accepted
