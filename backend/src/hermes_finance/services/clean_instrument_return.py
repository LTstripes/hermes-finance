"""Read-only projection of clean security operands from an existing analysis."""

from dataclasses import asdict, replace
from datetime import timedelta
from decimal import Decimal

from hermes_finance.domain.clean_instrument_return import (
    calculate_clean_return,
    clean_trade_date,
    cost_only_trade,
    fee_only_trade_conflict,
)


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


def clean_gold_metric(observed, *, current=True):
    """Project existing dated gold operands without using separate fees."""
    from hermes_finance.services.returns_view import metric

    operands = [
        observed.get(key)
        for key in ("valuation_kopecks", "sale_amount_kopecks", "buy_amount_kopecks")
    ]
    reasons = set(observed.get("reason_codes", ())) - {"gold_separate_fees_unknown"}
    if observed.get("amount_basis") == "derived":
        reasons.add("gold_amount_derived")
    if not current:
        reasons.add("source_dependency_changed")
    reasons = tuple(sorted(reasons))
    value = (
        int(operands[0]) + int(operands[1]) - int(operands[2])
        if current
        and not (set(reasons) - {"gold_amount_derived"})
        and all(value is not None for value in operands)
        else None
    )
    return metric(value, reasons=reasons, method="clean_gold_history", estimate=bool(reasons))


def project_clean_analysis(analysis, isin, *, instrument_type=None):
    """Do not change or attest the events, the account bridge, or source receipts."""
    ignored_cost_reasons = {"unallocated_instrument_cost", "native_commission_unavailable"}
    if getattr(analysis.coverage, "unresolved_cost_only", False):
        ignored_cost_reasons.add("unresolved_account_cash_attribution")
    cost_sign_events = [e for e in analysis.events if "cost_sign_conflict" in e.reason_codes]
    if cost_sign_events and all(e.kind in {"FEE", "TAX"} for e in cost_sign_events):
        ignored_cost_reasons.add("cost_sign_conflict")
    unresolved_money = [e for e in analysis.events if "unrecognized_money" in e.reason_codes]
    if unresolved_money and all(
        e.attribution_basis == "explicit_tax_unclassified" for e in unresolved_money
    ):
        ignored_cost_reasons.add("unrecognized_money")

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
    quantity_reconciled = _clean_quantity_reconciled(analysis, events, isin)
    conflicts = [
        event for event in analysis.events if "trade_money_cash_conflict" in event.reason_codes
    ]
    fee_conflicts_only = bool(conflicts) and all(
        event.isin == isin and fee_only_trade_conflict(event) for event in conflicts
    )
    missing_components = [
        event for event in analysis.events if "trade_components_missing" in event.reason_codes
    ]
    fee_missing_only = bool(missing_components) and all(
        event.isin == isin and cost_only_trade(event) for event in missing_components
    )

    def clean_complete(name):
        coverage = analysis.coverage[name]
        reasons = set(coverage.reason_codes) - ignored_cost_reasons
        if name == "events":
            # A stale payout link affects payout coverage, not a separately
            # reconciled trade principal and valuation.
            reasons = {
                reason
                for reason in reasons
                if not reason.startswith("payout_link_") and reason != "unattributed_income"
            }
        if quantity_reconciled:
            if name == "events":
                if fee_missing_only:
                    reasons.discard("trade_components_missing")
                if fee_conflicts_only:
                    reasons.discard("trade_money_cash_conflict")
                if instrument_type == "stock" and getattr(
                    analysis.coverage, "fee_only_bridge", False
                ):
                    reasons.discard("native_money_cash_bridge_mismatch")
            if name == "quantity":
                reasons -= {
                    "quantity_events_incomplete",
                    "quantity_reconciliation_mismatch",
                    "cross_boundary_settlement",
                }
        return (coverage.complete or bool(coverage.reason_codes)) and not reasons

    clean = calculate_clean_return(
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
    if "source_sections_not_financially_accepted" in getattr(analysis, "reason_codes", ()):
        reason = "source_sections_not_financially_accepted"

        def partial(metric):
            return replace(
                metric,
                status="partial" if metric.value is not None else "unavailable",
                reason_codes=tuple(sorted(set(metric.reason_codes) | {reason})),
            )

        def unavailable(metric):
            return replace(
                metric,
                value=None,
                status="unavailable",
                reason_codes=tuple(sorted(set(metric.reason_codes) | {reason})),
            )

        known = (
            replace(partial(clean.known_result), value=clean.payouts.value)
            if clean.payouts.value not in (None, 0)
            else unavailable(clean.known_result)
        )
        return replace(
            clean,
            **{
                name: partial(getattr(clean, name))
                for name in (
                    "opening_value",
                    "closing_value",
                    "buys",
                    "sells",
                    "coupons",
                    "dividends",
                    "payouts",
                    "redemption",
                )
            },
            valuation_and_trades=unavailable(clean.valuation_and_trades),
            known_result=known,
            pnl=unavailable(clean.pnl),
            modified_dietz=unavailable(clean.modified_dietz),
        )
    return clean


def _clean_quantity_reconciled(analysis, events, isin):
    """Recheck principal dates and holdings before removing cost-only blockers."""
    from collections import defaultdict
    from decimal import Decimal, localcontext

    if (
        not any(cost_only_trade(event) for event in events)
        and ("cross_boundary_settlement" not in analysis.coverage["quantity"].reason_codes)
        and not getattr(analysis.coverage, "fee_only_bridge", False)
    ):
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
                (not event.counted and not cost_only_trade(event))
                or not event.current
                or event.quantity_delta is None
                or event.depository_settlement_date is None
            ):
                return False
            if event.kind in {"BUY", "SELL"}:
                principal_day = clean_trade_date(event)
                if principal_day is None:
                    return False
                cash_inside = analysis.opening_date < principal_day <= analysis.closing_date
            else:
                cash_inside = any(
                    analysis.opening_date < leg.date <= analysis.closing_date
                    for leg in event.cash_legs
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


def read_clean_account(session, source_account, start, end, *, isin=None, include_purchases=False):
    """Return one exact source scope and period without saving an attestation."""
    from hermes_finance.services.returns_view import _catalogue_names, _display_name
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
    views = None
    if include_purchases or any(
        row.analysis is not None
        and any("repo_trade_unsupported" in event.reason_codes for event in row.analysis.events)
        for row in source.instruments
    ):
        from hermes_finance.services.source_monthly_returns import _selected_sources

        selected, _ = _selected_sources(session, source_account)
        if all(original is not None and not error for original, _, error in selected):
            views = [view for _, view, _ in selected]
    instruments = []
    names = _catalogue_names(session, source.instruments)
    for row in source.instruments:
        analysis = purchase_analysis = row.analysis
        if views is not None:
            from hermes_finance.services.clean_repo_pairs import (
                clean_and_purchase_repo_projections,
                saved_proof_repo_evidence_complete,
            )

            allow_pair = saved_proof_repo_evidence_complete(
                session, source_account, start, end, views, row.isin
            )
            analysis, purchase_analysis = clean_and_purchase_repo_projections(
                analysis, views, row.isin, allow_pair=allow_pair
            )
        clean = project_clean_analysis(analysis, row.isin, instrument_type=row.instrument_type)
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
        item = {
            "isin": row.isin,
            "name": _display_name(row.source_name, row.isin) or names.get(row.isin) or row.isin,
            "instrument_type": row.instrument_type,
            "opening_date": row.analysis.opening_date,
            "closing_date": row.analysis.closing_date,
            **metrics,
        }
        if include_purchases:
            from hermes_finance.services.clean_purchase_returns import (
                clean_purchase_price_contributions,
            )

            item["purchases"] = clean_purchase_price_contributions(
                purchase_analysis, clean, row.isin, instrument_type=row.instrument_type
            )
        instruments.append(item)
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


def read_clean_overview(session, *, isin=None, include_purchases=False):
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
                    "result": read_clean_account(
                        session, account, start, end, isin=isin, include_purchases=include_purchases
                    ),
                }
            )
        return {"contract_version": "clean_returns_overview_v1", "accounts": accounts}


