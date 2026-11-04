"""Read-only, exact-source bridge from current historical redemption proof."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from hermes_finance.statement_import.mybroker import MyBrokerError, digest


def _single_transfer(view):
    from hermes_finance.statement_import.mybroker_return_structure import _inventory_tree

    root = _inventory_tree(view["observations"])
    rows = root.findall(
        "m:Trades3/m:Report/m:Tablix1/m:Details_Collection/m:Details", {"m": "MyBroker"}
    )
    return dict(rows[0].attrib) if len(rows) == 1 else None


def verified_redemptions(session, source_account, selected, native_scope, cancellation_dates):
    """Return narrow evidence only when two current original-bound proofs agree.

    Multiple cancellations, ambiguous rows, stale proofs or changed sources
    retain the existing broad uncertainty. No money or proof is written.
    """
    from hermes_finance.services import source_investment_proofs as proofs
    from hermes_finance.services.source_money_classifications import source_reference
    from hermes_finance.services.source_monthly_returns import _money

    if not cancellation_dates or native_scope is None or len(native_scope) != 1:
        return {}, {}
    try:
        views = [v for _, v, error in selected if not error and v]
        if len(views) != len(selected):
            return {}, {}
        analyses = {}
        reports = proofs.read_reports(
            session, source_account=source_account, analyses=analyses, include_xirr=False
        )
        current_ids = {r["proof_id"] for r in reports if r["status"] == "current"}
        candidates = []
        for row, plan in proofs._report_rows(session, source_account):
            if row.id not in current_ids:
                continue
            source = next((v for v in views if v["document_sha256"] == plan["source_sha256"]), None)
            native = plan.get("native", {}).get("cancellations", [])
            if source is None or len(native) != 1:
                continue
            account, isin, day_text, quantity = native[0]
            day = date.fromisoformat(day_text)
            if account not in native_scope or Decimal(quantity) >= 0:
                continue
            if day.replace(day=1) not in cancellation_dates.get(source["id"], ()):
                continue
            transfer = _single_transfer(source)
            if not transfer or any(
                transfer.get(field) != digest(value)
                for field, value in (
                    ("acc_code", account),
                    ("settlement_date", day_text + "T00:00:00"),
                    ("qty", quantity),
                )
            ):
                continue
            analysis = analyses.get(row.id, {}).get(isin)
            events = (
                [
                    e
                    for e in analysis.events
                    if e.kind == "REDEMPTION"
                    and e.current
                    and e.counted
                    and not e.reason_codes
                    and e.classification_status == "confirmed"
                    and e.isin == isin
                    and e.event_date == day
                    and e.native_source_account == account
                    and len(e.source_references) == 1
                    and len(e.cash_legs) == 1
                    and e.cash_legs[0].account_cash_kopecks > 0
                ]
                if analysis
                else []
            )
            if len(events) != 1:
                continue
            event = replace(
                events[0], quantity_delta=Decimal(quantity), depository_settlement_date=day
            )
            prefix = source["document_sha256"] + ":money:"
            reference = event.source_references[0]
            if not reference.startswith(prefix) or not reference[len(prefix) :].isdigit():
                continue
            ordinal = int(reference[len(prefix) :])
            raw = [r for r in source["document"]["money"] if r["ordinal"] == ordinal]
            if len(raw) != 1:
                continue
            ref = source_reference(source["id"], raw[0])
            flows = [
                (key, flow)
                for key, flow in _money(session, source, None, [])
                if flow.source_references == (ref,)
            ]
            if (
                len(flows) != 1
                or flows[0][1].amount_kopecks != event.cash_legs[0].account_cash_kopecks
                or flows[0][1].event_date != day
            ):
                continue
            key = f"money:{flows[0][0][0]}:{flows[0][0][1]}"
            candidates.append((transfer, day.replace(day=1), isin, key, event))
        scopes, event_map, conflicts = {}, {}, set()
        for view in views:
            transfer = _single_transfer(view)
            if transfer is None:
                continue
            matches = [
                (month, isin, key, event)
                for original, month, isin, key, event in candidates
                if original == transfer and month in cancellation_dates.get(view["id"], ())
            ]
            identities = {(month, isin, key) for month, isin, key, _ in matches}
            if len(identities) != 1:
                continue
            month, isin, key, event = matches[0]
            scopes[(view["id"], month)] = isin
            old = event_map.get(key)
            if old is not None and (
                old.isin,
                old.event_date,
                old.cash_legs[0].account_cash_kopecks,
                old.quantity_delta,
                old.depository_settlement_date,
            ) != (
                event.isin,
                event.event_date,
                event.cash_legs[0].account_cash_kopecks,
                event.quantity_delta,
                event.depository_settlement_date,
            ):
                conflicts.add(key)
            else:
                event_map[key] = event
        if conflicts:
            for key in conflicts:
                event_map.pop(key, None)
            scopes = {
                scope: isin
                for scope, isin in scopes.items()
                if any(
                    month == scope[1] and candidate_isin == isin and key not in conflicts
                    for _, month, candidate_isin, key, _ in candidates
                )
            }
        return scopes, event_map
    except (
        MyBrokerError,
        ValueError,
        TypeError,
        KeyError,
        ArithmeticError,
        AttributeError,
        IndexError,
        ET.ParseError,
    ):
        return {}, {}


def apply_verified_redemptions(events, evidence):
    """Replace only the identical unresolved cash observation, never a total."""
    result, resolved = [], set()
    for event in events:
        proof = evidence.get(event.event_key)
        if (
            proof is not None
            and proof.kind == "REDEMPTION"
            and proof.current
            and proof.counted
            and not proof.reason_codes
            and proof.classification_status == "confirmed"
            and proof.quantity_delta is not None
            and proof.quantity_delta < 0
            and proof.depository_settlement_date is not None
            and event.kind == "UNRESOLVED"
            and event.classification == "unknown"
            and event.classification_origin == "default_rule"
            and event.isin in (None, proof.isin)
            and event.native_source_account == proof.native_source_account
            and event.event_date == proof.event_date
            and set(event.reason_codes)
            == {"unrecognized_money", "redemption_amortization_unsupported"}
            and len(event.cash_legs) == len(proof.cash_legs) == 1
            and event.cash_legs[0].account_cash_kopecks
            == proof.cash_legs[0].account_cash_kopecks
            > 0
        ):
            event = replace(
                event,
                isin=proof.isin,
                effective_isin=proof.isin,
                kind="REDEMPTION",
                quantity_delta=proof.quantity_delta,
                depository_settlement_date=proof.depository_settlement_date,
                cash_settlement_date=proof.cash_legs[0].date,
                classification_status="confirmed",
                attribution_basis="current_historical_redemption_proof",
                current=True,
                counted=True,
                reason_codes=(),
                cash_legs=(replace(event.cash_legs[0], role="redemption"),),
            )
            resolved.add(event.event_key)
        result.append(event)
    return tuple(result), frozenset(resolved)
