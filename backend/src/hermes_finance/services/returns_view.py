"""Read-only presentation composition. The existing readers own every return.

No financial facts, provenance payloads, providers or persisted presentation cache.
Money crosses this boundary as integer-minor-unit strings, including large values.
"""

import json
from datetime import date, timedelta

from sqlalchemy import select

from hermes_finance.database import coherent_read_snapshot
from hermes_finance.domain import PerformanceScope
from hermes_finance.persistence import Account, ReportingMonth, SourceIntakeOriginal
from hermes_finance.services.performance_attribution import performance_attribution_for_interval
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_monthly_returns import read_monthly_returns


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


def _accounts(session):
    # Do not infer a financial-account mapping from a filename, name or suffix.
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
    return (
        [{"id": f"source:{a}", "label": a, "basis": "statements"} for a in sorted(aliases)]
        + [
            {"id": f"account:{a.id}", "label": a.name, "basis": "accepted"}
            for a in session.scalars(select(Account).order_by(Account.id))
        ]
        + [{"id": "portfolio", "label": "Общий портфель", "basis": "accepted"}]
    )


def read_context(session):
    with coherent_read_snapshot(session):
        closed = [m for m in _months(session) if m.status == "closed"]
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
                    source_periods.setdefault(f"source:{alias}", []).append(
                        bounds(original.covered_from - timedelta(days=1), original.covered_to)
                    )
        for periods in source_periods.values():
            periods.append(bounds(min(p["start"] for p in periods), max(p["end"] for p in periods)))
        return {
            "accounts": _accounts(session),
            "source_periods": source_periods,
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
    if scope not in {a["id"] for a in _accounts(session)}:
        raise ValueError("returns_scope_unknown")


def _instrument_metric(item, *, unit="kopecks"):
    # Partial known subtotals and conditional estimates never stand in for P&L.
    return metric(
        item.value if item.status in {"supported", "provisional"} else None,
        reasons=item.reason_codes,
        method="modified_dietz" if unit == "fraction" else "instrument_return_v2",
        unit=unit,
    )


def _instrument(row, start, end):
    analysis = row.analysis
    if (analysis.opening_date, analysis.closing_date, analysis.contract_version) != (
        start,
        end,
        "instrument_return_v2",
    ):
        raise ValueError("returns_period_mismatch")
    return {
        "isin": row.isin,
        "name": row.source_name or row.isin,
        "kind": row.instrument_type,
        "period": bounds(start, end),
        "pnl": _instrument_metric(analysis.pnl),
        "rate": _instrument_metric(analysis.modified_dietz, unit="fraction"),
        "coupons": _instrument_metric(analysis.components["coupons"]),
        "dividends": _instrument_metric(analysis.components["dividends"]),
        "conditional": analysis.statement_estimate.pnl.value is not None,
    }


def _monthly(row):
    result = row.result
    reasons = (*result.reason_codes, *row.flags)
    return {
        "period": bounds(result.opening_date, result.closing_date),
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


def _source_view(session, account, start, end):
    monthly = read_monthly_returns(session, source_account=account)
    instruments = read_instrument_returns(
        session, source_account=account, opening_date=start, closing_date=end
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
    if instruments.instruments:
        analysis = instruments.instruments[0].analysis
        periods.append(bounds(analysis.history_start, analysis.history_end))
    return {
        "selected": selected,
        "all_history": whole,
        "history": history,
        "periods": periods,
        "instruments": [_instrument(row, start, end) for row in instruments.instruments],
        "instrument_reason_codes": [],
        "proof_status": (monthly.source_proof or {}).get("status", "absent"),
    }


def _accepted_result(session, scope, start, end):
    kind = PerformanceScope.PORTFOLIO if scope == "portfolio" else PerformanceScope.ACCOUNT
    account_id = None if scope == "portfolio" else int(scope.split(":", 1)[1])
    selection = dict(start_date=start, end_date=end, scope=kind, account_id=account_id)
    pnl = performance_attribution_for_interval(session, **selection)
    rate = twrr_for_interval(session, **selection)
    return {
        "period": bounds(start, end),
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
        "coupons": metric(reasons=("accepted_income_breakdown_unavailable",), estimate=False),
        "dividends": metric(reasons=("accepted_income_breakdown_unavailable",), estimate=False),
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
                    "pnl": metric(method="PERF04A", **missing),
                    "rate": metric(method="twrr", unit="percentage_points", **missing),
                    "coupons": metric(**missing),
                    "dividends": metric(**missing),
                }
            )
        cursor = following
    return history


def read_overview(session, *, scope, start, end):
    with coherent_read_snapshot(session):
        _validate_scope(session, scope)
        if scope.startswith("source:"):
            view = _source_view(session, scope.removeprefix("source:"), start, end)
        else:
            closed = [m for m in _months(session) if m.status == "closed"]
            history = _accepted_history(session, scope, closed)
            first = closed[0].snapshot_date if closed else None
            last = closed[-1].snapshot_date if closed else None
            whole = (
                _accepted_result(session, scope, first, last) if first and first < last else None
            )
            view = {
                "selected": _accepted_result(session, scope, start, end),
                "all_history": whole,
                "history": history,
                "periods": [r["period"] for r in history] + ([whole["period"]] if whole else []),
                "instruments": [],
                "instrument_reason_codes": ["accepted_instrument_breakdown_unavailable"],
                "proof_status": "not_applicable",
            }
        return {"scope": scope, **view}


def read_detail(session, *, scope, start, end, isin):
    with coherent_read_snapshot(session):
        _validate_scope(session, scope)
        if not scope.startswith("source:"):
            raise ValueError("returns_instrument_scope_unsupported")
        result = read_instrument_returns(
            session,
            source_account=scope.removeprefix("source:"),
            opening_date=start,
            closing_date=end,
            isin=isin,
        )
        if len(result.instruments) != 1:
            raise LookupError("returns_instrument_missing")
        row = result.instruments[0]
        analysis = row.analysis
        return {
            "scope": scope,
            **_instrument(row, start, end),
            "opening_quantity": None
            if analysis.opening.quantity is None
            else str(analysis.opening.quantity),
            "closing_quantity": None
            if analysis.closing.quantity is None
            else str(analysis.closing.quantity),
            "buys": _instrument_metric(analysis.components["buys"]),
            "sells": _instrument_metric(analysis.components["sells"]),
            "conditional_pnl": _instrument_metric(analysis.statement_estimate.pnl),
            "conditional_rate": _instrument_metric(
                analysis.statement_estimate.modified_dietz, unit="fraction"
            ),
            "reason_codes": list(analysis.reason_codes),
            "events": [
                {
                    "ordinal": ordinal,
                    "kind": e.kind,
                    "date": e.event_date,
                    "cash_date": e.cash_settlement_date,
                    "quantity_date": e.depository_settlement_date,
                    "quantity": None if e.quantity_delta is None else str(e.quantity_delta),
                    "amount": metric(
                        e.net_payout_kopecks
                        if e.kind in {"COUPON", "DIVIDEND"}
                        else e.native_trade_amount_kopecks
                    ),
                    "counted": e.counted and e.current,
                }
                for ordinal, e in enumerate(analysis.events)
                if e.event_date is None
                or any(
                    day is not None and start < day <= end
                    for day in (
                        e.event_date,
                        e.cash_settlement_date,
                        e.depository_settlement_date,
                        *(leg.date for leg in e.cash_legs),
                    )
                )
            ],
        }
