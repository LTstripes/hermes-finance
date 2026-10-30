"""Allowlisted AI handoff of existing provisional source readers; no calculations.

Only representation conversions (kopecks -> RUB and fraction -> percent) live
here. Source aliases never establish a financial Account mapping.
"""

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal, localcontext

from hermes_finance.domain.values import RubleAmount
from hermes_finance.services import returns_overall, source_investment_proofs
from hermes_finance.services.owner_manual_gold_history import read_gold_histories
from hermes_finance.services.returns_view import _source_scopes
from hermes_finance.services.source_instrument_returns import (
    _identities,
    read_instrument_returns,
)
from hermes_finance.services.source_monthly_returns import (
    _selected_sources,
    read_monthly_returns,
    source_read_snapshot,
)

READING_GUIDE = {
    "pnl": "Personal investment outcome in RUB, not bond yield to maturity (YTM).",
    "modified_dietz": "Approximate personal return for the stated interval; not annualized.",
    "xirr_annualized": "Annualized money-weighted return; compare with matching annualized periods.",
    "xirr_period": "Money-weighted return converted by the producer to the stated interval.",
    "capital_flows": "Contributions and withdrawals are capital flows, not profit or income.",
    "counting": "Coupons/dividends and costs may already be included in P&L. Components and events explain it; never add them again. Do not add account and instrument results or sum rates.",
    "unknown": "NULL is unknown/unavailable, not zero. Known partial income can coexist with unknown valuation or return.",
    "periods": "Compare identical dates and coverage. All-history endpoints do not prove intervening monthly valuations; available months are not full history.",
    "authority": "Source-only provisional observations; financial_authority=none. Separate from accepted Performance and financial Close.",
    "identity": "Source account refs are local to this file. No verified join to current_portfolio accounts is asserted.",
    "events": "Cash legs show account and opposite instrument-flow signs. Only included_in_interval legs enter the interval cash economics; outside amounts are NULL. producer_eligible preserves source eligibility; counted means at least one eligible in-window cash leg. Cross-boundary dates are chronology, not extra profit. Events repeat across overlapping intervals and must not be summed across them.",
}
EXCLUDED = [
    "unproved_realized_unrealized_split",
    "unproved_gross_income_or_withheld_tax",
    "allocation_of_account_wide_costs_to_instruments",
    "hypothetical_scenarios",
]


def _money(value):
    return (
        None if value is None else {"amount": RubleAmount(int(value)).to_api(), "currency": "RUB"}
    )


def _percent(value):
    if value is None:
        return None
    number = Decimal(value)
    with localcontext() as context:
        context.prec = max(60, len(number.as_tuple().digits) + 4)
        return format(number.scaleb(2), "f")


def _metric(
    value=None,
    *,
    status=None,
    reasons=(),
    method="source_cash_economics",
    rate=False,
    annualized=False,
):
    return {
        "value": _percent(value) if rate else _money(value),
        "unit": "percent" if rate else "RUB",
        "status": status
        or ("unavailable" if value is None else ("partial" if reasons else "provisional")),
        "reason_codes": sorted(set(reasons)),
        "method": method,
        "annualized": annualized,
        "approximate": True,
    }


def _producer_metric(row, name):
    raw = row[name]
    return _metric(
        raw["value"],
        status=raw["status"],
        reasons=raw["reason_codes"],
        method=raw.get("method", "source_cash_economics"),
        rate=name in {"modified_dietz", "xirr_annualized", "xirr_period"},
        annualized=raw.get("annualized", False),
    )


def _domain_metric(metric):
    return _metric(metric.value, status=metric.status, reasons=metric.reason_codes)


def _endpoint(endpoint):
    return {
        "date": endpoint.date.isoformat(),
        "quantity": None if endpoint.quantity is None else str(endpoint.quantity),
        "reported_value": _money(endpoint.reported_value_kopecks),
        "economic_value": _money(endpoint.economic_value_kopecks),
        "accrued_interest": _money(endpoint.accrued_interest_kopecks),
        "valuation_basis": endpoint.valuation_basis,
        "reason_codes": sorted(set(endpoint.reason_codes)),
    }


