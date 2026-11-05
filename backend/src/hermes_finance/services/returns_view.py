"""Read-only presentation composition. The existing readers own every return.

No financial writes, providers or persisted presentation cache. On-demand detail
retains the existing v2 analysis and provenance; overview remains compact.
Money crosses this boundary as integer-minor-unit strings, including large values.
"""

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from hermes_finance.domain import PerformanceScope, RubleAmount
from hermes_finance.persistence import (
    Account,
    Instrument,
    InvestmentCashFlow,
    ReportingMonth,
    SourceIntakeOriginal,
)
from hermes_finance.services.instrument_cash_income import known_instrument_cash_income
from hermes_finance.services.performance_attribution import performance_attribution_for_interval
from hermes_finance.services.performance_availability import (
    _membership_at,
    _scope_membership_coverage,
)
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.returns_account_link import account_link
from hermes_finance.services.source_instrument_returns import (
    ReturnBreakdown,
    read_instrument_returns,
)
from hermes_finance.services.source_monthly_returns import (
    _SOURCE_SCOPE_READS,
    _selected_sources,
    read_monthly_returns,
    source_read_snapshot,
)


def metric(value=None, *, reasons=(), method="", unit="kopecks", estimate=True):
    return {
        "value": None if value is None else str(value),
        "reason_codes": list(dict.fromkeys(reasons)),
        "method": method,
        "unit": unit,
        "estimate": estimate,
    }


def bounds(start, end):
    return {"start": start, "end": end}


def _months(session):
    return list(session.scalars(select(ReportingMonth).order_by(ReportingMonth.period_end)))


def _source_scopes(session):
    """Copy the proved alias map only within the current protected source read."""
    cache = session.info.get(_SOURCE_SCOPE_READS)
    if cache is None:
        return _read_source_scopes(session)
    if "canonical" not in cache:
        cache["canonical"] = _read_source_scopes(session)
    return dict(cache["canonical"])


def _read_source_scopes(session):
    """Group only aliases proved by every selected document, using the reader.

    Unreadable, conflicting and multi-account documents preserve their entries.
    No transitive grouping or persisted identity changes.
    """
    aliases = set()
    for raw in session.scalars(select(SourceIntakeOriginal.native_accounts_json)):
        try:
            accounts = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(accounts, list):
            continue
        aliases.update(
            a for a in accounts if isinstance(a, str) and a and not any(c.isspace() for c in a)
        )
    selections = {a: _selected_sources(session, a, identity_only=True) for a in aliases}
    canonical = {a: a for a in aliases}
    for alias, (selected, native) in selections.items():
        if not native or not selected:
            continue
        target = next(iter(native))
        if target not in selections or target == alias:
            continue
        target_selected, target_native = selections[target]
        if target_native != {target}:
            continue
        if not {o.id for o, _, _ in selected} <= {o.id for o, _, _ in target_selected}:
            continue
        if all(
            error is None
            and view is not None
            and view["native_scope"] == {target}
            and alias in {target, view["document"]["filename_account"]}
            for _, view, error in selected
        ):
            canonical[alias] = target
    # Never follow an alias chain.
    return {a: target if canonical[target] == target else a for a, target in canonical.items()}


def _accounts(session, canonical=None):
    canonical = _source_scopes(session) if canonical is None else canonical
    display_names = session.info.get("returns_account_display_names", {})
    links = {a: account_link(session, a, canonical) for a in set(canonical.values())}
    return (
        [
            {
                "id": f"source:{a}",
                "label": display_names.get(f"source:{a}") or links[a]["label"],
                "account_link": links[a],
                "basis": "statements",
            }
            for a in sorted(set(canonical.values()))
        ]
        + [
            {"id": f"account:{a.id}", "label": a.name, "basis": "accepted"}
            for a in session.scalars(select(Account).order_by(Account.id))
        ]
        + [{"id": "portfolio", "label": "Общий портфель", "basis": "accepted"}]
    )


