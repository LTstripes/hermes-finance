"""Read-only adapter: build a HermesStateView from a reporting month (R06-04).

This lives in the service layer (not in ``broker_data``) because the R06-03
source guard forbids the ``broker_data`` package from importing SQLAlchemy
persistence. The reconciliation domain package stays pure; this module is the
narrow read-only boundary that loads relevant Hermes investment/account state.

Performs ZERO writes; the session is left untouched. Broker snapshot provider
data is NOT persisted here.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.broker_data.reconciliation.dto import (
    HermesAccountView,
    HermesCashView,
    HermesInstrumentView,
    HermesPositionView,
    HermesStateView,
)
from hermes_finance.persistence import (
    Account,
    CashBalance,
    Instrument,
    PositionSnapshot,
)
from hermes_finance.services.reporting_months import get_reporting_month


def load_hermes_state_for_month(session: Session, reporting_month_id: int) -> HermesStateView:
    month = get_reporting_month(session, reporting_month_id)
    month_status = str(month.status)

    accounts = list(session.scalars(select(Account).order_by(Account.id)))
    account_ids = {acc.id for acc in accounts}
    account_views = tuple(
        HermesAccountView(
            account_id=acc.id,
            name=acc.name,
            account_type=str(acc.account_type),
            external_code=acc.external_code,
            status=str(acc.status),
        )
        for acc in accounts
    )

    instruments = list(session.scalars(select(Instrument).order_by(Instrument.id)))
    instrument_ids = {inst.id for inst in instruments}
    instrument_views = tuple(
        HermesInstrumentView(
            instrument_id=inst.id,
            name=inst.name,
            instrument_type=str(inst.instrument_type),
            isin=inst.isin,
            ticker=inst.ticker,
        )
        for inst in instruments
    )

    positions = list(
        session.scalars(
            select(PositionSnapshot)
            .where(PositionSnapshot.reporting_month_id == reporting_month_id)
            .order_by(PositionSnapshot.account_id, PositionSnapshot.instrument_id)
        )
    )
    position_views: list[HermesPositionView] = []
    for pos in positions:
        if pos.account_id not in account_ids or pos.instrument_id not in instrument_ids:
            # Skip dangling references defensively; reconciliation needs both
            # sides canonical and present.
            continue
        position_views.append(
            HermesPositionView(
                account_id=pos.account_id,
                instrument_id=pos.instrument_id,
                quantity=Decimal(pos.quantity),
                market_price_per_unit_kopecks=pos.market_price_per_unit_kopecks,
                accrued_interest_kopecks=pos.accrued_interest_kopecks,
                market_value_kopecks=pos.market_value_kopecks,
                unrealized_result_kopecks=pos.unrealized_result_kopecks,
            )
        )

    cash = list(
        session.scalars(
            select(CashBalance).where(CashBalance.reporting_month_id == reporting_month_id)
        )
    )
    cash_views = tuple(
        HermesCashView(
            name=cb.name,
            amount_kopecks=cb.amount_kopecks,
            currency=str(cb.currency),
        )
        for cb in cash
    )

    return HermesStateView(
        month_id=month.id,
        month_status=month_status,
        accounts=account_views,
        instruments=instrument_views,
        positions=tuple(position_views),
        cash_balances=cash_views,
    )