def _events(analysis):
    rows = []

    def in_window(day):
        return day is not None and analysis.opening_date < day <= analysis.closing_date

    for event in analysis.events:
        # Preserve cross-boundary chronology, but apply the economics' cash
        # window separately to every leg. Outside cash amounts are not exported.
        if not (
            event.event_date is None
            or any(
                in_window(d)
                for d in (
                    event.event_date,
                    event.cash_settlement_date,
                    event.depository_settlement_date,
                    *(leg.date for leg in event.cash_legs),
                )
            )
        ):
            continue
        eligible = event.counted and event.current
        all_cash_inside = bool(event.cash_legs) and all(
            in_window(leg.date) for leg in event.cash_legs
        )
        rows.append(
            {
                "kind": event.kind,
                "date": None if event.event_date is None else event.event_date.isoformat(),
                "cash_date": None
                if event.cash_settlement_date is None
                else event.cash_settlement_date.isoformat(),
                "quantity_date": None
                if event.depository_settlement_date is None
                else event.depository_settlement_date.isoformat(),
                "quantity_delta": str(event.quantity_delta)
                if event.quantity_delta is not None
                and in_window(event.depository_settlement_date or event.event_date)
                else None,
                **{
                    name: _money(getattr(event, field)) if all_cash_inside else None
                    for name, field in (
                        ("trade_amount", "native_trade_amount_kopecks"),
                        ("accrued_interest", "accrued_interest_kopecks"),
                        ("commission", "commission_kopecks"),
                        ("gross_payout", "gross_payout_kopecks"),
                        ("withheld_tax", "withheld_tax_kopecks"),
                        ("net_payout", "net_payout_kopecks"),
                    )
                },
                "producer_eligible": eligible,
                "counted": eligible and any(in_window(leg.date) for leg in event.cash_legs),
                "cash_scope": "no_cash"
                if not event.cash_legs
                else ("within_interval" if all_cash_inside else "cross_boundary"),
                "cash_legs": [
                    {
                        "date": leg.date.isoformat(),
                        "account_cash": _money(leg.account_cash_kopecks)
                        if in_window(leg.date)
                        else None,
                        "instrument_flow": _money(leg.instrument_flow_kopecks)
                        if in_window(leg.date)
                        else None,
                        "included_in_interval": eligible and in_window(leg.date),
                    }
                    for leg in event.cash_legs
                ],
                "reason_codes": sorted(set(event.reason_codes)),
            }
        )
    return sorted(rows, key=lambda r: (r["date"] or "", r["kind"], str(r)))


def _instrument(isin, meta, analysis, raw=None):
    metrics = {}
    for name in ("pnl", "known_subtotal", "modified_dietz", "xirr_annualized", "xirr_period"):
        if raw is not None:
            metrics[name] = _producer_metric(raw, name)
        elif name in {"pnl", "known_subtotal"}:
            metrics[name] = _domain_metric(getattr(analysis, name))
        elif name == "modified_dietz":
            m = analysis.modified_dietz
            metrics[name] = _metric(
                m.value, status=m.status, reasons=m.reason_codes, method=m.method, rate=True
            )
        else:
            metrics[name] = _metric(
                reasons=("source_method_not_available",),
                method="xirr",
                rate=True,
                annualized=name == "xirr_annualized",
            )
    return {
        "isin": isin,
        "name": meta.get("name"),
        "instrument_type": meta.get("kind"),
        "opening": _endpoint(analysis.opening),
        "closing": _endpoint(analysis.closing),
        "metrics": metrics,
        "components": {k: _domain_metric(v) for k, v in sorted(analysis.components.items())},
        "coverage": {
            k: {"complete": v.complete, "reason_codes": sorted(set(v.reason_codes))}
            for k, v in sorted(analysis.coverage.items())
        },
        "reason_codes": sorted(set(analysis.reason_codes)),
        "assumptions": sorted(set(analysis.assumptions)),
        "events": _events(analysis),
    }


