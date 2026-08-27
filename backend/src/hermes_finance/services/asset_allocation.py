"""Canonical liquid-asset allocation by the accepted five dashboard classes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.liquid_capital import LiquidCapitalResult
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import Account, Instrument, PositionSnapshot

ASSET_CLASSES: tuple[str, ...] = (
    "cash",
    "deposits",
    "stocks",
    "bonds",
    "gold_other",
)


@dataclass(frozen=True, slots=True)
class AssetClassSlice:
    asset_class: str
    amount: RubleAmount


def asset_allocation_for_month(
    session: Session,
    reporting_month_id: int,
    liquid: LiquidCapitalResult,
) -> tuple[AssetClassSlice, ...]:
    """Split liquid assets into cash, deposits, stocks, bonds and gold/other.

    Securities market value is split by ``instrument_type``: ``stock`` and
    ``bond`` are their own classes; every remaining instrument type plus
    ``other_liquid_assets`` is grouped under ``gold_other``. Real estate is
    never included because it is outside liquid capital.
    """
    rows = session.execute(
        select(Instrument.instrument_type, func.sum(PositionSnapshot.market_value_kopecks))
        .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
        .join(Account, PositionSnapshot.account_id == Account.id)
        .where(PositionSnapshot.reporting_month_id == reporting_month_id)
        .where(Account.include_in_capital.is_(True))
        .group_by(Instrument.instrument_type)
    ).all()
    by_type = {instrument_type: int(total or 0) for instrument_type, total in rows}
    stocks = RubleAmount(by_type.get("stock", 0))
    bonds = RubleAmount(by_type.get("bond", 0))
    gold_other = RubleAmount(
        sum(value for kind, value in by_type.items() if kind not in ("stock", "bond"))
        + liquid.breakdown.other_liquid_assets.kopecks
    )
    return (
        AssetClassSlice("cash", liquid.breakdown.cash),
        AssetClassSlice("deposits", liquid.breakdown.deposits),
        AssetClassSlice("stocks", stocks),
        AssetClassSlice("bonds", bonds),
        AssetClassSlice("gold_other", gold_other),
    )


def asset_allocation_for_months(
    session: Session,
    reporting_month_ids: Iterable[int],
    liquid_by_month: dict[int, LiquidCapitalResult],
) -> dict[int, tuple[AssetClassSlice, ...]]:
    """Build allocations for several months with one grouped position read."""
    month_ids = tuple(dict.fromkeys(reporting_month_ids))
    if not month_ids:
        return {}

    rows = session.execute(
        select(
            PositionSnapshot.reporting_month_id,
            Instrument.instrument_type,
            func.sum(PositionSnapshot.market_value_kopecks),
        )
        .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
        .join(Account, PositionSnapshot.account_id == Account.id)
        .where(PositionSnapshot.reporting_month_id.in_(month_ids))
        .where(Account.include_in_capital.is_(True))
        .group_by(PositionSnapshot.reporting_month_id, Instrument.instrument_type)
    ).all()
    by_month: dict[int, dict[str, int]] = {month_id: {} for month_id in month_ids}
    for month_id, instrument_type, total in rows:
        by_month[month_id][instrument_type] = int(total or 0)

    allocations: dict[int, tuple[AssetClassSlice, ...]] = {}
    for month_id in month_ids:
        by_type = by_month[month_id]
        liquid = liquid_by_month[month_id]
        gold_other = RubleAmount(
            sum(value for kind, value in by_type.items() if kind not in ("stock", "bond"))
            + liquid.breakdown.other_liquid_assets.kopecks
        )
        allocations[month_id] = (
            AssetClassSlice("cash", liquid.breakdown.cash),
            AssetClassSlice("deposits", liquid.breakdown.deposits),
            AssetClassSlice("stocks", RubleAmount(by_type.get("stock", 0))),
            AssetClassSlice("bonds", RubleAmount(by_type.get("bond", 0))),
            AssetClassSlice("gold_other", gold_other),
        )
    return allocations
