"""Integration tests for the ORM liquid-capital application service."""

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    DebtType,
    DepositType,
    InstrumentType,
    PriceSource,
    RubleAmount,
)
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.debts import create_debt
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.properties import create_property_snapshot
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "liquid_capital.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session) -> int:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    return month.id


def test_zero_month_returns_all_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        result = liquid_capital_for_month(session, month_id)
        assert result.total_assets == RubleAmount(0)
        assert result.total_debts_included == RubleAmount(0)
        assert result.liquid_capital_net == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_cash_deposit_and_position_sums_correctly(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        create_cash_balance(session, reporting_month_id=month_id, name="Wallet", amount="1000.00")
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Synthetic Deposit",
            deposit_type=DepositType.DEPOSIT,
            balance="5000.00",
            annual_rate="10.00",
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=10,
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            price_date=date(2030, 5, 12),
            price_source=PriceSource.MANUAL,
        )
        result = liquid_capital_for_month(session, month_id)
        assert result.total_assets == RubleAmount(100_000 + 500_000 + 150_000)
        assert result.breakdown.cash == RubleAmount(100_000)
        assert result.breakdown.deposits == RubleAmount(500_000)
        assert result.breakdown.securities == RubleAmount(150_000)
    finally:
        session.close()
        database.engine.dispose()


def test_property_snapshot_does_not_change_result(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_property_snapshot(
            session,
            reporting_month_id=month_id,
            name="Synthetic Flat",
            estimated_value="10000000.00",
            mortgage_balance="5000000.00",
            monthly_payment="50000.00",
        )
        result = liquid_capital_for_month(session, month_id)
        assert result.total_assets == RubleAmount(0)
        assert result.liquid_capital_net == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_account_include_in_capital_false_excludes_deposit_and_position(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        excluded_account = create_account(
            session,
            name="Excluded Account",
            account_type=AccountType.BROKERAGE,
            include_in_capital=False,
        )
        included_account = create_account(
            session,
            name="Included Account",
            account_type=AccountType.BROKERAGE,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=excluded_account.id,
            name="Excluded Deposit",
            deposit_type=DepositType.SAVINGS,
            balance="10000.00",
            annual_rate="5.00",
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=included_account.id,
            name="Included Deposit",
            deposit_type=DepositType.SAVINGS,
            balance="3000.00",
            annual_rate="5.00",
        )
        instrument = create_instrument(
            session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK
        )
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=excluded_account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit="1000.00",
            market_price_per_unit="2000.00",
            price_date=date(2030, 5, 12),
            price_source=PriceSource.MANUAL,
        )
        result = liquid_capital_for_month(session, month_id)
        assert result.breakdown.deposits == RubleAmount(300_000)
        assert result.breakdown.securities == RubleAmount(0)
        assert result.total_assets == RubleAmount(300_000)
    finally:
        session.close()
        database.engine.dispose()


def test_cash_include_in_capital_false_excluded(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            name="Included",
            amount="500.00",
            include_in_capital=True,
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            name="Excluded",
            amount="200.00",
            include_in_capital=False,
        )
        result = liquid_capital_for_month(session, month_id)
        assert result.breakdown.cash == RubleAmount(50_000)
    finally:
        session.close()
        database.engine.dispose()


def test_debts_included_subtracted_and_excluded_ignored(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_cash_balance(session, reporting_month_id=month_id, name="Cash", amount="10000.00")
        create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Card Debt",
            current_balance="3000.00",
        )
        create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.OTHER,
            name="Other Debt",
            current_balance="5000.00",
            include_in_liquid_capital=False,
        )
        result = liquid_capital_for_month(session, month_id)
        assert result.total_debts_included == RubleAmount(300_000)
        assert result.liquid_capital_net == RubleAmount(1_000_000 - 300_000)
    finally:
        session.close()
        database.engine.dispose()


def test_net_can_be_negative_when_debts_exceed_assets(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_cash_balance(session, reporting_month_id=month_id, name="Cash", amount="1000.00")
        create_debt(
            session,
            reporting_month_id=month_id,
            debt_type=DebtType.CREDIT_CARD,
            name="Big Card Debt",
            current_balance="5000.00",
        )
        result = liquid_capital_for_month(session, month_id)
        assert result.liquid_capital_net == RubleAmount(100_000 - 500_000)
    finally:
        session.close()
        database.engine.dispose()


def test_breakdown_by_class_sums_to_total_assets(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        create_cash_balance(session, reporting_month_id=month_id, name="Wallet", amount="500.00")
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Depo",
            deposit_type=DepositType.DEPOSIT,
            balance="2000.00",
            annual_rate="8.00",
        )
        instrument = create_instrument(
            session, name="Synthetic Fund", instrument_type=InstrumentType.FUND
        )
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=5,
            average_cost_per_unit="100.00",
            market_price_per_unit="120.00",
            price_date=date(2030, 5, 12),
            price_source=PriceSource.MANUAL,
        )
        result = liquid_capital_for_month(session, month_id)
        breakdown_sum = (
            result.breakdown.cash.kopecks
            + result.breakdown.deposits.kopecks
            + result.breakdown.securities.kopecks
            + result.breakdown.other_liquid_assets.kopecks
        )
        assert breakdown_sum == result.total_assets.kopecks
    finally:
        session.close()
        database.engine.dispose()


def test_per_account_breakdown_present(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Depo",
            deposit_type=DepositType.DEPOSIT,
            balance="3000.00",
            annual_rate="8.00",
        )
        instrument = create_instrument(
            session, name="Synthetic Fund", instrument_type=InstrumentType.FUND
        )
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=5,
            average_cost_per_unit="100.00",
            market_price_per_unit="120.00",
            price_date=date(2030, 5, 12),
            price_source=PriceSource.MANUAL,
        )
        result = liquid_capital_for_month(session, month_id)
        accounts = dict((item.account_id, item.amount) for item in result.accounts)
        assert account.id in accounts
        assert accounts[account.id] == RubleAmount(300_000 + 60_000)
    finally:
        session.close()
        database.engine.dispose()
