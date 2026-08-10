"""Integration tests for the ORM monthly-summary service (C10).

Covers the wiring of every Phase-C calculator into the unified
:class:`MonthlySummaryResult` against a real SQLite database:
- empty month assembly (None deltas, delta warning, ``calculation_version``);
- two-month delta matrix with hand-computed kopecks;
- ``forecast_version`` passthrough into forecast and coverage;
- warnings aggregation order (normalized bonus before delta warning);
- IIS wiring (one IIS account + received benefit, non-IIS adds nothing);
- deltas react only to liquid capital and passive income series.

All amounts are exact integer kopecks via :class:`RubleAmount`; every
fixture value is synthetic (2031/2032).
"""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DepositType,
    ExpectedCashFlowType,
    IncomeType,
    InstrumentType,
    RubleAmount,
    TaxBenefitStatus,
)
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.iis import create_iis_profile, create_tax_benefit
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.monthly_summary import monthly_summary
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

DELTA_WARNING = "Нет предыдущего месяца для расчёта дельты"
NORM_BONUS_WARNING = "Нет закрытых месяцев для оценки нормализованной премии"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "monthly_summary.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, year: int, month: int) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 10)
    )
    return reporting_month.id


def add_deposit(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    balance: str,
    actual_interest_received: str,
) -> None:
    create_deposit_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        name="Synthetic Deposit 1",
        deposit_type=DepositType.DEPOSIT,
        balance=balance,
        annual_rate="10.00",
        actual_interest_received=actual_interest_received,
    )


def add_salary(session: Session, *, month_id: int, net_amount: str) -> None:
    create_income_entry(
        session,
        reporting_month_id=month_id,
        income_type=IncomeType.SALARY,
        name="Synthetic Salary",
        gross_amount=net_amount,
        tax_amount="0.00",
        net_amount=net_amount,
    )


# --- empty month (single month, no data at all) ---


def test_empty_month_assembles(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        summary = monthly_summary(session, month_id)

        assert summary.year == 2031
        assert summary.month == 1
        assert summary.calculation_version == "v1"
        assert summary.iis == ()
        assert summary.liquid_capital.liquid_capital_net == RubleAmount(0)
        assert summary.passive_income_actual == RubleAmount(0)
        # no previous month -> deltas are None
        assert summary.liquid_capital_delta is None
        assert summary.passive_income_delta is None
        # delta warning present and appended last
        assert DELTA_WARNING in summary.warnings
        assert summary.warnings[-1] == DELTA_WARNING
    finally:
        session.close()
        database.engine.dispose()


# --- two months with different liquid capital and passive income ---


def test_two_months_deltas_hand_computed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        jan_id = build_month(session, 2031, 1)
        feb_id = build_month(session, 2031, 2)
        deposit_account = create_account(
            session, name="Synthetic Deposit Account", account_type=AccountType.DEPOSIT
        )
        # Jan: 100000.00 balance / 3000.00 interest; Feb: 150000.00 / 4500.00
        add_deposit(
            session,
            month_id=jan_id,
            account_id=deposit_account.id,
            balance="100000.00",
            actual_interest_received="3000.00",
        )
        add_deposit(
            session,
            month_id=feb_id,
            account_id=deposit_account.id,
            balance="150000.00",
            actual_interest_received="4500.00",
        )

        jan = monthly_summary(session, jan_id)
        feb = monthly_summary(session, feb_id)

        # Jan has no previous month: deltas are None.
        assert jan.liquid_capital_delta is None
        assert jan.passive_income_delta is None
        assert DELTA_WARNING in jan.warnings

        # Exact kopecks: 100000.00 RUB = 10_000_000; 150000.00 RUB = 15_000_000.
        assert jan.liquid_capital.liquid_capital_net == RubleAmount(10_000_000)
        assert feb.liquid_capital.liquid_capital_net == RubleAmount(15_000_000)
        assert feb.liquid_capital_delta == RubleAmount(5_000_000)  # 50000.00 RUB

        # Passive income: 3000.00 RUB = 300_000; 4500.00 RUB = 450_000 kopecks.
        assert jan.passive_income_actual == RubleAmount(300_000)
        assert feb.passive_income_actual == RubleAmount(450_000)
        assert feb.passive_income_delta == RubleAmount(150_000)  # 1500.00 RUB

        # Feb has a previous month: no delta warning.
        assert DELTA_WARNING not in feb.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- forecast_version passthrough ---


def test_forecast_version_passthrough(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 1)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        # A v2-only expected coupon: 1000.00 gross, 130.00 tax, 870.00 net.
        create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2031, 11, 1),
            gross_amount="1000.00",
            expected_tax_amount="130.00",
            expected_net_amount="870.00",
            source="synthetic calendar",
            source_as_of_date=date(2031, 1, 10),
            forecast_version="v2",
        )

        # v2: the flow is seen by the forecast and coverage.
        v2_summary = monthly_summary(session, month_id, forecast_version="v2")
        assert v2_summary.forecast.annual_total == RubleAmount(87_000)  # 870.00 RUB
        assert v2_summary.forecast.monthly_total == RubleAmount(7_250)  # 87000/12
        assert v2_summary.coverage.forecast_monthly == RubleAmount(7_250)

        # Default v1: the v2 flow is excluded from the forecast.
        v1_summary = monthly_summary(session, month_id)
        assert v1_summary.forecast.annual_total == RubleAmount(0)
        assert v1_summary.calculation_version == "v1"
    finally:
        session.close()
        database.engine.dispose()