def read_context(session):
    with source_read_snapshot(session):
        closed = [m for m in _months(session) if m.status == "closed"]
        canonical = _source_scopes(session)
        source_periods = {}
        for original in session.scalars(select(SourceIntakeOriginal)):
            try:
                aliases = json.loads(original.native_accounts_json)
            except (ValueError, TypeError):
                continue
            if not isinstance(aliases, list):
                continue
            for alias in aliases:
                if isinstance(alias, str) and alias and not any(c.isspace() for c in alias):
                    source_periods.setdefault(f"source:{canonical.get(alias, alias)}", []).append(
                        bounds(original.covered_from - timedelta(days=1), original.covered_to)
                    )
        saved_month_ends = {
            key: max(p["end"] for p in periods) for key, periods in source_periods.items()
        }
        for periods in source_periods.values():
            periods[:] = list({(p["start"], p["end"]): p for p in periods}.values())
            periods.append(bounds(min(p["start"] for p in periods), max(p["end"] for p in periods)))
        from hermes_finance.services.source_investment_proofs import read_report_headers

        history_periods = {}
        history_rank = {}
        for proof in read_report_headers(session):
            key = f"source:{canonical.get(proof['source_account'], proof['source_account'])}"
            period = bounds(
                date.fromisoformat(proof["covered_from"]) - timedelta(days=1),
                date.fromisoformat(proof["covered_to"]),
            )
            if period not in source_periods.setdefault(key, []):
                source_periods[key].append(period)
            rank = (proof["covered_to"], proof["proof_id"])
            if proof["history_from_zero"] and rank > history_rank.get(key, ("", 0)):
                history_rank[key] = rank
                history_periods[key] = period
        # Selection metadata can extend to saved newer months; numerical reads
        # still require the current base proof, every month and matching seams.
        for key, period in history_periods.items():
            latest = saved_month_ends.get(key, period["end"])
            if latest > period["end"]:
                history_periods[key] = {**period, "end": latest}
                if history_periods[key] not in source_periods[key]:
                    source_periods[key].append(history_periods[key])
        return {
            "accounts": _accounts(session, canonical),
            "scope_aliases": {f"source:{a}": f"source:{b}" for a, b in canonical.items() if a != b},
            "source_periods": source_periods,
            # Selection metadata only. The ordinary reader still validates the
            # exact proof's currentness before exposing any numerical result.
            "source_history_periods": history_periods,
            "default_period": bounds(
                closed[-1].period_start - timedelta(days=1), closed[-1].period_end
            )
            if closed
            else None,
            "closed_periods": [
                bounds(m.period_start - timedelta(days=1), m.period_end) for m in closed
            ],
        }


def _validate_scope(session, scope):
    if scope.startswith("source:"):
        canonical = _source_scopes(session)
        if scope[7:] in canonical:
            return f"source:{canonical[scope[7:]]}"
    elif scope == "portfolio" or scope in {
        f"account:{account_id}" for account_id in session.scalars(select(Account.id))
    }:
        return scope
    else:
        raise ValueError("returns_scope_unknown")
    raise ValueError("returns_scope_unknown")


def _instrument_metric(item, *, unit="kopecks"):
    # Partial known subtotals and conditional estimates never stand in for P&L.
    return metric(
        item.value if item.status in {"supported", "provisional"} else None,
        reasons=item.reason_codes,
        method="modified_dietz" if unit == "fraction" else "instrument_return_v2",
        unit=unit,
    )


def _estimate_metric(estimate, name, *, unit="kopecks"):
    if not hasattr(estimate, name):
        return metric(reasons=("statement_estimate_not_applicable",), unit=unit)
    result = _instrument_metric(getattr(estimate, name), unit=unit)
    result["reason_codes"] = sorted(
        set(result["reason_codes"]) | set(getattr(estimate, "assumptions", ()))
    )
    return result


def _display_name(name, isin):
    from hermes_finance.services.source_investment_proofs import display_name_for_isin

    return display_name_for_isin(isin, (name,))


def _catalogue_names(session, rows):
    # Exact stored ISIN only. Aliases, tickers and broker mappings cannot establish
    # identity here. This metadata does not change the source reader's authority.
    isins = {row.isin for row in rows if not _display_name(row.source_name, row.isin)}
    if not isins:
        return {}
    return {
        isin: _display_name(name, isin)
        for isin, name in session.execute(
            select(Instrument.isin, Instrument.name).where(Instrument.isin.in_(isins))
        )
    }


