"""Shared guard for editing month-scoped child entities.

A closed reporting month is immutable until an explicit ``reopen``
(AGENTS.md financial invariants, PROJECT_WIKI section 7 item 7). Every
month-scoped CRUD service routes its create/update/delete through these
helpers so the invariant lives in exactly one place. Entities without a
``reporting_month_id`` foreign key (accounts, instruments, goals,
app_settings, iis profiles) must not use this guard.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from hermes_finance.domain import ReportingMonthStatus
from hermes_finance.persistence import ReportingMonth
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    ReportingMonthNotFoundError,
)

_EDIT_ERROR_MESSAGE = "closed reporting month must be reopened before editing"


def require_editable_reporting_month(session: Session, month_id: int) -> ReportingMonth:
    """Acquire SQLite's writer reservation before checking DRAFT.

    Raises ``ReportingMonthNotFoundError`` when the month does not exist and
    ``ClosedReportingMonthError`` when the month is closed. The reservation
    remains on this session's transaction through the child write and commit;
    a concurrent Close must wait for that commit or win before this UPDATE.
    A SELECT (even in a SQLAlchemy autobegin transaction) does not acquire
    that reservation with the configured pysqlite driver. Use raw SQL so the
    no-op does not run ReportingMonth.updated_at's ORM onupdate callback.
    """
    result = session.execute(
        text(
            "UPDATE reporting_months SET status = status WHERE id = :month_id AND status = :draft"
        ),
        {"month_id": month_id, "draft": ReportingMonthStatus.DRAFT.value},
    )
    reporting_month = session.get(ReportingMonth, month_id, populate_existing=True)
    if result.rowcount == 1:
        return reporting_month
    session.rollback()
    if reporting_month is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")
    raise ClosedReportingMonthError(_EDIT_ERROR_MESSAGE)


def require_editable_child_month(session: Session, child: object) -> ReportingMonth:
    """Resolve the parent reporting month of an existing month-scoped child row
    and require it to be editable.

    Call after the child row has been resolved (so a missing child still
    raises the service's own not-found error) and before any mutation.
    """
    return require_editable_reporting_month(session, child.reporting_month_id)