def _bounds(start, end):
    return {"opening_date": start.isoformat(), "closing_date": end.isoformat()}


def _proof_interval(proof, analyses, metadata):
    start = date.fromisoformat(proof["covered_from"]) - timedelta(days=1)
    end = date.fromisoformat(proof["covered_to"])
    raw = proof["interval"]
    result = {
        **_bounds(start, end),
        "source_contract": source_investment_proofs.VERSION,
        "currentness": proof["status"],
        "history_from_zero": proof["history_from_zero"],
        "reason_codes": sorted(set(proof["reason_codes"] if raw is None else raw["reason_codes"])),
        "account": None,
        "instruments": [],
    }
    if raw is None:
        return result
    result["account"] = {
        "opening_value": _money(raw["opening_kopecks"]),
        "closing_value": _money(raw["closing_kopecks"]),
        "contributions": _money(raw["contributions_kopecks"]),
        "withdrawals": _money(raw["withdrawals_kopecks"]),
        "metrics": {
            k: _producer_metric(raw, k)
            for k in ("pnl", "known_subtotal", "modified_dietz", "xirr_annualized", "xirr_period")
        },
        "income": {
            k: _metric(raw[k + "_kopecks"], reasons=raw.get("income_reason_codes", {}).get(k, ()))
            for k in ("coupons", "dividends")
        },
        "detail_status": "known_rows_not_complete_cost_coverage",
        "external_flows": [
            {"date": f["date"], "amount": _money(f["amount_kopecks"]), "status": f["status"]}
            for f in raw["external_flows"]
        ],
        "account_only": [
            {"kind": r["kind"], "amount": _money(r["amount_kopecks"])} for r in raw["account_only"]
        ],
    }
    for item in raw["instruments"]:
        analysis = analyses.get(item["isin"])
        if analysis is not None:
            result["instruments"].append(
                _instrument(item["isin"], metadata.get(item["isin"], {}), analysis, item)
            )
    return result


def _monthly_interval(session, account, row, flows):
    r = row.result
    result = read_instrument_returns(
        session,
        source_account=account,
        opening_date=r.opening_date,
        closing_date=r.closing_date,
        include_monthly_history=False,
    )
    reasons = sorted(set(r.reason_codes + row.flags))
    return {
        **_bounds(r.opening_date, r.closing_date),
        "source_contract": "source_monthly_returns/instrument_return_v2",
        "currentness": "current",
        "history_from_zero": False,
        "reason_codes": reasons,
        "account": {
            "opening_value": _money(r.opening_kopecks),
            "closing_value": _money(r.closing_kopecks),
            "contributions": _money(r.contributions_kopecks),
            "withdrawals": _money(r.withdrawals_kopecks),
            "metrics": {
                "pnl": _metric(r.growth_kopecks, reasons=reasons),
                "known_subtotal": _metric(reasons=("source_method_not_available",)),
                "modified_dietz": _metric(
                    r.modified_dietz_return, reasons=reasons, method="modified_dietz", rate=True
                ),
                "xirr_annualized": _metric(
                    reasons=("source_method_not_available",),
                    method="xirr",
                    rate=True,
                    annualized=True,
                ),
                "xirr_period": _metric(
                    reasons=("source_method_not_available",), method="xirr", rate=True
                ),
            },
            "income": {
                k: _metric(getattr(row, k + "_kopecks"), reasons=row.flags)
                for k in ("coupons", "dividends")
            },
            "external_flows": [
                {
                    "date": f.event_date.isoformat(),
                    "amount": _money(f.amount_kopecks),
                    "status": f.status,
                }
                for f in flows
                if f.included and r.opening_date < f.event_date <= r.closing_date
            ],
            "account_only": [],
            "detail_status": "account_only_not_projected",
        },
        "instruments": [
            _instrument(i.isin, {"name": i.source_name, "kind": i.instrument_type}, i.analysis)
            for i in result.instruments
            if i.analysis is not None
        ],
    }


