"""Analytical FIFO over existing clean source events; no journal is persisted."""

import hashlib
from collections import Counter
from dataclasses import replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import (
    clean_trade_amount,
    clean_trade_date,
    cost_only_trade,
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


def clean_purchase_price_contributions(analysis, clean, isin, *, instrument_type):
    """FIFO price/sale contributions, exclusive of payouts and all costs.

    Complete clean trade and quantity coverage, a zero opening inventory, and
    unique execution order are required. In ambiguous cases the events remain
    visible elsewhere but individual returns are withheld.
    """
    if (
        analysis.opening.quantity != 0
        or clean.opening_value.value != 0
        or clean.closing_value.value is None
        or clean.closing_value.status != "supported"
        or clean.buys.status != "supported"
        or clean.sells.status != "supported"
        or clean.redemption.status != "supported"
        or clean.redemption.value != 0
        or clean.valuation_and_trades.status != "supported"
        or analysis.closing.quantity is None
        or not analysis.closing.quantity.is_finite()
        or analysis.closing.quantity < 0
    ):
        return None
    trades = []
    for event in analysis.events:
        if event.isin != isin or event.kind in {"FEE", "TAX", "COUPON", "DIVIDEND"}:
            continue
        if (
            event.kind not in {"BUY", "SELL"}
            or not event.current
            or not (event.counted or cost_only_trade(event))
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
        settlement, amount = clean_trade_date(event), clean_trade_amount(event)
        day, instant = _execution(event)
        q = event.quantity_delta
        if (
            q is None
            or not q.is_finite()
            or q == 0
            or (q > 0) != (event.kind == "BUY")
            or amount is None
            or day is None
            or settlement is None
            or event.depository_settlement_date is None
            or not analysis.opening_date < settlement <= analysis.closing_date
            or not analysis.opening_date < event.depository_settlement_date <= analysis.closing_date
        ):
            return None
        trades.append((event, day, instant, settlement, q, amount))
    if not trades or len({row[0].event_key for row in trades}) != len(trades):
        return None
    native_ids = [row[0].native_identity for row in trades if row[0].native_identity]
    if len(native_ids) != len(set(native_ids)):
        return None
    counts = Counter(row[1] for row in trades)
    same_day = [(row[1], row[2]) for row in trades if counts[row[1]] > 1]
    if any(row[0].kind == "SELL" for row in trades) and (
        any(instant is None for _, instant in same_day) or len(same_day) != len(set(same_day))
    ):
        return None
    trades.sort(key=lambda row: (row[1], row[2] or datetime.min.time()))

    with localcontext() as context:
        context.prec = 200
        lots = []
        buy_sum = sell_sum = 0
        for event, day, _instant, settlement, q, amount in trades:
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
                    }
                )
                buy_sum += amount
                continue
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
            shares = _allocate(
                amount, [part for _, part in consumed], [lot["key"] for lot, _ in consumed]
            )
            if shares is None:
                return None
            for (lot, part), share in zip(consumed, shares, strict=True):
                lot["remaining"] -= part
                lot["proceeds"] += share
        if (
            not lots
            or sum((lot["remaining"] for lot in lots), Decimal(0)) != analysis.closing.quantity
            or buy_sum != clean.buys.value
            or sell_sum != clean.sells.value
        ):
            return None
        valuation = clean.closing_value.value
        if valuation < 0:
            return None
        values = _allocate(
            valuation, [lot["remaining"] for lot in lots], [lot["key"] for lot in lots]
        )
        if values is None:
            return None
        results = []
        for lot, value in zip(lots, values, strict=True):
            result = value + lot["proceeds"] - lot["cost"]
            results.append(
                {
                    "id": hashlib.sha256(lot["key"].encode("utf-8")).hexdigest()[:24],
                    "date": lot["date"],
                    "settlement_date": lot["settlement"],
                    "quantity": format(lot["quantity"], "f"),
                    "remaining_quantity": format(lot["remaining"], "f"),
                    "cost_kopecks": str(lot["cost"]),
                    "sale_proceeds_kopecks": str(lot["proceeds"]),
                    "value_kopecks": str(value),
                    "price_result_kopecks": str(result),
                    "return_fraction": format(Decimal(result) / Decimal(lot["cost"]), "f")
                    if lot["cost"]
                    else None,
                }
            )
        if (
            sum(int(row["price_result_kopecks"]) for row in results)
            != clean.valuation_and_trades.value
        ):
            return None
        return results
