"""Framework-independent DTOs and arithmetic for R07-06A.

This module deliberately models support state separately from concentration.
``unavailable`` and ``unknown`` are data-quality outcomes, never risk scores
or recommendations. Percentages use ``Decimal`` and ``ROUND_HALF_UP`` via the
existing financial value contract.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from hermes_finance.domain.values import FINANCIAL_ROUNDING, RubleAmount

_PERCENT_SCALE = Decimal("0.01")


class RiskSupportStatus(StrEnum):
    SUPPORTED = "supported"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class MetricSupport:
    status: RiskSupportStatus
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SupportIssue:
    source_kind: str
    source_id: int | None
    support: MetricSupport


@dataclass(frozen=True, slots=True)
class AllocationSlice:
    key: str
    label: str
    amount: RubleAmount
    share_pct: Decimal | None
    account_id: int | None = None
    instrument_id: int | None = None
    instrument_type: str | None = None


@dataclass(frozen=True, slots=True)
class AllocationMetric:
    support: MetricSupport
    denominator: RubleAmount
    covered_amount: RubleAmount
    unallocated_amount: RubleAmount
    coverage_pct: Decimal | None
    items: tuple[AllocationSlice, ...]
    excluded: tuple[SupportIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class ConcentrationItem:
    key: str
    label: str
    amount: RubleAmount
    share_pct: Decimal | None
    account_id: int | None = None
    account_name: str | None = None
    instrument_id: int | None = None
    instrument_name: str | None = None
    instrument_type: str | None = None
    position_id: int | None = None
    event_count: int | None = None
    is_approximate: bool = False


@dataclass(frozen=True, slots=True)
class ConcentrationMetric:
    support: MetricSupport
    denominator: RubleAmount
    top_n: int
    top_amount: RubleAmount
    top_share_pct: Decimal | None
    items: tuple[ConcentrationItem, ...]
    excluded: tuple[SupportIssue, ...] = ()
    is_approximate: bool = False


@dataclass(frozen=True, slots=True)
class RiskAllocationResult:
    reporting_month_id: int
    as_of_date: date
    base_currency: str
    liquid_assets_total: RubleAmount
    allocation_by_asset_class: AllocationMetric
    allocation_by_account: AllocationMetric
    top_positions: ConcentrationMetric
    payout_concentration: ConcentrationMetric
    redemption_concentration: ConcentrationMetric
    support: dict[str, MetricSupport]


def percentage(amount_kopecks: int, denominator_kopecks: int) -> Decimal | None:
    """Return a two-decimal percentage, or ``None`` for a zero denominator."""
    if denominator_kopecks <= 0:
        return None
    return (Decimal(amount_kopecks) / Decimal(denominator_kopecks) * Decimal(100)).quantize(
        _PERCENT_SCALE, rounding=FINANCIAL_ROUNDING
    )


def support_from_issues(
    issues: Iterable[SupportIssue],
    *,
    extra_reason_codes: Iterable[str] = (),
) -> MetricSupport:
    """Collapse row-level issues into one deterministic metric state."""
    issues = tuple(issues)
    statuses = {issue.support.status for issue in issues}
    if RiskSupportStatus.UNAVAILABLE in statuses:
        status = RiskSupportStatus.UNAVAILABLE
    elif RiskSupportStatus.UNKNOWN in statuses:
        status = RiskSupportStatus.UNKNOWN
    else:
        status = RiskSupportStatus.SUPPORTED
    reasons = {reason for issue in issues for reason in issue.support.reason_codes}
    reasons.update(extra_reason_codes)
    return MetricSupport(status=status, reason_codes=tuple(sorted(reasons)))
