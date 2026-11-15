"""ORM total-income projection: saved net facts, closed-only and zero writes."""

from datetime import date
from pathlib import Path

import pytest
from _month_close_helpers import close_fixture_month
from sqlalchemy import event, select

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, DepositType, IncomeType, RubleAmount
from hermes_finance.persistence import AppSettings, Base, IncomeEntry
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.reporting_months import create_reporting_month, reopen_reporting_month
from hermes_finance.services.settings import update_settings
from hermes_finance.services.total_income import total_income


def test_seeded_closed_history_is_read_only_and_excludes_draft(tmp_path: Path) -> None:
    database = create_database(tmp_path / "total.db")
    Base.metadata.create_all(database.engine)
    try:
        with database.session_factory() as session:
            account = create_account(
                session, name="Synthetic deposit", account_type=AccountType.DEPOSIT
            )
            ids = []
            for month, salary in ((1, "0.00"), (4, "10000.00"), (6, "20000.00")):
                report = create_reporting_month(
                    session, year=2031, month=month, snapshot_date=date(2031, month, 28)
                )
                ids.append(report.id)
                for kind, net, passive in (
                    (IncomeType.SALARY, salary, False),
                    (IncomeType.BONUS, "120.00", False),
                    (IncomeType.BONUS, "240.00", False),
                    (IncomeType.CASHBACK, "5.00", False),
                    (IncomeType.SIDE_INCOME, "7.00", False),
                    (IncomeType.OTHER, "8.00", True),
                ):
                    create_income_entry(
                        session,
                        reporting_month_id=report.id,
                        income_type=kind,
                        name=f"Synthetic {kind}",
                        gross_amount=net,
                        tax_amount="0.00",
                        net_amount=net,
                        include_in_cash_flow=False,
                        include_in_passive_income=passive,
                    )
                create_deposit_snapshot(
                    session,
                    reporting_month_id=report.id,
                    account_id=account.id,
                    name="Synthetic interest",
                    deposit_type=DepositType.DEPOSIT,
                    balance="1000.00",
                    annual_rate="10.00",
                    actual_interest_received="22.00",
                )
                close_fixture_month(session, report.id)
            draft = create_reporting_month(
                session, year=2031, month=7, snapshot_date=date(2031, 7, 28)
            )
            update_settings(session, passive_income_history_start_month="2031-04")
            saved = list(session.execute(select(IncomeEntry.id, IncomeEntry.net_amount_kopecks)))
            statements: list[str] = []

            def record(_conn, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)

            event.listen(database.engine, "before_cursor_execute", record)
            try:
                model = total_income(session, month_id=ids[-1])
            finally:
                event.remove(database.engine, "before_cursor_execute", record)
            assert not any(
                s.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}
                for s in statements
            )
            assert (
                list(session.execute(select(IncomeEntry.id, IncomeEntry.net_amount_kopecks)))
                == saved
            )
            result = model.result
            assert model.latest_closed_report_id == ids[-1]
            assert [p.reporting_month_id for p in result.points] == ids
            assert result.points[0].salary_is_estimate
            assert result.points[0].salary_net == RubleAmount.from_api("10000.00")
            assert result.points[0].passive_actual is None
            assert result.points[1].passive_actual == RubleAmount.from_api("30.00")
            assert result.points[1].other_net == RubleAmount.from_api("20.00")
            assert result.all.salary_sum == RubleAmount.from_api("40000.00")
            assert result.all.bonus_sum == RubleAmount.from_api("1080.00")
            assert result.all.passive_sum == RubleAmount.from_api("60.00")
            assert result.all.passive_months == 2
            assert result.all.monthly_average == RubleAmount.from_api("13453.33")
            assert result.all.current_level == RubleAmount.from_api("20120.00")
            for invalid in (ids[0], draft.id, 99999):
                with pytest.raises(LookupError):
                    total_income(session, month_id=invalid)
            reopen_reporting_month(session, ids[-1])
            assert total_income(session).latest_closed_report_id == ids[-2]
            assert total_income(session).result.all.months_observed == 2
    finally:
        database.engine.dispose()


def test_empty_read_does_not_seed_settings(tmp_path: Path) -> None:
    database = create_database(tmp_path / "empty.db")
    Base.metadata.create_all(database.engine)
    try:
        with database.session_factory() as session:
            result = total_income(session)
            assert result.latest_closed_report_id is None
            assert result.result.all.monthly_average is None
            assert list(session.scalars(select(AppSettings))) == []
    finally:
        database.engine.dispose()
