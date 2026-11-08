"""AI-only presentation of existing clean-return readers; no return calculator."""

from copy import deepcopy
from decimal import Decimal

from fastapi.encoders import jsonable_encoder

from hermes_finance.services import returns_view
from hermes_finance.services.clean_instrument_return import clean_export_data
from hermes_finance.services.returns_overall import (
    _account_result_notes,
    _accounts_have_full_result,
    _source_accounts,
)
from hermes_finance.services.source_instrument_returns import read_instrument_returns


def _unknown(reason):
    return {
        "value": None,
        "status": "unknown",
        "reason_codes": [reason],
        "assumptions": [],
    }


def _split(item, detail, *, conflicted):
    # A proved empty endpoint makes the entire supported result realized.
    quantity = detail.get("closing_quantity") if detail else None
    closed = quantity is not None and Decimal(quantity) == 0
    known = (
        closed
        and not conflicted
        and item["pnl"]["value"] is not None
        and item["pnl"]["status"] in {"supported", "provisional"}
    )
    return {
        "position_state": "closed" if closed else "open" if quantity is not None else "unknown",
        "status": "known" if known else "unknown",
        "realized_result": deepcopy(item["pnl"]) if known else _unknown("split_not_provided"),
        "unrealized_result": {
            **deepcopy(item["pnl"]),
            "value": "0",
        }
        if known
        else _unknown("split_not_provided"),
    }


def _payments(detail, *, isin, account_ref, account_name):
    if not detail:
        return []
    analysis = detail["analysis"]
    rows = []
    for event in analysis.events:
        if (
            event.isin != isin
            or event.kind not in {"COUPON", "DIVIDEND", "REDEMPTION"}
            or not event.current
            or not event.counted
        ):
            continue
        for leg in event.cash_legs:
            if not analysis.opening_date < leg.date <= analysis.closing_date:
                continue
            rows.append(
                {
                    "date": leg.date,
                    "amount_kopecks": str(leg.account_cash_kopecks),
                    "kind": event.kind.lower(),
                    "account_ref": account_ref,
                    "account_name": account_name,
                    "source": event.provider,
                    "reason_codes": list(event.reason_codes),
                    "assumptions": list(event.assumptions),
                }
            )
    # Do not deduplicate by date/amount: equal credited operations can be distinct.
    return sorted(rows, key=lambda row: (row["date"], row["kind"], row["amount_kopecks"]))


def _account_details(session, account, *, clean_projection=True, native_period=True):
    """Read all exact-ISIN analyses together, using the clean card's reader flags."""
    if not account["result"]["instruments"]:
        return {}
    period = account["period"]
    try:
        result = read_instrument_returns(
            session,
            source_account=account["scope"].removeprefix("source:"),
            opening_date=period["start"],
            closing_date=period["end"],
            include_monthly_history=False,
            available_period=native_period,
            clean_projection=clean_projection,
        )
    except (ValueError, LookupError):
        return {}
    return {
        row.isin: {
            "analysis": row.analysis,
            "closing_quantity": None
            if row.analysis.closing.quantity is None
            else str(row.analysis.closing.quantity),
        }
        for row in result.instruments
        if row.analysis is not None
    }