def _instrument(row, start, end, catalogue_names):
    analysis = row.analysis
    if (analysis.opening_date, analysis.closing_date, analysis.contract_version) != (
        start,
        end,
        "instrument_return_v2",
    ):
        raise ValueError("returns_period_mismatch")
    return {
        "isin": row.isin,
        "name": _display_name(row.source_name, row.isin)
        or catalogue_names.get(row.isin)
        or row.isin,
        "kind": row.instrument_type,
        "period": bounds(start, end),
        "valuation_date": analysis.closing.date
        if analysis.closing.reported_value_kopecks is not None
        else (
            analysis.opening.date if analysis.opening.reported_value_kopecks is not None else None
        ),
        "pnl": _instrument_metric(analysis.pnl),
        "rate": _instrument_metric(analysis.modified_dietz, unit="fraction"),
        "coupons": _instrument_metric(analysis.components["coupons"]),
        "dividends": _instrument_metric(analysis.components["dividends"]),
        "conditional": analysis.statement_estimate.pnl.value is not None,
        "conditional_pnl": _estimate_metric(analysis.statement_estimate, "pnl"),
        "conditional_rate": _estimate_metric(
            analysis.statement_estimate, "modified_dietz", unit="fraction"
        ),
    }


def _monthly(row):
    result = row.result
    reasons = (*result.reason_codes, *row.flags)
    return {
        "period": bounds(result.opening_date, result.closing_date),
        "valuation_date": result.closing_date
        if result.closing_kopecks is not None
        else (result.opening_date if result.opening_kopecks is not None else None),
        "pnl": metric(result.growth_kopecks, reasons=reasons, method="source_monthly"),
        "rate": metric(
            result.modified_dietz_return,
            reasons=reasons,
            method="modified_dietz",
            unit="fraction",
        ),
        "coupons": metric(row.coupons_kopecks, reasons=row.flags, method="credited_payments"),
        "dividends": metric(row.dividends_kopecks, reasons=row.flags, method="credited_payments"),
    }


def _period_flags(months, start, end):
    # Monthly calculation blockers already have period-specific counterparts.
    # Only additional source advisories (e.g. seams) also apply to outer results.
    return tuple(
        flag
        for row in months
        if start <= row.result.opening_date and row.result.closing_date <= end
        for flag in row.flags
        if flag not in row.result.reason_codes
    )


def _period_result(period, start, end, months):
    flags = _period_flags(months, start, end)
    return {
        "period": bounds(start, end),
        "valuation_date": max(
            (
                r.result.closing_date
                if r.result.closing_kopecks is not None
                else r.result.opening_date
                for r in months
                if start <= r.result.opening_date
                and r.result.closing_date <= end
                and (r.result.closing_kopecks is not None or r.result.opening_kopecks is not None)
            ),
            default=None,
        ),
        "pnl": metric(
            period.growth_kopecks,
            reasons=(*period.growth_reason_codes, *flags),
            method="source_period",
        ),
        "rate": metric(
            period.chained_return,
            reasons=(*period.chain_reason_codes, *flags),
            method="chained_modified_dietz",
            unit="fraction",
        ),
        "coupons": metric(reasons=("income_interval_unavailable",)),
        "dividends": metric(reasons=("income_interval_unavailable",)),
    }


def _period_income(result, months, start, end):
    # Only additive credited income is composed. Never sum returns or partial months.
    rows = [r for r in months if start <= r.result.opening_date and r.result.closing_date <= end]
    complete = (
        bool(rows) and rows[0].result.opening_date == start and rows[-1].result.closing_date == end
    )
    complete = complete and all(
        a.result.closing_date == b.result.opening_date for a, b in zip(rows, rows[1:])
    )
    for name in ("coupons", "dividends"):
        values = [getattr(r, f"{name}_kopecks") for r in rows]
        available = complete and all(v is not None for v in values)
        reasons = tuple(flag for row in rows for flag in row.flags)
        result[name] = metric(
            sum(values) if available else None,
            reasons=reasons if available else (*reasons, "income_interval_unavailable"),
            method="credited_payments",
        )


