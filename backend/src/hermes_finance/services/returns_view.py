"""Read-only presentation composition. The existing readers own every return.

No financial writes, providers or persisted presentation cache. On-demand detail
retains the existing v2 analysis and provenance; overview remains compact.
Money crosses this boundary as integer-minor-unit strings, including large values.
"""

import json
from datetime import date, timedelta

from sqlalchemy import select

from hermes_finance.domain import PerformanceScope
from hermes_finance.persistence import (
    Account,
    BrokerIdentityMapping,
    Instrument,
    ReportingMonth,
    SourceIntakeOriginal,
)
from hermes_finance.services.performance_attribution import performance_attribution_for_interval
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.source_instrument_returns import read_instrument_returns
from hermes_finance.services.source_monthly_returns import (
    _native_scope,
    _selected_sources,
    read_monthly_returns,
    source_read_snapshot,
)
from hermes_finance.statement_import.mybroker import PROVIDER


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
    selections = {a: _selected_sources(session, a) for a in aliases}
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
            and _native_scope(view["document"]) == {target}
            and alias in {target, view["document"]["filename_account"]}
            for _, view, error in selected
        ):
            canonical[alias] = target
    # Never follow an alias chain.
    return {a: target if canonical[target] == target else a for a, target in canonical.items()}


def _accounts(session, canonical=None):
    canonical = _source_scopes(session) if canonical is None else canonical
    labels = {}
    for alias, account_id, name in session.execute(
        select(BrokerIdentityMapping.provider_identity, Account.id, Account.name)
        .join(Account, Account.id == BrokerIdentityMapping.hermes_account_id)
        .where(
            BrokerIdentityMapping.provider == PROVIDER,
            BrokerIdentityMapping.subject_kind == "account",
            BrokerIdentityMapping.status == "effective",
        )
    ):
        if alias in canonical:
            labels.setdefault(canonical[alias], set()).add((account_id, name))
    return (
        [
            {
                "id": f"source:{a}",
                "label": f"{next(iter(labels[a]))[1]} · {a}" if len(labels.get(a, ())) == 1 else a,
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
        for periods in source_periods.values():
            periods[:] = list({(p["start"], p["end"]): p for p in periods}.values())
            periods.append(bounds(min(p["start"] for p in periods), max(p["end"] for p in periods)))
        return {
            "accounts": _accounts(session, canonical),
            "scope_aliases": {f"source:{a}": f"source:{b}" for a, b in canonical.items() if a != b},
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


def _display_name(name, isin):
    name = (name or "").strip()
    return name if name and name.upper() != isin.upper() else None


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
    names = _catalogue_names(session, instruments.instruments)
    return {
        "selected": selected,
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
            view = {
                "selected": _accepted_result(session, scope, start, end),
                "all_history": whole,
                "available_months_total": None,
                "selected_available_months_total": None,
                "history": history,
                "periods": [r["period"] for r in history] + ([whole["period"]] if whole else []),
                "instruments": [],
                "instrument_reason_codes": ["accepted_instrument_breakdown_unavailable"],
                "proof_status": "not_applicable",
            }
        return {"scope": scope, **view}


def read_detail(session, *, scope, start, end, isin):
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
        )
        if len(result.instruments) != 1:
            raise LookupError("returns_instrument_missing")
        row = result.instruments[0]
        analysis = row.analysis
        return {
            "scope": scope,
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
