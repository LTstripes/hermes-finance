"""Whole-portfolio exact TWRR service (R08-03)."""

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
    TwrrAvailabilityStatus,
    TwrrBoundary,
    TwrrQuality,
    calculate_twrr,
)
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)


@dataclass(frozen=True, slots=True)
class PortfolioTwrrResult:
    """Exact whole-portfolio TWRR plus explicit availability metadata."""

    scope: PerformanceScope
    start_date: date
    end_date: date
    performance_currency: str
    availability: TwrrAvailabilityStatus
    quality: TwrrQuality
    return_rate: Decimal | None
    reason_codes: tuple[str, ...] = ()

    @property
    def is_available(self) -> bool:
        return self.availability is TwrrAvailabilityStatus.AVAILABLE

    @property
    def value(self) -> Decimal | None:
        """Period return in percentage points for the API/presentation adapter."""

        if self.return_rate is None:
            return None
        return self.return_rate * Decimal(100)


def _unavailable(
    *,
    start_date: date,
    end_date: date,
    performance_currency: str,
    reason_codes: Iterable[str],
) -> PortfolioTwrrResult:
    return PortfolioTwrrResult(
        scope=PerformanceScope.PORTFOLIO,
        start_date=start_date,
        end_date=end_date,
        performance_currency=performance_currency,
        availability=TwrrAvailabilityStatus.NOT_COMPUTABLE,
        quality=TwrrQuality.UNAVAILABLE,
        return_rate=None,
        reason_codes=tuple(sorted(set(reason_codes))),
    )


def _signed_flow_amount(flow: object) -> int | None:
    if not hasattr(flow, "boundary_amount_kopecks"):
        return None
    amount = flow.boundary_amount_kopecks
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        return None
    classification = flow.classification
    if classification is ExternalFlowClassification.EXTERNAL_CONTRIBUTION:
        return amount
    if classification is ExternalFlowClassification.EXTERNAL_WITHDRAWAL:
        return -amount
    return None


def _boundaries_from_availability(
    result: PerformanceAvailability,
) -> tuple[tuple[TwrrBoundary, ...], tuple[str, ...]]:
    """Translate classified persisted evidence into exact TWRR boundaries."""

    flow_by_id = {flow.id: flow for flow in result.external_flows.flows}
    boundaries: list[TwrrBoundary] = []
    reasons: set[str] = set()
    for evidence in result.external_flow_boundaries:
        if not evidence.is_available:
            reasons.update(evidence.reason_codes)
            if not evidence.reason_codes:
                reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)
            continue
        if evidence.pre_external_flow is None or evidence.post_external_flow is None:
            reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)
            continue

        signed_flow = 0
        for flow_id in evidence.flow_ids:
            flow = flow_by_id.get(flow_id)
            if flow is None:
                reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
                break
            amount = _signed_flow_amount(flow)
            if amount is None:
                reasons.add(AvailabilityReasonCode.EXTERNAL_FLOWS_INCOMPLETE.value)
                break
            signed_flow += amount
        else:
            try:
                boundaries.append(
                    TwrrBoundary(
                        event_date=evidence.event_date,
                        signed_flow_kopecks=signed_flow,
                        pre_value_kopecks=evidence.pre_external_flow.total_value.kopecks,
                        post_value_kopecks=evidence.post_external_flow.total_value.kopecks,
                    )
                )
            except (TypeError, ValueError):
                reasons.add(AvailabilityReasonCode.VALUATION_BOUNDARY_MISSING.value)

    return tuple(boundaries), tuple(sorted(reasons))


def portfolio_twrr_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
) -> PortfolioTwrrResult:
    """Calculate exact whole-portfolio TWRR when R08-01C permits it."""

    availability = performance_availability_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=PerformanceScope.PORTFOLIO,
    )
    if not availability.twrr.is_available:
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=availability.twrr.reason_codes,
        )

    opening = availability.opening_valuation.point
    closing = availability.closing_valuation.point
    if (
        opening is None
        or closing is None
        or opening.total_value is None
        or closing.total_value is None
        or not availability.opening_valuation.is_available
        or not availability.closing_valuation.is_available
    ):
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=(
                AvailabilityReasonCode.OPENING_VALUATION_MISSING.value,
                AvailabilityReasonCode.CLOSING_VALUATION_MISSING.value,
            ),
        )

    boundaries, boundary_reasons = _boundaries_from_availability(availability)
    if boundary_reasons:
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=boundary_reasons,
        )
    solver_result = calculate_twrr(
        opening.total_value.kopecks,
        closing.total_value.kopecks,
        boundaries,
    )
    if not solver_result.is_available:
        return _unavailable(
            start_date=start_date,
            end_date=end_date,
            performance_currency=availability.performance_currency,
            reason_codes=solver_result.reason_codes,
        )
    return PortfolioTwrrResult(
        scope=PerformanceScope.PORTFOLIO,
        start_date=start_date,
        end_date=end_date,
        performance_currency=availability.performance_currency,
        availability=solver_result.availability,
        quality=solver_result.quality,
        return_rate=solver_result.return_rate,
        reason_codes=solver_result.reason_codes,
    )


def twrr_for_interval(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    scope: PerformanceScope | str = PerformanceScope.PORTFOLIO,
    account_id: int | None = None,
) -> PortfolioTwrrResult:
    """Generic entry point that intentionally supports portfolio scope only."""

    try:
        normalized_scope = PerformanceScope(scope)
    except ValueError as error:
        raise ValueError(f"unsupported TWRR scope: {scope!r}") from error
    if normalized_scope is not PerformanceScope.PORTFOLIO or account_id is not None:
        raise ValueError("R08-03 TWRR supports portfolio scope only")
    return portfolio_twrr_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
    )


# Discoverable aliases for downstream callers.
calculate_portfolio_twrr = portfolio_twrr_for_interval
get_portfolio_twrr = portfolio_twrr_for_interval