def _isin_totals(rows, *, conflicts, legacy_detail):
    """Copy one account's ready metrics; never recompute cross-account totals."""
    if len(rows) != 1:
        reason = "cross_account_clean_totals_not_provided"
        return {
            **{
                key: returns_view.metric(reasons=(reason,), estimate=False)
                for key in ("reported_value", "redemption", "payouts", "pnl")
            },
            "partial": True,
            "reason_codes": [reason],
        }
    _, item, original, scope = rows[0]
    accounts = [{"scope": scope, "clean": original}]
    whole = _accounts_have_full_result(accounts, conflicts)
    notes = _account_result_notes(accounts)

    def copied(field):
        if scope in conflicts:
            return returns_view.metric(
                reasons=("source_account_identity_mapping_conflict",), estimate=False
            )
        value = original[field]["value"]
        complete = whole and value is not None
        return returns_view.metric(
            None if value is None else int(value),
            reasons=notes if complete else ("clean_partial_result", *notes),
            method="known_clean_instruments",
            estimate=not complete or bool(notes),
        )

    reasons = ["known_instrument_accounts_only"]
    if not whole:
        # The card retains its ordinary endpoint's coverage notes when its clean
        # result is partial, including stale/unavailable ordinary history. Reuse
        # its source index and batch details by account/period, never by ISIN.
        detail = None if scope in conflicts else legacy_detail(scope, item["isin"])
        if scope in conflicts or detail is None or detail["closing_quantity"] is None:
            reasons.append("instrument_accounts_missing_or_excluded")
    return {
        "reported_value": copied("closing_value"),
        "redemption": copied("redemption"),
        "payouts": copied("payouts"),
        "pnl": copied("known_result"),
        "partial": not whole,
        "reason_codes": notes if whole else reasons,
    }


