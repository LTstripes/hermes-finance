"""Analytical FIFO over existing clean source events; no journal is persisted."""

import hashlib
from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import (
    clean_trade_assumptions,
    clean_trade_date,
    cost_only_trade,
    trade_amount_with_nkd,
)


def _allocate(amount, weights, keys):
    """Assign integer kopecks proportionally, preserving the exact total."""
    total = sum(weights, Decimal(0))
    if not total:
        return [0] * len(weights) if amount == 0 else None
    raw = [Decimal(amount) * weight / total for weight in weights]
    values = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in raw]
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] - values[i]), keys[i]))
    for index in order[: amount - sum(values)]:
        values[index] += 1
    return values


def _execution(event):
    """Keep date-only facts distinct from actual time; never invent an order."""
    day, instant = event.execution_date, None
    if event.trade_time:
        try:
            value = datetime.fromisoformat(event.trade_time)
        except (ValueError, TypeError):
            return None, None
        if value.tzinfo is not None or (day is not None and day != value.date()):
            return None, None
        day = value.date()
        if "T" in event.trade_time or " " in event.trade_time:
            instant = value.time()
    return day, instant


def _unordered_buys_resolve_as_a_group(group, prefix, by_day):
    """Unordered buys are safe if no sale splits them across transactions."""
    if any(row[0].kind != "BUY" for row in group):
        return False
    with localcontext() as context:
        context.prec = 200
        ahead = sum((row[4] for row in prefix), Decimal(0))
        if ahead < 0:
            return False
        group_quantity = sum((row[4] for row in group), Decimal(0))
        for day in sorted(day for day in by_day if day > group[0][1]):
            sales = [row for row in by_day[day] if row[0].kind == "SELL"]
            instants = [row[2] for row in sales]
            if len(sales) > 1 and (None in instants or len(instants) != len(set(instants))):
                total = sum((-row[4] for row in sales), Decimal(0))
                if total > ahead:
                    return False
                ahead -= total
                continue
            for sale in sorted(sales, key=lambda row: row[2] or datetime.min.time()):
                quantity = -sale[4]
                if quantity <= ahead:
                    ahead -= quantity
                elif quantity - ahead >= group_quantity:
                    return True
                else:
                    return False
        return True


def _observed_purchase_facts(analysis, isin, *, instrument_type):
    """Expose independently supported purchases without inferring FIFO results."""
    identity_counts = defaultdict(int)
    key_counts = defaultdict(int)
    for event in analysis.events:
        if event.native_identity and event.kind in {"BUY", "SELL", "UNRESOLVED"}:
            identity_counts[event.native_identity] += 1
        key_counts[event.event_key] += 1
    rows = []
    for event in analysis.events:
        if (
            event.isin != isin
            or event.kind != "BUY"
            or not event.current
            or not event.native_source_account
            or not event.native_identity
            or identity_counts[event.native_identity] != 1
            or key_counts[event.event_key] != 1
            or not (event.counted and not event.reason_codes or cost_only_trade(event))
        ):
            continue
        if (
            instrument_type == "stock"
            and event.native_total_basis is None
            and event.attribution_basis == "native_money_group_bridge"
            and event.accrued_interest_kopecks in (None, 0)
        ):
            event = replace(event, native_total_basis="excludes_paid_nkd")
        day, _ = _execution(event)
        settlement = clean_trade_date(event)
        quantity = event.quantity_delta
        amount = trade_amount_with_nkd(event)
        if (
            day is None
            or settlement is None
            or event.depository_settlement_date is None
            or quantity is None
            or not quantity.is_finite()
            or quantity <= 0
            or amount is None
            or day > analysis.closing_date
            or not analysis.opening_date < settlement <= analysis.closing_date
            or not analysis.opening_date < event.depository_settlement_date <= analysis.closing_date
            or day > settlement
            or day > event.depository_settlement_date
        ):
            continue
        rows.append(
            {
                "id": hashlib.sha256(event.event_key.encode("utf-8")).hexdigest()[:24],
                "date": day,
                "settlement_date": settlement,
                "quantity": format(quantity, "f"),
                "remaining_quantity": None,
                "cost_kopecks": str(amount),
                "sale_proceeds_kopecks": None,
                "value_kopecks": None,
                "price_result_kopecks": None,
                "return_fraction": None,
                "status": "partial",
                "reason_codes": ["purchase_allocation_unproven", *clean_trade_assumptions(event)],
            }
        )
    return sorted(rows, key=lambda row: (row["date"], row["id"])) or None


