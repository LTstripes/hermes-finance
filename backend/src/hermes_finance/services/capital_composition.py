"""Read-only historical liquid-asset composition for Analytics (R03-12).

The contract is fixed by ADR 0007. Historical points contain CLOSED months
only and reuse the canonical asset-allocation assembler plus the canonical
liquid-capital service. Missing calendar months are not synthesized here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import ReportingMonth
from hermes_finance.services.asset_allocation import (
    ASSET_CLASSES,
    AssetClassSlice,
    asset_allocation_for_months,
)
from hermes_finance.services.liquid_capital import liquid_capital_for_months


@dataclass(frozen=True, slots=True)
class CapitalCompositionPoint:
    reporting_month_id: int
    year: int
    month: int
    snapshot_date: date
    allocation: tuple[AssetClassSlice, ...]
    liquid_assets_total: RubleAmount
    included_debts: RubleAmount
    liquid_capital_net: RubleAmount
    linked_pair_assets: RubleAmount
    linked_pair_debts: RubleAmount
    linked_pair_net_contribution: RubleAmount


@dataclass(frozen=True, slots=True)
class CapitalCompositionHistory:
    asset_classes: tuple[str, ...]
    points: tuple[CapitalCompositionPoint, ...]


@dataclass(frozen=True, slots=True)
class ClosedReportComparison:
    """The latest closed snapshot compared with the previous closed snapshot.

    This is intentionally separate from the monthly-summary deltas.  The
    monthly summary compares against the previous chronological reporting
    month, while this read model has a closed-to-closed basis for Home.
    """

    asset_classes: tuple[str, ...]
    current: CapitalCompositionPoint | None
    previous: CapitalCompositionPoint | None
    asset_class_deltas: tuple[AssetClassSlice, ...] | None
    liquid_assets_total_delta: RubleAmount | None
    included_debts_delta: RubleAmount | None
    liquid_capital_net_delta: RubleAmount | None
    linked_pair_assets_delta: RubleAmount | None
    linked_pair_debts_delta: RubleAmount | None
    linked_pair_net_contribution_delta: RubleAmount | None


def _amount_delta(current: RubleAmount, previous: RubleAmount) -> RubleAmount:
    return RubleAmount(current.kopecks - previous.kopecks)


def closed_report_comparison(session: Session) -> ClosedReportComparison:
    """Return the latest closed report and its previous closed report.

    Draft months are excluded by :func:`capital_composition_history`, so a
    newer draft can never become either side of this comparison.  All totals
    and allocations are read from the existing canonical services.
    """

    history = capital_composition_history(session)
    current = history.points[-1] if history.points else None
    previous = history.points[-2] if len(history.points) >= 2 else None
    if current is None or previous is None:
        return ClosedReportComparison(
            asset_classes=history.asset_classes,
            current=current,
            previous=previous,
            asset_class_deltas=None,
            liquid_assets_total_delta=None,
            included_debts_delta=None,
            liquid_capital_net_delta=None,
            linked_pair_assets_delta=None,
            linked_pair_debts_delta=None,
            linked_pair_net_contribution_delta=None,
        )

    previous_allocation = {item.asset_class: item.amount for item in previous.allocation}
    asset_class_deltas = tuple(
        AssetClassSlice(
            asset_class=item.asset_class,
            amount=_amount_delta(item.amount, previous_allocation[item.asset_class]),
        )
        for item in current.allocation
    )
    return ClosedReportComparison(
        asset_classes=history.asset_classes,
        current=current,
        previous=previous,
        asset_class_deltas=asset_class_deltas,
        liquid_assets_total_delta=_amount_delta(
            current.liquid_assets_total, previous.liquid_assets_total
        ),
        included_debts_delta=_amount_delta(current.included_debts, previous.included_debts),
        liquid_capital_net_delta=_amount_delta(
            current.liquid_capital_net, previous.liquid_capital_net
        ),
        linked_pair_assets_delta=_amount_delta(
            current.linked_pair_assets, previous.linked_pair_assets
        ),
        linked_pair_debts_delta=_amount_delta(
            current.linked_pair_debts, previous.linked_pair_debts
        ),
        linked_pair_net_contribution_delta=_amount_delta(
            current.linked_pair_net_contribution, previous.linked_pair_net_contribution
        ),
    )


def capital_composition_history(session: Session) -> CapitalCompositionHistory:
    """Return deterministic CLOSED-month capital composition in calendar order."""
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        )
    )

    month_ids = [month.id for month in months]
    liquid_by_month = liquid_capital_for_months(session, month_ids)
    allocation_by_month = asset_allocation_for_months(session, month_ids, liquid_by_month)
    points: list[CapitalCompositionPoint] = []
    for month in months:
        liquid = liquid_by_month[month.id]
        allocation = allocation_by_month[month.id]
        points.append(
            CapitalCompositionPoint(
                reporting_month_id=month.id,
                year=month.year,
                month=month.month,
                snapshot_date=month.snapshot_date,
                allocation=allocation,
                liquid_assets_total=liquid.total_assets,
                included_debts=liquid.total_debts_included,
                liquid_capital_net=liquid.liquid_capital_net,
                linked_pair_assets=liquid.linked_pair_assets,
                linked_pair_debts=liquid.linked_pair_debts,
                linked_pair_net_contribution=liquid.linked_pair_net_contribution,
            )
        )

    return CapitalCompositionHistory(asset_classes=ASSET_CLASSES, points=tuple(points))
