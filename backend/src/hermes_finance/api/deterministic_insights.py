"""Read-only deterministic financial insights API (R07-11A / issue #178)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.deterministic_insights import (
    DeterministicInsight,
    DeterministicInsightsResult,
    InsightPeriod,
    InsightProvenance,
    InsightSeverity,
    build_deterministic_insights,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION

router = APIRouter(prefix="/api/months", tags=["deterministic-insights"])


class InsightPeriodOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int


class InsightProvenanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    provider: str | None
    observed_at: date | None


class DeterministicInsightOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    type: str
    severity: InsightSeverity
    message: str
    evidence: dict[str, object]
    comparison_period: InsightPeriodOut | None
    source: str
    as_of: date | None
    provenance: list[InsightProvenanceOut]
    reason: str


class DeterministicInsightsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: str
    ruleset_version: str
    forecast_version: str
    reporting_month_id: int
    year: int
    month: int
    status: str
    snapshot_date: date | None
    evaluated_on: date
    insights: list[DeterministicInsightOut]


def _period_out(period: InsightPeriod | None) -> InsightPeriodOut | None:
    if period is None:
        return None
    return InsightPeriodOut(year=period.year, month=period.month)


def _provenance_out(provenance: InsightProvenance) -> InsightProvenanceOut:
    return InsightProvenanceOut(
        source=provenance.source,
        provider=provenance.provider,
        observed_at=provenance.observed_at,
    )


def _insight_out(insight: DeterministicInsight) -> DeterministicInsightOut:
    return DeterministicInsightOut(
        code=insight.code,
        type=insight.type,
        severity=insight.severity,
        message=insight.message,
        evidence=insight.evidence,
        comparison_period=_period_out(insight.comparison_period),
        source=insight.source,
        as_of=insight.as_of,
        provenance=[_provenance_out(item) for item in insight.provenance],
        reason=insight.reason,
    )


def deterministic_insights_to_out(
    result: DeterministicInsightsResult,
) -> DeterministicInsightsOut:
    return DeterministicInsightsOut(
        contract_version=result.contract_version,
        ruleset_version=result.ruleset_version,
        forecast_version=result.forecast_version,
        reporting_month_id=result.reporting_month_id,
        year=result.year,
        month=result.month,
        status=result.status,
        snapshot_date=result.snapshot_date,
        evaluated_on=result.evaluated_on,
        insights=[_insight_out(item) for item in result.insights],
    )


@router.get(
    "/{month_id}/deterministic-insights",
    response_model=DeterministicInsightsOut,
)
def get_deterministic_insights(
    month_id: int,
    request: Request,
    forecast_version: str = Query(
        default=DEFAULT_FORECAST_VERSION,
        min_length=1,
        max_length=32,
    ),
    session: Session = Depends(session_for_request),
) -> DeterministicInsightsOut:
    result = build_deterministic_insights(
        session,
        month_id,
        evaluated_on=moscow_today(request),
        forecast_version=forecast_version,
    )
    return deterministic_insights_to_out(result)
