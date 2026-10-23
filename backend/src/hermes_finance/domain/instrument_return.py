"""Instrument cash economics. Integer minor units; no persistence or source authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from hermes_finance.domain.monthly_return_chain import calculate_interval_return


@dataclass(frozen=True)
class Metric:
    value: int | Decimal | None
    status: Literal["supported", "provisional", "partial", "unavailable"]
    reason_codes: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class DietzMetric(Metric):
    method: Literal["modified_dietz"] = "modified_dietz"
    approximate: bool = True
    annualized: bool = False
    capital_days: int | None = None


@dataclass(frozen=True)
class Coverage:
    complete: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Endpoint:
    date: date
    quantity: Decimal | None
    reported_value_kopecks: int | None
    economic_value_kopecks: int | None
    accrued_interest_kopecks: int | None
    valuation_basis: Literal["dirty", "clean_plus_nkd", "reported_unknown"]
    source_references: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CashLeg:
    role: str
    date: date
    account_cash_kopecks: int
    instrument_flow_kopecks: int
    source_references: tuple[str, ...]
    ownership: str

    def __post_init__(self):
        if type(self.account_cash_kopecks) is not int or (
            self.instrument_flow_kopecks != -self.account_cash_kopecks
        ):
            raise ValueError("cash leg signs/units disagree")


@dataclass(frozen=True, kw_only=True)
class InstrumentEvent:
    event_key: str
    provider: str
    native_source_account: str
    isin: str | None
    kind: Literal["BUY", "SELL", "COUPON", "DIVIDEND", "FEE", "TAX", "REDEMPTION", "UNRESOLVED"]
    source_references: tuple[str, ...]
    event_date: date | None
    native_identity: str | None = None
    native_ids: tuple[str, ...] = ()
    trade_time: str | None = None
    cash_settlement_date: date | None = None
    depository_settlement_date: date | None = None
    quantity_delta: Decimal | None = None
    unit_price: Decimal | None = None
    price_unit: Literal["RUB_PER_UNIT", "PERCENT_OF_FACE", "UNKNOWN"] = "UNKNOWN"
    face_value: Decimal | None = None
    face_value_date: date | None = None
    native_trade_amount_kopecks: int | None = None
    native_total_basis: str | None = None
    proof_dependency: str | None = None
    accrued_interest_kopecks: int | None = None
    commission_kopecks: int | None = None
    gross_payout_kopecks: int | None = None
    withheld_tax_kopecks: int | None = None
    net_payout_kopecks: int | None = None
    classification: str | None = None
    classification_origin: str | None = None
    classification_status: str | None = None
    persisted_link_status: str | None = None
    attribution_basis: str | None = None
    effective_isin: str | None = None
    current: bool = True
    counted: bool = True
    cash_legs: tuple[CashLeg, ...] = ()
    reason_codes: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceReference:
    intake_id: int
    original_digest: str
    parser_version: str
    journal_revision: int
    manifest_digest: str
    classification_dependencies: tuple[str, ...]
    link_dependencies: str


@dataclass(frozen=True)
class StatementEstimate:
    pnl: Metric
    modified_dietz: DietzMetric
    assumptions: tuple[str, ...]


@dataclass(frozen=True)
class AccountReconciliation:
    opening_date: date
    closing_date: date
    account_growth: Metric
    instrument_pnl: Metric
    account_only_result: Metric
    residual: Metric
    complete: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class InstrumentAnalysis:
    opening_date: date
    closing_date: date
    history_start: date
    history_end: date
    history_complete_since_acquisition: bool
    events: tuple[InstrumentEvent, ...]
    opening: Endpoint
    closing: Endpoint
    components: dict[str, Metric]
    pnl: Metric
    known_subtotal: Metric
    modified_dietz: DietzMetric
    coverage: dict[str, Coverage]
    source_references: tuple[SourceReference, ...]
    reason_codes: tuple[str, ...]
    assumptions: tuple[str, ...]
    statement_estimate: StatementEstimate
    chained_monthly: Metric = field(default_factory=lambda: Metric(None, "unavailable"))
    contract_version: Literal["instrument_return_v2"] = "instrument_return_v2"


def calculate_economics(opening, closing, events, coverage):
    """Count cash once, retain known components, withhold incomplete full metrics."""
    start, end = opening.date, closing.date
    if start >= end:
        raise ValueError("opening_date must precede closing_date")
    legs = [
        (event, leg)
        for event in events
        if event.counted
        for leg in event.cash_legs
        if start < leg.date <= end
    ]
    owners = [leg.ownership for _, leg in legs]
    if len(owners) != len(set(owners)):
        raise ValueError("duplicate cash ownership")
    assumptions = tuple(sorted({a for e in events for a in e.assumptions}))
    reasons = tuple(
        sorted({r for c in coverage.values() if not c.complete for r in c.reason_codes})
    )
    flow_reasons = tuple(
        sorted(
            {
                r
                for k, c in coverage.items()
                if k != "valuation" and not c.complete
                for r in c.reason_codes
            }
        )
    )
    flow_complete = all(c.complete for k, c in coverage.items() if k != "valuation")
    components = {}
    for name, kind in (
        ("buys", "BUY"),
        ("sells", "SELL"),
        ("coupons", "COUPON"),
        ("dividends", "DIVIDEND"),
        ("redemption", "REDEMPTION"),
        ("fees", "FEE"),
        ("taxes", "TAX"),
    ):
        selected = [leg for e, leg in legs if e.kind == kind]
        value = sum(
            leg.instrument_flow_kopecks
            if kind in {"BUY", "FEE", "TAX"}
            else leg.account_cash_kopecks
            for leg in selected
        )
        complete = coverage["payouts" if kind in {"COUPON", "DIVIDEND"} else "costs"].complete
        components[name] = Metric(
            value if selected or complete else None,
            ("provisional" if assumptions else "supported")
            if complete
            else ("partial" if selected else "unavailable"),
            () if complete else flow_reasons,
            assumptions,
        )
    flows = [
        (leg.date, leg.instrument_flow_kopecks, "assumed" if e.assumptions else "confirmed")
        for e, leg in legs
    ]

    def result(v0, v1, available, why, extra_assumptions=()):
        used = tuple(sorted(set(assumptions + extra_assumptions)))
        row = calculate_interval_return((start, v0), (end, v1), flows)
        status = "provisional" if used else "supported"
        pnl = Metric(
            row.growth_kopecks if available else None,
            status if available and row.growth_kopecks is not None else "unavailable",
            why if not available else tuple(r for r in row.reason_codes if r == "missing_endpoint"),
            used,
        )
        rate_reasons = tuple(sorted(set(why + row.reason_codes)))
        capital_days = (
            None
            if v0 is None or not available
            else (v0 * (end - start).days + sum(a * (end - d).days for d, a, _ in flows))
        )
        rate = DietzMetric(
            row.modified_dietz_return if available else None,
            status if available and row.modified_dietz_return is not None else "unavailable",
            rate_reasons,
            used,
            capital_days=capital_days,
        )
        return pnl, rate

    pnl, rate = result(
        opening.economic_value_kopecks,
        closing.economic_value_kopecks,
        flow_complete and coverage["valuation"].complete,
        reasons,
    )
    basis_assumptions = tuple(
        sorted(
            (set(opening.reason_codes + closing.reason_codes) & {"bond_valuation_basis_unknown"})
            | (set(assumptions) & {"face_value_assumed"})
        )
    )
    estimate_applicable = bool(basis_assumptions) and "instrument_type_unknown" not in reasons
    estimate_pnl, estimate_rate = result(
        opening.reported_value_kopecks,
        closing.reported_value_kopecks,
        flow_complete and estimate_applicable,
        flow_reasons
        if estimate_applicable
        else flow_reasons + ("statement_estimate_not_applicable",),
        basis_assumptions,
    )
    v0, v1 = opening.economic_value_kopecks, closing.economic_value_kopecks
    b, s = components["buys"], components["sells"]
    valuation = None if None in (v0, v1, b.value, s.value) else v1 - v0 - b.value + s.value
    components["valuation_and_trades"] = Metric(
        valuation,
        "partial" if reasons else ("provisional" if assumptions else "supported"),
        reasons,
        assumptions,
    )
    # This subtotal is explicitly observed cash plus known valuation change, never full P.
    known = -sum(leg.instrument_flow_kopecks for _, leg in legs)
    if v0 is not None and v1 is not None:
        known += v1 - v0
    subtotal = Metric(
        known if legs or (v0 is not None and v1 is not None) else None,
        "partial",
        reasons,
        assumptions,
    )
    return (
        components,
        pnl,
        subtotal,
        rate,
        StatementEstimate(
            estimate_pnl, estimate_rate, tuple(sorted(set(assumptions + basis_assumptions)))
        ),
    )


def chain_monthly(analyses, start, end):
    if not analyses or analyses[0].opening_date != start or analyses[-1].closing_date != end:
        return Metric(None, "unavailable", ("incomplete_monthly_chain",))
    with localcontext() as context:
        context.prec = 60
        context.rounding = ROUND_HALF_UP
        product = Decimal(1)
        assumptions = set()
        previous = None
        for row in analyses:
            if previous and (
                previous.closing_date != row.opening_date
                or previous.closing.economic_value_kopecks != row.opening.economic_value_kopecks
                or previous.closing.quantity != row.opening.quantity
            ):
                return Metric(None, "unavailable", ("seam_mismatch",))
            rate = row.modified_dietz.value
            if rate is None or 1 + rate < 0:
                return Metric(None, "unavailable", ("incomplete_monthly_chain",))
            product *= 1 + rate
            assumptions.update(row.assumptions)
            previous = row
        return Metric(
            product - 1,
            "provisional" if assumptions else "supported",
            assumptions=tuple(sorted(assumptions)),
        )
