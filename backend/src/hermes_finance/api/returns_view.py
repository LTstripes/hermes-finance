"""Exact, allowlisted presentation DTOs for the ordinary Returns workspace."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, field_serializer
from sqlalchemy.orm import Session

from hermes_finance.api.settings import session_for_request
from hermes_finance.domain.instrument_return import InstrumentAnalysis
from hermes_finance.services import returns_basket, returns_view

router = APIRouter(prefix="/api/returns", tags=["returns"])


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Period(DTO):
    start: date
    end: date


class Metric(DTO):
    value: str | None
    reason_codes: list[str]
    method: str
    unit: Literal["kopecks", "fraction", "percentage_points"]
    estimate: bool


class Result(DTO):
    period: Period
    pnl: Metric
    rate: Metric
    coupons: Metric
    dividends: Metric


class Account(DTO):
    id: str
    label: str
    basis: Literal["statements", "accepted"]


class Context(DTO):
    accounts: list[Account]
    scope_aliases: dict[str, str]
    source_periods: dict[str, list[Period]]
    default_period: Period | None
    closed_periods: list[Period]


class Instrument(DTO):
    isin: str
    name: str
    kind: str | None
    period: Period
    pnl: Metric
    rate: Metric
    coupons: Metric
    dividends: Metric
    conditional: bool


class MissingMonth(DTO):
    period: Period
    reason_codes: list[str]


class AvailableMonths(DTO):
    period: Period
    partial: Literal[True]
    pnl: Metric
    included: list[Period]
    missing: list[MissingMonth]
    covered_months: int
    total_months: int


class Overview(DTO):
    scope: str
    selected: Result
    all_history: Result | None
    available_months_total: AvailableMonths | None
    selected_available_months_total: AvailableMonths | None
    history: list[Result]
    periods: list[Period]
    instruments: list[Instrument]
    instrument_reason_codes: list[str]
    proof_status: str


class Event(DTO):
    ordinal: int
    kind: str
    date: date | None
    cash_date: date | None
    quantity_date: date | None
    quantity: str | None
    amount: Metric
    counted: bool


class Detail(Instrument):
    scope: str
    analysis: InstrumentAnalysis
    opening_quantity: str | None
    closing_quantity: str | None
    buys: Metric
    sells: Metric
    conditional_pnl: Metric
    conditional_rate: Metric
    reason_codes: list[str]
    events: list[Event]

    @field_serializer("analysis", mode="wrap", when_used="json")
    def exact_analysis(self, value, handler) -> dict:
        """Reuse the v2 allowlist, preserving exact money at the Returns boundary."""

        def exact(item, key=""):
            if type(item) is int and (key.endswith("_kopecks") or key in {"value", "capital_days"}):
                return str(item)
            if isinstance(item, dict):
                return {name: exact(child, name) for name, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [exact(child) for child in item]
            return item

        return exact(handler(value))


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


def selection(
    request: Request,
    response: Response,
    scope: Annotated[str, Query(min_length=1, max_length=264)],
    start: date,
    end: date,
):
    no_store(response)
    if start >= end or any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    return dict(scope=scope, start=start, end=end)


def read(reader, session, **kwargs):
    try:
        return reader(session, **kwargs)
    except (ValueError, LookupError):
        raise HTTPException(
            422, "returns_selection_unavailable", headers={"Cache-Control": "no-store"}
        ) from None


@router.get("/context", response_model=Context)
def context(response: Response, session: Session = Depends(session_for_request)):
    no_store(response)
    return returns_view.read_context(session)


@router.get("/overview", response_model=Overview)
def overview(selected: dict = Depends(selection), session: Session = Depends(session_for_request)):
    return read(returns_view.read_overview, session, **selected)


@router.get("/instrument", response_model=Detail)
def instrument(
    isin: Annotated[str, Query(pattern=r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")],
    selected: dict = Depends(selection),
    session: Session = Depends(session_for_request),
):
    return read(returns_view.read_detail, session, isin=isin, **selected)


class BasketCell(DTO):
    period: Period
    value_kopecks: str | None
    reason_codes: list[str]


class BasketComponent(DTO):
    id: str
    label: str
    category: Literal["brokerage_iis", "deposits", "gold"]
    basis: Literal["statements", "accepted", "unsupported"]
    method: str
    cells: list[BasketCell]


class BasketSubtotal(DTO):
    value_kopecks: str | None
    covered_cells: int
    total_cells: int
    method: str
    reason_codes: list[str]


class Basket(DTO):
    period: Period
    categories: list[Literal["brokerage", "iis", "deposits", "gold"]]
    partial: Literal[True]
    result_kopecks: None
    known_partial_subtotal_kopecks: str | None
    rate: Metric
    reason_codes: list[str]
    source_subtotal: BasketSubtotal
    deposit_received_interest: BasketSubtotal
    components: list[BasketComponent]


@router.get("/basket", response_model=Basket)
def basket(
    request: Request,
    response: Response,
    start: date,
    end: date,
    categories: Annotated[str, Query(max_length=64)] = ",".join(returns_basket.CATEGORIES),
    session: Session = Depends(session_for_request),
):
    no_store(response)
    if start >= end or any(len(request.query_params.getlist(k)) != 1 for k in request.query_params):
        raise HTTPException(422, "returns_selection_invalid", headers={"Cache-Control": "no-store"})
    return read(returns_basket.read_basket, session, start=start, end=end, categories=categories)
