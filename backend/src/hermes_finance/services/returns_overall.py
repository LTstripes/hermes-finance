"""Read-only all-history presentation, without a cross-category return kernel.

Each source result keeps its exact original-bound interval and authority. Known
deposit receipts and saved gold valuation are separate components, never extra
operands added to investment P&L. The union model remains explicitly unavailable.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext
from types import SimpleNamespace

from sqlalchemy import select

from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    DepositSnapshot,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services import returns_view, source_investment_proofs
from hermes_finance.services.source_instrument_returns import _identities
from hermes_finance.services.source_monthly_returns import _selected_sources, source_read_snapshot
from hermes_finance.statement_import.mybroker import PROVIDER


def _unknown(reason, *, rate=False):
    return returns_view.metric(
        reasons=(reason,), unit="fraction" if rate else "kopecks", estimate=False
    )


def _period(month):
    return returns_view.bounds(month.period_start - timedelta(days=1), month.period_end)


def _deposits(session, months):
    rows = list(session.scalars(select(DepositSnapshot).order_by(DepositSnapshot.id)))
    by_month = defaultdict(list)
    for row in rows:
        by_month[row.reporting_month_id].append(row)
    periods, known, excluded = [], [], False
    for month in months:
        selected = by_month.get(month.id, [])
        if not selected and not rows:
            continue
        periods.append({"period": _period(month), "status": month.status, "rows": len(selected)})
        if month.status == "closed":
            known.extend(row.actual_interest_received_kopecks for row in selected)
        else:
            excluded = True
    reasons = ["known_received_interest_only", "deposit_full_history_not_proven"]
    if excluded:
        reasons.append("draft_deposit_interest_excluded")
    return {
        "interest": returns_view.metric(
            sum(known) if known else None,
            reasons=reasons,
            method="deposit_received_interest",
            estimate=False,
        ),
        "partial": True,
        "periods": periods,
        "reason_codes": reasons,
    }


def _gold(session, months):
    from hermes_finance.services.owner_manual_gold_history import read_gold_histories

    closed = {month.id: month for month in months if month.status == "closed"}
    rows = session.execute(
        select(PositionSnapshot, Instrument, Account)
        .join(Instrument, Instrument.id == PositionSnapshot.instrument_id)
        .join(Account, Account.id == PositionSnapshot.account_id)
        .where(Instrument.instrument_type == "gold")
        .order_by(PositionSnapshot.id)
    )
    latest, targets = {}, {}
    for position, instrument, account in rows:
        if instrument.currency == "RUB":
            targets[(account.id, instrument.id)] = {
                "account_id": account.id,
                "instrument_id": instrument.id,
                "label": instrument.name,
            }
        if position.reporting_month_id not in closed:
            continue
        month = closed[position.reporting_month_id]
        key = (account.id, instrument.id)
        rank = (month.period_end, position.id)
        if key not in latest or rank > latest[key][0]:
            latest[key] = (rank, position, instrument, account, month)
    result = []
    for _, position, instrument, account, month in latest.values():
        reasons = ["saved_snapshot_unrealized_only", "current_catalogue_gold_classification"]
        if position.historical_instrument_type != "gold":
            reasons.append("historical_gold_classification_unproven")
        cost = position.cost_basis_kopecks
        value = position.market_value_kopecks
        unrealized = position.unrealized_result_kopecks
        consistent = cost is not None and unrealized is not None and value - cost == unrealized
        rate = None
        if not consistent:
            reasons.append("gold_snapshot_cost_result_missing_or_conflicting")
        elif cost > 0:
            with localcontext() as context:
                context.prec = 60
                rate = Decimal(unrealized) / Decimal(cost)
        else:
            reasons.append("gold_cost_return_denominator_unavailable")
        result.append(
            {
                "account_id": account.id,
                "instrument_id": instrument.id,
                "label": instrument.name,
                "date": position.price_date,
                "quantity": str(position.quantity),
                "market_value": returns_view.metric(value, reasons=reasons, estimate=False),
                "cost_basis": returns_view.metric(cost, reasons=reasons, estimate=False),
                "unrealized_result": returns_view.metric(
                    unrealized if consistent else None, reasons=reasons, estimate=False
                ),
                "cost_return": returns_view.metric(
                    rate,
                    reasons=reasons,
                    method="saved_unrealized_over_cost",
                    unit="fraction",
                    estimate=False,
                ),
            }
        )
    histories = []
    for row in read_gold_histories(session, include_events=False):
        observed = row["result"]
        instrument = session.get(Instrument, row["instrument_id"])
        if instrument and instrument.instrument_type == "gold" and instrument.currency == "RUB":
            targets[(row["account_id"], instrument.id)] = {
                "account_id": row["account_id"],
                "instrument_id": instrument.id,
                "label": instrument.name,
            }
        provenance = ["owner_attested_gold_history", "gold_tax_not_provided"]
        reasons = list(dict.fromkeys([*provenance, *row["reason_codes"]]))

        def amount(key, component=None):
            return returns_view.metric(
                observed[key],
                reasons=list(
                    dict.fromkeys(
                        [
                            *provenance,
                            *(
                                observed.get(f"{component}_reason_codes", row["reason_codes"])
                                if component
                                else row["reason_codes"]
                                if observed[key] is None
                                else []
                            ),
                        ]
                    )
                ),
                method=observed["method"],
                estimate=False,
            )

        interval = observed.get("period") or {}
        opening, closing = interval.get("covered_from"), interval.get("covered_to")
        histories.append(
            {
                "account_id": row["account_id"],
                "instrument_id": row["instrument_id"],
                "label": instrument.name if instrument else "Gold",
                "revision": row["revision"],
                "source_kind": row["source_kind"],
                "authority": row["authority"],
                "currentness": row["currentness"],
                "period": returns_view.bounds(
                    date.fromisoformat(opening) - timedelta(days=1), date.fromisoformat(closing)
                )
                if opening and closing
                else None,
                "valuation_date": observed.get("valuation_date")
                if observed.get("valuation_kopecks") is not None
                else None,
                "valuation_status": (row.get("valuation") or {}).get("month_status"),
                "amount_basis": observed["amount_basis"],
                "tax_treatment": observed["tax_treatment"],
                "total_result": amount("total_result_kopecks", "total"),
                "realized_result": amount("realized_result_kopecks", "realized"),
                "unrealized_result": amount("unrealized_result_kopecks", "unrealized"),
                "buy_amount": amount("buy_amount_kopecks"),
                "sale_amount": amount("sale_amount_kopecks"),
                "separate_fees": amount("separate_fees_kopecks"),
                "reason_codes": reasons,
            }
        )
    return {
        "snapshots": result,
        "histories": histories,
        "targets": [row for _, row in sorted(targets.items())],
        "period_result": _unknown(
            "gold_history_results_have_individual_periods"
            if histories
            else "gold_dated_trade_history_unavailable"
        ),
        "reason_codes": [
            "gold_results_keep_individual_periods",
            "owner_attested_source_not_financial_close",
        ]
        if histories
        else ["gold_period_return_unproven", "snapshot_result_not_period_return"],
    }


def _source_accounts(
    session,
    *,
    include_instrument_details=True,
    captured_analyses=None,
    captured_reports=None,
):
    canonical = returns_view._source_scopes(session)
    labels = {a["id"]: a["label"] for a in returns_view._accounts(session, canonical)}
    accounts, grouped = [], defaultdict(list)
    for account in sorted(set(canonical.values())):
        scope = f"source:{account}"
        captured = {}
        reports = (
            source_investment_proofs.read_report_summaries(
                session, source_account=account, analyses=captured
            )
            if include_instrument_details
            else source_investment_proofs.read_account_summaries(session, source_account=account)
        )
        historical = [p for p in reports if p["history_from_zero"]]
        proof = (
            max(historical, key=lambda p: (p["covered_to"], p["proof_id"])) if historical else None
        )
        selected, _ = _selected_sources(session, account)
        metadata = _identities([view for _, view, error in selected if not error and view])
        result = returns_view._investment_report_result(proof) if proof else None
        status = proof["status"] if proof else "absent"
        reasons = list(proof["reason_codes"]) if proof else ["all_history_source_proof_absent"]
        analyses = captured.get(proof["proof_id"], {}) if proof and status == "current" else {}
        if captured_analyses is not None:
            captured_analyses[scope] = analyses
        if captured_reports is not None:
            captured_reports[scope] = proof if proof and status == "current" else None
        display = (
            source_investment_proofs.read_report_display_candidates(
                session, source_account=account, proof_id=proof["proof_id"]
            )
            if proof and status == "current"
            else {"source": {}, "pdf": {}}
        )
        keys = (
            sorted(analyses)
            if include_instrument_details and status == "current"
            else (
                sorted({item["isin"] for item in (proof["interval"] or {}).get("instruments", [])})
                if status == "current"
                else sorted(metadata)
            )
        )
        prototypes = [
            SimpleNamespace(
                isin=isin,
                source_name=source_investment_proofs.resolve_display_name(
                    isin,
                    source_labels=metadata[isin]["names"] | set(display["source"].get(isin, ())),
                    pdf_labels=display["pdf"].get(isin, ()),
                ),
            )
            for isin in keys
        ]
        names = returns_view._catalogue_names(session, prototypes)
        period = result["period"] if result else None
        for row in prototypes:
            meta = metadata[row.isin]
            if row.isin in analyses:
                row.analysis = analyses[row.isin]
                row.instrument_type = next(iter(meta["types"])) if len(meta["types"]) == 1 else None
                instrument = returns_view._instrument(
                    row, row.analysis.opening_date, row.analysis.closing_date, names
                )
                item = {
                    key: instrument[key]
                    for key in ("period", "pnl", "rate", "coupons", "dividends")
                }
                name, kind = instrument["name"], instrument["kind"]
            else:
                # Metadata can survive an unavailable proof; no older numbers
                # or current catalogue values are substituted for its operands.
                reason = (
                    "instrument_details_not_requested"
                    if not include_instrument_details and status == "current"
                    else "all_history_source_proof_unavailable"
                )
                item = {
                    "period": period,
                    "pnl": _unknown(reason),
                    "rate": _unknown(reason, rate=True),
                    "coupons": _unknown(reason),
                    "dividends": _unknown(reason),
                }
                name = row.source_name or names.get(row.isin) or row.isin
                kind = next(iter(meta["types"])) if len(meta["types"]) == 1 else None
            grouped[row.isin].append(
                {
                    "scope": scope,
                    "label": labels[scope],
                    "name": name,
                    "kind": kind,
                    "details_loaded": include_instrument_details and status == "current",
                    **item,
                }
            )
        accounts.append(
            {
                "scope": scope,
                "label": labels[scope],
                "period": period,
                "result": result,
                "proof_status": status,
                "reason_codes": reasons,
                "instrument_count": len(keys),
            }
        )
    instruments = []
    for isin, rows in sorted(grouped.items()):
        names = {r["name"] for r in rows if r["name"] != isin}
        kinds = {r["kind"] for r in rows if r["kind"] is not None}
        instruments.append(
            {
                "isin": isin,
                "name": next(iter(names)) if len(names) == 1 else isin,
                "kind": next(iter(kinds)) if len(kinds) == 1 else None,
                "accounts": [
                    {key: value for key, value in row.items() if key not in {"name", "kind"}}
                    for row in rows
                ],
                "reason_codes": ["instrument_name_conflict"]
                if len(names) > 1
                else ([] if names else ["instrument_name_unavailable"]),
            }
        )
    return accounts, instruments, canonical


def _account_mappings(session, canonical):
    """Exact accepted identity metadata; never a name/amount join."""
    mappings = defaultdict(set)
    for alias, account_id in session.execute(
        select(
            BrokerIdentityMapping.provider_identity, BrokerIdentityMapping.hermes_account_id
        ).where(
            BrokerIdentityMapping.provider == PROVIDER,
            BrokerIdentityMapping.subject_kind == "account",
            BrokerIdentityMapping.status == "effective",
        )
    ):
        if alias in canonical:
            mappings[canonical[alias]].add(account_id)
    reverse = defaultdict(set)
    for native, identities in mappings.items():
        for identity in identities:
            reverse[identity].add(native)
    return mappings, reverse


def _identity_conflict(native, mappings, reverse):
    return len(mappings[native]) > 1 or any(len(reverse[a]) > 1 for a in mappings[native])


def _paid_income(accounts, mappings, reverse, *, kind):
    """Known credited account coupons once, independent of valuation/P&L.

    These are latest current exact whole-history account operands. Instrument
    explanations, monthly overlap, forecasts and accepted copies are not addends.
    """
    rows, values, seen = [], [], set()
    for account in accounts:
        native = account["scope"].removeprefix("source:")
        if native in seen:
            continue
        seen.add(native)
        amount = (
            account["result"][f"{kind}s"]
            if account["result"]
            else _unknown("all_history_source_proof_absent")
        )
        reasons = list(dict.fromkeys([*account["reason_codes"], *amount["reason_codes"]]))
        if _identity_conflict(native, mappings, reverse):
            excluded = "source_account_identity_mapping_conflict"
        elif account["proof_status"] != "current":
            excluded = f"current_{kind}_history_unavailable"
        elif amount["value"] is None:
            excluded = f"{kind}_income_unavailable"
        else:
            excluded = None
            values.append(int(amount["value"]))
        rows.append(
            {
                "scope": account["scope"],
                "label": account["label"],
                "period": account["period"],
                "amount": amount,
                "proof_status": account["proof_status"],
                "included": excluded is None,
                "exclusion_reason": excluded,
                "reason_codes": list(dict.fromkeys([*reasons, *([excluded] if excluded else [])])),
            }
        )
    reasons = [f"known_source_history_{kind}s_only", "source_only_not_financial_close"]
    if any(not row["included"] for row in rows):
        reasons.append(f"{kind}_history_accounts_missing_or_excluded")
    if (
        len(
            {
                (row["period"]["start"], row["period"]["end"])
                for row in rows
                if row["included"] and row["period"]
            }
        )
        > 1
    ):
        reasons.append(f"{kind}_account_history_periods_differ")
    return {
        "known_total": returns_view.metric(
            sum(values) if values else None, reasons=reasons, method=f"known_source_history_{kind}s"
        ),
        "partial": True,
        "selected_accounts": len(rows),
        "included_accounts": len(values),
        "accounts": rows,
        "reason_codes": reasons,
    }


def _coupon_income(accounts, mappings, reverse):
    return _paid_income(accounts, mappings, reverse, kind="coupon")


def _mixed_result(session, accounts, gold, months, mappings, reverse):
    """Distinct supported operands; no account-plus-explanation or stale fallback."""
    components, included_native = [], []

    def component(identity, category, label, amount, interval, valuation_date, authority, reasons):
        return {
            "id": identity,
            "category": category,
            "label": label,
            "selected": True,
            "available": amount["value"] is not None,
            "included": False,
            "amount": amount,
            "interval": interval,
            "valuation_date": valuation_date,
            "coverage": {
                "status": "partial" if amount["value"] is not None else "unavailable",
                "reason_codes": list(dict.fromkeys(reasons)),
            },
            "method": amount["method"],
            "authority": authority,
            "exclusion_reason": None,
        }

    for account in accounts:
        native = account["scope"].removeprefix("source:")
        amount = (
            account["result"]["pnl"]
            if account["result"]
            else _unknown("all_history_source_proof_absent")
        )
        row = component(
            account["scope"],
            "brokerage",
            account["label"],
            amount,
            account["period"],
            None,
            "source_only",
            account["reason_codes"],
        )
        conflicting = _identity_conflict(native, mappings, reverse)
        if conflicting:
            row["coverage"]["status"] = "conflict"
            row["exclusion_reason"] = "source_account_identity_mapping_conflict"
        elif account["proof_status"] != "current" or not row["available"]:
            row["exclusion_reason"] = "current_whole_history_result_unavailable"
        else:
            row["included"] = True
            included_native.append(native)
        components.append(row)

    unresolved = any(len(mappings[native]) != 1 for native in included_native)
    covered_accounts = {a for native in included_native for a in mappings[native]}
    snapshot_accounts = defaultdict(list)

    def include_snapshot(row, account_id):
        if not row["available"]:
            row["exclusion_reason"] = (
                "owner_gold_component_unavailable"
                if row["authority"] == "owner_attestation"
                else "snapshot_component_unavailable"
            )
        elif unresolved:
            row["exclusion_reason"] = "source_snapshot_overlap_unproven"
        elif account_id in covered_accounts:
            row["exclusion_reason"] = "snapshot_account_already_covered_by_source"
        else:
            row["included"] = True
        components.append(row)
        snapshot_accounts[account_id].append(row)

    month_by_id = {month.id: month for month in months}
    deposits = defaultdict(list)
    for snapshot, account in session.execute(
        select(DepositSnapshot, Account)
        .join(Account, Account.id == DepositSnapshot.account_id)
        .order_by(DepositSnapshot.id)
    ):
        deposits[account.id].append((snapshot, account))
    for account_id, rows in deposits.items():
        known = [
            (s, month_by_id[s.reporting_month_id])
            for s, _ in rows
            if s.reporting_month_id in month_by_id
            and month_by_id[s.reporting_month_id].status == "closed"
        ]
        amount = returns_view.metric(
            sum(s.actual_interest_received_kopecks for s, _ in known) if known else None,
            reasons=("known_received_interest_only", "deposit_full_history_not_proven"),
            method="deposit_received_interest",
            estimate=False,
        )
        interval = (
            returns_view.bounds(
                min(m.period_start for _, m in known) - timedelta(days=1),
                max(m.period_end for _, m in known),
            )
            if known
            else None
        )
        row = component(
            f"deposit:{account_id}",
            "deposits",
            rows[0][1].name,
            amount,
            interval,
            None,
            "accepted_snapshot",
            amount["reason_codes"],
        )
        include_snapshot(row, account_id)
    for snapshot in gold["snapshots"]:
        if any(
            (row["account_id"], row["instrument_id"])
            == (snapshot["account_id"], snapshot["instrument_id"])
            for row in gold["histories"]
        ):
            # Manual whole-history total replaces this same pair's unrealized
            # explanation, even when blocked; no silent numeric fallback.
            continue
        amount = {**snapshot["unrealized_result"], "method": "saved_snapshot_unrealized"}
        row = component(
            f"gold:{snapshot['account_id']}:{snapshot['instrument_id']}",
            "gold",
            snapshot["label"],
            amount,
            None,
            snapshot["date"],
            "accepted_snapshot",
            amount["reason_codes"],
        )
        include_snapshot(row, snapshot["account_id"])
    for history in gold["histories"]:
        row = component(
            f"gold:{history['account_id']}:{history['instrument_id']}",
            "gold",
            history["label"],
            history["total_result"],
            history["period"],
            history["valuation_date"],
            "owner_attestation",
            history["reason_codes"],
        )
        include_snapshot(row, history["account_id"])
    for rows in snapshot_accounts.values():
        if len({row["category"] for row in rows}) > 1:
            for row in rows:
                if row["included"]:
                    row["included"] = False
                    row["exclusion_reason"] = "canonical_snapshot_overlap_unproven"
    included = [int(row["amount"]["value"]) for row in components if row["included"]]
    reasons = ["partial_mixed_result_not_portfolio_pnl", "unknown_components_may_reduce_result"]
    return {
        "known_result": returns_view.metric(
            sum(included) if included else None,
            reasons=reasons,
            method="known_nonoverlapping_components",
        ),
        "rate": _unknown("mixed_component_periods_and_flows_not_unified", rate=True),
        "selected_component_count": len(components),
        "available_component_count": sum(row["available"] for row in components),
        "included_component_count": len(included),
        "components": components,
        "reason_codes": reasons,
    }


def read_overall(session, *, include_instrument_details=False):
    with source_read_snapshot(session):
        months = returns_view._months(session)
        accounts, instruments, canonical = _source_accounts(
            session, include_instrument_details=include_instrument_details
        )
        mappings, reverse = _account_mappings(session, canonical)
        for instrument in instruments:
            for account in instrument["accounts"]:
                native = account["scope"].removeprefix("source:")
                account["canonical_account_id"] = (
                    next(iter(mappings[native]))
                    if len(mappings[native]) == 1
                    and not _identity_conflict(native, mappings, reverse)
                    else None
                )
        gold = _gold(session, months)
        return {
            "contract_version": "returns_overall_v1",
            "overall": {
                "pnl": _unknown("overall_aggregation_pending_review"),
                "rate": _unknown("overall_aggregation_pending_review", rate=True),
                "partial": True,
                "reason_codes": ["overall_aggregation_pending_review"],
            },
            "source_accounts": accounts,
            "instruments": instruments,
            "deposits": _deposits(session, months),
            "gold": gold,
            "mixed_result": _mixed_result(session, accounts, gold, months, mappings, reverse),
            "coupon_income": _coupon_income(accounts, mappings, reverse),
            "dividend_income": _paid_income(accounts, mappings, reverse, kind="dividend"),
            "reason_codes": [
                "source_only_not_financial_close",
                "overall_aggregation_pending_review",
            ],
        }


def _known_sum(metrics, *, method):
    """Retain known partial amounts, never promote estimates or unknown to zero."""
    metrics = list(metrics)
    values = [int(m["value"]) for m in metrics if m["value"] is not None and not m["estimate"]]
    reasons = list(dict.fromkeys(r for m in metrics for r in m["reason_codes"]))
    if len(values) != len(metrics):
        reasons.append("instrument_accounts_missing_or_excluded")
    return returns_view.metric(
        sum(values) if values else None, reasons=reasons, method=method, estimate=False
    )


def _current_source_analysis(analysis, period, *, current):
    # Callers have just read the current exact proof; this is its native
    # analysis, never a statement estimate or an interior-period fallback.
    return bool(
        current
        and period
        and getattr(analysis, "opening_date", None) == period["start"]
        and getattr(analysis, "closing_date", None) == period["end"]
        and tuple(getattr(analysis, "assumptions", ())) == ("source_only_xml_pdf",)
    )


def _component_metric(item, *, current_source=False):
    # A known partial credited component is useful; provisional assumptions do
    # not become a supported addend merely because they have a numeric value.
    source_only = (
        current_source
        and item.status == "provisional"
        and set(item.reason_codes) == {"source_sections_not_financially_accepted"}
        and not getattr(item, "assumptions", ())
    )
    return returns_view.metric(
        item.value if item.status in {"supported", "partial"} or source_only else None,
        reasons=item.reason_codes,
        method="instrument_return_v2",
        estimate=False,
    )


def read_instrument_card(session, isin, *, overview=None):
    """Compose one lazy exact-ISIN card from the ordinary, guarded detail reader."""
    with source_read_snapshot(session):
        overview = overview if overview is not None else read_overall(session)
        instrument = next((row for row in overview["instruments"] if row["isin"] == isin), None)
        if instrument is None:
            raise LookupError("returns_instrument_missing")
        sources = {row["scope"]: row for row in overview["source_accounts"]}
        canonical = returns_view._source_scopes(session)
        mappings, reverse = _account_mappings(session, canonical)
        accounts = []
        for indexed in instrument["accounts"]:
            source = sources[indexed["scope"]]
            reasons = list(source["reason_codes"])
            detail, excluded = None, None
            native = source["scope"].removeprefix("source:")
            if _identity_conflict(native, mappings, reverse):
                excluded = "source_account_identity_mapping_conflict"
            elif source["proof_status"] != "current" or not source["period"]:
                excluded = "current_instrument_history_unavailable"
            else:
                period = source["period"]
                try:
                    detail = returns_view.read_detail(
                        session,
                        scope=source["scope"],
                        start=period["start"],
                        end=period["end"],
                        isin=isin,
                    )
                except (ValueError, LookupError):
                    excluded = "instrument_history_detail_unavailable"
            if excluded:
                reasons.append(excluded)
            accounts.append(
                {
                    "scope": source["scope"],
                    "label": source["label"],
                    "canonical_account_id": indexed["canonical_account_id"],
                    "period": source["period"],
                    "proof_status": source["proof_status"],
                    "included": excluded is None,
                    "exclusion_reason": excluded,
                    "reason_codes": reasons,
                    "detail": detail,
                }
            )
        details = [row["detail"] for row in accounts if row["included"] and row["detail"]]
        omitted = len(details) != len(accounts)

        def aggregate(name):
            operands = [
                _component_metric(
                    row["detail"]["analysis"].pnl
                    if name == "pnl"
                    else row["detail"]["analysis"].components[name],
                    current_source=_current_source_analysis(
                        row["detail"]["analysis"],
                        row["period"],
                        current=row["proof_status"] == "current",
                    ),
                )
                for row in accounts
                if row["included"] and row["detail"]
            ]
            if omitted:
                operands.append(_unknown("instrument_accounts_missing_or_excluded"))
            return _known_sum(operands, method=f"known_instrument_accounts_{name}")

        endpoints = [row["analysis"].closing for row in details]
        quantities = [e.quantity for e in endpoints if e.quantity is not None]
        reasons = ["known_instrument_accounts_only"]
        if omitted or len(quantities) != len(endpoints):
            reasons.append("instrument_accounts_missing_or_excluded")
        dates = sorted({e.date for e in endpoints})
        if len(dates) > 1:
            reasons.append("instrument_account_valuation_dates_differ")
        values = [
            returns_view.metric(e.reported_value_kopecks, reasons=e.reason_codes, estimate=False)
            for e in endpoints
        ]
        if omitted:
            values.append(_unknown("instrument_accounts_missing_or_excluded"))
        with localcontext() as context:
            context.prec = 80
            quantity = str(sum(quantities, Decimal(0))) if quantities else None
        summary = {
            "quantity": {"value": quantity, "partial": True, "reason_codes": reasons},
            "reported_value": _known_sum(values, method="reported_endpoint_values"),
            "valuation_dates": dates,
            "partial": True,
            "reason_codes": reasons,
            "pnl": aggregate("pnl"),
            "coupons": aggregate("coupons"),
            "dividends": aggregate("dividends"),
            "valuation_and_trades": aggregate("valuation_and_trades"),
            "costs": aggregate("fees"),
            "taxes": aggregate("taxes"),
            "redemption": aggregate("redemption"),
            "rate": _unknown("combined_rate_periods_and_flows_not_proven", rate=True),
        }
        return {
            "contract_version": "returns_instrument_card_v1",
            "isin": isin,
            "name": instrument["name"],
            "kind": instrument["kind"],
            "summary": summary,
            "accounts": accounts,
            "reason_codes": reasons,
        }


def read_income(session, *, kind):
    """Lazy credited-income drilldown, retaining account totals if attribution is partial."""
    if kind not in {"coupon", "dividend"}:
        raise ValueError("returns_income_kind_invalid")
    with source_read_snapshot(session):
        captured, reports = {}, {}
        accounts, instruments, canonical = _source_accounts(
            session,
            include_instrument_details=True,
            captured_analyses=captured,
            captured_reports=reports,
        )
        mappings, reverse = _account_mappings(session, canonical)
        summary = _paid_income(accounts, mappings, reverse, kind=kind)
        names = {row["isin"]: row["name"] for row in instruments}
        grouped, events, reasons = defaultdict(list), [], []
        for account in summary["accounts"]:
            if not account["included"]:
                continue
            start, end = account["period"]["start"], account["period"]["end"]
            seen, conflicts, event_total = {}, set(), 0
            for isin, analysis in captured.get(account["scope"], {}).items():
                proof = reports.get(account["scope"]) or {}
                amount = _component_metric(
                    analysis.components[f"{kind}s"],
                    current_source=_current_source_analysis(
                        analysis, account["period"], current=proof.get("status") == "current"
                    ),
                )
                grouped[isin].append(
                    {
                        "scope": account["scope"],
                        "label": account["label"],
                        "period": account["period"],
                        "amount": amount,
                    }
                )
                for event in analysis.events:
                    if event.kind != kind.upper() or not event.counted or not event.current:
                        continue
                    # A source event key, never date/amount, identifies a credited operation.
                    legs = tuple(leg for leg in event.cash_legs if start < leg.date <= end)
                    if not legs:
                        reasons.append("income_event_cash_date_or_amount_unavailable")
                        continue
                    identity = (isin, tuple((leg.date, leg.account_cash_kopecks) for leg in legs))
                    if event.event_key in seen and seen[event.event_key][0] != identity:
                        conflicts.add(event.event_key)
                        reasons.append("income_event_identity_conflict")
                    else:
                        seen[event.event_key] = (identity, isin, event, legs)
            for key, (_, isin, event, legs) in seen.items():
                if key in conflicts:
                    continue
                # Same operands as economics; never guess net from gross/withholding.
                for leg in legs:
                    event_total += leg.account_cash_kopecks
                    events.append(
                        {
                            "scope": account["scope"],
                            "label": account["label"],
                            "isin": isin,
                            "name": names.get(isin, isin),
                            "date": leg.date,
                            "amount": returns_view.metric(
                                leg.account_cash_kopecks,
                                reasons=event.reason_codes,
                                method="actual_credited_income",
                                estimate=False,
                            ),
                        }
                    )
            # Exact account Money operands whose instrument identity is not yet
            # supported still belong in the paid-income chronology. They never
            # become an ISIN attribution or another account-total addend.
            unallocated = {}
            for row in ((reports.get(account["scope"]) or {}).get("interval") or {}).get(
                "exceptions", []
            ):
                if row["classification"] != kind or row["currency"] != "RUB":
                    continue
                day = row["date"]
                day = date.fromisoformat(day) if isinstance(day, str) else day
                if day is None or not start < day <= end or row["amount_kopecks"] is None:
                    continue
                identity = (day, row["amount_kopecks"])
                reference = row["reference"]
                if reference in unallocated and unallocated[reference] != identity:
                    unallocated[reference] = None
                    reasons.append("income_event_identity_conflict")
                elif reference not in unallocated:
                    unallocated[reference] = identity
            for row in unallocated.values():
                if row is None:
                    continue
                day, value = row
                event_total += int(value)
                events.append(
                    {
                        "scope": account["scope"],
                        "label": account["label"],
                        "isin": None,
                        "name": None,
                        "date": day,
                        "amount": returns_view.metric(
                            value,
                            reasons=("payout_identity_unresolved",),
                            method="actual_credited_income",
                            estimate=False,
                        ),
                    }
                )
            if account["amount"]["value"] != str(event_total):
                reasons.append("known_account_income_not_fully_attributed")
        rows = [
            {
                "isin": isin,
                "name": names.get(isin, isin),
                "amount": _known_sum(
                    (row["amount"] for row in entries), method=f"known_instrument_{kind}s"
                ),
                "accounts": entries,
            }
            for isin, entries in sorted(grouped.items())
        ]
        return {
            "contract_version": "returns_income_v1",
            "kind": kind,
            "summary": summary,
            "instruments": rows,
            "events": sorted(
                events, key=lambda row: (row["date"], row["scope"], row["isin"] or "")
            ),
            "reason_codes": list(dict.fromkeys([*summary["reason_codes"], *reasons])),
        }
