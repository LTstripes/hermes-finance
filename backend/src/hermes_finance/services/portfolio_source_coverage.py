"""Read-time coverage of the sources required for the known capital subtotal."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain.portfolio_source_coverage import PortfolioSourceCoverage
from hermes_finance.persistence import Account, CashBalance, Debt, DepositSnapshot, PositionSnapshot


def portfolio_source_coverage_for_months(
    session: Session, month_ids: list[int]
) -> dict[int, PortfolioSourceCoverage]:
    """A linked row, including a zero row, represents its account; unassigned cash does not."""
    if not month_ids:
        return {}

    required = set(
        session.scalars(
            select(Account.id).where(
                Account.status == "active", Account.include_in_capital.is_(True)
            )
        )
    )
    represented: dict[int, set[int]] = {month_id: set() for month_id in month_ids}
    evidence: set[int] = set()
    for model in (PositionSnapshot, DepositSnapshot, CashBalance):
        for month_id, account_id in session.execute(
            select(model.reporting_month_id, model.account_id).where(
                model.reporting_month_id.in_(month_ids)
            )
        ):
            evidence.add(month_id)
            if account_id is not None:
                represented[month_id].add(account_id)
    evidence.update(
        session.scalars(
            select(Debt.reporting_month_id).where(
                Debt.reporting_month_id.in_(month_ids), Debt.include_in_liquid_capital.is_(True)
            )
        )
    )

    result = {}
    for month_id in month_ids:
        missing = tuple(sorted(required - represented[month_id]))
        if month_id not in evidence:
            result[month_id] = PortfolioSourceCoverage(
                "unavailable", ("portfolio_snapshot_missing",), missing
            )
        elif missing:
            result[month_id] = PortfolioSourceCoverage(
                "partial", ("active_account_snapshot_missing",), missing
            )
        else:
            result[month_id] = PortfolioSourceCoverage("complete")
    return result


def portfolio_source_coverage_for_month(session: Session, month_id: int) -> PortfolioSourceCoverage:
    return portfolio_source_coverage_for_months(session, [month_id])[month_id]


def combined_portfolio_source_coverage(
    current: PortfolioSourceCoverage, previous: PortfolioSourceCoverage
) -> PortfolioSourceCoverage:
    """A difference of known subtotals inherits both endpoints' limitations."""
    reasons = tuple(sorted(set(current.reason_codes) | set(previous.reason_codes)))
    statuses = (current.status, previous.status)
    status = (
        "unavailable"
        if "unavailable" in statuses
        else "partial"
        if "partial" in statuses
        else "complete"
    )
    return PortfolioSourceCoverage(status, reasons)