def source_returns_section(session, *, as_of_date, reporting_period, source_account_refs=None):
    """Build an additive section without joining source aliases to Account IDs."""
    with source_read_snapshot(session):
        analyses = {}
        proofs = source_investment_proofs.read_reports(session, analyses=analyses)
        proofs = [p for p in proofs if date.fromisoformat(p["covered_to"]) <= as_of_date]
        canonical = _source_scopes(session)
        accounts = sorted(
            set(canonical.values())
            | {canonical.get(p["source_account"], p["source_account"]) for p in proofs}
        )
        exported = []
        month_start = date(*reporting_period, 1)
        month_end = month_start.replace(day=monthrange(*reporting_period)[1])
        for ordinal, account in enumerate(accounts, 1):
            if source_account_refs is not None:
                # Request-local representation context only; never serialized.
                source_account_refs[f"source:{account}"] = f"source-account-{ordinal}"
            selected, _ = _selected_sources(session, account)
            identities = _identities([v for _, v, e in selected if not e and v is not None])
            metadata = {
                isin: {
                    "name": next(iter(m["names"])) if len(m["names"]) == 1 else None,
                    "kind": next(iter(m["types"])) if len(m["types"]) == 1 else None,
                }
                for isin, m in identities.items()
            }
            intervals = {}
            proof_order = {}
            # The same latest scope wins as in the ordinary proof reader. A stale
            # latest scope never falls back to a formerly numeric result.
            for proof in sorted(proofs, key=lambda p: p["proof_id"], reverse=True):
                if canonical.get(proof["source_account"], proof["source_account"]) != account:
                    continue
                key = (proof["covered_from"], proof["covered_to"])
                if key not in intervals:
                    proof_order[key] = proof["proof_id"]
                    intervals[key] = _proof_interval(
                        proof, analyses.get(proof["proof_id"], {}), metadata
                    )
            monthly = read_monthly_returns(session, source_account=account)
            for row in monthly.months:
                r = row.result
                if r.closing_date > as_of_date:
                    continue
                key = ((r.opening_date + timedelta(days=1)).isoformat(), r.closing_date.isoformat())
                if key not in intervals:
                    intervals[key] = _monthly_interval(session, account, row, monthly.flows)
            ordered = sorted(
                intervals.values(), key=lambda i: (i["opening_date"], i["closing_date"])
            )
            for index, item in enumerate(ordered, 1):
                item["ref"] = f"source-account-{ordinal}-interval-{index}"
            history = [i for i in ordered if i["history_from_zero"]]
            whole = (
                max(
                    history,
                    key=lambda i: (
                        i["closing_date"],
                        proof_order[
                            (
                                (
                                    date.fromisoformat(i["opening_date"]) + timedelta(days=1)
                                ).isoformat(),
                                i["closing_date"],
                            )
                        ],
                    ),
                )
                if history
                else None
            )
            requested_end = min(month_end, as_of_date)
            selected_interval = next(
                (
                    i
                    for i in ordered
                    if i["opening_date"] == (month_start - timedelta(days=1)).isoformat()
                    and i["closing_date"] == requested_end.isoformat()
                ),
                None,
            )
            monthly_refs = [i["ref"] for i in ordered if _is_full_month(i)]
            exported.append(
                {
                    "ref": f"source-account-{ordinal}",
                    "financial_account_ref": None,
                    "mapping_status": "not_asserted",
                    "all_history_ref": None if whole is None else whole["ref"],
                    "all_history_reason_codes": ["full_history_source_interval_unavailable"]
                    if whole is None
                    else whole["reason_codes"],
                    "selected_month": {
                        **_bounds(month_start - timedelta(days=1), month_end),
                        "through_date": requested_end.isoformat(),
                        "complete_calendar_month": requested_end == month_end,
                        "interval_ref": None
                        if selected_interval is None
                        else selected_interval["ref"],
                        "reason_codes": ["selected_source_interval_unavailable"]
                        if selected_interval is None
                        else selected_interval["reason_codes"],
                    },
                    "monthly_history_refs": monthly_refs,
                    "intervals": ordered,
                }
            )
        return {
            "status": "partial" if exported else "unavailable",
            "reason_codes": ["source_returns_provisional"]
            if exported
            else ["source_returns_absent"],
            "data": {
                "as_of_date": as_of_date.isoformat(),
                "authority": "provisional",
                "financial_authority": "none",
                "units": {
                    "money": "RUB decimal string (producer integer kopecks / 100)",
                    "rates": "percentage points decimal string (producer Decimal fraction * 100)",
                    "quantity": "units decimal string",
                },
                "reading_guide": READING_GUIDE,
                "included_components": [
                    "source_linked_cash_and_valuation",
                    "producer_supported_components_and_events",
                ],
                "excluded_components": EXCLUDED,
                "accounts": exported,
            }
            if exported
            else None,
        }