# --- warnings aggregation: no closed months + no previous month ---


def test_warnings_aggregation_no_closed_months_and_no_previous(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2032, 1)
        summary = monthly_summary(session, month_id)

        assert NORM_BONUS_WARNING in summary.warnings
        assert DELTA_WARNING in summary.warnings
        # Fixed order: normalized-bonus warning comes before the delta warning,
        # and the delta warning is the final element.
        assert summary.warnings.index(NORM_BONUS_WARNING) < summary.warnings.index(DELTA_WARNING)
        assert summary.warnings[-1] == DELTA_WARNING
        # Forecast warnings are also aggregated.
        assert "Нет закрытых месяцев для оценки дивидендного компонента" in summary.warnings
        assert "Нет ожидаемых выплат в календаре прогноза" in summary.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- IIS wiring ---


def test_iis_wiring_received_benefit_and_non_iis_ignored(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, 2031, 3)
        iis_account = create_account(
            session, name="Synthetic IIS Account", account_type=AccountType.IIS
        )
        create_iis_profile(
            session,
            account_id=iis_account.id,
            iis_type="A",
            opened_at=date(2031, 1, 1),
        )
        create_tax_benefit(
            session,
            account_id=iis_account.id,
            tax_year=2031,
            benefit_type="A",
            status=TaxBenefitStatus.RECEIVED,
            amount="52000.00",
        )

        summary = monthly_summary(session, month_id)
        assert len(summary.iis) == 1
        assert summary.iis[0].portfolio_result_without_tax_benefit == RubleAmount(0)
        # 52000.00 RUB = 5_200_000 kopecks.
        assert summary.iis[0].portfolio_result_with_tax_benefit == RubleAmount(5_200_000)
        assert summary.iis[0].breakdown.received_tax_benefits == RubleAmount(5_200_000)

        # A second, non-IIS account must not add anything to the IIS tuple.
        create_account(session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE)
        summary_after = monthly_summary(session, month_id)
        assert len(summary_after.iis) == 1
    finally:
        session.close()
        database.engine.dispose()


# --- deltas react only to liquid capital and passive income ---


def test_deltas_only_liquid_capital_and_passive_income(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        jan_id = build_month(session, 2031, 1)
        feb_id = build_month(session, 2031, 2)
        deposit_account = create_account(
            session, name="Synthetic Deposit Account", account_type=AccountType.DEPOSIT
        )
        # Identical capital and passive income in both months.
        add_deposit(
            session,
            month_id=jan_id,
            account_id=deposit_account.id,
            balance="100000.00",
            actual_interest_received="3000.00",
        )
        add_deposit(
            session,
            month_id=feb_id,
            account_id=deposit_account.id,
            balance="100000.00",
            actual_interest_received="3000.00",
        )
        # Only the salary entry differs between the months.
        add_salary(session, month_id=jan_id, net_amount="100000.00")
        add_salary(session, month_id=feb_id, net_amount="150000.00")

        jan = monthly_summary(session, jan_id)
        close_reporting_month(session, jan_id)
        feb = monthly_summary(session, feb_id)

        # Salary is neither liquid capital nor passive income, so a salary-only
        # change must leave both deltas at exactly zero kopecks (not None).
        assert jan.liquid_capital.liquid_capital_net == RubleAmount(10_000_000)
        assert feb.liquid_capital.liquid_capital_net == RubleAmount(10_000_000)
        assert jan.passive_income_actual == RubleAmount(300_000)
        assert feb.passive_income_actual == RubleAmount(300_000)
        assert feb.liquid_capital_delta is not None
        assert feb.passive_income_delta is not None
        assert feb.liquid_capital_delta == RubleAmount(0)
        assert feb.passive_income_delta == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()
