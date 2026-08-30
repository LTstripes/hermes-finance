"""Read-only freshness/provenance summary API (R07-07 / issue #139)."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.market_data import moscow_today
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.freshness_provenance import (
    FreshnessCoverage,
    FreshnessFamily,
    FreshnessItem,
    FreshnessProvenanceSummary,
    FreshnessReason,
    ReportingMonthContext,
    build_freshness_provenance_summary,
)

router = APIRouter(prefix="/api/months", tags=["freshness-provenance"])


class FreshnessReasonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str


class FreshnessCoverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_count: int
    current_count: int
    stale_count: int
    unavailable_count: int
    unknown_count: int
    missing_count: int
    manual_count: int
    provider_count: int


class FreshnessItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_kind: str
    label: str
    freshness_status: str
    source_kind: str
    source_timestamp_kind: str
    source_date: date | None
    source_datetime: datetime | None
    fetched_at: datetime | None
    import_apply_time: datetime | None
    local_edit_time: datetime | None
    reason_codes: list[str]
    account_name: str | None = None
    instrument_name: str | None = None


class FreshnessFamilyOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family_id: str
    title: str
    status: str
    providers: list[str]
    coverage: FreshnessCoverageOut
    reasons: list[FreshnessReasonOut]
    items: list[FreshnessItemOut]


class ReportingMonthContextOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    year: int
    month: int
    status: str
    snapshot_date: date
    source: str


class FreshnessProvenanceSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month: ReportingMonthContextOut
    evaluated_on: date
    quote_valuation_target_date: date
    generated_at: datetime
    families: list[FreshnessFamilyOut]
    reasons: list[FreshnessReasonOut]
    providers: list[str]


def _reason_out(reason: FreshnessReason) -> FreshnessReasonOut:
    return FreshnessReasonOut(
        code=reason.code.value,
        severity=reason.severity.value,
        message=reason.message,
    )


def _coverage_out(coverage: FreshnessCoverage) -> FreshnessCoverageOut:
    return FreshnessCoverageOut(
        row_count=coverage.row_count,
        current_count=coverage.current_count,
        stale_count=coverage.stale_count,
        unavailable_count=coverage.unavailable_count,
        unknown_count=coverage.unknown_count,
        missing_count=coverage.missing_count,
        manual_count=coverage.manual_count,
        provider_count=coverage.provider_count,
    )


def _item_out(item: FreshnessItem) -> FreshnessItemOut:
    return FreshnessItemOut(
        item_kind=item.item_kind,
        label=item.label,
        freshness_status=item.freshness_status.value,
        source_kind=item.source_kind,
        source_timestamp_kind=item.source_timestamp_kind.value,
        source_date=item.source_date,
        source_datetime=item.source_datetime,
        fetched_at=item.fetched_at,
        import_apply_time=item.import_apply_time,
        local_edit_time=item.local_edit_time,
        reason_codes=[code.value for code in item.reason_codes],
        account_name=item.account_name,
        instrument_name=item.instrument_name,
    )


def _family_out(family: FreshnessFamily) -> FreshnessFamilyOut:
    return FreshnessFamilyOut(
        family_id=family.family_id.value,
        title=family.title,
        status=family.status.value,
        providers=list(family.providers),
        coverage=_coverage_out(family.coverage),
        reasons=[_reason_out(reason) for reason in family.reasons],
        items=[_item_out(item) for item in family.items],
    )


def _month_out(month: ReportingMonthContext) -> ReportingMonthContextOut:
    return ReportingMonthContextOut(
        id=month.id,
        year=month.year,
        month=month.month,
        status=month.status,
        snapshot_date=month.snapshot_date,
        source=month.source,
    )


def _summary_out(summary: FreshnessProvenanceSummary) -> FreshnessProvenanceSummaryOut:
    return FreshnessProvenanceSummaryOut(
        reporting_month=_month_out(summary.reporting_month),
        evaluated_on=summary.evaluated_on,
        quote_valuation_target_date=summary.quote_valuation_target_date,
        generated_at=summary.generated_at,
        families=[_family_out(family) for family in summary.families],
        reasons=[_reason_out(reason) for reason in summary.reasons],
        providers=list(summary.providers),
    )


@router.get("/{month_id}/freshness-provenance", response_model=FreshnessProvenanceSummaryOut)
def get_freshness_provenance(
    month_id: int,
    request: Request,
    session: Session = Depends(session_for_request),
) -> FreshnessProvenanceSummaryOut:
    today = moscow_today(request)
    clock = getattr(request.app.state, "freshness_generated_at", None)
    generated_at = clock() if callable(clock) else None
    summary = build_freshness_provenance_summary(
        session,
        month_id,
        today=today,
        generated_at=generated_at,
    )
    return _summary_out(summary)
