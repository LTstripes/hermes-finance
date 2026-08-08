"""Investment cash flows API (D06)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.domain import InvestmentCashFlowType, RubleAmount
from hermes_finance.services.investment_cash_flows import (
    create_investment_cash_flow,
    delete_investment_cash_flow,
    get_investment_cash_flow,
    list_investment_cash_flows,
    update_investment_cash_flow,
)

router = APIRouter(prefix="/api/investment-flows", tags=["investment-flows"])


class InvestmentFlowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reporting_month_id: int
    account_id: int
    flow_type: str = Field(min_length=1, max_length=32)
    event_date: date
    gross_amount: MoneyValue
    tax_amount: MoneyValue | None = None
    commission_amount: MoneyValue | None = None
    net_amount: MoneyValue
    instrument_id: int | None = None
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    source: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class InvestmentFlowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_type: str | None = Field(default=None, min_length=1, max_length=32)
    event_date: date | None = None
    gross_amount: MoneyValue | None = None
    tax_amount: MoneyValue | None = None
    commission_amount: MoneyValue | None = None
    net_amount: MoneyValue | None = None
    instrument_id: int | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    source: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class InvestmentFlowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporting_month_id: int
    account_id: int
    instrument_id: int | None
    flow_type: str
    event_date: date
    gross_amount: MoneyValue
    tax_amount: MoneyValue
    commission_amount: MoneyValue
    net_amount: MoneyValue
    currency: str
    source: str
    notes: str | None


def _validate_flow_type(value: str) -> str:
    try:
        InvestmentCashFlowType(value)
    except ValueError as error:
        raise ValueError(f"unsupported investment flow type: {value!r}") from error
    return value


def _amount(money: MoneyValue) -> RubleAmount:
    return RubleAmount.from_api(money.amount)


def _money(kopecks: int) -> MoneyValue:
    return MoneyValue(amount=RubleAmount(kopecks).to_api(), currency="RUB")


def _response(flow: object) -> InvestmentFlowResponse:
    return InvestmentFlowResponse(
        id=flow.id,
        reporting_month_id=flow.reporting_month_id,
        account_id=flow.account_id,
        instrument_id=flow.instrument_id,
        flow_type=flow.flow_type,
        event_date=flow.event_date,
        gross_amount=_money(flow.gross_amount_kopecks),
        tax_amount=_money(flow.tax_amount_kopecks),
        commission_amount=_money(flow.commission_amount_kopecks),
        net_amount=_money(flow.net_amount_kopecks),
        currency=flow.currency,
        source=flow.source,
        notes=flow.notes,
    )


@router.get("", response_model=list[InvestmentFlowResponse])
def list_flows(
    month_id: int = Query(...),
    account_id: int | None = Query(default=None),
    session: Session = Depends(session_for_request),
) -> list[InvestmentFlowResponse]:
    flows = [
        flow
        for flow in list_investment_cash_flows(session)
        if flow.reporting_month_id == month_id
        and (account_id is None or flow.account_id == account_id)
    ]
    return [_response(flow) for flow in flows]


@router.post("", response_model=InvestmentFlowResponse, status_code=status.HTTP_201_CREATED)
def create_flow(
    payload: InvestmentFlowCreate,
    session: Session = Depends(session_for_request),
) -> InvestmentFlowResponse:
    _validate_flow_type(payload.flow_type)
    flow = create_investment_cash_flow(
        session,
        reporting_month_id=payload.reporting_month_id,
        account_id=payload.account_id,
        flow_type=payload.flow_type,
        event_date=payload.event_date,
        gross_amount=_amount(payload.gross_amount),
        tax_amount=_amount(payload.tax_amount)
        if payload.tax_amount is not None
        else RubleAmount(0),
        commission_amount=_amount(payload.commission_amount)
        if payload.commission_amount is not None
        else RubleAmount(0),
        net_amount=_amount(payload.net_amount),
        instrument_id=payload.instrument_id,
        currency=payload.currency,
        source=payload.source,
        notes=payload.notes,
    )
    return _response(flow)


@router.get("/{flow_id}", response_model=InvestmentFlowResponse)
def get_flow(
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> InvestmentFlowResponse:
    return _response(get_investment_cash_flow(session, flow_id))


@router.patch("/{flow_id}", response_model=InvestmentFlowResponse)
def update_flow(
    flow_id: int,
    payload: InvestmentFlowUpdate,
    session: Session = Depends(session_for_request),
) -> InvestmentFlowResponse:
    if payload.flow_type is not None:
        _validate_flow_type(payload.flow_type)
    flow = update_investment_cash_flow(
        session,
        flow_id,
        flow_type=payload.flow_type,
        event_date=payload.event_date,
        gross_amount=_amount(payload.gross_amount) if payload.gross_amount is not None else None,
        tax_amount=_amount(payload.tax_amount) if payload.tax_amount is not None else None,
        commission_amount=_amount(payload.commission_amount)
        if payload.commission_amount is not None
        else None,
        net_amount=_amount(payload.net_amount) if payload.net_amount is not None else None,
        instrument_id=payload.instrument_id,
        currency=payload.currency,
        source=payload.source,
        notes=payload.notes,
    )
    return _response(flow)


@router.delete("/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flow(
    flow_id: int,
    session: Session = Depends(session_for_request),
) -> None:
    delete_investment_cash_flow(session, flow_id)
