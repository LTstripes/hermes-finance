"""Treasury-style expected cash-flow ladder API (R07-05)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from hermes_finance.api.settings import MoneyValue, session_for_request
from hermes_finance.services.cash_flow_ladder import (
    CashFlowLadderEvent,
    CashFlowLadderMonth,
    CashFlowLadderResult,
    UpcomingEventsWindow,
    build_cash_flow_ladder,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION

router = APIRouter(prefix="/api/months", tags=["cash-flow-ladder"])


class CashFlowLadderEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_kind: str
    source_id: int
    expected_date: date
    flow_type: str
    component: str
    account_id: int
    account_name: str
    instrument_id: int | None
    instrument_name: str | None
    expected_net_amount: MoneyValue
    is_approximate: bool
    source: str
    provider: str | None
    provider_instrument_uid: str | None
    provider_identity_key: str | None
    reconciliation_id: int | None
    counting_decision: str | None
    linked_manual_id: int | None
    linked_provider_payout_id: int | None
    source_as_of_date: date | None


class CashFlowLadderMonthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    year: int
    month: int
    coupon: MoneyValue
    dividend: MoneyValue
    deposit_interest: MoneyValue
    other_capital_income: MoneyValue
    redemption_principal: MoneyValue
    passive_income: MoneyValue
    total_cash_flow: MoneyValue
    is_approximate: bool
    items: list[CashFlowLadderEventOut]


class UpcomingEventsWindowOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int
    from_date: date
    to_date: date
    passive_income: MoneyValue
    redemption_principal: MoneyValue
    total_cash_flow: MoneyValue
    items: list[CashFlowLadderEventOut]


class CashFlowLadderOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of_date: date
    forecast_version: str
    months: list[CashFlowLadderMonthOut]
    upcoming_14_days: UpcomingEventsWindowOut
    upcoming_30_days: UpcomingEventsWindowOut
    warnings: list[str]


def _money(amount: object) -> MoneyValue:
    return MoneyValue(amount=amount.to_api(), currency="RUB")


def _event_out(event: CashFlowLadderEvent) -> CashFlowLadderEventOut:
    return CashFlowLadderEventOut(
        source_kind=event.source_kind.value,
        source_id=event.source_id,
        expected_date=event.expected_date,
        flow_type=event.flow_type,
        component=event.component,
        account_id=event.account_id,
        account_name=event.account_name,
        instrument_id=event.instrument_id,
        instrument_name=event.instrument_name,
        expected_net_amount=_money(event.expected_net_amount),
        is_approximate=event.is_approximate,
        source=event.source,
        provider=event.provider,
        provider_instrument_uid=event.provider_instrument_uid,
        provider_identity_key=event.provider_identity_key,
        reconciliation_id=event.reconciliation_id,
        counting_decision=event.counting_decision,
        linked_manual_id=event.linked_manual_id,
        linked_provider_payout_id=event.linked_provider_payout_id,
        source_as_of_date=event.source_as_of_date,
    )


def _month_out(month: CashFlowLadderMonth) -> CashFlowLadderMonthOut:
    return CashFlowLadderMonthOut(
        year=month.year,
        month=month.month,
        coupon=_money(month.coupon),
        dividend=_money(month.dividend),
        deposit_interest=_money(month.deposit_interest),
        other_capital_income=_money(month.other_capital_income),
        redemption_principal=_money(month.redemption_principal),
        passive_income=_money(month.passive_income),
        total_cash_flow=_money(month.total_cash_flow),
        is_approximate=month.is_approximate,
        items=[_event_out(item) for item in month.items],
    )


def _window_out(window: UpcomingEventsWindow) -> UpcomingEventsWindowOut:
    return UpcomingEventsWindowOut(
        days=window.days,
        from_date=window.from_date,
        to_date=window.to_date,
        passive_income=_money(window.passive_income),
        redemption_principal=_money(window.redemption_principal),
        total_cash_flow=_money(window.total_cash_flow),
        items=[_event_out(item) for item in window.items],
    )


def cash_flow_ladder_to_out(result: CashFlowLadderResult) -> CashFlowLadderOut:
    return CashFlowLadderOut(
        as_of_date=result.as_of_date,
        forecast_version=result.forecast_version,
        months=[_month_out(month) for month in result.months],
        upcoming_14_days=_window_out(result.upcoming_14_days),
        upcoming_30_days=_window_out(result.upcoming_30_days),
        warnings=list(result.warnings),
    )


@router.get("/{month_id}/cash-flow-ladder", response_model=CashFlowLadderOut)
def get_cash_flow_ladder(
    month_id: int,
    forecast_version: str = Query(default=DEFAULT_FORECAST_VERSION, min_length=1, max_length=32),
    session: Session = Depends(session_for_request),
) -> CashFlowLadderOut:
    return cash_flow_ladder_to_out(
        build_cash_flow_ladder(session, month_id, forecast_version=forecast_version)
    )