def _is_full_month(interval):
    first = date.fromisoformat(interval["opening_date"]) + timedelta(days=1)
    last = date.fromisoformat(interval["closing_date"])
    return first.day == 1 and last == first.replace(day=monthrange(first.year, first.month)[1])


OVERALL_READING_GUIDE = {
    "snapshot": "Current persisted Returns snapshot, independent of the selected reporting month and its historical as_of_date. Observation dates and intervals belong to each operand; generated_at is not a valuation date.",
    "mixed_result": "Known included nonoverlapping components only. This is partial, not full portfolio P&L or a lower bound: omitted components may be negative. Inspect selected, available, included, exclusion_reason, dates, method and authority. There is no common portfolio rate.",
    "counting": READING_GUIDE["counting"],
    "income": "Known credited coupons and dividends are explanatory income, independent of P&L availability. Account totals use the shared reader's inclusion rules; do not add instrument, monthly, forecast or accepted copies. Event attribution is not asserted: known account income may be unattributed to an instrument, and instrument events do not constitute a complete account payment ledger.",
    "gold": "Saved snapshot cost return is nonannualized. Separate owner_manual_gold_history facts retain owner_attestation authority, completeness/zero-start declarations, event amount/fee basis and independent result reasons. Only the producer's exact as_of_date event prefix enters its result; valuation_date can be NULL. Tax treatment is not provided. Revisions are alternative history versions, never additional events or profit. Do not add snapshot unrealized results to overlapping whole-history results.",
    "instruments": "Unified instrument summaries retain their own supported amount and date bounds. Every rate is exported independently with its method and availability; do not sum account rates.",
    "unknown": READING_GUIDE["unknown"],
    "identity": "Source account refs match source_returns within this file. Component and saved snapshot refs are local pseudonyms, not account numbers or database identities.",
    "authority": "Per-component source_only, accepted_snapshot and owner_attestation authority remains explicit. This read-only presentation does not confer financial Close authority on source observations or attestations.",
}


def _overall_date(value):
    return value.isoformat() if isinstance(value, date) else value


def _overall_period(value):
    if value is None:
        return None
    return {key: _overall_date(value[key]) for key in ("start", "end")}


def _overall_metric(raw):
    """Only unit conversion; preserve the common reader's exact support/method."""
    unit = raw["unit"]
    if unit not in {"kopecks", "fraction"}:
        raise ValueError("returns_overall_metric_unit_unsupported")
    return {
        "value": _percent(raw["value"]) if unit == "fraction" else _money(raw["value"]),
        "unit": "percent" if unit == "fraction" else "RUB",
        "reason_codes": sorted(set(raw["reason_codes"])),
        "method": raw["method"],
        "approximate": raw["estimate"],
    }


def _overall_result(raw):
    if raw is None:
        return None
    return {
        "period": _overall_period(raw["period"]),
        **{key: _overall_metric(raw[key]) for key in ("pnl", "rate", "coupons", "dividends")},
    }


