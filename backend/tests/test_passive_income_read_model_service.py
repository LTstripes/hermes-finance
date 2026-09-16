"""Service tests for the Home passive-income read model."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, DepositType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.passive_income_history import passive_income_history
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month
from hermes_finance.services.settings import update_settings


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "passive_income_read_model.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def test_history_keeps_closed_points_and_marks_average_window_after_boundary(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic deposit", account_type=AccountType.DEPOSIT
        )

        before_id = create_reporting_month(
            session, year=2031, month=1, snapshot_date=date(2031, 1, 31)
        ).id
        create_deposit_snapshot(
            session,
            reporting_month_id=before_id,
            account_id=account.id,
            name="Synthetic January deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="100.00",
        )
        close_reporting_month(session, before_id)

        boundary_id = create_reporting_month(
            session, year=2031, month=5, snapshot_date=date(2031, 5, 31)
        ).id
        close_reporting_month(session, boundary_id)
        draft_id = create_reporting_month(
            session, year=2031, month=6, snapshot_date=date(2031, 6, 30)
        ).id
        assert draft_id > boundary_id

        update_settings(session, passive_income_history_start_month="2031-05")
        result = passive_income_history(session)

        assert [point.reporting_month_id for point in result.points] == [before_id, boundary_id]
        assert [point.passive_income_actual for point in result.points] == [
            RubleAmount(10_000),
            RubleAmount(0),
        ]
        assert [point.included_in_average_window for point in result.points] == [False, True]
        assert result.average.average == RubleAmount(0)
        assert result.average.count_months == 1
        assert result.average.months_used == ("2031-05",)
        assert result.latest_closed_report_id == boundary_id
        assert result.selected_report is not None
        assert result.selected_report.reporting_month_id == boundary_id
        assert result.selected_report.result.breakdown.deposit_interest == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()
