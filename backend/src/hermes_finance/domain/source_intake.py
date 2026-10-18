"""Strict zero-economic journal command DTOs; no client proof/waiver flags."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstrumentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    isin: str = Field(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    hermes_id: int | None = Field(default=None, gt=0, strict=True)
    proof_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CurrencyOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    isin: str = Field(min_length=1, max_length=32)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class SaveIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["source_intake_v1"] = "source_intake_v1"
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    account_id: int | None = Field(default=None, gt=0, strict=True)
    reporting_month_id: int | None = Field(default=None, gt=0, strict=True)


class ReviewIntake(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["source_intake_v1"] = "source_intake_v1"
    expected_head_seq: int = Field(gt=0, strict=True)
    account_id: int | None = Field(default=None, gt=0, strict=True)
    reporting_month_id: int | None = Field(default=None, gt=0, strict=True)
    default_enabled: bool = Field(default=True, strict=True)
    account_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    overrides: list[CurrencyOverride] = Field(default_factory=list, max_length=1000)
    instrument_decisions: list[InstrumentSelection] = Field(default_factory=list, max_length=1000)
    deferred_isins: list[str] = Field(default_factory=list, max_length=1000)
    finance_request_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


class ConfirmIntake(ReviewIntake):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    confirmation_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
