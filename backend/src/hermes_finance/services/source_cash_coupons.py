"""H2-A2 v3 adapter for existing, independently effective Money coupon targets.

No acceptance or economic writer lives here. Both Money disposition and legacy
ICF partition consume the same exhaustive target authority.
"""

import json

from hermes_finance.persistence import (
    AppliedStatementEvent,
    BrokerMoneyOccurrenceOwner,
    BrokerMonthApply,
    Instrument,
    InvestmentCashFlow,
    MyBrokerImport,
    ReportingMonth,
)
from hermes_finance.services import broker_money as money
from hermes_finance.services.broker_money_ownership import key, owners
from hermes_finance.services.historical_owner_flows import _rows
from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def authority(session, account_id, a, b, scoped_money, *, retained=None):
    """Bind presence AND absence of proof, complete owners and current PDF support."""
    scoped_keys = {(source_id, "money", row["ordinal"]) for source_id, row in scoped_money}
    permanent = _rows(session, BrokerMoneyOccurrenceOwner)
    relevant_owners = [o for o in permanent if key(o) in scoped_keys]
    target_ids = (
        {o.investment_cash_flow_id for o in relevant_owners if o.role == "coupon"}
        | {
            f.id
            for f in _rows(session, InvestmentCashFlow)
            if f.account_id == account_id and a < f.event_date <= b and f.flow_type == "coupon"
        }
        | {t["target_id"] for t in (retained or {}).get("targets", [])}
    )
    # Retained IDs prevent deletion/remapping from erasing the old dependency.
    targets, accepted_keys, effective_ids = [], {}, set()
    try:
        latest = money.latest_proofs(session)
        journal = money.receipts(session)
        relevant_receipts = [
            money.material(receipt)
            for receipt, proof in journal
            if any(t["role"] == "coupon" and t["target_id"] in target_ids for t in proof["targets"])
            or any(key(o) in scoped_keys for o in proof["occurrences"])
        ]
    except (ValueError, TypeError, KeyError, MyBrokerError):
        return (
            {
                "targets": [],
                "owners": [money.material(o) for o in relevant_owners],
                "journal": [],
                "blockers": ["coupon_money_journal_invalid"],
            },
            {},
            set(),
        )
    for target_id in sorted(target_ids):
        blockers = set()
        item = {"target_id": target_id}
        target_owners = [
            o for o in permanent if o.role == "coupon" and o.investment_cash_flow_id == target_id
        ]
        item["owners"] = [money.material(o) for o in target_owners]
        current_proof = latest.get(("coupon", target_id))
        item["receipt"] = money.material(current_proof[0]) if current_proof else None
        cohort = []
        try:
            current = money._target(session, "coupon", target_id)
            item["current_target"] = current
            if current_proof is None:
                blockers.add("coupon_money_proof_missing")
            else:
                receipt, proof, accepted = current_proof
                blockers.update(money.proof_blockers(session, receipt, proof, accepted))
                cohort = [
                    o
                    for o in proof["occurrences"]
                    if (o["role"], o["target_id"]) == ("coupon", target_id)
                ]
                cohort_keys = [key(o) for o in cohort]
                if (
                    not cohort
                    or len(cohort_keys) != len(set(cohort_keys))
                    or set(cohort_keys) != {key(o) for o in target_owners}
                ):
                    blockers.add("coupon_occurrence_set_conflict")
                facts = current["facts"]
                instrument = session.get(Instrument, int(facts["instrument_id"])) if facts else None
                item["instrument"] = money.material(instrument)
                month = session.get(ReportingMonth, receipt.reporting_month_id)
                item["month_geometry"] = (
                    {
                        field: str(getattr(month, field))
                        for field in (
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
                if (
                    not facts
                    or facts["account_id"] != str(account_id)
                    or facts["reporting_month_id"] != str(receipt.reporting_month_id)
                    or receipt.account_id != account_id
                    or facts["flow_type"] != "coupon"
                    or facts["currency"] != "RUB"
                    or not a.isoformat() < facts["event_date"] <= b.isoformat()
                    or month is None
                    or not month.period_start.isoformat()
                    <= facts["event_date"]
                    <= month.period_end.isoformat()
                    or instrument is None
                    or instrument.instrument_type != "bond"
                    or instrument.currency != "RUB"
                ):
                    blockers.add("coupon_target_scope_conflict")
                for occurrence in cohort:
                    source = session.get(MyBrokerImport, occurrence["import_id"])
                    rows = (
                        [
                            r
                            for r in json.loads(source.normalized_json)["money"]
                            if r["ordinal"] == occurrence["ordinal"]
                        ]
                        if source
                        else []
                    )
                    found = owners(session, [occurrence])
                    if (
                        occurrence["section"] != "money"
                        or len(rows) != 1
                        or len(found) != 1
                        or found[0]["role"] != "coupon"
                        or found[0]["target_id"] != target_id
                        or found[0]["row_fingerprint"] != occurrence["row_fingerprint"]
                        or digest(rows[0]) != occurrence["row_fingerprint"]
                    ):
                        blockers.add("coupon_ownership_conflict")
                    if len(rows) == 1 and (
                        not facts
                        or rows[0]["date"] != facts["event_date"]
                        or rows[0]["currency"] != facts["currency"]
                        or money.broker_months._minor(rows[0]["amount"])
                        != int(facts["net_amount_kopecks"])
                    ):
                        blockers.add("coupon_source_facts_conflict")
                for owner in target_owners:
                    original = session.get(BrokerMonthApply, owner.accepted_request_id)
                    original_proof = json.loads(original.projection_json) if original else {}
                    if not any(
                        key(o) == key(owner)
                        and o["role"] == "coupon"
                        and o["target_id"] == target_id
                        and o["row_fingerprint"] == owner.row_fingerprint
                        for o in original_proof.get("occurrences", [])
                    ):
                        blockers.add("coupon_owner_receipt_missing")
                # Frozen fiscal/PDF meaning comes from canonical Money. It also
                # validates additive typed attachments; never invent tax zero.
                from hermes_finance.services.statement_import_apply import (
                    _linked_flow_matches_accepted,
                )

                flow = session.get(InvestmentCashFlow, target_id)
                if any(
                    event.status != "active"
                    or flow is None
                    or not _linked_flow_matches_accepted(session, event=event, flow=flow)
                    for event in _rows(session, AppliedStatementEvent)
                    if event.investment_cash_flow_id == target_id
                ):
                    blockers.add("coupon_typed_statement_conflict")
        except (ValueError, TypeError, KeyError, MyBrokerError, AttributeError):
            blockers.add("coupon_money_evidence_invalid")
        try:
            item["cohort_owners"] = owners(session, cohort)
        except (ValueError, TypeError, KeyError):
            item["cohort_owners"] = None
            blockers.add("coupon_money_evidence_invalid")
        item["blockers"] = sorted(blockers)
        if not blockers:
            effective_ids.add(target_id)
            accepted_keys.update((key(o), target_id) for o in cohort)
        targets.append(item)
    return (
        {
            "targets": targets,
            "owners": [money.material(o) for o in relevant_owners],
            "journal": relevant_receipts,
            "blockers": [],
        },
        accepted_keys,
        effective_ids,
    )
