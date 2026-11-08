"""AI-only presentation of existing clean-return readers; no return calculator."""

from copy import deepcopy
from decimal import Decimal

from fastapi.encoders import jsonable_encoder

from hermes_finance.services.clean_instrument_return import clean_export_data
from hermes_finance.services.returns_overall import read_clean_instrument_card


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


def review_clean_returns(session, overview, overall, *, account_names, instrument_names):
    """Project names, dated receipts and existing guarded exact-ISIN summaries.

    The source card owns cross-account totals and their exclusion rules. It has
    no multi-account buys/sells aggregate; those fields stay explicitly unknown.
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
    cards = {}
    entries = {}
    for raw, account in zip(overview["accounts"], data["accounts"], strict=True):
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
            if isin not in cards:
                cards[isin] = read_clean_instrument_card(session, isin)
            card_account = next(
                (row for row in cards[isin]["accounts"] if row["scope"] == raw["scope"]), None
            )
            detail = card_account.get("detail") if card_account else None
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
            entries.setdefault(isin, []).append((account, item))

    summaries = []
    for isin, rows in sorted(entries.items()):
        summary = cards[isin]["summary"]
        single = len(rows) == 1
        single = single and not any(
            row.get("exclusion_reason") == "source_account_identity_mapping_conflict"
            for row in cards[isin]["accounts"]
        )
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
                    for account, item in rows
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
