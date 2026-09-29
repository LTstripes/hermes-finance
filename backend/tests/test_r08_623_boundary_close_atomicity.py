"""Independent-connection races for performance evidence and monthly Close."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event, current_thread, main_thread

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

import hermes_finance.services.cash_boundary_coverage as cash_service
import hermes_finance.services.in_kind_boundary_coverage as in_kind_service
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType
from hermes_finance.persistence import Base, InKindMovement
from hermes_finance.persistence import CashBoundaryCoverage as CashCoverage
from hermes_finance.persistence import InKindBoundaryCoverage as InKindCoverage
from hermes_finance.services.accounts import create_account
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)

FEB_START = date(2030, 2, 1)
FEB_END = date(2030, 2, 28)
JAN_START = date(2030, 1, 1)
JAN_END = date(2030, 1, 31)
MAR_START = date(2030, 3, 1)
MAR_END = date(2030, 3, 31)


def _seed(tmp_path: Path):
    database = create_database(tmp_path / "boundary-close.db")
    Base.metadata.create_all(database.engine)
    with database.session_factory() as session:
        january = create_reporting_month(session, year=2030, month=1, snapshot_date=JAN_END)
        february = create_reporting_month(session, year=2030, month=2, snapshot_date=FEB_END)
        account = create_account(
            session, name="Synthetic Boundary Account", account_type=AccountType.BROKERAGE
        )
        return database, january.id, february.id, account.id


def _coverage_module(kind: str):
    return cash_service if kind == "cash" else in_kind_service


def _coverage_model(kind: str):
    return CashCoverage if kind == "cash" else InKindCoverage


def _create(module, session, account_id: int, start: date, end: date, **kwargs):
    return getattr(
        module, f"create_{'cash' if module is cash_service else 'in_kind'}_boundary_coverage"
    )(session, account_id=account_id, covered_from=start, covered_to=end, **kwargs)


@pytest.mark.parametrize(
    "kind,operation",
    [
        ("cash", "create"),
        ("cash", "attest"),
        ("cash", "update"),
        ("cash", "revoke"),
        ("in_kind", "create"),
        ("in_kind", "attest"),
        ("in_kind", "update"),
        ("in_kind", "revoke"),
        ("in_kind", "movement"),
    ],
)
@pytest.mark.parametrize("winner", ["writer", "close"])
def test_evidence_write_serializes_with_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, operation: str, winner: str
) -> None:
    database, _, month_id, account_id = _seed(tmp_path)
    module = _coverage_module(kind)
    model = _coverage_model(kind)
    coverage_id = None
    if operation in {"update", "revoke"} or (kind == "cash" and operation == "attest"):
        with database.session_factory() as session:
            coverage_id = _create(
                module,
                session,
                account_id,
                FEB_START,
                FEB_END,
                coverage_state="complete" if operation == "revoke" else "unknown",
            ).id

    reached = Event()
    release = Event()
    pause_before_reserve = winner == "close" and operation in {"update", "revoke"}
    if pause_before_reserve:
        original_reserve = module.reserve_reporting_month_interval_writer

        def paused_reserve(*args, **kwargs):
            if current_thread() is not main_thread() and not reached.is_set():
                reached.set()
                assert release.wait(10)
            return original_reserve(*args, **kwargs)

        monkeypatch.setattr(module, "reserve_reporting_month_interval_writer", paused_reserve)
    original_guard = getattr(module, f"require_editable_{kind}_boundary_interval")

    def paused_guard(*args, **kwargs):
        if winner == "close" and not pause_before_reserve:
            reached.set()
            assert release.wait(10)
        result = original_guard(*args, **kwargs)
        if winner == "writer":
            reached.set()
            assert release.wait(10)
        return result

    monkeypatch.setattr(module, original_guard.__name__, paused_guard)

    def mutate() -> str:
        with database.session_factory() as session:
            try:
                if operation == "create":
                    _create(module, session, account_id, FEB_START, FEB_END)
                elif operation == "attest":
                    getattr(module, f"attest_{kind}_boundary_history")(
                        session,
                        account_id=account_id,
                        covered_from=FEB_START,
                        covered_to=FEB_END,
                    )
                elif operation == "update":
                    getattr(module, f"update_{kind}_boundary_coverage")(
                        session, coverage_id, coverage_state="complete"
                    )
                elif operation == "revoke":
                    getattr(module, f"revoke_{kind}_boundary_coverage")(session, coverage_id)
                else:
                    in_kind_service.create_in_kind_movement(
                        session,
                        reporting_month_id=month_id,
                        event_date=date(2030, 2, 15),
                        movement_kind="external_in",
                        destination_account_id=account_id,
                    )
            except ClosedReportingMonthError:
                return "closed"
            return "committed"

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(mutate)
            try:
                assert reached.wait(10)
                with database.session_factory() as closer:
                    closer.execute(text("PRAGMA busy_timeout=0"))
                    if winner == "close":
                        close_reporting_month(closer, month_id)
                    else:
                        with pytest.raises(OperationalError, match="database is locked"):
                            close_reporting_month(closer, month_id)
                        closer.rollback()
            finally:
                release.set()
            assert future.result(timeout=10) == ("committed" if winner == "writer" else "closed")

        if winner == "writer":
            with database.session_factory() as closer:
                close_reporting_month(closer, month_id)
        with database.session_factory() as check:
            if operation == "movement":
                assert len(check.scalars(select(InKindMovement)).all()) == (
                    1 if winner == "writer" else 0
                )
            else:
                rows = check.scalars(select(model)).all()
                assert len(rows) == (0 if winner == "close" and coverage_id is None else 1)
                if coverage_id is not None:
                    assert rows[0].coverage_state == (
                        "complete"
                        if (operation in {"update", "attest"} and winner == "writer")
                        or (operation == "revoke" and winner == "close")
                        else "unknown"
                    )
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("kind", ["cash", "in_kind"])
def test_update_checks_old_and_new_intervals_and_reopen(tmp_path: Path, kind: str) -> None:
    database, january_id, _, account_id = _seed(tmp_path)
    module = _coverage_module(kind)
    model = _coverage_model(kind)
    try:
        with database.session_factory() as writer:
            january = _create(module, writer, account_id, JAN_START, JAN_END)
            february = _create(module, writer, account_id, FEB_START, FEB_END)
            january_coverage_id, february_coverage_id = january.id, february.id
        with database.session_factory() as lifecycle:
            close_reporting_month(lifecycle, january_id)

        update = getattr(module, f"update_{kind}_boundary_coverage")
        with database.session_factory() as writer:
            with pytest.raises(ClosedReportingMonthError):
                update(writer, january_coverage_id, covered_from=MAR_START, covered_to=MAR_END)
            with pytest.raises(ClosedReportingMonthError):
                update(writer, february_coverage_id, covered_from=JAN_START, covered_to=JAN_END)
        with database.session_factory() as check:
            assert [
                (row.covered_from, row.covered_to)
                for row in check.scalars(select(model).order_by(model.id))
            ] == [(JAN_START, JAN_END), (FEB_START, FEB_END)]

        with database.session_factory() as lifecycle:
            reopen_reporting_month(lifecycle, january_id)
        with database.session_factory() as writer:
            update(writer, january_coverage_id, covered_from=MAR_START, covered_to=MAR_END)
            update(writer, february_coverage_id, covered_from=JAN_START, covered_to=JAN_END)
        with database.session_factory() as check:
            assert [
                (row.covered_from, row.covered_to)
                for row in check.scalars(select(model).order_by(model.id))
            ] == [(MAR_START, MAR_END), (JAN_START, JAN_END)]
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("kind", ["cash", "in_kind"])
def test_update_rechecks_old_interval_after_competing_move_and_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    database, january_id, _, account_id = _seed(tmp_path)
    module = _coverage_module(kind)
    model = _coverage_model(kind)
    update = getattr(module, f"update_{kind}_boundary_coverage")
    with database.session_factory() as session:
        coverage_id = _create(module, session, account_id, FEB_START, FEB_END).id

    reached = Event()
    release = Event()
    original_reserve = module.reserve_reporting_month_interval_writer

    def paused_reserve(*args, **kwargs):
        if current_thread() is not main_thread() and not reached.is_set():
            reached.set()
            assert release.wait(10)
        return original_reserve(*args, **kwargs)

    monkeypatch.setattr(module, "reserve_reporting_month_interval_writer", paused_reserve)

    def stale_update() -> str:
        with database.session_factory() as writer:
            try:
                update(writer, coverage_id, covered_from=MAR_START, covered_to=MAR_END)
            except ClosedReportingMonthError:
                return "closed"
            return "committed"

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(stale_update)
            try:
                assert reached.wait(10)
                with database.session_factory() as competing_writer:
                    update(
                        competing_writer,
                        coverage_id,
                        covered_from=JAN_START,
                        covered_to=JAN_END,
                    )
                with database.session_factory() as closer:
                    close_reporting_month(closer, january_id)
            finally:
                release.set()
            assert future.result(timeout=10) == "closed"
        with database.session_factory() as check:
            row = check.scalar(select(model))
            assert (row.covered_from, row.covered_to) == (JAN_START, JAN_END)
    finally:
        database.engine.dispose()


@pytest.mark.parametrize("kind", ["cash", "in_kind"])
def test_failed_staging_rolls_back_evidence_and_releases_close(tmp_path: Path, kind: str) -> None:
    database, _, month_id, account_id = _seed(tmp_path)
    module = _coverage_module(kind)
    model = _coverage_model(kind)
    try:
        with database.session_factory() as writer:
            getattr(module, f"stage_create_{kind}_boundary_coverage")(
                writer,
                account_id=account_id,
                covered_from=FEB_START,
                covered_to=FEB_END,
            )
            with pytest.raises(ValueError, match="provenance_kind must not be empty"):
                getattr(module, f"stage_create_{kind}_boundary_coverage")(
                    writer,
                    account_id=account_id,
                    covered_from=FEB_START,
                    covered_to=FEB_END,
                    provenance_kind=" ",
                )
            writer.rollback()
        with database.session_factory() as closer:
            closer.execute(text("PRAGMA busy_timeout=0"))
            close_reporting_month(closer, month_id)
        with database.session_factory() as check:
            assert check.scalars(select(model)).all() == []
    finally:
        database.engine.dispose()
