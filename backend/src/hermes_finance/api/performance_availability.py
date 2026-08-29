"""Read-only performance availability API (R08-01C)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain import PerformanceAvailability, PerformanceScope, RubleAmount
from hermes_finance.domain.performance_availability import ValuationBoundaryEvidence
from hermes_finance.domain.valuation_points import ValuationPoint
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


class ExactMoneyOut(BaseModel):
    """A minor-unit-backed decimal amount; foreign currencies remain explicit."""

    model_config = ConfigDict(extra="forbid")

    amount: str
    currency: str = Field(min_length=3, max_length=3)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter code")
        return normalized


class ValuationComponentOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    status: str
    amount: ExactMoneyOut | None
    source_kind: str
    source_ids: list[int]
    reason_codes: list[str]


class ValuationProvenanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str
    source_ids: list[int]
    observed_date: date | None
    quality: str


class ValuationCoverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    components: list[ValuationComponentOut]
    reason_codes: list[str]
    scope_membership_status: str
    scope_membership_reason_codes: list[str]


class ValuationBoundaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    requested_date: date
    availability: str
    reporting_month_id: int | None
    valuation_date: date | None
    status: str
    quality: str
    performance_currency: str
    total_value: ExactMoneyOut | None
    coverage: ValuationCoverageOut | None
    provenance: list[ValuationProvenanceOut]
    reason_codes: list[str]


class ScopeMembershipCoverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    account_ids: list[int]
    missing_or_ambiguous_account_ids: list[int]
    reason_codes: list[str]


class ExternalFlowEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    reporting_month_id: int
    account_id: int
    event_date: date
    boundary_amount: ExactMoneyOut
    direction: str
    kind: str
    scope_membership: str
    classification: str
    transfer_link_id: int | None
    transfer_status: str | None
    source: str


class ExternalFlowCoverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    flows: list[ExternalFlowEvidenceOut]
    legacy_unclassified_flow_ids: list[int]
    reason_codes: list[str]


class PerformanceMetricPrerequisitesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str
    availability: str
    reason_codes: list[str]


class PerformanceAvailabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    account_id: int | None
    start_date: date
    end_date: date
    performance_currency: str
    availability: str
    reason_codes: list[str]
    opening_valuation: ValuationBoundaryOut
    closing_valuation: ValuationBoundaryOut
    scope_membership: ScopeMembershipCoverageOut
    external_flows: ExternalFlowCoverageOut
    xirr: PerformanceMetricPrerequisitesOut
    twrr: PerformanceMetricPrerequisitesOut


def _money(amount_kopecks: int, currency: str) -> ExactMoneyOut:
    return ExactMoneyOut(
        amount=RubleAmount(amount_kopecks).to_api(),
        currency=currency,
    )


def _valuation_coverage(point: ValuationPoint) -> ValuationCoverageOut:
    coverage = point.coverage
    return ValuationCoverageOut(
        status=coverage.status.value,
        components=[
            ValuationComponentOut(
                name=component.name,
                status=component.status.value,
                amount=(
                    None
                    if component.amount is None
                    else _money(component.amount.kopecks, point.performance_currency)
                ),
                source_kind=component.source_kind,
                source_ids=list(component.source_ids),
                reason_codes=list(component.reason_codes),
            )
            for component in coverage.components
        ],
        reason_codes=list(coverage.reason_codes),
        scope_membership_status=coverage.scope_membership_status.value,
        scope_membership_reason_codes=list(coverage.scope_membership_reason_codes),
    )


def _valuation_boundary(
    evidence: ValuationBoundaryEvidence,
    *,
    fallback_currency: str,
) -> ValuationBoundaryOut:
    point = evidence.point
    if point is None:
        return ValuationBoundaryOut(
            role=evidence.role,
            requested_date=evidence.requested_date,
            availability="not_computable",
            reporting_month_id=None,
            valuation_date=None,
            status="missing",
            quality="unavailable",
            performance_currency=fallback_currency,
            total_value=None,
            coverage=None,
            provenance=[],
            reason_codes=list(evidence.reason_codes),
        )
    return ValuationBoundaryOut(
        role=evidence.role,
        requested_date=evidence.requested_date,
        availability=("available" if evidence.is_available else "not_computable"),
        reporting_month_id=evidence.reporting_month_id,
        valuation_date=point.valuation_date,
        status=point.status.value,
        quality=point.quality.value,
        performance_currency=point.performance_currency,
        total_value=(
            None
            if point.total_value is None
            else _money(point.total_value.kopecks, point.performance_currency)
        ),
        coverage=_valuation_coverage(point),
        provenance=[
            ValuationProvenanceOut(
                source_kind=item.source_kind,
                source_ids=list(item.source_ids),
                observed_date=item.observed_date,
                quality=item.quality.value,
            )
            for item in point.provenance
        ],
        reason_codes=list(evidence.reason_codes),
    )


def _response(result: PerformanceAvailability) -> PerformanceAvailabilityResponse:
    return PerformanceAvailabilityResponse(
        scope=result.scope.value,
        account_id=result.account_id,
        start_date=result.start_date,
        end_date=result.end_date,
        performance_currency=result.performance_currency,
        availability=result.availability.value,
        reason_codes=list(result.reason_codes),
        opening_valuation=_valuation_boundary(
            result.opening_valuation,
            fallback_currency=result.performance_currency,
        ),
        closing_valuation=_valuation_boundary(
            result.closing_valuation,
            fallback_currency=result.performance_currency,
        ),
        scope_membership=ScopeMembershipCoverageOut(
            status=result.scope_membership.status,
            account_ids=list(result.scope_membership.account_ids),
            missing_or_ambiguous_account_ids=list(
                result.scope_membership.missing_or_ambiguous_account_ids
            ),
            reason_codes=list(result.scope_membership.reason_codes),
        ),
        external_flows=ExternalFlowCoverageOut(
            status=result.external_flows.status,
            flows=[
                ExternalFlowEvidenceOut(
                    id=flow.id,
                    reporting_month_id=flow.reporting_month_id,
                    account_id=flow.account_id,
                    event_date=flow.event_date,
                    boundary_amount=_money(flow.boundary_amount_kopecks, flow.currency),
                    direction=flow.direction,
                    kind=flow.kind,
                    scope_membership=flow.scope_membership.value,
                    classification=flow.classification.value,
                    transfer_link_id=flow.transfer_link_id,
                    transfer_status=(
                        None if flow.transfer_status is None else flow.transfer_status.value
                    ),
                    source=flow.source,
                )
                for flow in result.external_flows.flows
            ],
            legacy_unclassified_flow_ids=list(result.external_flows.legacy_unclassified_flow_ids),
            reason_codes=list(result.external_flows.reason_codes),
        ),
        xirr=PerformanceMetricPrerequisitesOut(
            metric=result.xirr.metric,
            availability=result.xirr.availability.value,
            reason_codes=list(result.xirr.reason_codes),
        ),
        twrr=PerformanceMetricPrerequisitesOut(
            metric=result.twrr.metric,
            availability=result.twrr.availability.value,
            reason_codes=list(result.twrr.reason_codes),
        ),
    )


@router.get("/availability", response_model=PerformanceAvailabilityResponse)
def read_performance_availability(
    start_date: date = Query(...),
    end_date: date = Query(...),
    scope: PerformanceScope = Query(default=PerformanceScope.PORTFOLIO),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> PerformanceAvailabilityResponse:
    result = performance_availability_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        account_id=account_id,
    )
    return _response(result)
