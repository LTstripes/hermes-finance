"""No-disposal purchase price contributions from the existing clean analysis.

This does not allocate sales or income and does not persist another journal.
"""

import hashlib
from dataclasses import replace
from decimal import ROUND_FLOOR, Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import (
    clean_trade_amount,
    clean_trade_date,
    cost_only_trade,
)


def clean_purchase_price_contributions(analysis, clean, isin, *, instrument_type):
    """Project only proved, fully held buys; return None when that is not proven."""
    if (
        analysis.opening.quantity != 0
        or clean.opening_value.value != 0
        or clean.closing_value.value is None
        or clean.closing_value.status != "supported"
        or clean.buys.status != "supported"
        or clean.sells.status != "supported"
        or clean.sells.value != 0
        or clean.redemption.status != "supported"
        or clean.redemption.value != 0
        or analysis.closing.quantity is None
        or not analysis.closing.quantity.is_finite()
        or analysis.closing.quantity <= 0
    ):
        return None
    buys = []
    for event in analysis.events:
        if event.isin != isin or event.kind in {"FEE", "TAX", "COUPON", "DIVIDEND"}:
            continue
        if (
            event.kind != "BUY"
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
        day, amount = clean_trade_date(event), clean_trade_amount(event)
        q = event.quantity_delta
        if (
            q is None
            or not q.is_finite()
            or q <= 0
            or amount is None
            or day is None
            or event.depository_settlement_date is None
            or not analysis.opening_date < day <= analysis.closing_date
            or not analysis.opening_date < event.depository_settlement_date <= analysis.closing_date
        ):
            return None
        buys.append((event.event_key, day, q, amount))
    if not buys or len({row[0] for row in buys}) != len(buys):
        return None
    with localcontext() as context:
        context.prec = 200
        total_quantity = sum((row[2] for row in buys), Decimal(0))
        if (
            total_quantity != analysis.closing.quantity
            or sum(row[3] for row in buys) != clean.buys.value
        ):
            return None
        valuation = clean.closing_value.value
        if valuation < 0:
            return None
        raw = [Decimal(valuation) * row[2] / total_quantity for row in buys]
        values = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in raw]
        # Stable largest remainder conserves the reported value to the kopeck.
        order = sorted(range(len(buys)), key=lambda i: (-(raw[i] - values[i]), buys[i][0]))
        for i in order[: valuation - sum(values)]:
            values[i] += 1
    return [
        {
            "id": hashlib.sha256(key.encode("utf-8")).hexdigest()[:24],
            "date": day,
            "quantity": format(quantity, "f"),
            "cost_kopecks": str(cost),
            "value_kopecks": str(value),
            "price_result_kopecks": str(value - cost),
        }
        for (key, day, quantity, cost), value in zip(buys, values, strict=True)
    ]
