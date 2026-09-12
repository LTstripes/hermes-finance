"""Read-only PERF04A selected-scope value bridge API."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain import PerformanceScope, RubleAmount
from hermes_finance.domain.performance_attribution import (
    ExternalFlowSummary,
    Perf04aCoverageEvidence,
    Perf04aEvidence,
    Perf04aValuationEvidence,
    PerformanceAttributionResult,
)
from hermes_finance.services.performance_attribution import (
    PERF04A_CONTRACT,
    PERF04A_CONTRACT_VERSION,
    PERF04A_METRIC,
    performance_attribution_for_interval,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


class ExactMoneyOut(BaseModel):
    """A signed exact integer-minor-unit amount rendered as a decimal string."""

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


class PerformanceAttributionPeriodOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date


class Perf04aValuationEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "not_computable"]
    reason_codes: list[str]


class Perf04aCoverageEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "unavailable", "unknown"]
    reason_codes: list[str]


class Perf04aEvidenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    opening_valuation: Perf04aValuationEvidenceOut
    closing_valuation: Perf04aValuationEvidenceOut
    scope_membership: Perf04aCoverageEvidenceOut
    cash_boundary_coverage: Perf04aCoverageEvidenceOut
    in_kind_boundary_coverage: Perf04aCoverageEvidenceOut
    external_flows: Perf04aCoverageEvidenceOut


class ExternalFlowSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contributions: ExactMoneyOut | None
    withdrawals: ExactMoneyOut | None
    signed_total: ExactMoneyOut | None


class PerformanceAttributionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: Literal["PERF04A"]
    contract_version: Literal[1]
    metric: Literal["value_change_after_external_flows"]
    grain: Literal["selected_scope"]
    scope: Literal["portfolio", "account"]
    account_id: int | None
    period: PerformanceAttributionPeriodOut
    performance_currency: str
    availability: Literal["available", "not_computable"]
    quality: Literal["exact", "unavailable"]
    opening_value: ExactMoneyOut | None
    closing_value: ExactMoneyOut | None
    value: ExactMoneyOut | None
    external_flow_summary: ExternalFlowSummaryOut
    evidence: Perf04aEvidenceOut
    reason_codes: list[str]


def _money(value: RubleAmount | None, currency: str) -> ExactMoneyOut | None:
    if value is None:
        return None
    return ExactMoneyOut(amount=value.to_api(), currency=currency)


def _valuation_evidence(
    evidence: Perf04aValuationEvidence,
) -> Perf04aValuationEvidenceOut:
    return Perf04aValuationEvidenceOut(
        availability=evidence.availability.value,
        reason_codes=list(evidence.reason_codes),
    )


def _coverage_evidence(evidence: Perf04aCoverageEvidence) -> Perf04aCoverageEvidenceOut:
    return Perf04aCoverageEvidenceOut(
        status=evidence.status,
        reason_codes=list(evidence.reason_codes),
    )


def _evidence(result: PerformanceAttributionResult) -> Perf04aEvidenceOut:
    evidence: Perf04aEvidence = result.evidence
    return Perf04aEvidenceOut(
        opening_valuation=_valuation_evidence(evidence.opening_valuation),
        closing_valuation=_valuation_evidence(evidence.closing_valuation),
        scope_membership=_coverage_evidence(evidence.scope_membership),
        cash_boundary_coverage=_coverage_evidence(evidence.cash_boundary_coverage),
        in_kind_boundary_coverage=_coverage_evidence(evidence.in_kind_boundary_coverage),
        external_flows=_coverage_evidence(evidence.external_flows),
    )


def _flow_summary(
    summary: ExternalFlowSummary,
    currency: str,
) -> ExternalFlowSummaryOut:
    return ExternalFlowSummaryOut(
        contributions=_money(summary.contributions, currency),
        withdrawals=_money(summary.withdrawals, currency),
        signed_total=_money(summary.signed_total, currency),
    )


def _response(result: PerformanceAttributionResult) -> PerformanceAttributionResponse:
    return PerformanceAttributionResponse(
        contract=PERF04A_CONTRACT,
        contract_version=PERF04A_CONTRACT_VERSION,
        metric=PERF04A_METRIC,
        grain="selected_scope",
        scope=result.scope.value,
        account_id=result.account_id,
        period=PerformanceAttributionPeriodOut(
            start_date=result.start_date,
            end_date=result.end_date,
        ),
        performance_currency=result.performance_currency,
        availability=result.availability.value,
        quality=result.quality.value,
        opening_value=_money(result.opening_value, result.performance_currency),
        closing_value=_money(result.closing_value, result.performance_currency),
        value=_money(result.value, result.performance_currency),
        external_flow_summary=_flow_summary(
            result.external_flow_summary,
            result.performance_currency,
        ),
        evidence=_evidence(result),
        reason_codes=list(result.reason_codes),
    )


@router.get("/attribution", response_model=PerformanceAttributionResponse)
def read_performance_attribution(
    start_date: date = Query(...),
    end_date: date = Query(...),
    scope: PerformanceScope = Query(default=PerformanceScope.PORTFOLIO),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> PerformanceAttributionResponse:
    result = performance_attribution_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
        scope=scope,
        account_id=account_id,
    )
    return _response(result)


__all__ = [
    "ExternalFlowSummaryOut",
    "PerformanceAttributionResponse",
    "PerformanceAttributionPeriodOut",
    "Perf04aCoverageEvidenceOut",
    "Perf04aEvidenceOut",
    "Perf04aValuationEvidenceOut",
    "router",
]
