"""Extend a current source history with disjoint calendar-month observations.

This is an ephemeral account projection, never a new proof or ledger. Rates are
recomputed from outer values and dated flows by the existing Dietz kernel.
"""

from datetime import date, timedelta

from hermes_finance.domain.monthly_return_chain import calculate_interval_return

CONTRACT = "source_account_history_v1"


def latest_history(reports):
    latest = {}
    for report in reports:
        key = (report.get("covered_from"), report.get("covered_to"))
        if key not in latest or report.get("proof_id", 0) > latest[key].get("proof_id", 0):
            latest[key] = report
    reports = list(latest.values())
    reliable = [
        p
        for p in reports
        if p.get("status") == "current"
        and p.get("interval")
        and p["interval"].get("pnl", {}).get("value") is not None
    ]
    if reliable:
        earliest = min(p["covered_from"] for p in reliable)
        return max(
            (p for p in reliable if p["covered_from"] == earliest),
            key=lambda p: (p["covered_to"], p["proof_id"]),
        )
    return max(
        (p for p in reports if p["history_from_zero"]),
        key=lambda p: (p["covered_to"], p["proof_id"]),
        default=None,
    )


def extend_history(proof, monthly, *, through=None):
    if proof is None:
        return None
    end = date.fromisoformat(proof["covered_to"])
    tail = sorted(
        (
            row
            for row in monthly.months
            if row.result.closing_date > end
            and (through is None or row.result.closing_date <= through)
        ),
        key=lambda row: (row.result.opening_date, row.result.closing_date),
    )
    if not tail:
        return proof
    # The full validated projection supplies dated flows even when the caller
    # requested the account-only index. Never rebuild them from aggregate totals.
    complete = next(
        (p for p in monthly.investment_reports if p["proof_id"] == proof["proof_id"]), proof
    )
    raw = complete["interval"] if complete["status"] == "current" else None
    if raw is None:
        return {
            **proof,
            "covered_to": str(tail[-1].result.closing_date),
            "derived_history": True,
            "status": complete["status"],
            "reason_codes": sorted(set(complete["reason_codes"]) | {"history_base_unavailable"}),
            "interval": None,
        }
    start = date.fromisoformat(proof["covered_from"]) - timedelta(days=1)
    reasons = set(proof["reason_codes"])
    blockers = set()
    valuation_only = {"missing_endpoint", "economic_endpoint_unavailable"}
    if raw["pnl"]["value"] is None and not (
        raw["opening_kopecks"] is not None
        and raw["closing_kopecks"] is None
        and not set(raw["reason_codes"]) - valuation_only
    ):
        blockers.add("history_base_unavailable")
    flows = list(raw.get("external_flows", ()))
    reasons.update(raw["reason_codes"])
    if "external_flows" not in raw:
        blockers.add("history_flow_schedule_unavailable")
    cursor = end
    previous = raw["closing_kopecks"]
    coupons = raw["coupons_kopecks"]
    dividends = raw["dividends_kopecks"]
    for row in tail:
        r = row.result
        if r.opening_date != cursor:
            blockers.add("history_interval_gap_or_overlap")
        if (
            previous is not None
            and r.opening_kopecks is not None
            and int(previous) != r.opening_kopecks
        ):
            blockers.add("history_seam_mismatch")
        reasons.update(r.reason_codes)
        reasons.update(row.flags)
        # An interior valuation is unnecessary for outer cash economics. Keep
        # every non-valuation failure and independently validate dated flows.
        allowed_missing = {"missing_endpoint", "missing_month_endpoint", "history_seam_unavailable"}
        if r.growth_kopecks is None and (set(r.reason_codes) | set(row.flags)) - allowed_missing:
            blockers.add("history_month_unavailable")
        matching = [
            p
            for p in monthly.investment_reports
            if p["covered_from"] == str(r.opening_date + timedelta(days=1))
            and p["covered_to"] == str(r.closing_date)
        ]
        if matching:
            chosen = max(matching, key=lambda p: p["proof_id"])
            interval = chosen["interval"] if chosen["status"] == "current" else None
            additions = [] if interval is None else interval.get("external_flows", [])
        else:
            additions = [
                {
                    "date": str(f.event_date),
                    "amount_kopecks": str(f.amount_kopecks),
                    "status": f.status,
                }
                for f in monthly.flows
                if f.included and r.opening_date < f.event_date <= r.closing_date
            ]
        if not _schedule_matches(additions, r.contributions_kopecks, r.withdrawals_kopecks):
            blockers.add("history_flow_schedule_unavailable")
        flows.extend(additions)
        coupons = _add_known(coupons, row.coupons_kopecks)
        dividends = _add_known(dividends, row.dividends_kopecks)
        cursor, previous = r.closing_date, r.closing_kopecks
    if not _schedule_matches(
        raw.get("external_flows", []), raw["contributions_kopecks"], raw["withdrawals_kopecks"]
    ):
        blockers.add("history_flow_schedule_unavailable")
    reasons.update(blockers)
    opening = None if raw["opening_kopecks"] is None else int(raw["opening_kopecks"])
    schedule = [
        (date.fromisoformat(f["date"]), int(f["amount_kopecks"]), f["status"]) for f in flows
    ]
    # Windows are disjoint (opening, closing]; a seam-day occurrence belongs to
    # the earlier interval once. Same-day distinct occurrences remain distinct.
    if any(not start < day <= cursor for day, _, _ in schedule):
        blockers.add("history_flow_outside_interval")
        reasons.update(blockers)
    result = calculate_interval_return(
        (start, opening),
        (cursor, previous),
        schedule if not blockers else [(cursor, 0, "unknown")],
    )
    if "history_interval_gap_or_overlap" in blockers:
        coupons = dividends = None
    codes = sorted(reasons | set(result.reason_codes))
    return {
        **proof,
        "covered_to": str(cursor),
        "derived_history": True,
        "reason_codes": codes,
        "interval": {
            "opening_kopecks": opening,
            "closing_kopecks": previous,
            "contributions_kopecks": result.contributions_kopecks,
            "withdrawals_kopecks": result.withdrawals_kopecks,
            "coupons_kopecks": coupons,
            "dividends_kopecks": dividends,
            "pnl": _metric(result.growth_kopecks, codes),
            "modified_dietz": _metric(result.modified_dietz_return, codes, method="modified_dietz"),
            "known_subtotal": _metric(None, ["source_method_not_available"]),
            "xirr_annualized": _metric(
                None, ["source_method_not_available"], method="xirr", annualized=True
            ),
            "xirr_period": _metric(
                None, ["source_method_not_available"], method="money_weighted_period"
            ),
            "external_flows": flows,
            "account_only": [],
            "instruments": [],
            "income_reason_codes": {k: codes for k in ("coupons", "dividends")},
            "reason_codes": codes,
        },
    }


def _add_known(left, right):
    return None if left is None or right is None else int(left) + int(right)


def _schedule_matches(flows, contributions, withdrawals):
    if contributions is None or withdrawals is None or any(f["status"] == "unknown" for f in flows):
        return False
    incoming = sum(int(f["amount_kopecks"]) for f in flows if int(f["amount_kopecks"]) > 0)
    outgoing = -sum(int(f["amount_kopecks"]) for f in flows if int(f["amount_kopecks"]) < 0)
    return incoming == int(contributions) and outgoing == int(withdrawals)


def _metric(value, reasons, *, method="source_cash_economics", annualized=False):
    return {
        "value": None if value is None else str(value),
        "status": "unavailable" if value is None else ("partial" if reasons else "provisional"),
        "reason_codes": list(reasons),
        "method": method,
        "annualized": annualized,
        "approximate": True,
    }