def _available_months(history, start, end, full):
    """A separately labelled RUB subtotal; never an interval return/rate.

    Enumerate calendar cells once. Long/partial reports, segments, instruments
    and credited payments cannot become extra operands.
    """
    if full and full["pnl"]["value"] is not None:
        return None
    included, missing, reasons, values = [], [], [], []
    cursor = (start + timedelta(days=1)).replace(day=1)
    while cursor <= end:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        opening, closing = cursor - timedelta(days=1), following - timedelta(days=1)
        cell = bounds(opening, closing)
        rows = [r for r in history if r["period"] == cell]
        codes = []
        if opening < start or closing > end:
            codes = ["partial_calendar_month"]
        elif len(rows) != 1:
            codes = ["calendar_month_missing" if not rows else "calendar_month_ambiguous"]
        elif rows[0]["pnl"]["value"] is None:
            codes = rows[0]["pnl"]["reason_codes"] or ["calendar_month_unavailable"]
        if codes:
            missing.append({"period": cell, "reason_codes": codes})
        else:
            values.append(int(rows[0]["pnl"]["value"]))
            included.append(cell)
            reasons.extend(rows[0]["pnl"]["reason_codes"])
        cursor = following
    return {
        "period": bounds(start, end),
        "valuation_date": max(
            (
                r.get("valuation_date")
                for r in history
                if r["period"] in included and r.get("valuation_date")
            ),
            default=None,
        ),
        "partial": True,
        "pnl": metric(
            sum(values) if values else None, reasons=reasons, method="available_calendar_months"
        ),
        "included": included,
        "missing": missing,
        "covered_months": len(included),
        "total_months": len(included) + len(missing),
    }


def _source_view(session, account, start, end):
    monthly = read_monthly_returns(session, source_account=account)
    instruments = read_instrument_returns(
        session,
        source_account=account,
        opening_date=start,
        closing_date=end,
        include_monthly_history=False,
    )
    history = [_monthly(row) for row in monthly.months]
    whole = None
    periods = [r["period"] for r in history]
    if monthly.months:
        first, last = monthly.months[0].result.opening_date, monthly.months[-1].result.closing_date
        whole = _period_result(monthly.period, first, last, monthly.months)
        _period_income(whole, monthly.months, first, last)
        periods.append(whole["period"])
    selected = next((r for r in history if r["period"] == bounds(start, end)), None)
    for segment in monthly.segments:
        periods.append(bounds(segment.start, segment.end))
        if selected is None and (start, end) == (segment.start, segment.end):
            selected = _period_result(segment, start, end, monthly.months)
    if selected is None and whole and whole["period"] == bounds(start, end):
        selected = whole.copy()
    if selected is None:
        # The dated instrument reader may support an outer/native interval even
        # when calendar months do not. Its account bridge is a separate read model.
        reconciliation = instruments.reconciliation
        selected = {
            "period": bounds(start, end),
            "valuation_date": end
            if reconciliation and reconciliation.account_growth.value is not None
            else None,
            "pnl": metric(
                reconciliation.account_growth.value
                if reconciliation.account_growth.status in {"supported", "provisional"}
                else None,
                reasons=(
                    *reconciliation.account_growth.reason_codes,
                    *_period_flags(monthly.months, start, end),
                ),
                method="source_account_reconciliation",
            )
            if reconciliation
            else metric(reasons=("interval_unavailable",)),
            "rate": metric(reasons=("interval_rate_unavailable",), unit="fraction"),
        }
    _period_income(selected, monthly.months, start, end)
    from hermes_finance.services.source_investment_proofs import read_reports

    reports = read_reports(session, source_account=account)

    for proof in reports:
        value = _investment_report_result(proof)
        periods.append(value["period"])
        if value["period"] == bounds(start, end):
            selected = value
    from hermes_finance.services.source_account_history import extend_history, latest_history

    historical = latest_history(reports)
    if historical:
        extended = extend_history(historical, monthly)
        whole = _investment_report_result(extended)
        periods.append(whole["period"])
        if whole["period"] == bounds(start, end):
            selected = whole.copy()
    if instruments.instruments:
        analysis = instruments.instruments[0].analysis
        periods.append(bounds(analysis.history_start, analysis.history_end))
    names = _catalogue_names(session, instruments.instruments)
    return {
        "selected": selected,
        "breakdown": instruments.breakdown,
        "all_history": whole,
        "available_months_total": _available_months(history, first, last, whole)
        if monthly.months
        else None,
        "selected_available_months_total": _available_months(history, start, end, selected),
        "history": history,
        "periods": periods,
        "instruments": [_instrument(row, start, end, names) for row in instruments.instruments],
        "instrument_reason_codes": [],
        "proof_status": (monthly.source_proof or {}).get("status", "absent"),
    }


