"""Shared guard for editing month-scoped child entities.

A closed reporting month is immutable until an explicit ``reopen``
(AGENTS.md financial invariants, PROJECT_WIKI section 7 item 7). Every
month-scoped CRUD service routes its create/update/delete through these
helpers so the invariant lives in exactly one place. Entities without a
``reporting_month_id`` foreign key (accounts, instruments, goals,
app_settings, iis profiles) must not use this guard.
"""

from sqlalchemy.orm import Session

from hermes_finance.domain import ReportingMonthStatus
from hermes_finance.persistence import ReportingMonth
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    ReportingMonthNotFoundError,
)

_EDIT_ERROR_MESSAGE = "closed reporting month must be reopened before editing"


def require_editable_reporting_month(session: Session, month_id: int) -> ReportingMonth:
    """Resolve a reporting month and require it to be editable (draft).

    Raises ``ReportingMonthNotFoundError`` when the month does not exist and
    ``ClosedReportingMonthError`` when the month is closed.
    """
    reporting_month = session.get(ReportingMonth, month_id)
    if reporting_month is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")
    if reporting_month.status == ReportingMonthStatus.CLOSED.value:
        raise ClosedReportingMonthError(_EDIT_ERROR_MESSAGE)
    return reporting_month


def require_editable_child_month(session: Session, child: object) -> ReportingMonth:
    """Resolve the parent reporting month of an existing month-scoped child row
    and require it to be editable.

    Call after the child row has been resolved (so a missing child still
    raises the service's own not-found error) and before any mutation.
    """
    return require_editable_reporting_month(session, child.reporting_month_id)
