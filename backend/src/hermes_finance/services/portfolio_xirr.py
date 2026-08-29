"""Whole-portfolio XIRR service (R08-02).

This service consumes the accepted R08-01C availability contract.  It does
not classify flows, select neighboring valuations, infer missing values, or
convert currencies.  Only the portfolio scope is exposed in this first slice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from hermes_finance.domain import (
    AvailabilityReasonCode,
    ExternalFlowClassification,
    PerformanceAvailability,
    PerformanceScope,
)
from hermes_finance.domain.xirr import (
    XirrAvailabilityStatus,
    XirrCashFlow,
    XirrQuality,
    calculate_xirr,
)
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)


@dataclass(frozen=True, slots=True)
class PortfolioXirrResult:
    """Exact whole-portfolio XIRR plus explicit availability metadata."""

    scope: PerformanceScope
    start_date: date
    end_date: date
    performance_currency: str
    availability: XirrAvailabilityStatus
    quality: XirrQuality
    annualized_rate: Decimal | None
    reason_codes: tuple[str, ...] = ()
    iterations: int = 0

    @property
    def is_available(self) -> bool:
        return self.availability is XirrAvailabilityStatus.AVAILABLE

    @property
    def value(self) -> Decimal | None:
        """Annualized percentage points for an API/presentation adapter."""

        if self.annualized_rate is None:
            return None
        return self.annualized_rate * Decimal(100)


def _unavailable(
    *,
    start_date: date,
    end_date: date,
    performance_currency: str,
    reason_codes: Iterable[str],
    iterations: int = 0,
) -> PortfolioXirrResult:
    return PortfolioXirrResult(
        scope=PerformanceScope.PORTFOLIO,
        start_date=start_date,
        end_date=end_date,
        performance_currency=performance_currency,
        availability=XirrAvailabilityStatus.NOT_COMPUTABLE,
        quality=XirrQuality.UNAVAILABLE,
        annualized_rate=None,
        reason_codes=tuple(sorted(set(reason_codes))),
        iterations=iterations,
    )


def _cash_flows_from_availability(
    result: PerformanceAvailability,
) -> tuple[XirrCashFlow, ...] | tuple[str, ...]:
    """Translate already-classified evidence into investor-perspective flows."""

    opening = result.opening_valuation.point
    closing = result.closing_valuation.point
    if opening is None or opening.total_value is None or not result.opening_valuation.is_available:
        return (AvailabilityReasonCode.OPENING_VALUATION_MISSING.value,)
    if closing is None or closing.total_value is None or not result.closing_valuation.is_available:
        return (AvailabilityReasonCode.CLOSING_VALUATION_MISSING.value,)

    cash_flows = [
        XirrCashFlow(
            event_date=result.start_date,
            amount_kopecks=-opening.total_value.kopecks,
        )
    ]
    for flow in result.external_flows.flows:
        amount = flow.boundary_amount_kopecks
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            return (AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value,)
        if flow.classification is ExternalFlowClassification.EXTERNAL_CONTRIBUTION:
            signed_amount = -amount
        elif flow.classification is ExternalFlowClassification.EXTERNAL_WITHDRAWAL:
            signed_amount = amount
        elif flow.classification is ExternalFlowClassification.INTERNAL_TRANSFER:
            continue
        else:
            return (AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value,)
        cash_flows.append(XirrCashFlow(event_date=flow.event_date, amount_kopecks=signed_amount))
    cash_flows.append(
        XirrCashFlow(
            event_date=result.end_date,
            amount_kopecks=closing.total_value.kopecks,
        )
    )
    return tuple(cash_flows)


def portfolio_xirr_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
) -> PortfolioXirrResult:
    """Calculate XIRR for the whole portfolio when R08-01C permits it."""

    availability = performance_availability_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=PerformanceScope.PORTFOLIO,
    )
    if not availability.xirr.is_available:
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=availability.xirr.reason_codes,
        )

    cash_flows = _cash_flows_from_availability(availability)
    if cash_flows and isinstance(cash_flows[0], str):
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=cash_flows,
        )

    solver_result = calculate_xirr(cash_flows)
    if not solver_result.is_available:
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=solver_result.reason_codes,
            iterations=solver_result.iterations,
        )
    return PortfolioXirrResult(
        scope=PerformanceScope.PORTFOLIO,
        start_date=start_date,
        end_date=end_date,
        performance_currency=availability.performance_currency,
        availability=solver_result.availability,
        quality=solver_result.quality,
        annualized_rate=solver_result.annualized_rate,
        reason_codes=solver_result.reason_codes,
        iterations=solver_result.iterations,
    )


def xirr_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> PortfolioXirrResult:
    """Generic entry point that intentionally rejects account XIRR for R08-02."""

    try:
        normalized_scope = PerformanceScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported XIRR scope: {scope!r}") from error
    if normalized_scope is not PerformanceScope.PORTFOLIO or account_id is not None:
        raise ValueError("R08-02 XIRR supports portfolio scope only")
    return portfolio_xirr_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
    )


# Discoverable aliases for downstream callers.
calculate_portfolio_xirr = portfolio_xirr_for_interval
get_portfolio_xirr = portfolio_xirr_for_interval
