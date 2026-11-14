"""Read-only all-history presentation with separate, explicit metric bases."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from hermes_finance.api.clean_return_types import (
    CleanDietzMetric,
    CleanInstrument,
    CleanMetric,
    CleanPositionRate,
    CleanPurchase,
)
from hermes_finance.api.read_cache import cached_read_endpoint
from hermes_finance.api.returns_view import (
    DTO,
    AccountLink,
    Detail,
    Metric,
    Period,
    Result,
    no_store,
    read,
)
from hermes_finance.api.settings import session_for_request
from hermes_finance.services.returns_overall import (
    read_clean_income,
    read_clean_instrument_card,
    read_clean_overall,
    read_income,
    read_instrument_card,
    read_overall,
)

router = APIRouter(prefix="/api/returns", tags=["returns"])


class HomeResult(DTO):
    amount: Metric
    partial: bool


class HomeAccount(DTO):
    scope: str
    label: str
    account_link: AccountLink | None


class HomeInstrument(DTO):
    isin: str
    name: str
    pnl: Metric
    accounts: list[HomeAccount]


class HomeSummary(DTO):
    contract_version: Literal["returns_home_summary_v1"]
    result: HomeResult
    positive: int
    negative: int
    unknown: int
    unchanged: int
    mixed_periods: bool
    ranked: list[HomeInstrument]


@router.get("/home-summary", response_model=HomeSummary)
@cached_read_endpoint
def home_summary(response: Response, session: Session = Depends(session_for_request)):
    from hermes_finance.services.returns_home import read_home_summary

    no_store(response)
    return read_home_summary(session)


class OverallResult(DTO):
    pnl: Metric
    rate: Metric
    partial: Literal[True]
    reason_codes: list[str]


class SourceAccount(DTO):
    account_link: AccountLink | None = None
    valuation_date: date | None
    scope: str
    label: str
    period: Period | None
    result: Result | None
    proof_status: Literal["current", "stale", "absent", "conflict"]
    reason_codes: list[str]
    instrument_count: int


class PositionDietzAlias(Metric):
    for_position_comparison: Literal[False]


class InstrumentAccount(Result):
    rate: PositionDietzAlias | Metric
    period: Period | None
    scope: str
    label: str
    canonical_account_id: int | None = None
    details_loaded: bool = True
    native_period: bool = False


class CleanInstrumentAccount(InstrumentAccount):
    simple_return: CleanPositionRate
    xirr: CleanPositionRate
    modified_dietz: CleanDietzMetric | CleanMetric
    realized_result: Metric
    unrealized_result: Metric
    current_value: Metric
    is_open: bool | None
    position_reason_codes: list[str]


class PositionResults(DTO):
    realized_result: CleanMetric
    unrealized_result: CleanMetric
    current_value: CleanMetric
    is_open: bool | None
    position_reason_codes: list[str]


class InstrumentAggregate(PositionResults):
    pnl: CleanMetric
    simple_return: CleanPositionRate
    xirr: CleanPositionRate


class InstrumentPosition(CleanInstrument, PositionResults):
    pass


class OverallInstrument(DTO):
    aggregate: InstrumentAggregate | None = None
    isin: str
    name: str
    kind: str | None
    accounts: list[CleanInstrumentAccount | InstrumentAccount]
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


class GoldTarget(DTO):
    account_id: int
    instrument_id: int
    label: str


class Gold(DTO):
    snapshots: list[GoldSnapshot]
    histories: list[GoldHistory]
    targets: list[GoldTarget]
    period_result: Metric
    reason_codes: list[str]


class ComponentCoverage(DTO):
    status: Literal["supported", "partial", "unavailable", "conflict"]
    reason_codes: list[str]


class MixedComponent(DTO):
    account_link: AccountLink | None = None
    period: Period | None
    id: str
    category: Literal["brokerage", "iis", "brokerage_iis", "deposits", "gold"]
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
    account_link: AccountLink | None = None
    valuation_date: date | None
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
    contract_version: Literal["returns_overall_v1", "returns_overall_v2"]
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
@cached_read_endpoint
def overall(
    request: Request,
    response: Response,
    include_instrument_summaries: Literal["true", "false"] = "false",
    basis: Literal["clean", "legacy"] = "clean",
    session: Session = Depends(session_for_request),
):
    no_store(response)
    if len(request.query_params.getlist("include_instrument_summaries")) > 1:
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    # An explicit visible summary table may request the existing guarded
    # instrument projection. This still defers XIRR and never reads cards.
    reader = read_clean_overall if basis == "clean" else read_overall
    return reader(session, include_instrument_details=include_instrument_summaries == "true")


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
    contract_version: Literal["returns_income_v1", "returns_income_v2"]
    kind: Literal["coupon", "dividend"]
    summary: CouponIncome
    instruments: list[IncomeInstrument]
    events: list[IncomeEvent]
    reason_codes: list[str]


class Quantity(DTO):
    value: str | None
    partial: bool
    reason_codes: list[str]


class CardSummary(DTO):
    quantity: Quantity
    reported_value: Metric
    valuation_dates: list[date]
    pnl: Metric
    coupons: Metric
    dividends: Metric
    payouts: Metric | None = None
    valuation_and_trades: Metric
    costs: Metric
    taxes: Metric
    redemption: Metric
    rate: PositionDietzAlias | Metric
    partial: bool
    reason_codes: list[str]


class CardAccount(DTO):
    account_link: AccountLink | None = None
    valuation_date: date | None
    scope: str
    label: str
    canonical_account_id: int | None
    period: Period | None
    proof_status: Literal["current", "stale", "absent", "conflict"]
    included: bool
    exclusion_reason: str | None
    reason_codes: list[str]
    detail: Detail | None
    clean: InstrumentPosition | CleanInstrument | None = None
    ai_account_ref: str | None = None
    purchases: list[CleanPurchase] | None = None


class InstrumentCard(DTO):
    aggregate: InstrumentAggregate | None = None
    contract_version: Literal["returns_instrument_card_v1", "returns_instrument_card_v2"]
    isin: str
    name: str
    kind: str | None
    summary: CardSummary
    accounts: list[CardAccount]
    reason_codes: list[str]


@router.get("/income", response_model=Income)
@cached_read_endpoint
def income(
    request: Request,
    response: Response,
    kind: Literal["coupon", "dividend"],
    basis: Literal["clean", "legacy"] = "clean",
    session: Session = Depends(session_for_request),
):
    no_store(response)
    if len(request.query_params.getlist("kind")) != 1:
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    return read(read_clean_income if basis == "clean" else read_income, session, kind=kind)


@router.get("/instrument-card", response_model=InstrumentCard, response_model_exclude_unset=True)
@cached_read_endpoint
def instrument_card(
    request: Request,
    response: Response,
    isin: Annotated[str, Query(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")],
    basis: Literal["clean", "legacy"] = "clean",
    session: Session = Depends(session_for_request),
):
    no_store(response)
    if len(request.query_params.getlist("isin")) != 1:
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    reader = read_clean_instrument_card if basis == "clean" else read_instrument_card
    return read(reader, session, isin=isin)
