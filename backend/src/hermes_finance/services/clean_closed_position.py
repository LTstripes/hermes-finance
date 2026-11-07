"""Narrow, read-only inference for a sold-out security's clean return."""

from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import clean_trade_date
from hermes_finance.domain.instrument_return import Coverage


def infer_closed_position(analysis, views, isin, kind):
    """Use balanced ordinary trades and absence in the last dated statement.

    This applies only to the whole available source span. Explicit intermediate
    quantities, source gaps and current proof conflicts must still agree.
    """
    from hermes_finance.services.clean_instrument_return import _clean_quantity_reconciled
    from hermes_finance.services.source_instrument_returns import _SOURCE_GAPS, _minor, _quantity

    if not views or kind not in {"stock", "bond"}:
        return analysis
    start, end = analysis.opening_date, analysis.closing_date
    if start != min(date.fromisoformat(v["covered_from"]) for v in views) - timedelta(
        days=1
    ) or end != max(date.fromisoformat(v["covered_to"]) for v in views):
        return analysis
    latest = [v for v in views if date.fromisoformat(v["covered_to"]) == end]
    if any(
        any(row["isin"] == isin for row in view["document"].get("positions", ())) for view in latest
    ):
        return analysis

    blockers = _SOURCE_GAPS | {
        "incomplete_source_coverage",
        "seam_mismatch",
        "overlapping_endpoint_conflict",
        "duplicate_position",
        "quantity_value_conflict",
        "endpoint_basis_unsupported",
        "investment_proof_stale",
        "source_sections_not_financially_accepted",
        "pdf_xml_position_mismatch",
        "pdf_position_invalid",
        "pdf_position_date_missing",
        "pdf_position_date_invalid",
    }
    reasons = set(analysis.reason_codes)
    for coverage in analysis.coverage.values():
        reasons.update(coverage.reason_codes)
        if not coverage.complete and not coverage.reason_codes:
            return analysis
    if reasons & blockers:
        return analysis
    for view in views:
        document = view["document"]
        if (
            "period_inferred_from_content" in document.get("warnings", ())
            or document.get("endpoint_basis")
            != {"beginning_value": "previous_day_eod", "ending_value": "covered_to_eod"}
            or "position_row_unclassified" in document.get("endpoint_blockers", ())
        ):
            return analysis

    opening, closing = analysis.opening, analysis.closing
    harmless_endpoint_reasons = {"missing_endpoint", "bond_valuation_basis_unknown"}
    if (
        opening.quantity not in (None, Decimal(0))
        or opening.reported_value_kopecks not in (None, 0)
        or closing.quantity is not None
        or closing.reported_value_kopecks is not None
        or set(opening.reason_codes) - harmless_endpoint_reasons
        or set(closing.reason_codes) - harmless_endpoint_reasons
    ):
        return analysis

    trades = [e for e in analysis.events if e.isin == isin and e.kind in {"BUY", "SELL"}]
    if (
        {e.kind for e in trades} != {"BUY", "SELL"}
        or any(
            "repo_trade_unsupported" in e.reason_codes
            or e.execution_date is None
            or clean_trade_date(e) is None
            or e.depository_settlement_date is None
            or e.execution_date > clean_trade_date(e)
            or e.execution_date > e.depository_settlement_date
            for e in trades
        )
        or any(e.isin == isin and e.kind == "REDEMPTION" for e in analysis.events)
    ):
        return analysis

    # These are analytical values, not printed broker position values.
    opening = replace(
        opening,
        quantity=Decimal(0),
        economic_value_kopecks=0,
        reason_codes=tuple(r for r in opening.reason_codes if r not in harmless_endpoint_reasons),
    )
    closing = replace(
        closing,
        quantity=Decimal(0),
        economic_value_kopecks=0,
        source_references=closing.source_references
        + tuple(f"position_absent:{v['id']}:closing" for v in latest),
        reason_codes=tuple(r for r in closing.reason_codes if r not in harmless_endpoint_reasons),
    )
    candidate = replace(analysis, opening=opening, closing=closing)
    own_events = [event for event in analysis.events if event.isin == isin]
    if not _clean_quantity_reconciled(candidate, own_events, isin):
        return analysis

    # Every explicit source position at an intermediate boundary must match
    # the same dated trade inventory, even when the outer quantities net to 0.
    with localcontext() as context:
        context.prec = 200
        moments = defaultdict(list)
        for trade in trades:
            try:
                instant = datetime.fromisoformat(trade.trade_time)
            except (TypeError, ValueError):
                return analysis
            if instant.tzinfo is not None or instant.date() != trade.execution_date:
                return analysis
            moments[instant].append(trade)
        held = Decimal(0)
        for instant in sorted(moments):
            group = moments[instant]
            # If trades share an instant, every possible ordering must be safe.
            held += sum((e.quantity_delta for e in group if e.kind == "SELL"), Decimal(0))
            if held < 0:
                return analysis
            held += sum((e.quantity_delta for e in group if e.kind == "BUY"), Decimal(0))
        for view in views:
            rows = [r for r in view["document"].get("positions", ()) if r["isin"] == isin]
            if len(rows) > 1:
                return analysis
            for is_closing in (False, True):
                boundary = (
                    date.fromisoformat(view["covered_to"])
                    if is_closing
                    else date.fromisoformat(view["covered_from"]) - timedelta(days=1)
                )
                if not rows or not start <= boundary <= end:
                    continue
                predicted = sum(
                    (e.quantity_delta for e in trades if e.depository_settlement_date <= boundary),
                    Decimal(0),
                )
                row = rows[0]
                quantity = _quantity(
                    row.get("actual_quantity" if is_closing else "beginning_actual_quantity")
                )
                raw_value = row.get("ending_value" if is_closing else "beginning_value")
                value = _minor(raw_value)
                if (
                    quantity is not None
                    and quantity != predicted
                    or raw_value is not None
                    and value is None
                    or value is not None
                    and (value < 0 or predicted == 0 and value != 0)
                ):
                    return analysis

    coverage = dict(analysis.coverage)
    for name, removed in (
        ("quantity", {"missing_quantity"}),
        ("endpoints", {"missing_endpoint"}),
        ("valuation", harmless_endpoint_reasons),
    ):
        remaining = tuple(r for r in coverage[name].reason_codes if r not in removed)
        coverage[name] = Coverage(not remaining, remaining)
    return replace(
        candidate,
        coverage=coverage,
        reason_codes=tuple(
            r
            for r in analysis.reason_codes
            if r not in harmless_endpoint_reasons | {"missing_quantity"}
        ),
    )
