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


@dataclass(frozen=True, slots=True)
class CapitalCompositionHistory:
    asset_classes: tuple[str, ...]
    points: tuple[CapitalCompositionPoint, ...]


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
            )
        )

    return CapitalCompositionHistory(asset_classes=ASSET_CLASSES, points=tuple(points))
