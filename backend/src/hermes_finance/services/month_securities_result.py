"""Same-period clean securities subtotal; never account economics or a portfolio rate."""

import calendar
from datetime import date, timedelta

from hermes_finance.services.clean_instrument_return import read_clean_account
from hermes_finance.services.returns_view import read_context
from hermes_finance.services.source_monthly_returns import source_read_snapshot


def month_securities_result(session, month):
    with source_read_snapshot(session):
        return _month_securities_result(session, month)


def _month_securities_result(session, month):
    end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
    start = end.replace(day=1) - timedelta(days=1)
    result = {
        "amount_kopecks": None,
        "period_start": start,
        "as_of": end,
        "status": "unavailable",
        "reason_codes": [],
        "included_count": 0,
        "total_count": 0,
    }
    if month.snapshot_date != end:
        return {**result, "reason_codes": ["month_end_snapshot_required"]}
    try:
        accounts = [a for a in read_context(session)["accounts"] if a["basis"] == "statements"]
    except (ValueError, LookupError):
        return {**result, "reason_codes": ["month_instrument_results_unavailable"]}
    ids = [a["account_link"]["financial_account_id"] for a in accounts if a.get("account_link")]
    values = []
    reasons = []
    missing = False
    provisional = False
    for account in accounts:
        link = account.get("account_link")
        if not link or link["status"] != "linked" or ids.count(link["financial_account_id"]) != 1:
            missing = True
            reasons.append("source_account_mapping_unavailable")
            continue
        try:
            view = read_clean_account(session, account["id"].removeprefix("source:"), start, end)
        except (ValueError, LookupError):
            missing = True
            reasons.append("month_instrument_results_unavailable")
            continue
        if view.get("gaps"):
            missing = True
            reasons.extend(gap["code"] for gap in view["gaps"])
        rows = view["instruments"]
        if not rows:
            missing = True
            reasons.append("month_instrument_results_unavailable")
        for item in rows:
            result["total_count"] += 1
            metric = item["pnl"]
            if item["opening_date"] != start or item["closing_date"] != end:
                missing = True
                reasons.append("instrument_result_date_mismatch")
                continue
            reasons.extend([*metric["reason_codes"], *metric["assumptions"]])
            if metric["value"] is None or metric["status"] not in {"supported", "provisional"}:
                missing = True
                continue
            values.append(int(metric["value"]))
            provisional |= metric["status"] == "provisional"
    if values:
        result.update(
            amount_kopecks=sum(values),
            included_count=len(values),
            status="partial" if missing else "provisional" if provisional else "supported",
        )
    else:
        reasons.append("month_instrument_results_unavailable")
    result["reason_codes"] = list(dict.fromkeys(reasons))
    return result