def _investment_report_result(proof):
    interval = proof["interval"]
    period = bounds(
        date.fromisoformat(proof["covered_from"]) - timedelta(days=1),
        date.fromisoformat(proof["covered_to"]),
    )
    reasons = tuple(proof["reason_codes"]) if interval is None else tuple(interval["reason_codes"])
    return {
        "period": period,
        "valuation_date": period["end"]
        if interval and interval.get("closing_kopecks") is not None
        else (
            period["start"] if interval and interval.get("opening_kopecks") is not None else None
        ),
        "pnl": metric(
            None
            if interval is None or interval["pnl"]["value"] is None
            else int(interval["pnl"]["value"]),
            reasons=reasons,
            method="source_account_history_v1"
            if proof.get("derived_history")
            else "source_xml_pdf_interval",
        ),
        "rate": metric(
            None
            if interval is None or interval["modified_dietz"]["value"] is None
            else Decimal(interval["modified_dietz"]["value"]),
            reasons=reasons,
            method="modified_dietz",
            unit="fraction",
        ),
        **{
            name: metric(
                None
                if interval is None or interval.get(name + "_kopecks") is None
                else int(interval[name + "_kopecks"]),
                reasons=tuple(proof["reason_codes"])
                if interval is None
                else tuple(interval.get("income_reason_codes", {}).get(name, ()))
                + (("non_rub_income_unknown",) if interval.get(name + "_kopecks") is None else ()),
                method="source_xml_actual_money",
            )
            for name in ("coupons", "dividends")
        },
    }


def _accepted_income(session, scope, start, end):
    """Project existing qualified ICF events once, independently of P&L/rate.

    The payout reader owns identity, currentness and gross/net/tax semantics.
    Its unknown interval coverage cannot establish an absent-payment zero.
    """
    pairs = select(InvestmentCashFlow.account_id, InvestmentCashFlow.instrument_id).where(
        InvestmentCashFlow.flow_type.in_(("coupon", "dividend")),
        InvestmentCashFlow.event_date > start,
        InvestmentCashFlow.event_date <= end,
    )
    membership_rows = None
    reasons = {"whole_interval_coverage_unknown"}
    if scope != "portfolio":
        pairs = pairs.where(InvestmentCashFlow.account_id == int(scope.split(":", 1)[1]))
    else:
        membership, membership_rows = _scope_membership_coverage(
            session,
            scope=PerformanceScope.PORTFOLIO,
            account_id=None,
            start_date=start,
            end_date=end,
        )
        reasons.update(membership.reason_codes)
    events, instruments = [], []
    for account_id, instrument_id in session.execute(
        pairs.distinct().order_by(InvestmentCashFlow.account_id, InvestmentCashFlow.instrument_id)
    ):
        if instrument_id is None:
            reasons.add("historical_instrument_identity_unknown")
            continue
        payout = known_instrument_cash_income(session, account_id, instrument_id, start, end)
        reasons.update(set(payout["reason_codes"]) - {"full_instrument_return_unavailable"})
        selected = []
        for event in payout["events"]:
            if (
                membership_rows is not None
                and _membership_at(
                    membership_rows.get(account_id, []), date.fromisoformat(event["date"])
                )
                is not True
            ):
                continue
            reasons.update(event["reason_codes"])
            if event["included_in_known_net"]:
                selected.append(event)
        events.extend(selected)
        if selected:
            instrument = session.get(Instrument, instrument_id)
            instruments.append(
                {
                    "id": f"{account_id}:{instrument_id}",
                    "account": payout["account"]["name"],
                    "name": instrument.name,
                    "isin": instrument.isin,
                    **_accepted_amounts(selected),
                }
            )
    return {
        **_accepted_amounts(events),
        "partial": True,
        "reason_codes": sorted(reasons),
        "instruments": instruments,
    }


def _accepted_amounts(events):
    def total(field, rows):
        values = [row[field] for row in rows]
        if not values or any(v is None for v in values):
            return None
        return str(sum(RubleAmount.from_api(v).kopecks for v in values))

    return {
        "net_kopecks": total("booked_net", events),
        "gross_kopecks": total("gross", events),
        "tax_kopecks": total("tax", events),
        "fees_kopecks": total("fee", events),
        "coupons_kopecks": total("booked_net", [e for e in events if e["kind"] == "coupon"]),
        "dividends_kopecks": total("booked_net", [e for e in events if e["kind"] == "dividend"]),
    }