def review_clean_returns(session, overview, overall, *, account_names, instrument_names):
    """Project names, dated receipts and existing guarded exact-ISIN summaries.

    Single-account summaries copy ready clean metrics with the card's result
    guards. Cross-account totals stay unknown rather than adding a second sum.
    """
    conflicts = {
        row["id"]
        for row in overall["mixed_result"]["components"]
        if row.get("exclusion_reason") == "source_account_identity_mapping_conflict"
    }
    data = clean_export_data(
        overview, gold=overall["gold"], include_purchases=True, purchase_conflicts=conflicts
    )
    data["schema_version"] = "1.2.0"
    data["units"].pop("modified_dietz")
    data["reading_guide"] = {
        "scope": "Current available history; every account keeps its own dates. Invested means observed-period purchases with NKD, excluding fees; it is not acquisition cost of opening holdings.",
        "counting": "ISIN summaries, account rows, purchases and payments explain the same result; do not add them together. Redemption is principal, not coupon/dividend income.",
        "rates": "Purchase return_fraction is simple price result on purchase cost, excludes payouts and is not annualized. Fractions use 1 = 100%, 0.1 = 10%. Position Modified Dietz is omitted; only account calendar-month totals may use it. Position XIRR is not available from the backend.",
        "split": "Realized/unrealized split is unknown unless the backend proves a closed position with a known result. Do not infer a split from sales or FIFO lots.",
        "gold": "Gold histories and saved snapshots can overlap; snapshots are not extra profit. Clean gold split remains unknown.",
    }
    sources = {row["scope"]: row for row in overall["source_accounts"]}
    raw_accounts = {row["scope"]: row for row in overview["accounts"]}
    legacy_index = None
    legacy_sources = {}
    legacy_batches = {}

    def legacy_detail(scope, isin):
        nonlocal legacy_index
        if legacy_index is None:
            sources, instruments, _ = _source_accounts(
                session, include_instrument_details=False, defer_history_proof_xirr=True
            )
            legacy_sources.update((row["scope"], row) for row in sources)
            legacy_index = {
                (row["scope"], instrument["isin"]): row
                for instrument in instruments
                for row in instrument["accounts"]
            }
        indexed = legacy_index.get((scope, isin))
        if not indexed or not indexed.get("period"):
            return None
        native = indexed.get("native_period", False)
        if legacy_sources[scope]["proof_status"] != "current" and not native:
            return None
        period = indexed["period"]
        key = (scope, period["start"], period["end"], native)
        if key not in legacy_batches:
            legacy_batches[key] = _account_details(
                session,
                {**raw_accounts[scope], "period": period},
                clean_projection=False,
                native_period=native,
            )
        return legacy_batches[key].get(isin)

    entries = {}
    for raw, account in zip(overview["accounts"], data["accounts"], strict=True):
        account_details = _account_details(session, raw)
        link = sources.get(raw["scope"], {}).get("account_link") or {}
        account["account_name"] = {
            "iis": "ИИС",
            "brokerage": "Брокерский",
        }.get(link.get("account_type"), "Счёт не сопоставлен")
        account["account_type"] = link.get("account_type")
        account["mapping_status"] = link.get("status", "unlinked")
        account["mapping_reason_codes"] = list(link.get("reason_codes", []))
        for original, item in zip(
            raw["result"]["instruments"], account["instruments"], strict=True
        ):
            isin = item["isin"]
            item["name"] = original["name"] or isin
            # This metric is not a position comparison measure.
            item.pop("modified_dietz")
            detail = account_details.get(isin)
            item["result_split"] = _split(item, detail, conflicted=raw["scope"] in conflicts)
            item["actual_payments"] = _payments(
                detail,
                isin=isin,
                account_ref=account["account_ref"],
                account_name=account["account_name"],
            )
            item["payment_coverage"] = {
                "status": "partial" if detail else "unknown",
                "reason_codes": ["source_observed_payments_not_complete_ledger"]
                if detail
                else ["instrument_history_detail_unavailable"],
            }
            for purchase in item.get("purchases") or []:
                purchase["return_context"] = {
                    "method": "simple_on_invested",
                    "label": "Простой результат цены на сумму покупки, без выплат",
                    "basis": "sale_proceeds_plus_remaining_value_minus_purchase_cost_over_purchase_cost",
                    "base_kopecks": purchase["cost_kopecks"],
                    "start_date": purchase["date"],
                    "end_date": item["closing_date"],
                    "annualized": False,
                    "unit": "fraction",
                }
            entries.setdefault(isin, []).append((account, item, original, raw["scope"]))

    summaries = []
    for isin, rows in sorted(entries.items()):
        summary = _isin_totals(rows, conflicts=conflicts, legacy_detail=legacy_detail)
        single = len(rows) == 1
        summaries.append(
            {
                "isin": isin,
                "name": rows[0][1]["name"],
                "source": "returns_instrument_card_v2",
                "invested_basis": "observed_period_purchases_with_nkd_excluding_fees",
                "accounts": [
                    {
                        "account_ref": account["account_ref"],
                        "account_name": account["account_name"],
                        "period": account["period"],
                        "invested": item["buys"],
                        "sales": item["sells"],
                    }
                    for account, item, _, _ in rows
                ],
                "invested": deepcopy(rows[0][1]["buys"])
                if single
                else _unknown("cross_account_invested_total_not_provided"),
                "sales": deepcopy(rows[0][1]["sells"])
                if single
                else _unknown("cross_account_sales_total_not_provided"),
                "current_value": deepcopy(summary["reported_value"]),
                "redemptions": deepcopy(summary["redemption"]),
                "payouts": deepcopy(summary["payouts"]),
                "total_result": deepcopy(summary["pnl"]),
                "partial": summary["partial"] or not single,
                "reason_codes": list(summary["reason_codes"])
                + ([] if single else ["cross_account_invested_and_sales_totals_not_provided"]),
                "split_status": "unknown",
            }
        )
    data["isin_summary"] = summaries
    for row, original in zip(data["gold"], overall["gold"]["histories"], strict=True):
        row["name"] = instrument_names.get(original["instrument_id"], "Золото")
        row["account_name"] = account_names.get(original["account_id"], "Счёт золота")
        row["split_status"] = "unknown"
    data["gold_snapshots"] = [
        {
            "name": instrument_names.get(row["instrument_id"], "Золото"),
            "account_name": account_names.get(row["account_id"], "Счёт золота"),
            "valuation_date": row["date"],
            "quantity": row["quantity"],
            "current_value": deepcopy(row["market_value"]),
            "cost_basis": deepcopy(row["cost_basis"]),
            "split_status": "unknown",
            "source": "saved_snapshot",
        }
        for row in overall["gold"]["snapshots"]
    ]
    return jsonable_encoder(data)
