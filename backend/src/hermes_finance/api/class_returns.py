"""Combined read-only API for the exact RUB no-crossing class subset."""

from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.orm import Session

from hermes_finance.api.class_endpoint_eligibility import CoverageResponse
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.class_returns import class_returns_for_interval

router = APIRouter(prefix="/api/performance", tags=["performance"])


class RequestedPeriod(BaseModel):
    start_date: date
    end_date: date


class CoveredPeriod(BaseModel):
    start_date: date | None
    end_date: date | None


class ClassReturnMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    availability: Literal["available", "not_computable"]
    quality: Literal["exact", "unavailable"]
    value: Decimal | None
    value_unit: Literal["percentage_points"]
    reason_codes: list[str]
    reason_source: Literal["evidence", "solver"] | None

    @field_serializer("value")
    def serialize_value(self, value: Decimal | None) -> str | None:
        if value is None:
            return None
        rendered = format(value, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


class ClassXirrMetric(ClassReturnMetric):
    annualized: Literal[True]


class ClassTwrrMetric(ClassReturnMetric):
    annualized: Literal[False]


class ClassReturnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_class: str
    requested_period: RequestedPeriod
    actual_covered_period: CoveredPeriod
    performance_currency: str
    valuation_basis: Literal["persisted_rub_market_value_kopecks"]
    historical_account_ids: list[int]
    coverage_state: str
    coverage_provenance: list[CoverageResponse]
    eligibility_status: Literal["eligible", "unavailable", "unsupported"]
    evidence_reason_codes: list[str]
    xirr: ClassXirrMetric
    twrr: ClassTwrrMetric


@router.get("/class-returns", response_model=ClassReturnsResponse)
def read_class_returns(
    asset_class: str,
    start_date: date,
    end_date: date,
    session: Session = Depends(session_for_request),
) -> dict:
    return class_returns_for_interval(
        session, asset_class=asset_class, start_date=start_date, end_date=end_date
    )
