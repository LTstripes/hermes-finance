from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import ReportingMonthSource, ReportingMonthStatus
from hermes_finance.persistence import Base, CashBalance, IncomeEntry
from hermes_finance.services import _guard as month_guard
from hermes_finance.services import reporting_months as reporting_months_service
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
            update_reporting_month(
                session, reporting_month.id, source=ReportingMonthSource.ALFA_PDF
            )
        with pytest.raises(ClosedReportingMonthError):
            delete_reporting_month(session, reporting_month.id)

        reopened = reopen_reporting_month(session, reporting_month.id)
        updated = update_reporting_month(
            session,
            reopened.id,
            snapshot_date=date(2026, 8, 3),
            source=ReportingMonthSource.ALFA_PDF,
        )
        assert updated.status == ReportingMonthStatus.DRAFT.value
        assert updated.snapshot_date == date(2026, 8, 3)
        assert updated.source == ReportingMonthSource.ALFA_PDF.value
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


@pytest.mark.parametrize(
    ("change", "expected_date", "expected_source"),
    [
        ({"snapshot_date": date(2026, 8, 3)}, date(2026, 8, 2), "manual"),
        ({"source": ReportingMonthSource.ALFA_PDF}, date(2026, 8, 2), "manual"),
    ],
)
def test_close_wins_after_patch_session_saw_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict,
    expected_date: date,
    expected_source: str,
) -> None:
    session, database = session_for(tmp_path)
    patch_read_draft = Event()
    release_patch = Event()
    try:
        month = create_reporting_month(session, year=2026, month=7, snapshot_date=expected_date)
        with database.session_factory() as patch_session:
            original_get = reporting_months_service.get_reporting_month

            def paused_get(candidate_session: Session, month_id: int):
                result = original_get(candidate_session, month_id)
                if candidate_session is patch_session:
                    assert result.status == "draft"
                    patch_read_draft.set()
                    assert release_patch.wait(10)
                return result

            monkeypatch.setattr(reporting_months_service, "get_reporting_month", paused_get)
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(update_reporting_month, patch_session, month.id, **change)
                try:
                    assert patch_read_draft.wait(10)
                    with database.session_factory() as closer:
                        close_reporting_month(closer, month.id)
                finally:
                    release_patch.set()
                with pytest.raises(ClosedReportingMonthError, match="must be reopened"):
                    future.result(timeout=10)

        session.expire_all()
        persisted = get_reporting_month(session, month.id)
        assert (persisted.status, persisted.snapshot_date, persisted.source) == (
            "closed",
            expected_date,
            expected_source,
        )
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("change", "expected_date", "expected_source"),
    [
        ({"snapshot_date": date(2026, 8, 3)}, date(2026, 8, 3), "manual"),
        ({"source": ReportingMonthSource.ALFA_PDF}, date(2026, 8, 2), "alfa_pdf"),
    ],
)
def test_patch_reserves_writer_until_commit_before_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict,
    expected_date: date,
    expected_source: str,
) -> None:
    session, database = session_for(tmp_path)
    patch_reserved = Event()
    release_patch = Event()
    try:
        month = create_reporting_month(session, year=2026, month=7, snapshot_date=date(2026, 8, 2))
        original_guard = month_guard.require_editable_reporting_month

        def paused_guard(patch_session: Session, month_id: int):
            result = original_guard(patch_session, month_id)
            patch_reserved.set()
            assert release_patch.wait(10)
            return result

        monkeypatch.setattr(month_guard, "require_editable_reporting_month", paused_guard)

        def patch() -> None:
            with database.session_factory() as patch_session:
                update_reporting_month(patch_session, month.id, **change)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(patch)
            try:
                assert patch_reserved.wait(10)
                with database.session_factory() as closer:
                    closer.execute(text("PRAGMA busy_timeout=0"))
                    with pytest.raises(OperationalError, match="database is locked"):
                        close_reporting_month(closer, month.id)
                    closer.rollback()
            finally:
                release_patch.set()
            future.result(timeout=10)

        close_reporting_month(session, month.id)
        session.expire_all()
        persisted = get_reporting_month(session, month.id)
        assert (persisted.status, persisted.snapshot_date, persisted.source) == (
            "closed",
            expected_date,
            expected_source,
        )
    finally:
        session.close()
        database.engine.dispose()


def test_failed_patch_rolls_back_parent_changes_and_releases_writer(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2026, month=7, snapshot_date=date(2026, 8, 2))
        with database.session_factory() as patch_session:
            with pytest.raises(ValueError, match="unsupported reporting month source"):
                update_reporting_month(
                    patch_session, month.id, snapshot_date=date(2026, 8, 3), source="invalid"
                )
            assert not patch_session.in_transaction()

        with database.session_factory() as closer:
            closer.execute(text("PRAGMA busy_timeout=0"))
            close_reporting_month(closer, month.id)

        session.expire_all()
        persisted = get_reporting_month(session, month.id)
        assert (persisted.status, persisted.snapshot_date, persisted.source) == (
            "closed",
            date(2026, 8, 2),
            "manual",
        )
    finally:
        session.close()
        database.engine.dispose()
