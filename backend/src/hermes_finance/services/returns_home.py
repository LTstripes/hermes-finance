"""Compact Home projection over the same eligible clean amounts as Returns.

Home has no position rates, FIFO decomposition or purchase rows. Its existing
known-subtotal and equal-period comparison rules are preserved explicitly.
"""

from hermes_finance.services.returns_overall import read_clean_overall


def _unknown():
    return {
        "value": None,
        "reason_codes": [],
        "method": "",
        "unit": "kopecks",
        "estimate": False,
    }


def _known_money(values):
    known = [value for value in values if value["value"] is not None]
    return {
        "value": str(sum(int(value["value"]) for value in known)) if known else None,
        "reason_codes": list(
            dict.fromkeys(
                [reason for value in values for reason in value["reason_codes"]]
                + (["selected_components_incomplete"] if len(known) != len(values) else [])
            )
        ),
        "method": "known_nonoverlapping_components",
        "unit": "kopecks",
        "estimate": any(value["estimate"] for value in known),
    }


def _periods(rows):
    return {(row["period"]["start"], row["period"]["end"]) for row in rows if row.get("period")}


def summarize_home(data):
    components = [
        row
        for row in data["mixed_result"]["components"]
        if row["category"] in {"brokerage", "iis", "brokerage_iis"}
    ]
    eligible = [row for row in components if row["included"]]
    multiple = len(_periods(eligible)) > 1
    rows = []
    periods = set()
    for instrument in data["instruments"]:
        accounts = instrument["accounts"]
        values = [row for row in accounts if row["native_period"] and row["details_loaded"]]
        unsafe = len(_periods(values)) > 1 or (
            len(values) > 1
            and any(
                component["id"] == account["scope"]
                and component["coverage"]["status"] == "conflict"
                for account in values
                for component in components
            )
        )
        amount = _unknown() if unsafe else _known_money([row["pnl"] for row in values])
        if len(values) != len(accounts) and amount["value"] is not None:
            amount["estimate"] = True
            amount["reason_codes"] = list(
                dict.fromkeys([*amount["reason_codes"], "selected_components_incomplete"])
            )
        if amount["value"] is not None:
            periods.update(_periods(values))
        rows.append(
            {
                "isin": instrument["isin"],
                "name": instrument["name"],
                "pnl": amount,
                "accounts": [
                    {key: account[key] for key in ("scope", "label", "account_link")}
                    for account in accounts
                ],
            }
        )
    known = [
        row
        for row in rows
        if row["pnl"]["value"] is not None
        and not {"clean_partial_result", "selected_components_incomplete"}.intersection(
            row["pnl"]["reason_codes"]
        )
    ]
    positive = [row for row in known if int(row["pnl"]["value"]) > 0]
    negative = [row for row in known if int(row["pnl"]["value"]) < 0]
    return {
        "contract_version": "returns_home_summary_v1",
        "result": {
            "amount": _unknown() if multiple else _known_money([row["amount"] for row in eligible]),
            "partial": multiple
            or any(
                not row["included"] or row["amount"]["value"] is None or row["amount"]["estimate"]
                for row in components
            ),
        },
        "positive": len(positive),
        "negative": len(negative),
        "unknown": len(rows) - len(known),
        "unchanged": len(known) - len(positive) - len(negative),
        "mixed_periods": len(periods) > 1,
        "ranked": (
            sorted(positive, key=lambda row: -int(row["pnl"]["value"]))[:3]
            + sorted(negative, key=lambda row: int(row["pnl"]["value"]))[:3]
            if len(periods) == 1
            else []
        ),
    }


def read_home_summary(session):
    return summarize_home(
        read_clean_overall(session, include_instrument_details=True, home_summary=True)
    )
