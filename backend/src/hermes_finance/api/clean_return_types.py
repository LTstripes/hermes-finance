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
