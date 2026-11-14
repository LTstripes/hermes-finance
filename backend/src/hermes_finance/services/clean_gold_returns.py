"""Clean FIFO gold decomposition; source amounts and receipts remain untouched."""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal, localcontext


def clean_gold_decomposition(declaration, observed, *, current=True):
    from hermes_finance.services.returns_view import metric

    reasons = set(observed["realized_reason_codes"]) - {
        "gold_separate_fees_unknown",
        "gold_cost_allocation_unproven",
    }
    if not current:
        reasons.add("source_dependency_changed")
    days = defaultdict(list)
    for event in declaration["events"]:
        if event["event_date"] <= observed["as_of_date"]:
            days[event["event_date"]].append(event)
    has_sales = any(e["side"] == "SELL" for events in days.values() for e in events)
    lots = []
    sold_cost = 0
    with localcontext() as ctx:
        ctx.prec = 80
        for day in sorted(days):
            events = days[day]
            buys = [e for e in events if e["side"] == "BUY"]
            sales = [e for e in events if e["side"] == "SELL"]
            # Dates do not establish an execution order within a day.
            if buys and sales or len(buys) > 1 and has_sales:
                reasons.add("gold_fifo_order_unproven")
                break
            for buy in buys:
                lots.append([Decimal(buy["grams"]), int(buy["amount_kopecks"])])
            quantity = sum((Decimal(e["grams"]) for e in sales), Decimal(0))
            while quantity and lots:
                grams, cost = lots[0]
                used = min(grams, quantity)
                allocated = (
                    cost
                    if used == grams
                    else int(
                        (Decimal(cost) * used / grams).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                    )
                )
                sold_cost += allocated
                quantity -= used
                if used == grams:
                    lots.pop(0)
                else:
                    lots[0] = [grams - used, cost - allocated]
            if quantity:
                reasons.add("gold_negative_running_quantity")
                break
    estimates = set()
    if "gold_separate_fees_unknown" in observed["reason_codes"]:
        estimates.add("gold_separate_fees_unknown")
    if observed["amount_basis"] == "derived":
        estimates.add("gold_amount_derived")
    valuation_reasons = set(observed["unrealized_reason_codes"]) - set(
        observed["realized_reason_codes"]
    )
    remaining = sum(cost for _, cost in lots)
    sales = observed["sale_amount_kopecks"]
    value = observed["valuation_kopecks"]
    return {
        "realized_result": metric(
            int(sales) - sold_cost if not reasons and sales is not None else None,
            reasons=sorted(reasons | estimates),
            method="clean_gold_fifo",
            estimate=bool(estimates),
        ),
        "unrealized_result": metric(
            int(value) - remaining
            if not reasons and not valuation_reasons and value is not None
            else None,
            reasons=sorted(reasons | valuation_reasons | estimates),
            method="clean_gold_fifo",
            estimate=bool(estimates),
        ),
    }
