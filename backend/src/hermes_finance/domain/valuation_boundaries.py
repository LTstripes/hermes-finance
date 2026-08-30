"""Observed valuation-boundary evidence for future exact TWRR consumers.

The objects in this module describe persisted observations and their explicit
relation to an external-flow boundary.  They intentionally stop at
availability: no return factor or other TWRR calculation belongs here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from hermes_finance.domain.valuation_points import (
    CoverageStatus,
    PerformanceScope,
    ValuationQuality,
)
from hermes_finance.domain.values import RubleAmount


class ValuationBoundaryRelation(StrEnum):
    """Which side of an explicitly identified external-flow boundary was observed."""

    PRE_EXTERNAL_FLOW = "pre_external_flow"
    POST_EXTERNAL_FLOW = "post_external_flow"


@dataclass(frozen=True, slots=True)
class ObservedValuationEvidence:
    """One exact-money observed valuation point persisted near a flow boundary."""

    id: int
    scope: PerformanceScope
    account_id: int | None
    observed_date: date
    total_value: RubleAmount
    performance_currency: str
    coverage: CoverageStatus
    quality: ValuationQuality
    provenance_kind: str
    provenance_reference: str | None
    relation: ValuationBoundaryRelation
    external_flow_id: int | None
    boundary_group_id: int | None

    @property
    def value(self) -> RubleAmount:
        """Compatibility spelling for consumers that call the value ``value``."""

        return self.total_value

    @property
    def is_available(self) -> bool:
        return self.coverage is CoverageStatus.COMPLETE and self.quality is ValuationQuality.EXACT


@dataclass(frozen=True, slots=True)
class ExternalFlowBoundaryEvidence:
    """Pre/post observed evidence for one flow or one same-date flow group."""

    boundary_group_id: int | None
    flow_ids: tuple[int, ...]
    event_date: date
    pre_external_flow: ObservedValuationEvidence | None
    post_external_flow: ObservedValuationEvidence | None
    reason_codes: tuple[str, ...] = ()

    @property
    def flow_group_id(self) -> int | None:
        """Compatibility spelling for downstream boundary-group consumers."""

        return self.boundary_group_id

    @property
    def is_available(self) -> bool:
        return (
            self.pre_external_flow is not None
            and self.post_external_flow is not None
            and self.pre_external_flow.is_available
            and self.post_external_flow.is_available
            and not self.reason_codes
        )


# Short aliases keep both the observed-point and boundary terminology usable
# without creating a second set of domain semantics.
ObservedValuationPoint = ObservedValuationEvidence
ValuationBoundaryEvidence = ExternalFlowBoundaryEvidence
