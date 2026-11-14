"""Additive position results; no portfolio aggregation or financial writes."""

from dataclasses import asdict, replace
from decimal import ROUND_HALF_UP, Decimal, localcontext

from hermes_finance.domain.clean_instrument_return import _position_rates
from hermes_finance.domain.instrument_return import Metric
from hermes_finance.services.clean_purchase_returns import _fifo_purchase_price_contributions


def metric_dto(metric):
    result = asdict(metric)
    for key in ("value", "invested_kopecks", "weighted_holding_days"):
        if key in result and result[key] is not None:
            value = result[key]
            if key == "weighted_holding_days":
                value = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            result[key] = format(value, "f") if isinstance(value, Decimal) else str(value)
    return result


def _metric(value, operands=(), reasons=()):
    reasons = tuple(sorted(set(reasons)))
    assumptions = tuple(sorted({a for item in operands for a in item.assumptions}))
    status = (
        "unavailable"
        if value is None
        else "partial"
        if any(item.status == "partial" for item in operands)
        else "provisional"
        if assumptions or any(item.status == "provisional" for item in operands)
        else "supported"
    )
    return Metric(value, status, reasons, assumptions)


def position_results(analysis, clean, isin, instrument_type):
    """Split each original lot cost once; its two parts conserve every kopeck.

    FIFO owns identity/order/quantity proof. Observed-purchase fallback never
    supplies cost allocation. Valuation and paid-income gaps remain independent.
    Unsupported amortization stays unknown under the existing source contract.
    """
    quantity = analysis.closing.quantity
    is_open = (
        quantity > 0 if quantity is not None and quantity.is_finite() and quantity >= 0 else None
    )
    fifo = _fifo_purchase_price_contributions(
        analysis, clean, isin, instrument_type=instrument_type, include_redemptions=True
    )
    realized = unrealized = None
    allocation_reasons = set()
    disposed_cost = remaining_cost = proceeds = 0
    if fifo is None:
        allocation_reasons.add("purchase_allocation_unproven")
    else:
        with localcontext() as context:
            context.prec = 200
            context.rounding = ROUND_HALF_UP
            for lot in fifo[0]:
                if any(
                    lot[key] is None
                    for key in ("cost_kopecks", "remaining_quantity", "sale_proceeds_kopecks")
                ):
                    allocation_reasons.update(lot["reason_codes"])
                    allocation_reasons.add("purchase_allocation_unproven")
                    continue
                cost = int(lot["cost_kopecks"])
                remaining = int(
                    (
                        Decimal(cost)
                        * Decimal(lot["remaining_quantity"])
                        / Decimal(lot["quantity"])
                    ).quantize(Decimal(1))
                )
                remaining_cost += remaining
                disposed_cost += cost - remaining
                proceeds += int(lot["sale_proceeds_kopecks"])
    trade_reasons = {
        reason
        for item in (clean.buys, clean.sells, clean.redemption)
        for reason in item.reason_codes
    }
    allocation_reasons.update(trade_reasons)
    realized_reasons = allocation_reasons | set(clean.payouts.reason_codes)
    if not realized_reasons and clean.payouts.value is not None:
        realized = proceeds - disposed_cost + clean.payouts.value
    elif clean.payouts.value is None:
        realized_reasons.add("paid_income_incomplete")
    unrealized_reasons = set(allocation_reasons)
    if is_open is False:
        unrealized, unrealized_reasons = 0, set()
    elif not unrealized_reasons and clean.closing_value.value is not None:
        unrealized = clean.closing_value.value - remaining_cost
    elif clean.closing_value.value is None:
        unrealized_reasons.update(
            clean.closing_value.reason_codes or ("clean_valuation_incomplete",)
        )
    return {
        "realized_result": metric_dto(
            _metric(
                realized,
                (clean.buys, clean.sells, clean.redemption, clean.payouts),
                realized_reasons,
            )
        ),
        "unrealized_result": metric_dto(
            _metric(unrealized, (clean.buys, clean.closing_value), unrealized_reasons)
        ),
        "current_value": metric_dto(clean.closing_value),
        "is_open": is_open,
        "position_reason_codes": [] if is_open is not None else ["closing_quantity_unknown"],
    }


def aggregate_positions(items, *, identity_conflict=False):
    """All-account instrument totals, with complete coverage per metric.

    Rates use the union of dated cash flows, with each open account's terminal
    value at its own EOD. Different account inception dates are allowed.
    Individual short-holding/no-root rates do not veto a complete combined flow
    population: eligibility and the solver are evaluated for that population.
    """

    def total(field):
        rows = [
            item.get(field, metric_dto(_metric(None, reasons=("instrument_accounts_incomplete",))))
            for item in items
        ]
        reasons = {r for row in rows for r in row["reason_codes"]}
        if identity_conflict:
            reasons.add("source_account_identity_mapping_conflict")
        if not rows or any(row["value"] is None for row in rows):
            reasons.add("instrument_accounts_incomplete")
        value = None if reasons else sum(int(row["value"]) for row in rows)
        operands = [
            Metric(
                row["value"], row["status"], tuple(row["reason_codes"]), tuple(row["assumptions"])
            )
            for row in rows
        ]
        return _metric(value, operands, reasons)

    result = {
        field: metric_dto(total(field))
        for field in ("pnl", "realized_result", "unrealized_result", "current_value")
    }
    flags = [item.get("is_open") for item in items]
    result["is_open"] = None if not flags or None in flags or identity_conflict else any(flags)
    result["position_reason_codes"] = (
        [] if result["is_open"] is not None else ["instrument_accounts_incomplete"]
    )
    flows, purchases = [], []
    invested = total("buys")
    weighted = None
    with localcontext() as context:
        context.prec = 200
        context.rounding = ROUND_HALF_UP
        inputs = [item.get("_position_inputs", {}) for item in items]
        if invested.value and all(row.get("weighted_holding_days") is not None for row in inputs):
            weighted = sum(
                Decimal(item["buys"]["value"]) * row["weighted_holding_days"]
                for item, row in zip(items, inputs, strict=True)
            ) / Decimal(invested.value)
        for item, row in zip(items, inputs, strict=True):
            flows.extend(row.get("dated_flows", ()))
            purchases.extend(row.get("purchases", ()))
            if not row.get("position_closed") and item["closing_value"]["value"] is not None:
                flows.append(
                    (item["closing_date"], -int(item["closing_value"]["value"]), "confirmed")
                )
        inception = bool(items) and all(
            item.get("simple_return", {}).get("invested_kopecks") is not None for item in items
        )
        # Terminal values are already in the merged flow set. The synthetic
        # closed flag prevents a second terminal amount; holding end below
        # includes open accounts' actual valuation dates.
        holding_ends = [item.get("xirr", {}).get("holding_end_date") for item in items]
        simple, annual = _position_rates(
            max((item["closing_date"] for item in items), default=None),
            None,
            invested,
            total("pnl"),
            flows,
            purchases,
            holding_ends,
            inception_proven=inception,
            position_closed=True,
            weighted_holding_days=weighted,
            annual_weighted_holding_days=weighted,
        )
        blockers = {
            code
            for item in items
            for code in item.get("xirr", {}).get("reason_codes", ())
            if code != "short_holding" and not code.startswith("not_computable_xirr_")
        }
        if blockers:
            annual = replace(
                annual,
                value=None,
                status="unavailable",
                reason_codes=tuple(sorted(blockers | set(annual.reason_codes))),
            )
    result.update(simple_return=metric_dto(simple), xirr=metric_dto(annual))
    return result