def _overall_income(raw, account_refs):
    return {
        "event_attribution": "not_asserted",
        "known_total": _overall_metric(raw["known_total"]),
        "partial": raw["partial"],
        "selected_accounts": raw["selected_accounts"],
        "included_accounts": raw["included_accounts"],
        "accounts": [
            {
                "source_account_ref": account_refs[row["scope"]],
                "period": _overall_period(row["period"]),
                "amount": _overall_metric(row["amount"]),
                "proof_status": row["proof_status"],
                "included": row["included"],
                "exclusion_reason": row["exclusion_reason"],
                "reason_codes": sorted(set(row["reason_codes"])),
            }
            for row in raw["accounts"]
        ],
        "reason_codes": sorted(set(raw["reason_codes"])),
    }


def _overall_mixed(raw, account_refs):
    return {
        **{key: _overall_metric(raw[key]) for key in ("known_result", "rate")},
        **{
            key: raw[key]
            for key in (
                "selected_component_count",
                "available_component_count",
                "included_component_count",
            )
        },
        "components": [
            {
                "ref": f"returns-component-{index}",
                "source_account_ref": account_refs.get(row["id"]),
                "category": row["category"],
                **{key: row[key] for key in ("selected", "available", "included")},
                "amount": _overall_metric(row["amount"]),
                "interval": _overall_period(row["interval"]),
                "valuation_date": _overall_date(row["valuation_date"]),
                "coverage": {
                    "status": row["coverage"]["status"],
                    "reason_codes": sorted(set(row["coverage"]["reason_codes"])),
                },
                **{key: row[key] for key in ("method", "authority", "exclusion_reason")},
            }
            for index, row in enumerate(raw["components"], 1)
        ],
        "reason_codes": sorted(set(raw["reason_codes"])),
    }


def _gold_declaration(raw):
    return {
        name: raw[name]
        for name in (
            "covered_from",
            "covered_to",
            "complete",
            "zero_start",
            "current_quantity",
            "current_quantity_date",
        )
    }


def _gold_events(raw, refs):
    return [
        {
            "ref": refs[row["event_id"]],
            **{
                name: row[name]
                for name in (
                    "event_date",
                    "side",
                    "grams",
                    "amount_basis",
                    "unit_price_rub",
                    "fee_state",
                )
            },
            "amount": _money(row["amount_kopecks"]),
            "separate_fee": _money(row["separate_fee_kopecks"]),
        }
        for row in raw
    ]


def _gold_history(raw, index, account_refs, instrument_refs):
    if not raw["events_loaded"]:
        raise ValueError("gold_history_events_not_loaded")
    event_keys = sorted(
        {row["event_id"] for row in raw["events"]}
        | {
            row["event_id"]
            for revision in raw["revisions"]
            for row in revision["declaration"]["events"]
        }
    )
    refs = {
        key: f"returns-gold-history-{index}-event-{ordinal}"
        for ordinal, key in enumerate(event_keys, 1)
    }
    valuation, result = raw["valuation"], raw["result"]
    return {
        "ref": f"returns-gold-history-{index}",
        "account_ref": account_refs[raw["account_id"]],
        "instrument_ref": instrument_refs[raw["instrument_id"]],
        **{
            name: raw[name]
            for name in (
                "contract_version",
                "source_kind",
                "authority",
                "revision",
                "currentness",
                "events_loaded",
            )
        },
        "declaration": _gold_declaration(raw["declaration"]),
        "events": _gold_events(raw["events"], refs),
        "valuation": None
        if valuation is None
        else {
            **{
                name: valuation[name]
                for name in (
                    "date",
                    "price_date",
                    "snapshot_date",
                    "quantity",
                    "price_source",
                    "month_status",
                    "provisional",
                )
            },
            "market_value": _money(valuation["market_value_kopecks"]),
        },
        "result": {
            **{
                name: _money(result[name + "_kopecks"])
                for name in (
                    "total_result",
                    "realized_result",
                    "unrealized_result",
                    "remaining_cost",
                    "buy_amount",
                    "sale_amount",
                    "separate_fees",
                    "net_sales",
                    "valuation",
                )
            },
            **{
                name: result[name]
                for name in (
                    "calculated_quantity",
                    "declared_calculated_quantity",
                    "as_of_date",
                    "valuation_date",
                    "valuation_basis",
                    "valuation_provisional",
                    "amount_basis",
                    "tax_treatment",
                    "method",
                )
            },
            "period": {name: result["period"][name] for name in ("covered_from", "covered_to")},
            **{
                name: sorted(set(result[name]))
                for name in (
                    "reason_codes",
                    "total_reason_codes",
                    "realized_reason_codes",
                    "unrealized_reason_codes",
                    "decomposition_reason_codes",
                )
            },
        },
        "reason_codes": sorted(set(raw["reason_codes"])),
        "revisions": [
            {
                "revision": row["revision"],
                "declaration": _gold_declaration(row["declaration"]),
                "events": _gold_events(row["declaration"]["events"], refs),
            }
            for row in raw["revisions"]
        ],
    }


