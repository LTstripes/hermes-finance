"""Expected cash flows API (D06)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import ExpectedCashFlowType, RubleAmount
from hermes_finance.services.expected_cash_flows import (
    calendar_expected_cash_flows,
    create_expected_cash_flow,
    delete_expected_cash_flow,
    get_expected_cash_flow,
    list_expected_cash_flows,
    update_expected_cash_flow,
)

router = APIRouter(prefix="/api/expected-flows", tags=["expected-flows"])


class ExpectedFlowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int
    instrument_id: int
    flow_type: str = Field(min_length=1, max_length=32)
    expected_date: date
    gross_amount: MoneyValue
    expected_tax_amount: MoneyValue | None = None
    expected_net_amount: MoneyValue | None = None
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    source: str = Field(min_length=1, max_length=64)
    source_as_of_date: date
    forecast_version: str = Field(min_length=1, max_length=32)
    is_confirmed: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class ExpectedFlowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_type: str | None = Field(default=None, min_length=1, max_length=32)
    expected_date: date | None = None
    gross_amount: MoneyValue | None = None
    expected_tax_amount: MoneyValue | None = None
    expected_net_amount: MoneyValue | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    is_confirmed: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ExpectedFlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int
    flow_type: str
    expected_date: date
    gross_amount: MoneyValue
    expected_tax_amount: MoneyValue | None
    expected_net_amount: MoneyValue
    currency: str
    source: str
    source_as_of_date: date
    forecast_version: str
    is_confirmed: bool
    is_approximate: bool
    notes: str | None


class CalendarItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    expected_date: date
    flow_type: str
    account_name: str
    instrument_name: str | None
    expected_net_amount: MoneyValue
    is_confirmed: bool
    is_approximate: bool
    source: str


class CalendarMonthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    coupon: MoneyValue
    dividend: MoneyValue
    interest: MoneyValue
    redemption: MoneyValue
    other: MoneyValue
    passive_net: MoneyValue
    total_net: MoneyValue
    items: list[CalendarItemOut]


def _validate_flow_type(value: str) -> str:
    try:
        ExpectedCashFlowType(value)
    except ValueError as error:
        raise ValueError(f"unsupported expected flow type: {value!r}") from error
    return value


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int | None) -> MoneyValue | None:
    if kopecks is None:
        return None
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(flow: object) -> ExpectedFlowResponse:
    return ExpectedFlowResponse(
        id=flow.id,
        reporting_month_id=flow.reporting_month_id,
        account_id=flow.account_id,
        instrument_id=flow.instrument_id,
        flow_type=flow.flow_type,
        expected_date=flow.expected_date,
        gross_amount=_money(flow.gross_amount_kopecks),  # type: ignore[arg-type]
        expected_tax_amount=_money(flow.expected_tax_amount_kopecks),
        expected_net_amount=_money(flow.expected_net_amount_kopecks),  # type: ignore[arg-type]
        currency=flow.currency,
        source=flow.source,
        source_as_of_date=flow.source_as_of_date,
        forecast_version=flow.forecast_version,
        is_confirmed=flow.is_confirmed,
        is_approximate=flow.is_approximate,
        notes=flow.notes,
    )


@router.get("/calendar", response_model=list[CalendarMonthOut])
def calendar_flows(
    month_id: int = Query(...),
    forecast_version: str = Query(...),
    from_date: date | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[CalendarMonthOut]:
    """Expected payouts grouped by calendar month over the 12-month horizon (E16)."""
    months = calendar_expected_cash_flows(
        session,
        reporting_month_id=month_id,
        forecast_version=forecast_version,
        from_date=from_date,
    )
    return [
        CalendarMonthOut(
            year=month.year,
            month=month.month,
            coupon=_money(month.coupon),
            dividend=_money(month.dividend),
            interest=_money(month.interest),
            redemption=_money(month.redemption),
            other=_money(month.other),
            passive_net=_money(month.passive_net),
            total_net=_money(month.total_net),
            items=[
                CalendarItemOut(
                    id=item.id,
                    expected_date=item.expected_date,
                    flow_type=item.flow_type,
                    account_name=item.account_name,
                    instrument_name=item.instrument_name,
                    expected_net_amount=_money(item.expected_net_amount),
                    is_confirmed=item.is_confirmed,
                    is_approximate=item.is_approximate,
                    source=item.source,
                )
                for item in month.items
            ],
        )
        for month in months
    ]


@router.get("", response_model=list[ExpectedFlowResponse])
def list_flows(
    month_id: int = Query(...),
    forecast_version: str = Query(...),
    from_date: date | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[ExpectedFlowResponse]:
    flows = list_expected_cash_flows(
        session,
        reporting_month_id=month_id,
        forecast_version=forecast_version,
        from_date=from_date,
    )
    return [_response(flow) for flow in flows]


@router.post("", response_model=ExpectedFlowResponse, status_code=status.HTTP_201_CREATED)
def create_flow(
    payload: ExpectedFlowCreate,
    session: Session = Depends(session_for_request),
) -> ExpectedFlowResponse:
    _validate_flow_type(payload.flow_type)
    flow = create_expected_cash_flow(
        session,
        reporting_month_id=payload.reporting_month_id,
        account_id=payload.account_id,
        instrument_id=payload.instrument_id,
        flow_type=payload.flow_type,
        expected_date=payload.expected_date,
        gross_amount=_amount(payload.gross_amount),
        expected_tax_amount=_amount(payload.expected_tax_amount)
        if payload.expected_tax_amount is not None
        else None,
        expected_net_amount=_amount(payload.expected_net_amount)
        if payload.expected_net_amount is not None
        else None,
        currency=payload.currency,
        source=payload.source,
        source_as_of_date=payload.source_as_of_date,
        forecast_version=payload.forecast_version,
        is_confirmed=payload.is_confirmed,
        notes=payload.notes,
    )
    return _response(flow)


@router.get("/{flow_id}", response_model=ExpectedFlowResponse)
def get_flow(
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> ExpectedFlowResponse:
    return _response(get_expected_cash_flow(session, flow_id))


@router.patch("/{flow_id}", response_model=ExpectedFlowResponse)
def update_flow(
    flow_id: int,
    payload: ExpectedFlowUpdate,
    session: Session = Depends(session_for_request),
) -> ExpectedFlowResponse:
    if payload.flow_type is not None:
        _validate_flow_type(payload.flow_type)
    flow = update_expected_cash_flow(
        session,
        flow_id,
        flow_type=payload.flow_type,
        expected_date=payload.expected_date,
        gross_amount=_amount(payload.gross_amount) if payload.gross_amount is not None else None,
        expected_tax_amount=_amount(payload.expected_tax_amount)
        if payload.expected_tax_amount is not None
        else None,
        expected_net_amount=_amount(payload.expected_net_amount)
        if payload.expected_net_amount is not None
        else None,
        currency=payload.currency,
        source=payload.source,
        is_confirmed=payload.is_confirmed,
        notes=payload.notes,
    )
    return _response(flow)


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flow(
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_expected_cash_flow(session, flow_id)
