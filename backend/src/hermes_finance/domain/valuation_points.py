"""Framework-independent valuation-point and coverage DTOs.

This module deliberately stops at an observed point-in-time value.  It does
not calculate XIRR/TWRR and it does not turn an incomplete component into a
zero.  Money remains integer RUB kopecks through :class:`RubleAmount`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from hermes_finance.domain.values import RubleAmount


class PerformanceScope(StrEnum):
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"


class ValuationPointStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ValuationQuality(StrEnum):
    EXACT = "exact"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class CoverageStatus(StrEnum):
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ComponentStatus(StrEnum):
    AUTHORITATIVE = "authoritative"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class ValuationReasonCode(StrEnum):
    SNAPSHOT_DATE_MISSING = "not_computable_snapshot_date_missing"
    REPORTING_MONTH_NOT_CLOSED = "not_computable_reporting_month_not_closed"
    SCOPE_COVERAGE_INCOMPLETE = "not_computable_scope_coverage_incomplete"
    SCOPE_CASH_UNCLASSIFIED = "not_computable_scope_cash_unclassified"
    CURRENCY_CONVERSION_INCOMPLETE = "not_computable_currency_conversion_incomplete"
    UNSUPPORTED_POSITION_VALUATION = "not_computable_unsupported_position_valuation"
    SCOPE_MEMBERSHIP_HISTORY_MISSING = "not_computable_scope_membership_history_missing"
    TRANSFER_IDENTITY_UNRESOLVED = "not_computable_transfer_identity_unresolved"
    VALUATION_BOUNDARY_ORDER_UNKNOWN = "not_computable_valuation_boundary_order_unknown"


@dataclass(frozen=True, slots=True)
class ValuationComponent:
    """One persisted valuation component or one explicit coverage issue."""

    name: str
    status: ComponentStatus
    amount: RubleAmount | None
    source_kind: str
    source_ids: tuple[int, ...] = ()
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValuationProvenance:
    source_kind: str
    source_ids: tuple[int, ...]
    observed_date: date | None
    quality: ValuationQuality


@dataclass(frozen=True, slots=True)
class ValuationCoverage:
    status: CoverageStatus
    components: tuple[ValuationComponent, ...]
    reason_codes: tuple[str, ...] = ()
    scope_membership_status: CoverageStatus = CoverageStatus.COMPLETE
    scope_membership_reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValuationPoint:
    reporting_month_id: int
    scope: PerformanceScope
    account_id: int | None
    valuation_date: date | None
    performance_currency: str
    status: ValuationPointStatus
    quality: ValuationQuality
    total_value: RubleAmount | None
    coverage: ValuationCoverage
    provenance: tuple[ValuationProvenance, ...] = ()

    @property
    def total(self) -> RubleAmount | None:
        """Compatibility spelling for consumers that call the value ``total``."""

        return self.total_value


def build_valuation_point(
    *,
    reporting_month_id: int,
    scope: PerformanceScope,
    account_id: int | None,
    valuation_date: date | None,
    performance_currency: str,
    components: Iterable[ValuationComponent],
    provenance: Iterable[ValuationProvenance] = (),
    extra_reason_codes: Iterable[str] = (),
    scope_membership_status: CoverageStatus = CoverageStatus.COMPLETE,
    scope_membership_reason_codes: Iterable[str] = (),
) -> ValuationPoint:
    """Build a deterministic point from explicitly classified components."""

    component_tuple = tuple(components)
    reasons = set(extra_reason_codes)
    if valuation_date is None:
        reasons.add(ValuationReasonCode.SNAPSHOT_DATE_MISSING.value)

    for component in component_tuple:
        reasons.update(component.reason_codes)

    statuses = {component.status for component in component_tuple}
    if ComponentStatus.UNAVAILABLE in statuses:
        status = ValuationPointStatus.UNAVAILABLE
        quality = ValuationQuality.UNAVAILABLE
        coverage_status = CoverageStatus.UNAVAILABLE
    elif not component_tuple or ComponentStatus.UNKNOWN in statuses:
        status = ValuationPointStatus.UNKNOWN
        quality = ValuationQuality.UNKNOWN
        coverage_status = CoverageStatus.UNKNOWN
    elif reasons:
        status = ValuationPointStatus.UNAVAILABLE
        quality = ValuationQuality.UNAVAILABLE
        coverage_status = CoverageStatus.UNAVAILABLE
    else:
        status = ValuationPointStatus.AVAILABLE
        quality = ValuationQuality.EXACT
        coverage_status = CoverageStatus.COMPLETE

    total_value = None
    if status is ValuationPointStatus.AVAILABLE:
        total_value = RubleAmount(
            sum(component.amount.kopecks for component in component_tuple if component.amount)
        )

    coverage = ValuationCoverage(
        status=coverage_status,
        components=component_tuple,
        reason_codes=tuple(sorted(reasons)),
        scope_membership_status=scope_membership_status,
        scope_membership_reason_codes=tuple(sorted(set(scope_membership_reason_codes))),
    )
    return ValuationPoint(
        reporting_month_id=reporting_month_id,
        scope=scope,
        account_id=account_id,
        valuation_date=valuation_date,
        performance_currency=performance_currency,
        status=status,
        quality=quality,
        total_value=total_value,
        coverage=coverage,
        provenance=tuple(provenance),
    )


calculate_valuation_point = build_valuation_point
