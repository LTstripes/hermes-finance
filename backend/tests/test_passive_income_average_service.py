"""Integration tests for the ORM passive-income average application service (C03)."""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DepositType,
    IncomeType,
    InstrumentType,
    InvestmentCashFlowType,
    RubleAmount,
)
from hermes_finance.domain.passive_income_average import MonthlyPassiveIncome
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.passive_income_average import passive_income_average
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "passive_income_average.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, year: int, month: int) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 1)
    )
    return reporting_month.id


def add_deposit_interest(session: Session, month_id: int, account_id: int, amount: str) -> None:
    create_deposit_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        name="Depo",
        deposit_type=DepositType.DEPOSIT,
        balance="100000.00",
        annual_rate="10.00",
        actual_interest_received=amount,
    )


# --- no closed months ---


def test_no_closed_months_returns_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        result = passive_income_average(session)
        assert result.sum_total == RubleAmount(0)
        assert result.average == RubleAmount(0)
        assert result.count_months == 0
        assert result.is_complete_12m is False
        assert result.months == ()
    finally:
        session.close()
        database.engine.dispose()


# --- three closed months ---


def test_three_closed_months_average_from_deposit_interest(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        for i, amount in enumerate(("500.00", "1000.00", "500.00"), start=1):
            month_id = build_month(session, 2031, i)
            add_deposit_interest(session, month_id, account.id, amount)
            close_reporting_month(session, month_id)

        result = passive_income_average(session)
        assert result.count_months == 3
        assert result.is_complete_12m is False
        assert result.sum_total == RubleAmount(200_000)
        # 2000.00 / 3 = 666.666... -> 666.67 RUB
        assert result.average == RubleAmount(66_667)
    finally:
        session.close()
        database.engine.dispose()


# --- draft months excluded ---


def test_draft_months_are_excluded(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        draft_id = build_month(session, 2031, 1)
        add_deposit_interest(session, draft_id, account.id, "1000.00")
        # draft month intentionally left open
        closed_id = build_month(session, 2031, 2)
        add_deposit_interest(session, closed_id, account.id, "500.00")
        close_reporting_month(session, closed_id)

        result = passive_income_average(session)
        assert result.count_months == 1
        assert result.sum_total == RubleAmount(50_000)
        assert result.average == RubleAmount(50_000)
        assert result.is_complete_12m is False
    finally:
        session.close()
        database.engine.dispose()


# --- 13 closed months: rolling window ---


def test_thirteen_closed_months_use_last_twelve(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        for i in range(1, 13):
            month_id = build_month(session, 2031, i)
            add_deposit_interest(session, month_id, account.id, f"{10 * i}.00")
            close_reporting_month(session, month_id)
        month_id = build_month(session, 2032, 1)
        add_deposit_interest(session, month_id, account.id, "130.00")
        close_reporting_month(session, month_id)

        result = passive_income_average(session)
        assert result.count_months == 12
        assert result.is_complete_12m is True
        # kept months are (2031, 2) .. (2031, 12), (2032, 1): 20..130 RUB
        assert result.sum_total == RubleAmount(90_000)
        assert result.average == RubleAmount(7_500)
        # oldest month (2031, 1) must be excluded
        assert result.months[0].year == 2031
        assert result.months[0].month == 2
        assert result.months[0].amount == RubleAmount(2_000)
        assert result.months[-1].year == 2032
        assert result.months[-1].month == 1
        assert result.months[-1].amount == RubleAmount(13_000)
    finally:
        session.close()
        database.engine.dispose()


# --- closed month with zero data ---


def test_closed_month_with_zero_data_counts_as_zero(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        month_id = build_month(session, 2031, 1)
        add_deposit_interest(session, month_id, account.id, "500.00")
        close_reporting_month(session, month_id)
        empty_id = build_month(session, 2031, 2)
        close_reporting_month(session, empty_id)

        result = passive_income_average(session)
        assert result.count_months == 2
        assert result.sum_total == RubleAmount(50_000)
        assert result.average == RubleAmount(25_000)
    finally:
        session.close()
        database.engine.dispose()


# --- per-month aggregation across sources ---


def test_month_aggregates_deposit_coupon_and_income_sources(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 5)
        deposit_account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        add_deposit_interest(session, month_id, deposit_account.id, "500.00")
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2031, 5, 10),
            gross_amount="1000.00",
            tax_amount="130.00",
            commission_amount="10.00",
            net_amount="860.00",
            source="synthetic",
        )
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SIDE_INCOME,
            name="Synthetic Rent",
            gross_amount="10000.00",
            tax_amount="1300.00",
            net_amount="8700.00",
            include_in_passive_income=True,
        )
        close_reporting_month(session, month_id)

        result = passive_income_average(session)
        # 500.00 + 860.00 + 8700.00 = 10060.00 RUB
        assert result.count_months == 1
        assert result.sum_total == RubleAmount(1_006_000)
        assert result.average == RubleAmount(1_006_000)
        assert result.months[0].amount == RubleAmount(1_006_000)
    finally:
        session.close()
        database.engine.dispose()


# --- ordering ---


def test_result_months_ordered_by_year_month(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        for year, month in ((2032, 3), (2031, 1), (2032, 1), (2031, 12), (2031, 6)):
            month_id = build_month(session, year, month)
            add_deposit_interest(session, month_id, account.id, "100.00")
            close_reporting_month(session, month_id)

        result = passive_income_average(session)
        assert result.count_months == 5
        assert all(isinstance(m, MonthlyPassiveIncome) for m in result.months)
        assert [(m.year, m.month) for m in result.months] == [
            (2031, 1),
            (2031, 6),
            (2031, 12),
            (2032, 1),
            (2032, 3),
        ]
        assert result.sum_total == RubleAmount(50_000)
        assert result.average == RubleAmount(10_000)
    finally:
        session.close()
        database.engine.dispose()