def _overall_gold(raw, histories):
    account_refs = {
        key: f"returns-gold-account-{index}"
        for index, key in enumerate(
            sorted(
                {row["account_id"] for row in raw["snapshots"]}
                | {row["account_id"] for row in histories}
            ),
            1,
        )
    }
    instrument_refs = {
        key: f"returns-gold-instrument-{index}"
        for index, key in enumerate(
            sorted(
                {row["instrument_id"] for row in raw["snapshots"]}
                | {row["instrument_id"] for row in histories}
            ),
            1,
        )
    }
    return {
        "snapshots": [
            {
                "ref": f"returns-gold-snapshot-{index}",
                "account_ref": account_refs[row["account_id"]],
                "instrument_ref": instrument_refs[row["instrument_id"]],
                "name": row["label"],
                "date": _overall_date(row["date"]),
                "quantity": row["quantity"],
                **{
                    key: _overall_metric(row[key])
                    for key in ("market_value", "cost_basis", "unrealized_result", "cost_return")
                },
            }
            for index, row in enumerate(raw["snapshots"], 1)
        ],
        "histories": [
            _gold_history(row, index, account_refs, instrument_refs)
            for index, row in enumerate(histories, 1)
        ],
        "period_result": _overall_metric(raw["period_result"]),
        "reason_codes": sorted(set(raw["reason_codes"])),
    }


def _overall_card(raw, account_refs, source_intervals, proof_instruments):
    summary = raw["summary"]
    accounts = []
    for row in raw["accounts"]:
        detail = row["detail"]
        period = _overall_period(row["period"])
        key = (
            row["scope"],
            None if period is None else (period["start"], period["end"]),
            raw["isin"],
        )
        accounts.append(
            {
                "source_account_ref": account_refs[row["scope"]],
                "source_interval_ref": source_intervals.get(key),
                "period": period,
                **{name: row[name] for name in ("proof_status", "included", "exclusion_reason")},
                "reason_codes": sorted(set(row["reason_codes"])),
                "detail": None
                if detail is None
                else {
                    "period": _overall_period(detail["period"]),
                    "opening_quantity": detail["opening_quantity"],
                    "closing_quantity": detail["closing_quantity"],
                    "conditional": detail["conditional"],
                    **{
                        name: _overall_metric(detail[name])
                        for name in (
                            "pnl",
                            "rate",
                            "coupons",
                            "dividends",
                            "buys",
                            "sells",
                            "conditional_pnl",
                            "conditional_rate",
                        )
                    },
                    "reason_codes": sorted(set(detail["reason_codes"])),
                    # Existing explicit analysis/event allowlist, with independent
                    # producer Dietz/XIRR support; never serialize the UI dict.
                    "analysis": _instrument(
                        raw["isin"],
                        {"name": raw["name"], "kind": raw["kind"]},
                        detail["analysis"],
                        proof_instruments.get(key),
                    ),
                },
            }
        )
    return {
        "contract_version": raw["contract_version"],
        "isin": raw["isin"],
        "name": raw["name"],
        "kind": raw["kind"],
        "summary": {
            "quantity": {
                "value": summary["quantity"]["value"],
                "partial": summary["quantity"]["partial"],
                "reason_codes": sorted(set(summary["quantity"]["reason_codes"])),
            },
            "valuation_dates": [_overall_date(day) for day in summary["valuation_dates"]],
            **{
                name: _overall_metric(summary[name])
                for name in (
                    "reported_value",
                    "pnl",
                    "coupons",
                    "dividends",
                    "valuation_and_trades",
                    "redemption",
                    "costs",
                    "taxes",
                    "rate",
                )
            },
            "partial": summary["partial"],
            "reason_codes": sorted(set(summary["reason_codes"])),
        },
        "accounts": accounts,
        "reason_codes": sorted(set(raw["reason_codes"])),
    }


