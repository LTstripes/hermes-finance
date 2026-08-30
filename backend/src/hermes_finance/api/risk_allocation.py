"""Read-only R07-06A allocation and concentration API."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain.risk_allocation import (
    AllocationMetric,
    AllocationSlice,
    ConcentrationItem,
    ConcentrationMetric,
    MetricSupport,
    RiskAllocationResult,
    RiskSupportStatus,
    SupportIssue,
)
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.risk_allocation import (
    DEFAULT_TOP_N,
    MAX_TOP_N,
    risk_allocation_for_month,
)

router = APIRouter(prefix="/api/analytics", tags=["risk-allocation"])


class MetricSupportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RiskSupportStatus
    reason_codes: list[str]


class SupportIssueOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str
    source_id: int | None
    status: RiskSupportStatus
    reason_codes: list[str]


class AllocationSliceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    amount: MoneyValue
    share_pct: str | None
    account_id: int | None
    instrument_id: int | None
    instrument_type: str | None


class AllocationMetricOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support: MetricSupportOut
    denominator: MoneyValue
    covered_amount: MoneyValue
    unallocated_amount: MoneyValue
    coverage_pct: str | None
    items: list[AllocationSliceOut]
    excluded: list[SupportIssueOut]


class ConcentrationItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    amount: MoneyValue
    share_pct: str | None
    account_id: int | None
    account_name: str | None
    instrument_id: int | None
    instrument_name: str | None
    instrument_type: str | None
    position_id: int | None
    event_count: int | None
    is_approximate: bool


class ConcentrationMetricOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support: MetricSupportOut
    denominator: MoneyValue
    top_n: int
    top_amount: MoneyValue
    top_share_pct: str | None
    items: list[ConcentrationItemOut]
    excluded: list[SupportIssueOut]
    is_approximate: bool


class RiskAllocationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    as_of_date: date
    base_currency: str
    liquid_assets_total: MoneyValue
    allocation_by_asset_class: AllocationMetricOut
    allocation_by_account: AllocationMetricOut
    top_positions: ConcentrationMetricOut
    payout_concentration: ConcentrationMetricOut
    redemption_concentration: ConcentrationMetricOut
    support: dict[str, MetricSupportOut]


def _money(amount: RubleAmount) -> MoneyValue:
    return MoneyValue(amount=amount.to_api(), currency="RUB")


def _percentage(value: object) -> str | None:
    return format(value, "f") if value is not None else None


def _support(support: MetricSupport) -> MetricSupportOut:
    return MetricSupportOut(
        status=support.status,
        reason_codes=list(support.reason_codes),
    )


def _issue(issue: SupportIssue) -> SupportIssueOut:
    return SupportIssueOut(
        source_kind=issue.source_kind,
        source_id=issue.source_id,
        status=issue.support.status,
        reason_codes=list(issue.support.reason_codes),
    )


def _allocation_slice(item: AllocationSlice) -> AllocationSliceOut:
    return AllocationSliceOut(
        key=item.key,
        label=item.label,
        amount=_money(item.amount),
        share_pct=_percentage(item.share_pct),
        account_id=item.account_id,
        instrument_id=item.instrument_id,
        instrument_type=item.instrument_type,
    )


def _allocation(metric: AllocationMetric) -> AllocationMetricOut:
    return AllocationMetricOut(
        support=_support(metric.support),
        denominator=_money(metric.denominator),
        covered_amount=_money(metric.covered_amount),
        unallocated_amount=_money(metric.unallocated_amount),
        coverage_pct=_percentage(metric.coverage_pct),
        items=[_allocation_slice(item) for item in metric.items],
        excluded=[_issue(issue) for issue in metric.excluded],
    )


def _concentration_item(item: ConcentrationItem) -> ConcentrationItemOut:
    return ConcentrationItemOut(
        key=item.key,
        label=item.label,
        amount=_money(item.amount),
        share_pct=_percentage(item.share_pct),
        account_id=item.account_id,
        account_name=item.account_name,
        instrument_id=item.instrument_id,
        instrument_name=item.instrument_name,
        instrument_type=item.instrument_type,
        position_id=item.position_id,
        event_count=item.event_count,
        is_approximate=item.is_approximate,
    )


def _concentration(metric: ConcentrationMetric) -> ConcentrationMetricOut:
    return ConcentrationMetricOut(
        support=_support(metric.support),
        denominator=_money(metric.denominator),
        top_n=metric.top_n,
        top_amount=_money(metric.top_amount),
        top_share_pct=_percentage(metric.top_share_pct),
        items=[_concentration_item(item) for item in metric.items],
        excluded=[_issue(issue) for issue in metric.excluded],
        is_approximate=metric.is_approximate,
    )


def _response(result: RiskAllocationResult) -> RiskAllocationOut:
    return RiskAllocationOut(
        reporting_month_id=result.reporting_month_id,
        as_of_date=result.as_of_date,
        base_currency=result.base_currency,
        liquid_assets_total=_money(result.liquid_assets_total),
        allocation_by_asset_class=_allocation(result.allocation_by_asset_class),
        allocation_by_account=_allocation(result.allocation_by_account),
        top_positions=_concentration(result.top_positions),
        payout_concentration=_concentration(result.payout_concentration),
        redemption_concentration=_concentration(result.redemption_concentration),
        support={key: _support(value) for key, value in result.support.items()},
    )


@router.get("/risk-allocation", response_model=RiskAllocationOut)
def get_risk_allocation(
    month_id: int = Query(...),
    top_n: int = Query(default=DEFAULT_TOP_N, ge=1, le=MAX_TOP_N),
    forecast_version: str = Query(
        default=DEFAULT_FORECAST_VERSION,
        min_length=1,
        max_length=32,
    ),
    session: Session = Depends(session_for_request),
) -> RiskAllocationOut:
    result = risk_allocation_for_month(
        session,
        month_id,
        top_n=top_n,
        forecast_version=forecast_version,
    )
    return _response(result)
