"""Read-only projection of clean security operands from an existing analysis."""

from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal

from hermes_finance.domain.clean_instrument_return import calculate_clean_return, missing_fee_only


def _clean_endpoint(endpoint, instrument_type):
    # An explicitly empty position has no accrued interest. A nonzero dirty
    # bond value cannot be made clean without an actual accrued-interest value.
    if (
        endpoint.quantity == 0
        and endpoint.reported_value_kopecks == 0
        and not (set(endpoint.reason_codes) - {"bond_valuation_basis_unknown"})
    ):
        return 0
    if (
        instrument_type == "stock"
        and endpoint.accrued_interest_kopecks in (None, 0)
        and endpoint.economic_value_kopecks is not None
        and not endpoint.reason_codes
    ):
        return endpoint.economic_value_kopecks
    if (
        endpoint.economic_value_kopecks is None
        or endpoint.accrued_interest_kopecks is None
        or endpoint.accrued_interest_kopecks < 0
        or endpoint.accrued_interest_kopecks > endpoint.economic_value_kopecks
    ):
        return None
    return endpoint.economic_value_kopecks - endpoint.accrued_interest_kopecks


def project_clean_analysis(analysis, isin, *, instrument_type=None):
    """Do not change or attest the events, the account bridge, or source receipts."""
    ignored_cost_reasons = {"unallocated_instrument_cost", "native_commission_unavailable"}

    def complete(*names):
        return all(
            (analysis.coverage[name].complete or bool(analysis.coverage[name].reason_codes))
            and not (set(analysis.coverage[name].reason_codes) - ignored_cost_reasons)
            for name in names
        )

    opening = _clean_endpoint(analysis.opening, instrument_type)
    closing = _clean_endpoint(analysis.closing, instrument_type)
    events = []
    for event in analysis.events:
        if event.isin != isin:
            continue
        # The investment-report adapter records the native amount only for a
        # unique, fully identified ordinary trade. Stocks have no NKD; do not
        # extend this inference to bonds, anonymous Money or REPO.
        if (
            instrument_type == "stock"
            and event.kind in {"BUY", "SELL"}
            and event.native_total_basis is None
            and event.attribution_basis == "native_money_group_bridge"
            and event.native_identity is not None
            and event.accrued_interest_kopecks in (None, 0)
        ):
            event = replace(event, native_total_basis="excludes_paid_nkd")
        events.append(event)
    fee_only_reconciled = _fee_only_quantity_reconciled(analysis, events, isin)

    def clean_complete(name):
        coverage = analysis.coverage[name]
        reasons = set(coverage.reason_codes) - ignored_cost_reasons
        if fee_only_reconciled:
            if name == "events":
                reasons.discard("trade_components_missing")
            if name == "quantity":
                reasons -= {"quantity_events_incomplete", "quantity_reconciliation_mismatch"}
        return (coverage.complete or bool(coverage.reason_codes)) and not reasons

    return calculate_clean_return(
        analysis.opening_date,
        analysis.closing_date,
        opening,
        closing,
        tuple(events),
        trades_complete=clean_complete("events") and clean_complete("quantity"),
        payouts_complete=complete("payouts"),
        redemptions_complete=clean_complete("quantity"),
        valuation_complete=opening is not None and closing is not None,
    )


def _fee_only_quantity_reconciled(analysis, events, isin):
    """Recheck quantity before disregarding a legacy missing-fee blocker."""
    from collections import defaultdict
    from decimal import Decimal, localcontext

    if not any(missing_fee_only(event) for event in events):
        return False
    if any(
        event.isin != isin and event.kind in {"BUY", "SELL", "REDEMPTION"}
        for event in analysis.events
    ):
        return False
    q0, q1 = analysis.opening.quantity, analysis.closing.quantity
    if q0 is None or q1 is None:
        return False
    daily = defaultdict(Decimal)
    with localcontext() as context:
        context.prec = 200
        for event in events:
            if event.kind not in {"BUY", "SELL", "REDEMPTION"}:
                continue
            if (
                (not event.counted and not missing_fee_only(event))
                or not event.current
                or event.quantity_delta is None
                or event.depository_settlement_date is None
            ):
                return False
            cash_inside = any(
                analysis.opening_date < leg.date <= analysis.closing_date for leg in event.cash_legs
            )
            if missing_fee_only(event):
                cash_inside = (
                    event.cash_settlement_date is not None
                    and analysis.opening_date < event.cash_settlement_date <= analysis.closing_date
                )
            depo_inside = (
                analysis.opening_date < event.depository_settlement_date <= analysis.closing_date
            )
            if cash_inside != depo_inside:
                return False
            if depo_inside:
                daily[event.depository_settlement_date] += event.quantity_delta
        holding = q0
        for change in (daily[day] for day in sorted(daily)):
            holding += change
            if holding < 0:
                return False
        return holding == q1


def read_clean_account(session, source_account, start, end, *, isin=None):
    """Return one exact source scope and period without saving an attestation."""
    from hermes_finance.services.source_instrument_returns import read_instrument_returns

    source = read_instrument_returns(
        session,
        source_account=source_account,
        isin=isin,
        opening_date=start,
        closing_date=end,
        include_monthly_history=False,
        available_period=True,
    )
    instruments = []
    for row in source.instruments:
        clean = project_clean_analysis(row.analysis, row.isin, instrument_type=row.instrument_type)
        metrics = asdict(clean)
        for metric in metrics.values():
            value = metric["value"]
            metric["value"] = (
                None
                if value is None
                else format(value, "f")
                if isinstance(value, Decimal)
                else str(value)
            )
        instruments.append(
            {
                "isin": row.isin,
                "name": row.source_name,
                "instrument_type": row.instrument_type,
                "opening_date": row.analysis.opening_date,
                "closing_date": row.analysis.closing_date,
                **metrics,
            }
        )
    return {
        "contract_version": "clean_instrument_return_v1",
        "authority": "provisional",
        "financial_authority": "none",
        "source_account": source_account,
        "native_source_account": source.native_source_account,
        "currency": "RUB",
        "instruments": instruments,
        "gaps": [{"code": gap.code, "month": gap.month, "isin": gap.isin} for gap in source.gaps],
    }


def read_clean_overview(session):
    """Read each source account's outer saved period in one source snapshot."""
    from hermes_finance.services.returns_view import _accounts, _source_scopes
    from hermes_finance.services.source_monthly_returns import (
        _selected_sources,
        source_read_snapshot,
    )

    with source_read_snapshot(session):
        canonical = _source_scopes(session)
        labels = {a["id"]: a["label"] for a in _accounts(session, canonical)}
        accounts = []
        for account in sorted(set(canonical.values())):
            selected, _ = _selected_sources(session, account)
            originals = [original for original, _, _ in selected if original is not None]
            if not originals:
                continue
            start = min(original.covered_from for original in originals) - timedelta(days=1)
            end = max(original.covered_to for original in originals)
            accounts.append(
                {
                    "scope": f"source:{account}",
                    "label": labels.get(f"source:{account}", account),
                    "period": {"start": start, "end": end},
                    "result": read_clean_account(session, account, start, end),
                }
            )
        return {"contract_version": "clean_returns_overview_v1", "accounts": accounts}
