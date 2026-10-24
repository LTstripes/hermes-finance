"""Presence, never completeness or a monetary total, of saved actual month facts.

Call in a coherent read snapshot or after reserving the SQLite writer. Source
acceptance is delegated to the existing canonical readers, never inferred from
an import, receipt, plan, forecast or source-intake journal row.
"""

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    CashBalance,
    Debt,
    DepositSnapshot,
    ExecutedTrade,
    ExpenseEntry,
    ExternalFlow,
    HistoricalEndpointRevision,
    HistoricalOwnerFlow,
    IncomeEntry,
    InKindMovement,
    InvestmentCashFlow,
    ObservedValuationPoint,
    PositionSnapshot,
    PropertySnapshot,
    ReportingMonth,
    SavingAllocation,
)

# Explicit month-owned actuals. A saved zero, excluded-from-total row or a
# quantity-only observation remains a fact. Do not replace EXISTS with SUM > 0.
MONTH_ACTUAL_MODELS = (
    CashBalance,
    DepositSnapshot,
    PositionSnapshot,
    IncomeEntry,
    ExpenseEntry,
    SavingAllocation,
    Debt,
    PropertySnapshot,
    InvestmentCashFlow,
    ExternalFlow,
    InKindMovement,
    ObservedValuationPoint,
)


def has_month_actual_facts(session: Session, month: ReportingMonth) -> bool:
    with session.no_autoflush:
        for model in MONTH_ACTUAL_MODELS:
            statement = select(model.id).where(model.reporting_month_id == month.id)
            if model in (IncomeEntry, ExpenseEntry, SavingAllocation):
                # Legacy NULL and unknown versions cannot prove a fresh actual.
                # Dates, recurrence and the value (including zero) are not provenance.
                statement = statement.where(model.actual_fact_origin == "saved_actual_v1")
            if session.scalar(statement.limit(1)) is not None:
                return True

        # These accepted facts are date-owned rather than month FK-owned. Use
        # the selected calendar period, never another month's/current holdings.
        from hermes_finance.services.historical_endpoints import _read as read_endpoint
        from hermes_finance.services.historical_owner_flows import _read_historical_owner_flow

        keys = session.scalars(
            select(HistoricalEndpointRevision.endpoint_key)
            .where(
                HistoricalEndpointRevision.valuation_date.between(
                    month.period_start, month.period_end
                )
            )
            .distinct()
        )
        for key in keys:
            if read_endpoint(session, key)["effective_state"] == "accepted":
                return True
        for flow_id in session.scalars(
            select(HistoricalOwnerFlow.id).where(
                HistoricalOwnerFlow.event_date.between(month.period_start, month.period_end)
            )
        ):
            if _read_historical_owner_flow(session, flow_id)["effective_state"] == "accepted":
                return True

        trades = []
        for trade in session.scalars(select(ExecutedTrade)):
            day = json.loads(trade.core_json)["trade_time"][:10]
            if month.period_start.isoformat() <= day <= month.period_end.isoformat():
                trades.append(trade)
        if trades:
            # Internal builders support both a committed read and a reserved
            # writer; the public reader opens its own read-only transaction.
            from hermes_finance.services.executed_trades import _context, _read

            context = _context(session)
            for row in trades:
                trade = _read(session, context, row)
                if trade["acceptance_state"] == "active" and not trade["conflicts"]:
                    return True
    return False