def clean_purchase_price_contributions(analysis, clean, isin, *, instrument_type):
    """Return supported FIFO results or independently observed purchase facts."""
    result = _fifo_purchase_price_contributions(
        analysis, clean, isin, instrument_type=instrument_type
    )
    return (
        result
        if result is not None
        else _observed_purchase_facts(analysis, isin, instrument_type=instrument_type)
    )


def _fifo_purchase_price_contributions(analysis, clean, isin, *, instrument_type):
    """FIFO price/sale contributions, exclusive of payouts and all costs.

    A zero opening inventory and complete source/quantity evidence are needed.
    A missing price or valuation affects only the dependent contributions. An
    ambiguous later execution order does not erase already closed purchases.
    """
    if (
        analysis.opening.quantity != 0
        or clean.opening_value.value != 0
        or analysis.closing.quantity is None
        or not analysis.closing.quantity.is_finite()
        or analysis.closing.quantity < 0
    ):
        return None
    coverage = getattr(analysis, "coverage", None)
    repo_barrier = getattr(coverage, "fifo_repo_barrier", None)
    if not coverage or not all(name in coverage for name in ("events", "quantity")):
        return None
    if "source_sections_not_financially_accepted" in getattr(analysis, "reason_codes", ()):
        return None
    # These reasons do not make native trade identity or quantity ambiguous.
    # Any unrelated source gap remains a blocker; it may contain another trade.
    permitted_event_reasons = {"unallocated_instrument_cost", "native_commission_unavailable"}
    if getattr(coverage, "unresolved_cost_only", False):
        permitted_event_reasons.add("unresolved_account_cash_attribution")
    if instrument_type == "stock" and getattr(coverage, "fee_only_bridge", False):
        permitted_event_reasons.add("native_money_cash_bridge_mismatch")
    missing_component_reasons = {"trade_components_missing", "trade_nkd_basis_unknown"}
    for event in analysis.events:
        if event.kind in {"FEE", "TAX"}:
            permitted_event_reasons.update(set(event.reason_codes) & {"cost_sign_conflict"})
            if event.attribution_basis == "explicit_tax_unclassified":
                permitted_event_reasons.add("unrecognized_money")
        if event.isin == isin and event.kind in {"BUY", "SELL"}:
            permitted_event_reasons.update(set(event.reason_codes) & missing_component_reasons)
            if cost_only_trade(event):
                permitted_event_reasons.update(
                    set(event.reason_codes)
                    & {
                        "overlapping_trade_conflict",
                        "overlap_trade_commission_only",
                        "overlap_trade_nkd_only",
                        "trade_money_cash_conflict",
                        "trade_nkd_basis_conflict",
                    }
                )
    from hermes_finance.services.clean_instrument_return import (
        _clean_quantity_reconciled,
        has_unidentified_trade_money,
        instrument_scoped_reasons,
    )

    scoped_events = [event for event in analysis.events if event.isin == isin]
    reconciled = _clean_quantity_reconciled(
        analysis, scoped_events, isin
    ) and not instrument_scoped_reasons(
        analysis,
        isin,
        (set(coverage["events"].reason_codes) | set(coverage["quantity"].reason_codes))
        - permitted_event_reasons,
    )
    event_coverage = coverage["events"]
    if not reconciled and (
        (not event_coverage.complete and not event_coverage.reason_codes)
        or set(event_coverage.reason_codes) - permitted_event_reasons
    ):
        return None
    quantity_coverage = coverage["quantity"]
    permitted_quantity_reasons = {
        "quantity_events_incomplete",
        "quantity_reconciliation_mismatch",
        "cross_boundary_settlement",
    }
    if not reconciled and (
        (not quantity_coverage.complete and not quantity_coverage.reason_codes)
        or set(quantity_coverage.reason_codes) - permitted_quantity_reasons
    ):
        return None
    trades = []
    for event in analysis.events:
        if event.kind in {"FEE", "TAX", "COUPON", "DIVIDEND"}:
            continue
        if event.isin not in {isin, None}:
            continue
        if reconciled and (event.isin is None or event.kind == "UNRESOLVED"):
            continue
        if (
            event.isin != isin
            or event.kind not in {"BUY", "SELL"}
            or not event.current
            or (
                not event.counted
                and (
                    not event.reason_codes
                    or not set(event.reason_codes) <= missing_component_reasons
                )
                and not cost_only_trade(event)
            )
        ):
            return None
        if (
            instrument_type == "stock"
            and event.native_total_basis is None
            and event.attribution_basis == "native_money_group_bridge"
            and event.native_identity is not None
            and event.accrued_interest_kopecks in (None, 0)
        ):
            event = replace(event, native_total_basis="excludes_paid_nkd")
        settlement = clean_trade_date(event)
        amount = trade_amount_with_nkd(event) if event.counted or cost_only_trade(event) else None
        day, instant = _execution(event)
        q = event.quantity_delta
        if (
            q is None
            or not q.is_finite()
            or q == 0
            or (q > 0) != (event.kind == "BUY")
            or day is None
            or settlement is None
            or event.depository_settlement_date is None
            or day > settlement
            or day > event.depository_settlement_date
            or not analysis.opening_date < settlement <= analysis.closing_date
            or not analysis.opening_date < event.depository_settlement_date <= analysis.closing_date
        ):
            return None
        trades.append((event, day, instant, settlement, q, amount))
    if not trades or len({row[0].event_key for row in trades}) != len(trades):
        return None
    with localcontext() as context:
        context.prec = 200
        if (
            repo_barrier is None
            and sum((row[4] for row in trades), Decimal(0)) != analysis.closing.quantity
        ):
            return None
    native_ids = [row[0].native_identity for row in trades if row[0].native_identity]
    if len(native_ids) != len(set(native_ids)):
        return None
    by_day = defaultdict(list)
    for trade in trades:
        by_day[trade[1]].append(trade)
    ordered, ambiguous_at = [], None
    for day in sorted(by_day):
        group = by_day[day]
        instants = [row[2] for row in group]
        ambiguous = len(group) > 1 and (None in instants or len(instants) != len(set(instants)))
        safe_unordered = ambiguous and _unordered_buys_resolve_as_a_group(group, ordered, by_day)
        if ambiguous and not safe_unordered:
            ambiguous_at = len(ordered)
            ordered.extend(sorted(group, key=lambda row: row[0].event_key))
            for later in sorted(d for d in by_day if d > day):
                ordered.extend(sorted(by_day[later], key=lambda row: row[0].event_key))
            break
        ordered.extend(
            sorted(group, key=lambda row: (row[2] or datetime.min.time(), row[0].event_key))
        )
    trades = ordered
    if repo_barrier is not None:
        repo_index = next(
            (
                i
                for i, row in enumerate(trades)
                if max(row[1], row[3], row[0].depository_settlement_date) >= repo_barrier
            ),
            len(trades),
        )
        ambiguous_at = min(ambiguous_at, repo_index) if ambiguous_at is not None else repo_index

    with localcontext() as context:
        context.prec = 200
        lots = []
        buy_sum = sell_sum = 0
        last_sale_day = max((row[1] for row in trades if row[0].kind == "SELL"), default=None)
        for index, (event, day, _instant, settlement, q, amount) in enumerate(trades):
            if ambiguous_at is not None and index >= ambiguous_at:
                if index == ambiguous_at:
                    for lot in lots:
                        if lot["remaining"]:
                            lot["remaining"] = None
                            if repo_barrier is None or any(
                                t[0].kind == "SELL" for t in trades[index:]
                            ):
                                lot["proceeds"] = None
                if event.kind == "BUY":
                    untouched = repo_barrier is None and (
                        last_sale_day is None or day > last_sale_day
                    )
                    lots.append(
                        {
                            "key": event.event_key,
                            "date": day,
                            "settlement": settlement,
                            "quantity": q,
                            "remaining": q if untouched else None,
                            "cost": amount,
                            "proceeds": 0 if untouched else None,
                            "assumptions": set(clean_trade_assumptions(event)),
                        }
                    )
                continue
            if event.kind == "BUY":
                lots.append(
                    {
                        "key": event.event_key,
                        "date": day,
                        "settlement": settlement,
                        "quantity": q,
                        "remaining": q,
                        "cost": amount,
                        "proceeds": 0,
                        "assumptions": set(clean_trade_assumptions(event)),
                    }
                )
                if amount is not None:
                    buy_sum += amount
                continue
            if amount is not None:
                sell_sum += amount
            pending = -q
            consumed = []
            for lot in lots:
                part = min(pending, lot["remaining"])
                if part > 0:
                    consumed.append((lot, part))
                    pending -= part
                if pending == 0:
                    break
            if pending != 0:
                return None
            shares = (
                _allocate(
                    amount, [part for _, part in consumed], [lot["key"] for lot, _ in consumed]
                )
                if amount is not None
                else [None] * len(consumed)
            )
            for (lot, part), share in zip(consumed, shares, strict=True):
                lot["remaining"] -= part
                lot["assumptions"].update(clean_trade_assumptions(event))
                lot["proceeds"] = (
                    lot["proceeds"] + share
                    if lot["proceeds"] is not None and share is not None
                    else None
                )
        if repo_barrier is not None and ambiguous_at == len(trades):
            for lot in lots:
                if lot["remaining"]:
                    lot["remaining"] = None
        if (
            not lots
            or (
                ambiguous_at is None
                and sum((lot["remaining"] for lot in lots), Decimal(0)) != analysis.closing.quantity
            )
            or (
                ambiguous_at is None
                and clean.buys.status == "supported"
                and buy_sum != clean.buys.value
            )
            or (
                ambiguous_at is None
                and clean.sells.status == "supported"
                and sell_sum != clean.sells.value
            )
        ):
            return None
        valuation = clean.closing_value.value if clean.closing_value.status == "supported" else None
        if valuation is not None and valuation < 0:
            return None
        if valuation is not None and ambiguous_at is None:
            values = _allocate(
                valuation, [lot["remaining"] for lot in lots], [lot["key"] for lot in lots]
            )
        else:
            values = []
            for lot in lots:
                remaining = lot["remaining"]
                if remaining == 0:
                    values.append(0)
                elif valuation is not None and remaining is not None and analysis.closing.quantity:
                    share = Decimal(valuation) * remaining / analysis.closing.quantity
                    values.append(int(share) if share == share.to_integral_value() else None)
                else:
                    values.append(None)
        if values is None:
            return None
        results = []
        for lot, value in zip(lots, values, strict=True):
            result = (
                value + lot["proceeds"] - lot["cost"]
                if value is not None and lot["proceeds"] is not None and lot["cost"] is not None
                else None
            )
            reasons = []
            if lot["remaining"] is None:
                reasons.append(
                    "repo_custody_unproven" if repo_barrier is not None else "fifo_order_ambiguous"
                )
            if lot["cost"] is None:
                reasons.append("purchase_amount_unknown")
            if lot["proceeds"] is None:
                reasons.append("sale_proceeds_unknown")
            if value is None:
                reasons.append("closing_value_unknown")
            reasons.extend(sorted(lot["assumptions"]))
            results.append(
                {
                    "id": hashlib.sha256(lot["key"].encode("utf-8")).hexdigest()[:24],
                    "date": lot["date"],
                    "settlement_date": lot["settlement"],
                    "quantity": format(lot["quantity"], "f"),
                    "remaining_quantity": format(lot["remaining"], "f")
                    if lot["remaining"] is not None
                    else None,
                    "cost_kopecks": str(lot["cost"]) if lot["cost"] is not None else None,
                    "sale_proceeds_kopecks": str(lot["proceeds"])
                    if lot["proceeds"] is not None
                    else None,
                    "value_kopecks": str(value) if value is not None else None,
                    "price_result_kopecks": str(result) if result is not None else None,
                    "return_fraction": format(Decimal(result) / Decimal(lot["cost"]), "f")
                    if result is not None and lot["cost"]
                    else None,
                    "status": "supported"
                    if result is not None and not lot["assumptions"]
                    else "partial",
                    "reason_codes": reasons,
                }
            )
        if (
            all(row["price_result_kopecks"] is not None for row in results)
            and clean.valuation_and_trades.value is not None
            and sum(int(row["price_result_kopecks"]) for row in results)
            != clean.valuation_and_trades.value
        ):
            return None
        if has_unidentified_trade_money(analysis):
            for row in results:
                row["status"] = "partial"
                row["reason_codes"] = sorted({*row["reason_codes"], "account_money_unattributed"})
        return results
