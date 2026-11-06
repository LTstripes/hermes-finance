"""Exact transport types for the clean return projection."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class CleanMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Annotated[str | None, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
    status: Literal["supported", "provisional", "partial", "unavailable"]
    reason_codes: tuple[str, ...]
    assumptions: tuple[str, ...]


class CleanPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]
    date: date
    settlement_date: date
    quantity: Annotated[str, Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")]
    remaining_quantity: Annotated[str | None, Field(pattern=r"^[0-9]+(?:\.[0-9]+)?$")]
    cost_kopecks: Annotated[str | None, Field(pattern=r"^[0-9]+$")]
    sale_proceeds_kopecks: Annotated[str | None, Field(pattern=r"^[0-9]+$")]
    value_kopecks: Annotated[str | None, Field(pattern=r"^[0-9]+$")]
    price_result_kopecks: Annotated[str | None, Field(pattern=r"^-?[0-9]+$")]
    return_fraction: Annotated[str | None, Field(pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
    status: Literal["supported", "partial"]
    reason_codes: tuple[str, ...]


class CleanInstrument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    isin: Annotated[str, Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")]
    name: str | None
    instrument_type: str | None
    opening_date: date
    closing_date: date
    opening_value: CleanMetric
    closing_value: CleanMetric
    buys: CleanMetric
    sells: CleanMetric
    coupons: CleanMetric
    dividends: CleanMetric
    payouts: CleanMetric
    redemption: CleanMetric
    valuation_and_trades: CleanMetric
    known_result: CleanMetric
    pnl: CleanMetric
    modified_dietz: CleanMetric
