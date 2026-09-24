"""Detach historical payout identity from an editable financial snapshot.

The month FK remains RESTRICT. Only rows needed by payout/revision history are
retained after a draft correction; all detached rows retain their source period.
Callers own the writer reservation and transaction.
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    ExpectedCashFlow,
    PositionSnapshot,
)


def archive_payout(session: Session, payout: AppliedProviderPayout, period: str) -> None:
    payout.reporting_month_id = None
    payout.archived_from_period = period


def position_has_payout_history(session: Session, snapshot_id: int) -> bool:
    return (
        session.scalar(
            select(AppliedProviderPayout.id)
            .where(AppliedProviderPayout.source_position_snapshot_id == snapshot_id)
            .limit(1)
        )
        is not None
        or session.scalar(
            select(AppliedPayoutRevision.id)
            .where(AppliedPayoutRevision.source_position_snapshot_id == snapshot_id)
            .limit(1)
        )
        is not None
    )


def archive_position_payouts(session: Session, snapshot_id: int, period: str) -> None:
    """Retire payouts currently sourced from a removed active position."""
    for payout in session.scalars(
        select(AppliedProviderPayout).where(
            AppliedProviderPayout.source_position_snapshot_id == snapshot_id,
            AppliedProviderPayout.reporting_month_id.is_not(None),
        )
    ):
        archive_payout(session, payout, period)


def archive_month_payout_history(session: Session, month_id: int, period: str) -> None:
    """Preserve the payout/revision/reconciliation FK graph before month deletion."""
    payouts = list(
        session.scalars(
            select(AppliedProviderPayout).where(
                or_(
                    AppliedProviderPayout.reporting_month_id == month_id,
                    AppliedProviderPayout.archived_from_period == period,
                )
            )
        )
    )
    payout_ids = [payout.id for payout in payouts]
    if not payout_ids:
        return
    snapshot_ids = {payout.source_position_snapshot_id for payout in payouts}
    snapshot_ids.update(
        session.scalars(
            select(AppliedPayoutRevision.source_position_snapshot_id).where(
                AppliedPayoutRevision.applied_payout_id.in_(payout_ids)
            )
        )
    )
    flow_ids = set(
        session.scalars(
            select(AppliedPayoutReconciliation.expected_cash_flow_id).where(
                AppliedPayoutReconciliation.applied_payout_id.in_(payout_ids)
            )
        )
    )
    for payout in payouts:
        archive_payout(session, payout, period)
    for snapshot in session.scalars(
        select(PositionSnapshot).where(
            PositionSnapshot.id.in_(snapshot_ids),
            PositionSnapshot.reporting_month_id == month_id,
        )
    ):
        snapshot.reporting_month_id = None
        snapshot.archived_from_period = period
    for flow in session.scalars(
        select(ExpectedCashFlow).where(
            ExpectedCashFlow.id.in_(flow_ids),
            ExpectedCashFlow.reporting_month_id == month_id,
        )
    ):
        flow.reporting_month_id = None
        flow.archived_from_period = period
    session.flush()
