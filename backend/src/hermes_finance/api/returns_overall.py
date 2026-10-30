"""Read-only all-history presentation with separate, explicit metric bases."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from hermes_finance.api.returns_view import DTO, Detail, Metric, Period, Result, no_store, read
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.returns_overall import read_income, read_instrument_card, read_overall

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
    canonical_account_id: int | None = None
    details_loaded: bool = True


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


class GoldHistory(DTO):
    account_id: int
    instrument_id: int
    label: str
    revision: int
    source_kind: Literal["owner_manual_gold_history"]
    authority: Literal["owner_attestation"]
    currentness: Literal["current", "dependency_changed"]
    period: Period | None
    valuation_date: date | None
    valuation_status: Literal["draft", "closed"] | None
    amount_basis: Literal["actual", "derived"]
    tax_treatment: Literal["not_provided"]
    total_result: Metric
    realized_result: Metric
    unrealized_result: Metric
    buy_amount: Metric
    sale_amount: Metric
    separate_fees: Metric
    reason_codes: list[str]


class Gold(DTO):
    snapshots: list[GoldSnapshot]
    histories: list[GoldHistory]
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
    authority: Literal["source_only", "accepted_snapshot", "owner_attestation"]
    exclusion_reason: str | None


class MixedResult(DTO):
    known_result: Metric
    rate: Metric
    selected_component_count: int
    available_component_count: int
    included_component_count: int
    components: list[MixedComponent]
    reason_codes: list[str]


class CouponAccount(DTO):
    scope: str
    label: str
    period: Period | None
    amount: Metric
    proof_status: Literal["current", "stale", "absent", "conflict"]
    included: bool
    exclusion_reason: str | None
    reason_codes: list[str]


class CouponIncome(DTO):
    known_total: Metric
    partial: Literal[True]
    selected_accounts: int
    included_accounts: int
    accounts: list[CouponAccount]
    reason_codes: list[str]


class Overall(DTO):
    contract_version: Literal["returns_overall_v1"]
    overall: OverallResult
    source_accounts: list[SourceAccount]
    instruments: list[OverallInstrument]
    deposits: Deposits
    gold: Gold
    mixed_result: MixedResult
    coupon_income: CouponIncome
    dividend_income: CouponIncome
    reason_codes: list[str]


@router.get("/overall", response_model=Overall)
def overall(response: Response, session: Session = Depends(session_for_request)):
    no_store(response)
    return read_overall(session)


class IncomeInstrumentAccount(DTO):
    scope: str
    label: str
    period: Period | None
    amount: Metric


class IncomeInstrument(DTO):
    isin: str
    name: str
    amount: Metric
    accounts: list[IncomeInstrumentAccount]


class IncomeEvent(DTO):
    scope: str
    label: str
    isin: str | None
    name: str | None
    date: date
    amount: Metric


class Income(DTO):
    contract_version: Literal["returns_income_v1"]
    kind: Literal["coupon", "dividend"]
    summary: CouponIncome
    instruments: list[IncomeInstrument]
    events: list[IncomeEvent]
    reason_codes: list[str]


class Quantity(DTO):
    value: str | None
    partial: Literal[True]
    reason_codes: list[str]


class CardSummary(DTO):
    quantity: Quantity
    reported_value: Metric
    valuation_dates: list[date]
    pnl: Metric
    coupons: Metric
    dividends: Metric
    valuation_and_trades: Metric
    costs: Metric
    taxes: Metric
    redemption: Metric
    rate: Metric
    partial: Literal[True]
    reason_codes: list[str]


class CardAccount(DTO):
    scope: str
    label: str
    canonical_account_id: int | None
    period: Period | None
    proof_status: Literal["current", "stale", "absent", "conflict"]
    included: bool
    exclusion_reason: str | None
    reason_codes: list[str]
    detail: Detail | None


class InstrumentCard(DTO):
    contract_version: Literal["returns_instrument_card_v1"]
    isin: str
    name: str
    kind: str | None
    summary: CardSummary
    accounts: list[CardAccount]
    reason_codes: list[str]


@router.get("/income", response_model=Income)
def income(
    request: Request,
    response: Response,
    kind: Literal["coupon", "dividend"],
    session: Session = Depends(session_for_request),
):
    no_store(response)
    if len(request.query_params.getlist("kind")) != 1:
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    return read(read_income, session, kind=kind)


@router.get("/instrument-card", response_model=InstrumentCard)
def instrument_card(
    request: Request,
    response: Response,
    isin: Annotated[str, Query(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")],
    session: Session = Depends(session_for_request),
):
    no_store(response)
    if len(request.query_params.getlist("isin")) != 1:
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    return read(read_instrument_card, session, isin=isin)
