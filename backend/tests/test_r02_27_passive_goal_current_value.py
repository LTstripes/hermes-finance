from datetime import date
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DepositType,
    GoalType,
    InstrumentType,
    InvestmentCashFlowType,
    RubleAmount,
)
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.goal_achievement import build_goal_achievement_summary
from hermes_finance.services.goals import create_goal
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)


def test_passive_goal_current_value_uses_actual_closed_month_average_without_expected_calendar(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path / "r02-27-passive-goal.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        deposit_account = create_account(
            session, name="Synthetic deposit", account_type=AccountType.DEPOSIT
        )
        brokerage = create_account(
            session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
        )
        bond = create_instrument(
            session, name="Synthetic bond", instrument_type=InstrumentType.BOND
        )
        stock = create_instrument(
            session, name="Synthetic stock", instrument_type=InstrumentType.STOCK
        )
        create_goal(
            session,
            name="Passive income",
            goal_type=GoalType.PASSIVE_INCOME,
            target_value=RubleAmount(100_000_00),
            calculation_mode="monthly_net_passive_income",
        )

        january = create_reporting_month(
            session, year=2031, month=1, snapshot_date=date(2031, 1, 31)
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=january.id,
            account_id=deposit_account.id,
            name="Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="1000.00",
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=january.id,
            account_id=brokerage.id,
            instrument_id=bond.id,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2031, 1, 20),
            gross_amount="2000.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="2000.00",
            source="synthetic",
        )
        close_reporting_month(session, january.id)

        february = create_reporting_month(
            session, year=2031, month=2, snapshot_date=date(2031, 2, 28)
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=february.id,
            account_id=deposit_account.id,
            name="Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="3000.00",
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=february.id,
            account_id=brokerage.id,
            instrument_id=bond.id,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2031, 2, 20),
            gross_amount="1000.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="1000.00",
            source="synthetic",
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=february.id,
            account_id=brokerage.id,
            instrument_id=stock.id,
            flow_type=InvestmentCashFlowType.DIVIDEND,
            event_date=date(2031, 2, 21),
            gross_amount="2000.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="2000.00",
            source="synthetic",
        )
        close_reporting_month(session, february.id)

        summary = build_goal_achievement_summary(session, february.id)
        result = summary[0].achievement_forecast

        # January = 3,000; February = 6,000; actual rolling average = 4,500 RUB.
        # There are deliberately no expected_cash_flows rows in this test.
        assert result.current_value == RubleAmount(4_500_00)
        assert str(result.progress_pct) == "4.50"
        assert result.remaining_amount == RubleAmount(95_500_00)
        assert result.source_forecast_version is None
        assert result.warnings == (
            "Среднее за доступный период. Учтено 2 месяцев из 12.",
        )
    finally:
        session.close()
        database.engine.dispose()