def clean_export_data(overview, *, gold=None, include_purchases=False, purchase_conflicts=()):
    """Project the same read into file-local account references for the AI report."""
    from fastapi.encoders import jsonable_encoder

    histories = (gold or {}).get("histories", [])
    account_refs = {
        value: f"gold-account-{index}"
        for index, value in enumerate(sorted({row["account_id"] for row in histories}), 1)
    }
    instrument_refs = {
        value: f"gold-instrument-{index}"
        for index, value in enumerate(sorted({row["instrument_id"] for row in histories}), 1)
    }

    def exported_instrument(instrument, scope):
        result = {**instrument, "name": None}
        if include_purchases:
            purchases = None if scope in purchase_conflicts else result.get("purchases")
            result["purchases"] = (
                None
                if purchases is None
                else [
                    {**purchase, "id": f"purchase-{index}"}
                    for index, purchase in enumerate(purchases, 1)
                ]
            )
        return result

    return jsonable_encoder(
        {
            "contract": "hermes.finance.clean_returns",
            "schema_version": "1.1.0" if include_purchases else "1.0.0",
            **(
                {"purchase_method": "fifo_clean_price_and_sales_without_payouts_v1"}
                if include_purchases
                else {}
            ),
            "source_contract": overview["contract_version"],
            "basis": "clean_principal_and_valuation_with_received_cash",
            "authority": "provisional",
            "currency": "RUB",
            "units": {
                "money": "integer_kopecks",
                "modified_dietz": "fraction_of_weighted_capital",
                "period": "opening_eod_exclusive_closing_eod_inclusive",
            },
            "accounts": [
                {
                    "account_ref": f"source-account-{index}",
                    "period": account["period"],
                    "instruments": [
                        exported_instrument(instrument, account["scope"])
                        for instrument in account["result"]["instruments"]
                    ],
                    "gaps": account["result"]["gaps"],
                }
                for index, account in enumerate(overview["accounts"], 1)
            ],
            "gold": [
                {
                    "account_ref": account_refs[row["account_id"]],
                    "instrument_ref": instrument_refs[row["instrument_id"]],
                    "period": row["period"],
                    "valuation_date": row["valuation_date"],
                    "currentness": row["currentness"],
                    "total_result": row["total_result"],
                    "buy_amount": row["buy_amount"],
                    "sale_amount": row["sale_amount"],
                }
                for row in histories
            ],
        }
    )
