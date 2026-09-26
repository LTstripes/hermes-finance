"""Read-only Analytics API (R03-12)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain.passive_income import PassiveIncomeResult
from hermes_finance.domain.portfolio_source_coverage import PortfolioSourceCoverage
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.capital_composition import (
    CapitalCompositionPoint,
    capital_composition_history,
    closed_report_comparison,
)
from hermes_finance.services.passive_income_history import (
    PassiveIncomeHistoryReadModel,
    PassiveIncomeSelectedReport,
    passive_income_history,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class AssetClassSliceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: str
    amount: MoneyValue


class CapitalCompositionPointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    allocation: list[AssetClassSliceOut]
    liquid_assets_total: MoneyValue
    included_debts: MoneyValue
    liquid_capital_net: MoneyValue
    portfolio_source_coverage: PortfolioSourceCoverage
    linked_pair_assets: MoneyValue
    linked_pair_debts: MoneyValue
    linked_pair_net_contribution: MoneyValue


class CapitalCompositionHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_classes: list[str]
    points: list[CapitalCompositionPointOut]


class ClosedReportSnapshotOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    year: int
    month: int
    status: Literal["closed"]
    snapshot_date: date
    allocation: list[AssetClassSliceOut]
    liquid_assets_total: MoneyValue
    included_debts: MoneyValue
    liquid_capital_net: MoneyValue
    portfolio_source_coverage: PortfolioSourceCoverage
    linked_pair_assets: MoneyValue
    linked_pair_debts: MoneyValue
    linked_pair_net_contribution: MoneyValue


class ClosedReportComparisonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparison_basis: Literal["latest_closed_to_previous_closed"]
    availability: Literal[
        "available",
        "previous_closed_report_unavailable",
        "no_closed_report",
    ]
    asset_classes: list[str]
    current: ClosedReportSnapshotOut | None
    previous: ClosedReportSnapshotOut | None
    asset_class_deltas: list[AssetClassSliceOut] | None
    liquid_assets_total_delta: MoneyValue | None
    included_debts_delta: MoneyValue | None
    liquid_capital_net_delta: MoneyValue | None
    liquid_capital_net_delta_coverage: PortfolioSourceCoverage | None
    linked_pair_assets_delta: MoneyValue | None
    linked_pair_debts_delta: MoneyValue | None
    linked_pair_net_contribution_delta: MoneyValue | None
    net_liquid_capital_reconciles: bool | None


class PassiveIncomeBreakdownOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deposit_interest: MoneyValue
    bond_coupons: MoneyValue
    dividends: MoneyValue
    other_capital_income: MoneyValue
    total_net_passive_income: MoneyValue


class PassiveIncomeHistoryPointOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    passive_income_actual: MoneyValue
    included_in_average_window: bool


class PassiveIncomeAverageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    average: MoneyValue
    count_months: int
    target_window_months: int
    is_complete_12m: bool
    configured_start_month: str | None
    months_used: list[str]


class PassiveIncomeSelectedReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    passive_income_actual: MoneyValue
    breakdown: PassiveIncomeBreakdownOut


class PassiveIncomeHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[PassiveIncomeHistoryPointOut]
    average: PassiveIncomeAverageOut
    latest_closed_report_id: int | None
    selected_report: PassiveIncomeSelectedReportOut | None


def _money(amount: RubleAmount) -> MoneyValue:
    return MoneyValue(amount=amount.to_api(), currency="RUB")


def _snapshot(point: CapitalCompositionPoint) -> ClosedReportSnapshotOut:
    return ClosedReportSnapshotOut(
        reporting_month_id=point.reporting_month_id,
        year=point.year,
        month=point.month,
        status="closed",
        snapshot_date=point.snapshot_date,
        allocation=[
            AssetClassSliceOut(asset_class=item.asset_class, amount=_money(item.amount))
            for item in point.allocation
        ],
        liquid_assets_total=_money(point.liquid_assets_total),
        included_debts=_money(point.included_debts),
        liquid_capital_net=_money(point.liquid_capital_net),
        portfolio_source_coverage=point.portfolio_source_coverage,
        linked_pair_assets=_money(point.linked_pair_assets),
        linked_pair_debts=_money(point.linked_pair_debts),
        linked_pair_net_contribution=_money(point.linked_pair_net_contribution),
    )


def _passive_income_breakdown_out(result: PassiveIncomeResult) -> PassiveIncomeBreakdownOut:
    breakdown = result.breakdown
    return PassiveIncomeBreakdownOut(
        deposit_interest=_money(breakdown.deposit_interest),
        bond_coupons=_money(breakdown.bond_coupons),
        dividends=_money(breakdown.dividends),
        other_capital_income=_money(breakdown.other_capital_income),
        total_net_passive_income=_money(result.total_net_passive_income),
    )


def _passive_income_selected_out(
    selected: PassiveIncomeSelectedReport,
) -> PassiveIncomeSelectedReportOut:
    return PassiveIncomeSelectedReportOut(
        reporting_month_id=selected.reporting_month_id,
        year=selected.year,
        month=selected.month,
        snapshot_date=selected.snapshot_date,
        passive_income_actual=_money(selected.result.total_net_passive_income),
        breakdown=_passive_income_breakdown_out(selected.result),
    )


def passive_income_history_to_out(
    history: PassiveIncomeHistoryReadModel,
) -> PassiveIncomeHistoryOut:
    average = history.average
    return PassiveIncomeHistoryOut(
        points=[
            PassiveIncomeHistoryPointOut(
                reporting_month_id=point.reporting_month_id,
                year=point.year,
                month=point.month,
                snapshot_date=point.snapshot_date,
                passive_income_actual=_money(point.passive_income_actual),
                included_in_average_window=point.included_in_average_window,
            )
            for point in history.points
        ],
        average=PassiveIncomeAverageOut(
            average=_money(average.average),
            count_months=average.count_months,
            target_window_months=12,
            is_complete_12m=average.is_complete_12m,
            configured_start_month=average.configured_start_month,
            months_used=list(average.months_used),
        ),
        latest_closed_report_id=history.latest_closed_report_id,
        selected_report=(
            _passive_income_selected_out(history.selected_report)
            if history.selected_report is not None
            else None
        ),
    )


@router.get("/capital-composition", response_model=CapitalCompositionHistoryOut)
def get_capital_composition(
    session: Session = Depends(session_for_request),
) -> CapitalCompositionHistoryOut:
    history = capital_composition_history(session)
    return CapitalCompositionHistoryOut(
        asset_classes=list(history.asset_classes),
        points=[
            CapitalCompositionPointOut(
                reporting_month_id=point.reporting_month_id,
                year=point.year,
                month=point.month,
                snapshot_date=point.snapshot_date,
                allocation=[
                    AssetClassSliceOut(
                        asset_class=item.asset_class,
                        amount=_money(item.amount),
                    )
                    for item in point.allocation
                ],
                liquid_assets_total=_money(point.liquid_assets_total),
                included_debts=_money(point.included_debts),
                liquid_capital_net=_money(point.liquid_capital_net),
                portfolio_source_coverage=point.portfolio_source_coverage,
                linked_pair_assets=_money(point.linked_pair_assets),
                linked_pair_debts=_money(point.linked_pair_debts),
                linked_pair_net_contribution=_money(point.linked_pair_net_contribution),
            )
            for point in history.points
        ],
    )


@router.get(
    "/closed-report-comparison",
    response_model=ClosedReportComparisonOut,
)
def get_closed_report_comparison(
    session: Session = Depends(session_for_request),
) -> ClosedReportComparisonOut:
    comparison = closed_report_comparison(session)
    if comparison.current is None:
        availability: Literal[
            "available", "previous_closed_report_unavailable", "no_closed_report"
        ] = "no_closed_report"
    elif comparison.previous is None:
        availability = "previous_closed_report_unavailable"
    else:
        availability = "available"

    has_previous = comparison.previous is not None
    reconciles = None
    if has_previous:
        assert comparison.liquid_assets_total_delta is not None
        assert comparison.included_debts_delta is not None
        assert comparison.liquid_capital_net_delta is not None
        reconciles = (
            comparison.liquid_assets_total_delta.kopecks - comparison.included_debts_delta.kopecks
            == comparison.liquid_capital_net_delta.kopecks
        )

    return ClosedReportComparisonOut(
        comparison_basis="latest_closed_to_previous_closed",
        availability=availability,
        asset_classes=list(comparison.asset_classes),
        current=_snapshot(comparison.current) if comparison.current is not None else None,
        previous=_snapshot(comparison.previous) if comparison.previous is not None else None,
        asset_class_deltas=(
            [
                AssetClassSliceOut(asset_class=item.asset_class, amount=_money(item.amount))
                for item in comparison.asset_class_deltas
            ]
            if comparison.asset_class_deltas is not None
            else None
        ),
        liquid_assets_total_delta=(
            _money(comparison.liquid_assets_total_delta)
            if comparison.liquid_assets_total_delta is not None
            else None
        ),
        included_debts_delta=(
            _money(comparison.included_debts_delta)
            if comparison.included_debts_delta is not None
            else None
        ),
        liquid_capital_net_delta=(
            _money(comparison.liquid_capital_net_delta)
            if comparison.liquid_capital_net_delta is not None
            else None
        ),
        liquid_capital_net_delta_coverage=comparison.liquid_capital_net_delta_coverage,
        linked_pair_assets_delta=(
            _money(comparison.linked_pair_assets_delta)
            if comparison.linked_pair_assets_delta is not None
            else None
        ),
        linked_pair_debts_delta=(
            _money(comparison.linked_pair_debts_delta)
            if comparison.linked_pair_debts_delta is not None
            else None
        ),
        linked_pair_net_contribution_delta=(
            _money(comparison.linked_pair_net_contribution_delta)
            if comparison.linked_pair_net_contribution_delta is not None
            else None
        ),
        net_liquid_capital_reconciles=reconciles,
    )


@router.get("/passive-income", response_model=PassiveIncomeHistoryOut)
def get_passive_income_history(
    reporting_month_id: int | None = Query(default=None, gt=0),
    session: Session = Depends(session_for_request),
) -> PassiveIncomeHistoryOut:
    """Return closed actual history and one closed report's source buckets."""
    return passive_income_history_to_out(
        passive_income_history(
            session,
            selected_reporting_month_id=reporting_month_id,
        )
    )