def returns_overall_section(session, *, source_account_refs, source_section):
    """Complete current snapshot, irrespective of the UI's lazy loading state."""
    with source_read_snapshot(session):
        overview = returns_overall.read_overall(session, include_instrument_details=True)
        source_intervals = {}
        scope_by_ref = {value: key for key, value in source_account_refs.items()}
        for account in (source_section["data"] or {}).get("accounts", []):
            scope = scope_by_ref[account["ref"]]
            for interval in account["intervals"]:
                for instrument in interval["instruments"]:
                    source_intervals[
                        (
                            scope,
                            (interval["opening_date"], interval["closing_date"]),
                            instrument["isin"],
                        )
                    ] = interval["ref"]
        # Reuse the same request-local full proof reader already used above by
        # source_returns. It supplies independent rate support, not new math.
        canonical = _source_scopes(session)
        proof_instruments = {}
        for proof in sorted(
            source_investment_proofs.read_reports(session), key=lambda p: p["proof_id"]
        ):
            if (
                proof["status"] != "current"
                or not proof["history_from_zero"]
                or proof["interval"] is None
            ):
                continue
            scope = "source:" + canonical.get(proof["source_account"], proof["source_account"])
            period = (
                (date.fromisoformat(proof["covered_from"]) - timedelta(days=1)).isoformat(),
                proof["covered_to"],
            )
            for instrument in proof["interval"]["instruments"]:
                proof_instruments[(scope, period, instrument["isin"])] = instrument
        data = {
            "contract_version": overview["contract_version"],
            "scope": "current_available_history_not_limited_to_selected_month",
            "reading_guide": dict(OVERALL_READING_GUIDE),
            "overall": {
                **{name: _overall_metric(overview["overall"][name]) for name in ("pnl", "rate")},
                "partial": overview["overall"]["partial"],
                "reason_codes": sorted(set(overview["overall"]["reason_codes"])),
            },
            "mixed_result": _overall_mixed(overview["mixed_result"], source_account_refs),
            **{
                name: _overall_income(overview[name], source_account_refs)
                for name in ("coupon_income", "dividend_income")
            },
            "source_accounts": [
                {
                    "ref": source_account_refs[row["scope"]],
                    "period": _overall_period(row["period"]),
                    "result": _overall_result(row["result"]),
                    "proof_status": row["proof_status"],
                    "reason_codes": sorted(set(row["reason_codes"])),
                    "instrument_count": row["instrument_count"],
                }
                for row in overview["source_accounts"]
            ],
            "instruments": [
                _overall_card(
                    returns_overall.read_instrument_card(session, row["isin"], overview=overview),
                    source_account_refs,
                    source_intervals,
                    proof_instruments,
                )
                for row in overview["instruments"]
            ],
            "deposits": {
                "interest": _overall_metric(overview["deposits"]["interest"]),
                "partial": overview["deposits"]["partial"],
                "periods": [
                    {
                        "period": _overall_period(row["period"]),
                        "status": row["status"],
                        "rows": row["rows"],
                    }
                    for row in overview["deposits"]["periods"]
                ],
                "reason_codes": sorted(set(overview["deposits"]["reason_codes"])),
            },
            "gold": _overall_gold(
                overview["gold"], read_gold_histories(session, include_events=True)
            ),
            "reason_codes": sorted(set(overview["reason_codes"])),
        }
        return {"status": "partial", "reason_codes": data["reason_codes"], "data": data}
