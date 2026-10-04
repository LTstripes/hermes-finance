"""Thin exact no-crossing class-return adapter over accepted endpoint evidence."""

from datetime import date
from decimal import Decimal, localcontext

from sqlalchemy.orm import Session

from hermes_finance.domain.twrr import TwrrResult, calculate_twrr
from hermes_finance.domain.xirr import XirrCashFlow, XirrResult, calculate_xirr
from hermes_finance.services.class_endpoint_eligibility import class_endpoint_eligibility


def _metric(result: XirrResult | TwrrResult, *, annualized: bool) -> dict:
    # Keep numerical availability/quality/reasons exactly as the solver reports.
    with localcontext() as context:
        context.prec = 60
        value = None if result.rate is None else result.rate * Decimal(100)
    return dict(
        availability=result.availability.value,
        quality=result.quality.value,
        value=value,
        value_unit="percentage_points",
        annualized=annualized,
        reason_codes=result.reason_codes,
        reason_source="solver" if result.reason_codes else None,
    )


def class_returns_for_interval(
    session: Session, *, asset_class: str, start_date: date, end_date: date
) -> dict:
    """Read one coherent eligibility result, then calculate from its values only.

    The accepted #698 reader owns all historical/evidence logic and the committed
    read snapshot. Its materialized result is the sole input to both pure solvers;
    no later DB reads, providers, cache or writes are needed here.
    """
    evidence = class_endpoint_eligibility(
        session, asset_class=asset_class, start_date=start_date, end_date=end_date
    )
    result = dict(
        asset_class=evidence["requested_class"],
        requested_period=dict(
            start_date=evidence["requested_opening_date"],
            end_date=evidence["requested_closing_date"],
        ),
        actual_covered_period=dict(
            start_date=evidence["actual_opening_date"], end_date=evidence["actual_closing_date"]
        ),
        performance_currency=evidence["currency"],
        valuation_basis="persisted_rub_market_value_kopecks",
        historical_account_ids=evidence["historical_account_ids"],
        coverage_state=evidence["coverage_state"],
        coverage_provenance=evidence["coverage_provenance"],
        eligibility_status=evidence["status"],
        evidence_reason_codes=evidence["reason_codes"],
    )
    if evidence["status"] != "eligible":
        for metric, annualized in (("xirr", True), ("twrr", False)):
            result[metric] = dict(
                availability="not_computable",
                quality="unavailable",
                value=None,
                value_unit="percentage_points",
                annualized=annualized,
                reason_codes=evidence["reason_codes"],
                reason_source="evidence",
            )
        return result

    opening = evidence["opening_value_kopecks"]
    closing = evidence["closing_value_kopecks"]
    result["xirr"] = _metric(
        calculate_xirr(
            (
                XirrCashFlow(evidence["actual_opening_date"], -opening),
                XirrCashFlow(evidence["actual_closing_date"], closing),
            )
        ),
        annualized=True,
    )
    result["twrr"] = _metric(calculate_twrr(opening, closing, boundaries=()), annualized=False)
    return result
