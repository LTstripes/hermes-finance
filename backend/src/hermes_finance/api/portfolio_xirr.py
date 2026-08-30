"""Read-only whole-portfolio XIRR API (R08-02)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.valuation_points import PerformanceScope
from hermes_finance.services.portfolio_xirr import (
    PortfolioXirrResult,
    portfolio_xirr_for_interval,
)

router = APIRouter(prefix="/api/performance", tags=["performance"])


class XirrPeriodOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date


class PortfolioXirrResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal["xirr"]
    scope: Literal["portfolio"]
    performance_currency: str
    value: str | None
    value_unit: Literal["percentage_points"]
    annualized: Literal[True]
    period: XirrPeriodOut
    availability: Literal["available", "not_computable"]
    quality: Literal["exact", "unavailable"]
    reason_codes: list[str]


def _decimal_api(value: Decimal | None) -> str | None:
    if value is None:
        return None
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _response(result: PortfolioXirrResult) -> PortfolioXirrResponse:
    return PortfolioXirrResponse(
        metric="xirr",
        scope="portfolio",
        performance_currency=result.performance_currency,
        value=_decimal_api(result.value),
        value_unit="percentage_points",
        annualized=True,
        period=XirrPeriodOut(start_date=result.start_date, end_date=result.end_date),
        availability=result.availability.value,
        quality=result.quality.value,
        reason_codes=list(result.reason_codes),
    )


@router.get("/xirr", response_model=PortfolioXirrResponse)
def read_portfolio_xirr(
    start_date: date = Query(...),
    end_date: date = Query(...),
    scope: PerformanceScope = Query(default=PerformanceScope.PORTFOLIO),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> PortfolioXirrResponse:
    if scope is not PerformanceScope.PORTFOLIO or account_id is not None:
        raise ValueError("R08-02 XIRR supports portfolio scope only")
    result = portfolio_xirr_for_interval(
        session,
        start_date=start_date,
        end_date=end_date,
    )
    return _response(result)