def _accepted_result(session, scope, start, end, income=None):
    kind = PerformanceScope.PORTFOLIO if scope == "portfolio" else PerformanceScope.ACCOUNT
    account_id = None if scope == "portfolio" else int(scope.split(":", 1)[1])
    selection = dict(start_date=start, end_date=end, scope=kind, account_id=account_id)
    pnl = performance_attribution_for_interval(session, **selection)
    rate = twrr_for_interval(session, **selection)
    income = _accepted_income(session, scope, start, end) if income is None else income
    return {
        "period": bounds(start, end),
        "valuation_date": end if pnl.value is not None or rate.value is not None else None,
        "pnl": metric(
            pnl.value.kopecks if pnl.value is not None else None,
            reasons=pnl.reason_codes,
            method="PERF04A",
            estimate=False,
        ),
        "rate": metric(
            rate.value,
            reasons=rate.reason_codes,
            method="twrr",
            unit="percentage_points",
            estimate=False,
        ),
        **{
            name: metric(
                income[name + "_kopecks"],
                reasons=income["reason_codes"],
                method="known-booked-net-payouts",
                estimate=False,
            )
            for name in ("coupons", "dividends")
        },
    }


def _accepted_history(session, scope, closed):
    if not closed:
        return []
    by_start = {m.period_start: m for m in closed}
    cursor = closed[0].period_start
    history = []
    while cursor <= closed[-1].period_start:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        start, end = cursor - timedelta(days=1), following - timedelta(days=1)
        if cursor in by_start:
            history.append(_accepted_result(session, scope, start, end))
        else:
            # A missing or DRAFT month is a visible gap, never a calculated zero.
            missing = dict(reasons=("calendar_month_not_closed",), estimate=False)
            history.append(
                {
                    "period": bounds(start, end),
                    "valuation_date": None,
                    "pnl": metric(method="PERF04A", **missing),
                    "rate": metric(method="twrr", unit="percentage_points", **missing),
                    "coupons": metric(**missing),
                    "dividends": metric(**missing),
                }
            )
        cursor = following
    return history


def read_overview(session, *, scope, start, end):
    with source_read_snapshot(session):
        resolved = _validate_scope(session, scope)
        if scope.startswith("source:"):
            view = _source_view(session, resolved.removeprefix("source:"), start, end)
        else:
            closed = [m for m in _months(session) if m.status == "closed"]
            history = _accepted_history(session, scope, closed)
            first = closed[0].snapshot_date if closed else None
            last = closed[-1].snapshot_date if closed else None
            whole = (
                _accepted_result(session, scope, first, last) if first and first < last else None
            )
            income = _accepted_income(session, scope, start, end)
            selected = _accepted_result(session, scope, start, end, income)
            view = {
                "selected": selected,
                "accepted_income": income,
                "breakdown": ReturnBreakdown(
                    payouts_kopecks=income["net_kopecks"],
                    price_and_trades_kopecks=None,
                    commissions_kopecks=None,
                    paid_nkd_kopecks=None,
                    taxes_kopecks=None,
                    other_kopecks=None,
                    total_kopecks=selected["pnl"]["value"],
                    complete=False,
                )
                if income["net_kopecks"] is not None
                else None,
                "all_history": whole,
                "available_months_total": None,
                "selected_available_months_total": None,
                "history": history,
                "periods": [r["period"] for r in history] + ([whole["period"]] if whole else []),
                "instruments": [],
                "instrument_reason_codes": ["accepted_instrument_breakdown_unavailable"],
                "proof_status": "not_applicable",
            }
        link = (
            account_link(session, resolved.removeprefix("source:"))
            if scope.startswith("source:")
            else None
        )
        for item in [view["selected"], view["all_history"], *view["history"], *view["instruments"]]:
            if item is not None:
                item["account_link"] = link
        return {"scope": scope, "account_link": link, **view}


