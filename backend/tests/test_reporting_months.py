from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import ReportingMonthSource, ReportingMonthStatus
from hermes_finance.persistence import Base, CashBalance, IncomeEntry
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
    get_reporting_month,
    list_reporting_months,
    reopen_reporting_month,
    update_reporting_month,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "reporting-months.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def test_create_reporting_month_keeps_period_and_snapshot_separate(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        reporting_month = create_reporting_month(
            session,
            year=2026,
            month=7,
            snapshot_date=date(2026, 8, 2),
        )

        assert reporting_month.period_start == date(2026, 7, 1)
        assert reporting_month.period_end == date(2026, 7, 31)
        assert reporting_month.snapshot_date == date(2026, 8, 2)
        assert reporting_month.status == ReportingMonthStatus.DRAFT.value
        assert reporting_month.source == ReportingMonthSource.MANUAL.value
        assert len(list_reporting_months(session)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_reporting_month_has_unique_year_and_month_and_valid_source(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        create_reporting_month(
            session,
            year=2026,
            month=7,
            snapshot_date=date(2026, 8, 2),
            source=ReportingMonthSource.EXCEL_MIGRATION,
        )

        with pytest.raises(ValueError, match="already exists"):
            create_reporting_month(
                session,
                year=2026,
                month=7,
                snapshot_date=date(2026, 8, 3),
            )
        with pytest.raises(ValueError, match="unsupported"):
            create_reporting_month(
                session,
                year=2026,
                month=8,
                snapshot_date=date(2026, 9, 1),
                source="imported",
            )
        with pytest.raises(ValueError, match="valid calendar month"):
            create_reporting_month(
                session,
                year=2026,
                month=13,
                snapshot_date=date(2026, 12, 31),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_closed_reporting_month_requires_reopen_before_edit_or_delete(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        reporting_month = create_reporting_month(
            session,
            year=2026,
            month=7,
            snapshot_date=date(2026, 8, 2),
        )
        closed = close_reporting_month(session, reporting_month.id)
        assert closed.status == ReportingMonthStatus.CLOSED.value

        with pytest.raises(ClosedReportingMonthError):
            update_reporting_month(session, reporting_month.id, snapshot_date=date(2026, 8, 3))
        with pytest.raises(ClosedReportingMonthError):
            delete_reporting_month(session, reporting_month.id)

        reopened = reopen_reporting_month(session, reporting_month.id)
        updated = update_reporting_month(session, reopened.id, snapshot_date=date(2026, 8, 3))
        assert updated.status == ReportingMonthStatus.DRAFT.value
        assert updated.snapshot_date == date(2026, 8, 3)
        delete_reporting_month(session, updated.id)
        with pytest.raises(LookupError):
            get_reporting_month(session, updated.id)
    finally:
        session.close()
        database.engine.dispose()


def test_delete_populated_draft_removes_month_owned_rows(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        reporting_month = create_reporting_month(
            session,
            year=2026,
            month=5,
            snapshot_date=date(2026, 5, 31),
        )
        session.add_all(
            [
                IncomeEntry(
                    reporting_month_id=reporting_month.id,
                    income_type="salary",
                    name="Зарплата",
                    gross_amount_kopecks=100_000,
                    tax_amount_kopecks=13_000,
                    net_amount_kopecks=87_000,
                    received_at=None,
                    is_recurring=True,
                    include_in_cash_flow=True,
                    include_in_passive_income=False,
                    notes=None,
                ),
                CashBalance(
                    reporting_month_id=reporting_month.id,
                    name="Наличные",
                    amount_kopecks=50_000,
                    currency="RUB",
                    include_in_capital=True,
                    notes=None,
                ),
            ]
        )
        session.commit()

        delete_reporting_month(session, reporting_month.id)

        assert session.get(type(reporting_month), reporting_month.id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(IncomeEntry)
                .where(IncomeEntry.reporting_month_id == reporting_month.id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CashBalance)
                .where(CashBalance.reporting_month_id == reporting_month.id)
            )
            == 0
        )
    finally:
        session.close()
        database.engine.dispose()


def test_snapshot_date_cannot_precede_reporting_period(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        with pytest.raises(ValueError, match="before the reporting period"):
            create_reporting_month(
                session,
                year=2026,
                month=7,
                snapshot_date=date(2026, 6, 30),
            )
    finally:
        session.close()
        database.engine.dispose()
