"""Read-only Analytics API (R03-12)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain.values import RubleAmount
from hermes_finance.services.capital_composition import capital_composition_history

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


class CapitalCompositionHistoryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_classes: list[str]
    points: list[CapitalCompositionPointOut]


def _money(amount: RubleAmount) -> MoneyValue:
    return MoneyValue(amount=amount.to_api(), currency="RUB")


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
            )
            for point in history.points
        ],
    )