def read_clean_source_overview(session, *, scope, start, end):
    """Selected source period on the same clean basis as the main overview."""
    from hermes_finance.services.clean_instrument_return import (
        read_clean_account,
        read_clean_overview,
    )

    with source_read_snapshot(session):
        view = read_overview(session, scope=scope, start=start, end=end)
        if not scope.startswith("source:"):
            return {**view, "contract_version": "returns_capital_v1"}
        resolved = _validate_scope(session, scope).removeprefix("source:")
        link = view["account_link"]
        cache = {}

        def build(first, last):
            key = (first, last)
            if key in cache:
                return cache[key]
            source = read_clean_account(session, resolved, first, last)
            instruments = []

            def converted(raw, *, rate=False):
                reasons = list(raw["reason_codes"]) + list(raw["assumptions"])
                if raw["status"] == "partial":
                    reasons.append("clean_partial_result")
                return metric(
                    raw["value"],
                    reasons=reasons,
                    method="modified_dietz" if rate else "clean_instrument_return_v1",
                    unit="fraction" if rate else "kopecks",
                    estimate=raw["status"] != "supported",
                )

            def subtotal(name):
                values = [row[name] for row in source["instruments"]]
                known = [int(value["value"]) for value in values if value["value"] is not None]
                return metric(
                    sum(known) if known else None,
                    reasons=("clean_partial_result",),
                    method="known_clean_instruments",
                    estimate=True,
                )

            for row in source["instruments"]:
                pnl = row["pnl"] if row["pnl"]["value"] is not None else row["known_result"]
                instruments.append(
                    {
                        "isin": row["isin"],
                        "name": row["name"] or row["isin"],
                        "kind": row["instrument_type"],
                        "period": bounds(first, last),
                        "valuation_date": last
                        if row["closing_value"]["value"] is not None
                        else None,
                        "account_link": link,
                        "pnl": converted(pnl),
                        "rate": converted(row["modified_dietz"], rate=True),
                        "coupons": converted(row["coupons"]),
                        "dividends": converted(row["dividends"]),
                        "conditional": False,
                    }
                )
            result = {
                "period": bounds(first, last),
                "valuation_date": last if any(r["valuation_date"] for r in instruments) else None,
                "account_link": link,
                "pnl": subtotal("known_result"),
                "rate": metric(
                    reasons=("combined_rate_periods_and_flows_not_proven",), unit="fraction"
                ),
                "coupons": subtotal("coupons"),
                "dividends": subtotal("dividends"),
            }
            cache[key] = (result, instruments)
            return cache[key]

        view["selected"], view["instruments"] = build(start, end)
        view["history"] = [
            build(row["period"]["start"], row["period"]["end"])[0] for row in view["history"]
        ]
        whole = next(
            (
                row
                for row in read_clean_overview(session)["accounts"]
                if row["scope"] == f"source:{resolved}"
            ),
            None,
        )
        view["all_history"] = (
            build(whole["period"]["start"], whole["period"]["end"])[0] if whole else None
        )
        view["breakdown"] = None
        view["available_months_total"] = None
        view["selected_available_months_total"] = None
        view["instrument_reason_codes"] = []
        view["contract_version"] = "returns_source_v2"
        return view


def apply_clean_detail(detail, clean):
    """Retain raw events, but omit the legacy cash-economic result from a v2 detail."""
    from dataclasses import replace

    from hermes_finance.domain.instrument_return import Metric as DomainMetric

    def converted(raw, *, rate=False):
        reasons = list(raw["reason_codes"]) + list(raw["assumptions"])
        if raw["status"] == "partial":
            reasons.append("clean_partial_result")
        return metric(
            raw["value"],
            reasons=reasons,
            method="modified_dietz" if rate else "clean_instrument_return_v1",
            unit="fraction" if rate else "kopecks",
            estimate=raw["status"] != "supported",
        )

    analysis = detail["analysis"]
    unavailable = DomainMetric(None, "unavailable", ("legacy_cash_economics_omitted",))
    unavailable_rate = replace(
        analysis.modified_dietz,
        value=None,
        status="unavailable",
        reason_codes=("legacy_cash_economics_omitted",),
    )
    detail["analysis"] = replace(
        analysis,
        components={name: unavailable for name in analysis.components},
        pnl=unavailable,
        known_subtotal=unavailable,
        modified_dietz=unavailable_rate,
        chained_monthly=unavailable,
        statement_estimate=replace(
            analysis.statement_estimate, pnl=unavailable, modified_dietz=unavailable_rate
        ),
    )
    pnl = clean["pnl"] if clean["pnl"]["value"] is not None else clean["known_result"]
    detail.update(
        contract_version="returns_source_detail_v2",
        clean=clean,
        pnl=converted(pnl),
        rate=converted(clean["modified_dietz"], rate=True),
        coupons=converted(clean["coupons"]),
        dividends=converted(clean["dividends"]),
        buys=converted(clean["buys"]),
        sells=converted(clean["sells"]),
        conditional=False,
        conditional_pnl=metric(reasons=("legacy_cash_economics_omitted",)),
        conditional_rate=metric(reasons=("legacy_cash_economics_omitted",), unit="fraction"),
        reason_codes=list(pnl["reason_codes"]),
    )
    return detail


