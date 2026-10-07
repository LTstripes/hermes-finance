"""Narrow ORM hooks for frozen H1 dependencies, including change-then-restore."""

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    BrokerIdentityMapping,
    CashBalance,
    DepositSnapshot,
    ExecutedTradeRevision,
    HistoricalEndpointApply,
    HistoricalEndpointRevision,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)


def _before_flush(session, _context, _instances):
    from hermes_finance.services.historical_endpoints import retire_dependencies

    changes = []
    for row in session.new:
        if isinstance(row, ExecutedTradeRevision):
            changes.append({"trade_id": row.trade_id})
        elif (
            isinstance(row, (PositionSnapshot, CashBalance, DepositSnapshot))
            and row.reporting_month_id is not None
        ):
            changes.append(
                {"month_id": row.reporting_month_id, "overlap_account_id": row.account_id}
            )
    for row in (*session.dirty, *session.deleted):
        if isinstance(row, (HistoricalEndpointRevision, HistoricalEndpointApply)):
            raise ValueError("historical endpoint history is append-only")
        deleted = row in session.deleted
        state = inspect(row)
        if isinstance(row, ReportingMonth):
            status = state.attrs.status.history
            reopened = status.has_changes() and row.status == "draft"
            if deleted or reopened or state.attrs.snapshot_date.history.has_changes():
                changes.append({"month_id": row.id, "reason": "month_dependency_changed"})
        elif isinstance(row, BrokerIdentityMapping):
            if deleted or any(
                state.attrs[field].history.has_changes()
                for field in (
                    "status",
                    "hermes_account_id",
                    "hermes_instrument_id",
                    "observed_isin",
                    "predecessor_mapping_id",
                    "successor_mapping_id",
                )
            ):
                changes.append({"mapping_id": row.id})
        elif isinstance(row, AccountPerformanceScopeMembership):
            if deleted or session.is_modified(row):
                changes.append({"membership_id": row.id})
        elif isinstance(row, Instrument):
            if deleted or state.attrs.isin.history.has_changes():
                changes.append({"instrument_id": row.id})
        elif isinstance(row, ExecutedTradeRevision):
            if deleted or session.is_modified(row):
                changes.append({"trade_id": row.trade_id})
        elif isinstance(row, PositionSnapshot):
            if deleted or any(
                state.attrs[field].history.has_changes()
                for field in (
                    "quantity",
                    "market_value_kopecks",
                    "historical_instrument_type",
                    "account_id",
                    "instrument_id",
                    "reporting_month_id",
                )
            ):
                changes.append({"position_id": row.id})
                if row.reporting_month_id is not None:
                    changes.append(
                        {"month_id": row.reporting_month_id, "overlap_account_id": row.account_id}
                    )
        elif isinstance(row, CashBalance):
            if deleted or any(
                state.attrs[field].history.has_changes()
                for field in (
                    "amount_kopecks",
                    "account_id",
                    "currency",
                    "include_in_capital",
                    "reporting_month_id",
                )
            ):
                changes.append({"cash_id": row.id})
                changes.append(
                    {"month_id": row.reporting_month_id, "overlap_account_id": row.account_id}
                )
        elif isinstance(row, DepositSnapshot):
            if deleted or session.is_modified(row):
                changes.append({"deposit_id": row.id})
                changes.append(
                    {"month_id": row.reporting_month_id, "overlap_account_id": row.account_id}
                )
    if changes:
        if not inspect(session.connection()).has_table("historical_endpoint_revisions"):
            return
        # Same transaction as the existing writer. No commit inside a lifecycle hook.
        session.execute(text("UPDATE reporting_months SET status = status WHERE 0"))
        for change in changes:
            retire_dependencies(session, **change)


def install_hooks() -> None:
    if not event.contains(Session, "before_flush", _before_flush):
        event.listen(Session, "before_flush", _before_flush)
