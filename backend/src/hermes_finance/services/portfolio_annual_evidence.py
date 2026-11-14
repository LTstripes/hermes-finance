"""Current native account operands for B9; no legacy proof is revived or written."""

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from hermes_finance.services.returns_read_inputs import source_blockers
from hermes_finance.services.source_money_classifications import default_classification
from hermes_finance.services.source_monthly_returns import (
    _FINANCIAL_COMPLETENESS_BLOCKERS,
    _flow_coverage_complete,
    _money,
    _native_scope,
    _saved_totals,
)
from hermes_finance.services.source_return_evidence import (
    bound_import,
    canonical_payout_groups,
    effective_section_blockers,
)
from hermes_finance.services.source_return_proofs import resolve_proof


def _zero_opening(document):
    """The same explicit quantities/cash inception test as source_report_preview.

    A missing historical price on an explicitly zero quantity needs no valuation.
    A missing quantity or cash balance can never establish inception.
    """
    cash = document.get("rub_money", [])
    return (
        len(cash) == 1
        and cash[0].get("currency") == "RUB"
        and cash[0].get("beginning_amount") is not None
        and Decimal(cash[0]["beginning_amount"]) == 0
        and all(
            row.get("beginning_actual_quantity") is not None
            and Decimal(row["beginning_actual_quantity"]) == 0
            and (row.get("beginning_value") is None or Decimal(row["beginning_value"]) == 0)
            for row in document.get("positions", [])
        )
    )


def _operation_classification(choice, amount):
    classification = default_classification(
        choice["operation"], choice["narrative"], None, Decimal(amount) / 100
    )
    if (
        classification == "unknown"
        and amount >= 0
        and choice["operation"].casefold().strip()
        in {"проценты на остаток", "проценты на остаток денежных средств", "cash interest"}
    ):
        return "cash_interest"
    if (
        classification == "unknown"
        and amount > 0
        and choice["operation"] == "Перевод"
        # The existing source_report_preview account-only compensation grammar.
        # This explains portfolio income without assigning it to an instrument.
        and re.fullmatch(
            r"Компенсация утраченных дивидендов по акциям [A-Z0-9_]+ дата фиксации реестра [0-9/]+\.",
            choice["narrative"],
        )
    ):
        return "dividend_compensation"
    return classification


def _inception_attested(session, native, views, first):
    """Keep the saved from-zero declaration, independently of old economics.

    A zero balance alone can also follow a full withdrawal. Require the sealed
    Owner declaration for this exact retained source, its zero quantities/cash,
    and no observed activity before its declared start. No stale financial
    operand, payout link or classification is consumed from that receipt.
    """
    from hermes_finance.services import source_investment_proofs as proofs

    if first is None:
        return False
    for row, plan in proofs._report_rows(session, native):
        if (
            plan["from_zero"] is True
            and plan["native_account"] == row.native_account == native
            and proofs._evidence_digest(plan) == row.dependency_digest
            and plan["covered_from"] <= str(first) <= plan["covered_to"]
            and any(
                view["id"] == plan["intake_id"]
                and view["document_sha256"] == plan["source_sha256"]
                and view["covered_from"] == plan["covered_from"]
                and view["covered_to"] == plan["covered_to"]
                and _zero_opening(view["document"])
                for view in views
            )
        ):
            return True
    return False


def _redemptions(session, native, start, end):
    """Reuse #1191's exact issue/cash/face/cancellation recognition unchanged."""
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    result = read_instrument_returns(
        session,
        source_account=native,
        opening_date=start - timedelta(days=1),
        closing_date=end,
        include_monthly_history=False,
        available_period=True,
        clean_projection=True,
    )
    events = {}
    for row in result.instruments:
        for event in row.analysis.events if row.analysis else ():
            if (
                event.kind == "REDEMPTION"
                and event.current
                and event.counted
                and not event.reason_codes
                and event.isin
                and event.native_source_account == native
                and event.quantity_delta is not None
                and event.quantity_delta.is_finite()
                and event.quantity_delta < 0
                and event.depository_settlement_date == event.event_date
                and len(event.cash_legs) == 1
                and event.cash_legs[0].role == "redemption"
                and event.cash_legs[0].date == event.event_date
                and event.cash_legs[0].account_cash_kopecks > 0
            ):
                for ref in event.source_references:
                    events[ref] = event if ref not in events or events[ref] == event else None
    return events


def read_native_history(session, native, selected, native_scope):
    try:
        return _read_native_history(session, native, selected, native_scope)
    except (ValueError, TypeError, KeyError, ArithmeticError, OSError):
        return None, None, None, (), {"overall_external_flows_incomplete"}, set()