def read_clean_source_detail(session, *, scope, start, end, isin):
    from hermes_finance.services.clean_instrument_return import read_clean_account

    with source_read_snapshot(session):
        resolved = _validate_scope(session, scope)
        if not scope.startswith("source:"):
            raise ValueError("returns_instrument_scope_unsupported")
        data = read_clean_account(session, resolved.removeprefix("source:"), start, end, isin=isin)
        if len(data["instruments"]) != 1:
            raise LookupError("returns_instrument_missing")
        detail = read_detail(
            session, scope=scope, start=start, end=end, isin=isin, native_period=True
        )
        return apply_clean_detail(detail, data["instruments"][0])


def read_detail(session, *, scope, start, end, isin, native_period=False):
    with source_read_snapshot(session):
        resolved = _validate_scope(session, scope)
        if not scope.startswith("source:"):
            raise ValueError("returns_instrument_scope_unsupported")
        result = read_instrument_returns(
            session,
            source_account=resolved.removeprefix("source:"),
            opening_date=start,
            closing_date=end,
            isin=isin,
            include_monthly_history=False,
            available_period=native_period,
        )
        if len(result.instruments) != 1:
            raise LookupError("returns_instrument_missing")
        row = result.instruments[0]
        analysis = row.analysis
        return {
            "scope": scope,
            "account_link": account_link(session, resolved.removeprefix("source:")),
            "analysis": analysis,
            **_instrument(row, start, end, _catalogue_names(session, (row,))),
            "opening_quantity": None
            if analysis.opening.quantity is None
            else str(analysis.opening.quantity),
            "closing_quantity": None
            if analysis.closing.quantity is None
            else str(analysis.closing.quantity),
            "buys": _instrument_metric(analysis.components["buys"]),
            "sells": _instrument_metric(analysis.components["sells"]),
            "reason_codes": list(analysis.reason_codes),
            "events": [
                {
                    "ordinal": ordinal,
                    "event_key": e.event_key,
                    "kind": e.kind,
                    "date": e.event_date,
                    "execution_date": e.execution_date,
                    "trade_time": e.trade_time,
                    "cash_date": e.cash_settlement_date,
                    "quantity_date": e.depository_settlement_date,
                    "quantity": None if e.quantity_delta is None else str(e.quantity_delta),
                    **{
                        name: None if (value := getattr(e, name)) is None else str(value)
                        for name in (
                            "unit_price",
                            "face_value",
                            "native_trade_amount_kopecks",
                            "accrued_interest_kopecks",
                            "commission_kopecks",
                            "gross_payout_kopecks",
                            "withheld_tax_kopecks",
                            "net_payout_kopecks",
                        )
                    },
                    "price_unit": e.price_unit,
                    "face_value_date": e.face_value_date,
                    "native_total_basis": e.native_total_basis,
                    # Compatibility amount is the native total or net payout.
                    # Only the dated cash legs describe cash counted in economics.
                    "amount": metric(
                        e.net_payout_kopecks
                        if e.kind in {"COUPON", "DIVIDEND"}
                        else e.native_trade_amount_kopecks
                    ),
                    "cash_legs": [
                        {
                            "role": leg.role,
                            "date": leg.date,
                            "account_cash_kopecks": str(leg.account_cash_kopecks),
                            "instrument_flow_kopecks": str(leg.instrument_flow_kopecks),
                            "source_references": leg.source_references,
                            "ownership": leg.ownership,
                        }
                        for leg in e.cash_legs
                    ],
                    "effective_isin": e.effective_isin,
                    "attribution_basis": e.attribution_basis,
                    "current": e.current,
                    "counted": e.counted and e.current,
                    "reason_codes": e.reason_codes,
                    "assumptions": e.assumptions,
                }
                for ordinal, e in enumerate(analysis.events)
                if e.event_date is None
                or any(
                    day is not None and start < day <= end
                    for day in (
                        e.event_date,
                        e.execution_date,
                        e.cash_settlement_date,
                        e.depository_settlement_date,
                        *(leg.date for leg in e.cash_legs),
                    )
                )
            ],
        }
