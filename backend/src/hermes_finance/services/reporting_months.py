from calendar import monthrange
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import ReportingMonthSource, ReportingMonthStatus
from hermes_finance.persistence import Base, ReportingMonth


class ReportingMonthNotFoundError(LookupError):
    pass


class ClosedReportingMonthError(ValueError):
    pass


CLOSE_SNAPSHOT_DATE_REQUIRED_CODE = "snapshot_date_required"
CLOSE_SNAPSHOT_DATE_REQUIRED_MESSAGE = "snapshot_date is required before closing a reporting month"


def close_hard_guards(reporting_month: ReportingMonth) -> tuple[tuple[str, str], ...]:
    """Return ``(code, message)`` pairs that the authoritative close already rejects.

    Close has no financial-data completeness gate. The HTTP close path only
    rejects a missing snapshot date after the month has been loaded. Do not
    invent additional hard blockers here.
    """
    snapshot_date = getattr(reporting_month, "snapshot_date", None)
    if snapshot_date is None:
        return ((CLOSE_SNAPSHOT_DATE_REQUIRED_CODE, CLOSE_SNAPSHOT_DATE_REQUIRED_MESSAGE),)
    return ()


def _period_bounds(year: int, month: int) -> tuple[date, date]:
    try:
        period_start = date(year, month, 1)
    except ValueError as error:
        raise ValueError("year and month must describe a valid calendar month") from error
    return period_start, date(year, month, monthrange(year, month)[1])


def _coerce_source(source: ReportingMonthSource | str) -> ReportingMonthSource:
    try:
        return ReportingMonthSource(source)
    except ValueError as error:
        raise ValueError(f"unsupported reporting month source: {source!r}") from error


def _reporting_month_owned_tables() -> tuple[object, ...]:
    """Return direct child tables whose lifecycle is owned by a reporting month.

    The schema deliberately keeps ``ON DELETE RESTRICT`` as a last-resort guard.
    The sanctioned draft-delete workflow removes month-owned rows explicitly in
    one transaction before deleting the parent month.
    """
    reporting_months = ReportingMonth.__table__
    owned_tables = []
    for table in reversed(Base.metadata.sorted_tables):
        if table is reporting_months:
            continue
        column = table.c.get("reporting_month_id")
        if column is None:
            continue
        if any(
            foreign_key.column.table is reporting_months and foreign_key.column.name == "id"
            for foreign_key in column.foreign_keys
        ):
            owned_tables.append(table)
    return tuple(owned_tables)


def list_reporting_months(session: Session) -> list[ReportingMonth]:
    statement = select(ReportingMonth).order_by(ReportingMonth.year, ReportingMonth.month)
    return list(session.scalars(statement))


def get_reporting_month(session: Session, month_id: int) -> ReportingMonth:
    reporting_month = session.get(ReportingMonth, month_id)
    if reporting_month is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")
    return reporting_month


def get_reporting_month_by_period(
    session: Session, *, year: int, month: int
) -> ReportingMonth | None:
    """Return the reporting month for ``(year, month)`` or ``None``.

    Read-only lookup used by the API layer to map duplicate-period creation
    attempts to an HTTP 409 conflict without changing the ValueError contract
    of :func:`create_reporting_month`.
    """
    return session.scalar(
        select(ReportingMonth).where(
            ReportingMonth.year == year,
            ReportingMonth.month == month,
        )
    )


def create_reporting_month(
    session: Session,
    *,
    year: int,
    month: int,
    snapshot_date: date,
    source: ReportingMonthSource | str = ReportingMonthSource.MANUAL,
) -> ReportingMonth:
    period_start, period_end = _period_bounds(year, month)
    if snapshot_date < period_start:
        raise ValueError("snapshot_date cannot be before the reporting period")
    normalized_source = _coerce_source(source)

    existing = session.scalar(
        select(ReportingMonth).where(
            ReportingMonth.year == year,
            ReportingMonth.month == month,
        )
    )
    if existing is not None:
        raise ValueError(f"reporting month {year:04d}-{month:02d} already exists")

    reporting_month = ReportingMonth(
        year=year,
        month=month,
        period_start=period_start,
        period_end=period_end,
        snapshot_date=snapshot_date,
        status=ReportingMonthStatus.DRAFT.value,
        source=normalized_source.value,
    )
    session.add(reporting_month)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError(f"reporting month {year:04d}-{month:02d} already exists") from error
    session.refresh(reporting_month)
    return reporting_month


def update_reporting_month(
    session: Session,
    month_id: int,
    *,
    snapshot_date: date | None = None,
    source: ReportingMonthSource | str | None = None,
) -> ReportingMonth:
    reporting_month = get_reporting_month(session, month_id)
    if reporting_month.status == ReportingMonthStatus.CLOSED.value:
        raise ClosedReportingMonthError("closed reporting month must be reopened before editing")

    if snapshot_date is not None:
        if snapshot_date < reporting_month.period_start:
            raise ValueError("snapshot_date cannot be before the reporting period")
        reporting_month.snapshot_date = snapshot_date
    if source is not None:
        reporting_month.source = _coerce_source(source).value

    session.commit()
    session.refresh(reporting_month)
    return reporting_month


def delete_reporting_month(session: Session, month_id: int) -> None:
    reporting_month = get_reporting_month(session, month_id)
    if reporting_month.status == ReportingMonthStatus.CLOSED.value:
        raise ClosedReportingMonthError("closed reporting month must be reopened before deletion")

    try:
        for table in _reporting_month_owned_tables():
            reporting_month_id = table.c.reporting_month_id
            session.execute(delete(table).where(reporting_month_id == month_id))
        session.delete(reporting_month)
        session.commit()
    except Exception:
        session.rollback()
        raise


def close_reporting_month(session: Session, month_id: int) -> ReportingMonth:
    reporting_month = get_reporting_month(session, month_id)
    reporting_month.status = ReportingMonthStatus.CLOSED.value
    session.commit()
    session.refresh(reporting_month)
    return reporting_month


def reopen_reporting_month(session: Session, month_id: int) -> ReportingMonth:
    reporting_month = get_reporting_month(session, month_id)
    reporting_month.status = ReportingMonthStatus.DRAFT.value
    session.commit()
    session.refresh(reporting_month)
    return reporting_month
