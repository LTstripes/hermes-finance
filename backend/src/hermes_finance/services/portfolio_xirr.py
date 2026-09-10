"""Whole-portfolio XIRR service (R08-02).

This service consumes the accepted R08-01C availability contract.  It does
does not classify flows, select neighboring valuations, infer missing values, or
convert currencies.  Accepted R08-02 portfolio semantics stay unchanged; the
account scope introduced for #146 reuses the exact same availability,
classification and solver path with the requested account's own evidence.
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
    """Exact XIRR for one scope plus explicit availability metadata."""

    scope: PerformanceScope
    start_date: date
    end_date: date
    performance_currency: str
    availability: XirrAvailabilityStatus
    quality: XirrQuality
    annualized_rate: Decimal | None
    reason_codes: tuple[str, ...] = ()
    iterations: int = 0
    account_id: int | None = None

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
    scope: PerformanceScope,
    account_id: int | None,
    start_date: date,
    end_date: date,
    performance_currency: str,
    reason_codes: Iterable[str],
    iterations: int = 0,
) -> PortfolioXirrResult:
    return PortfolioXirrResult(
        scope=scope,
        account_id=account_id if scope is PerformanceScope.ACCOUNT else None,
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


def _xirr_for_scope_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope,
    account_id: int | None,
) -> PortfolioXirrResult:
    """Reuse the accepted availability, translation and solver path per scope."""

    availability = performance_availability_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        account_id=account_id,
    )
    if not availability.xirr.is_available:
        return _unavailable(
            scope=scope,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=availability.xirr.reason_codes,
        )

    cash_flows = _cash_flows_from_availability(availability)
    if cash_flows and isinstance(cash_flows[0], str):
        return _unavailable(
            scope=scope,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=cash_flows,
        )

    solver_result = calculate_xirr(cash_flows)
    if not solver_result.is_available:
        return _unavailable(
            scope=scope,
            account_id=account_id,
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=solver_result.reason_codes,
            iterations=solver_result.iterations,
        )
    return PortfolioXirrResult(
        scope=scope,
        account_id=account_id if scope is PerformanceScope.ACCOUNT else None,
        start_date=start_date,
        end_date=end_date,
        performance_currency=availability.performance_currency,
        availability=solver_result.availability,
        quality=solver_result.quality,
        annualized_rate=solver_result.annualized_rate,
        reason_codes=solver_result.reason_codes,
        iterations=solver_result.iterations,
    )


def portfolio_xirr_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
) -> PortfolioXirrResult:
    """Calculate XIRR for the whole portfolio when R08-01C permits it."""

    return _xirr_for_scope_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=PerformanceScope.PORTFOLIO,
        account_id=None,
    )


def xirr_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> PortfolioXirrResult:
    """Generic entry point for the accepted portfolio and account scopes."""

    try:
        normalized_scope = PerformanceScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported XIRR scope: {scope!r}") from error
    if normalized_scope is PerformanceScope.ACCOUNT:
        if account_id is None:
            raise ValueError("account_id is required for account XIRR scope")
    elif account_id is not None:
        raise ValueError("account_id must be omitted for portfolio XIRR scope")
    return _xirr_for_scope_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=normalized_scope,
        account_id=account_id,
    )


# Discoverable aliases for downstream callers.
calculate_portfolio_xirr = portfolio_xirr_for_interval
get_portfolio_xirr = portfolio_xirr_for_interval
