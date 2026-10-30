"""Read-only all-history presentation with separate, explicit metric bases."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from hermes_finance.api.returns_view import DTO, Metric, Period, Result, no_store
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.returns_overall import read_overall

router = APIRouter(prefix="/api/returns", tags=["returns"])


class OverallResult(DTO):
    pnl: Metric
    rate: Metric
    partial: Literal[True]
    reason_codes: list[str]


class SourceAccount(DTO):
    scope: str
    label: str
    period: Period | None
    result: Result | None
    proof_status: Literal["current", "stale", "absent", "conflict"]
    reason_codes: list[str]
    instrument_count: int


class InstrumentAccount(Result):
    period: Period | None
    scope: str
    label: str


class OverallInstrument(DTO):
    isin: str
    name: str
    kind: str | None
    accounts: list[InstrumentAccount]
    reason_codes: list[str]


class DepositPeriod(DTO):
    period: Period
    status: str
    rows: int


class Deposits(DTO):
    interest: Metric
    partial: Literal[True]
    periods: list[DepositPeriod]
    reason_codes: list[str]


class GoldSnapshot(DTO):
    account_id: int
    instrument_id: int
    label: str
    date: date
    quantity: str
    market_value: Metric
    cost_basis: Metric
    unrealized_result: Metric
    cost_return: Metric


class Gold(DTO):
    snapshots: list[GoldSnapshot]
    period_result: Metric
    reason_codes: list[str]


class ComponentCoverage(DTO):
    status: Literal["supported", "partial", "unavailable", "conflict"]
    reason_codes: list[str]


class MixedComponent(DTO):
    id: str
    category: Literal["brokerage", "deposits", "gold"]
    label: str
    selected: bool
    available: bool
    included: bool
    amount: Metric
    interval: Period | None
    valuation_date: date | None
    coverage: ComponentCoverage
    method: str
    authority: Literal["source_only", "accepted_snapshot"]
    exclusion_reason: str | None


class MixedResult(DTO):
    known_result: Metric
    rate: Metric
    selected_component_count: int
    available_component_count: int
    included_component_count: int
    components: list[MixedComponent]
    reason_codes: list[str]


class Overall(DTO):
    contract_version: Literal["returns_overall_v1"]
    overall: OverallResult
    source_accounts: list[SourceAccount]
    instruments: list[OverallInstrument]
    deposits: Deposits
    gold: Gold
    mixed_result: MixedResult
    reason_codes: list[str]


@router.get("/overall", response_model=Overall)
def overall(response: Response, session: Session = Depends(session_for_request)):
    no_store(response)
    return read_overall(session)
