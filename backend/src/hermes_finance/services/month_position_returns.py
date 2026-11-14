"""Read-only dated clean results for statement positions, without changing snapshots."""

from collections import defaultdict

from hermes_finance.persistence import Instrument, ReportingMonth
from hermes_finance.services.clean_instrument_return import read_clean_account
from hermes_finance.services.returns_view import read_context


def month_position_returns(session, month_id, positions):
    native = [row for row in positions if row.price_source == "broker_statement_native"]
    if not native:
        return {}
    month = session.get(ReportingMonth, month_id)
    end = month.snapshot_date if month is not None else None

    def unavailable(reason, start=None):
        return {
            "amount_kopecks": None,
            "as_of": end,
            "period_start": start,
            "status": "unavailable",
            "reason_codes": [reason],
        }

    if end is None:
        return {row.id: unavailable("snapshot_date_required") for row in native}
    try:
        context = read_context(session)
    except (ValueError, LookupError):
        return {row.id: unavailable("source_history_unavailable") for row in native}
    sources = defaultdict(list)
    for account in context["accounts"]:
        link = account.get("account_link")
        if link and link["status"] == "linked":
            sources[link["financial_account_id"]].append(account["id"])
    results = {}
    for account_id in {row.account_id for row in native}:
        rows = [row for row in native if row.account_id == account_id]
        scopes = sources[account_id]
        if len(scopes) != 1:
            results.update(
                {row.id: unavailable("source_account_mapping_unavailable") for row in rows}
            )
            continue
        scope = scopes[0]
        history = context["source_history_periods"].get(scope)
        if history is None or history["start"] >= end:
            results.update({row.id: unavailable("source_history_unavailable") for row in rows})
            continue
        start = history["start"]
        # Navigation metadata alone grants no availability. The existing reader
        # checks source proofs and each instrument's financial operands.
        try:
            view = read_clean_account(session, scope.removeprefix("source:"), start, end)
        except (ValueError, LookupError):
            results.update(
                {row.id: unavailable("instrument_result_unavailable", start) for row in rows}
            )
            continue
        instruments = defaultdict(list)
        for item in view["instruments"]:
            instruments[item["isin"]].append(item)
        for row in rows:
            instrument = session.get(Instrument, row.instrument_id)
            matches = instruments[instrument.isin] if instrument and instrument.isin else []
            if len(matches) != 1:
                results[row.id] = unavailable("instrument_result_unavailable", start)
                continue
            item = matches[0]
            if item["closing_date"] != end or row.price_date != end:
                results[row.id] = unavailable("position_result_date_mismatch", start)
                continue
            metric = item["pnl"]
            known = metric["value"] is not None and metric["status"] in {"supported", "provisional"}
            results[row.id] = {
                "amount_kopecks": int(metric["value"]) if known else None,
                "as_of": end,
                "period_start": start,
                "status": metric["status"],
                "reason_codes": list(
                    dict.fromkeys([*metric["reason_codes"], *metric["assumptions"]])
                ),
            }
    return results