def _read_native_history(session, native, selected, native_scope):
    reasons, estimates = set(), set()
    views = [v for _, v, error in selected if v and not error]
    if not selected or len(views) != len(selected) or native_scope != {native}:
        return None, None, None, (), {"overall_external_flows_incomplete"}, estimates
    start = min(date.fromisoformat(v["covered_from"]) for v in views)
    end = max(date.fromisoformat(v["covered_to"]) for v in views)
    earliest = [v for v in views if v["covered_from"] == str(start)]
    if not all(_zero_opening(v["document"]) for v in earliest):
        reasons.add("overall_inception_unproven")
    ranges = [
        (
            v["id"],
            date.fromisoformat(v["covered_from"]),
            date.fromisoformat(v["covered_to"]),
            None,
            None,
        )
        for v in views
    ]
    if not _flow_coverage_complete(ranges, start, end):
        reasons.add("overall_external_flows_incomplete")

    cancellations, _ = resolve_proof(session, native, selected, native_scope)
    groups, activity, choices = defaultdict(list), [], {}
    payout_groups = canonical_payout_groups(session, views)
    for view in views:
        document = view["document"]
        blockers = source_blockers(session, view)
        if view["id"] in cancellations:
            blockers -= {"unparsed_source_rows", "4_Transfers_unsupported", "5_UFSR_unsupported"}
        original_blockers = blockers.copy()
        blockers = effective_section_blockers(session, bound_import(session, view), blockers)
        if (
            _native_scope(document) != native_scope
            or "period_inferred_from_content" in document.get("warnings", [])
            or _FINANCIAL_COMPLETENESS_BLOCKERS.intersection(blockers)
            or blockers - original_blockers
        ):
            reasons.add("overall_external_flows_incomplete")
        choices.update((c["source_reference"], c) for c in view["money_classifications"])
        activity.extend(date.fromisoformat(r["date"]) for r in document.get("money", []))
        activity.extend(
            date.fromisoformat(t["core"]["trade_time"][:10])
            for t in document.get("trades", [])
            if t["core"].get("trade_time")
        )
        gaps = []
        for key, flow in _money(session, view, None, gaps, payout_groups=payout_groups):
            groups[key].append(flow)
        if any(g.code != "broker_gift_external_flow" for g in gaps):
            reasons.add("overall_external_flows_incomplete")

    first = min(activity, default=None)
    if first is None or first < start or not _inception_attested(session, native, views, first):
        reasons.add("overall_inception_unproven")
    closings = [_saved_totals(v["document"])[1] for v in views if v["covered_to"] == str(end)]
    closing = closings[0] if len(set(closings)) == 1 else None
    if closing is None:
        reasons.add("overall_valuation_unavailable")
    redemptions = _redemptions(session, native, start, end) if cancellations else {}
    resolved_cancellations, flows = set(), []
    for observations in groups.values():
        confirmed = [f for f in observations if f.status == "confirmed"]
        chosen = confirmed or observations
        flow = chosen[0]
        refs = {ref for f in observations for ref in f.source_references}
        if (
            len({(f.included, f.classification, f.amount_kopecks, f.event_date) for f in chosen})
            != 1
        ):
            reasons.add("overall_external_flows_incomplete")
            continue
        covering = {
            v["id"] for v in views if v["covered_from"] <= str(flow.event_date) <= v["covered_to"]
        }
        present = [int(ref.split(":")[1]) for ref in refs]
        if set(present) != covering or len(present) != len(covering):
            reasons.add("overall_external_flows_incomplete")
        classification = flow.classification
        if classification == "unknown":
            evidence = [redemptions.get(ref) for ref in refs]
            if (
                evidence
                and all(
                    e is not None
                    and e.event_date == flow.event_date
                    and e.cash_legs[0].account_cash_kopecks == flow.amount_kopecks
                    for e in evidence
                )
                and len({e.event_key for e in evidence}) == 1
            ):
                classification = "redemption"
                from hermes_finance.services.source_redemption_evidence import _single_transfer

                resolved_cancellations.update(
                    (v["id"], flow.event_date.replace(day=1))
                    for v in views
                    if v["id"] in covering and _single_transfer(v) is not None
                )
            else:
                # Re-evaluate source operation types only for unchanged default
                # UNKNOWNs. Explicit Owner UNKNOWN remains unknown.
                defaults = {
                    _operation_classification(c, flow.amount_kopecks)
                    for ref in refs
                    if (c := choices[ref])["origin"] == "default_rule" and c["status"] == "assumed"
                }
                if len(defaults) == 1 and all(
                    choices[ref]["origin"] == "default_rule" for ref in refs
                ):
                    classification = next(iter(defaults))
        if classification == "unknown":
            if abs(flow.amount_kopecks) < 10000:
                estimates.add("overall_small_unknown_assumed_internal")
            else:
                reasons.add("overall_external_flows_incomplete")
        elif classification == "internal_transfer":
            reasons.add("overall_internal_transfer_unproven")
        elif classification in {"external_deposit", "external_withdrawal", "external_gift"}:
            if (
                not flow.included
                or not flow.amount_kopecks
                or (classification == "external_withdrawal") != (flow.amount_kopecks < 0)
            ):
                reasons.add("overall_external_flows_incomplete")
            else:
                flows.append((flow.event_date, flow.amount_kopecks))
        elif classification not in {
            "redemption",
            "coupon",
            "dividend",
            "tax",
            "fee",
            "trade_settlement",
            "cash_interest",
            "dividend_compensation",
        }:
            reasons.add("overall_external_flows_incomplete")
    pending = {(key, month) for key, months in cancellations.items() for month in months}
    if pending - resolved_cancellations:
        reasons.add("overall_external_flows_incomplete")
    return first, end, closing, tuple(flows), reasons, estimates
