"""Integration tests for the ORM coverage/goal application service (C05)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExpectedCashFlowType,
    ExpenseType,
    InstrumentType,
    InvestmentCashFlowType,
    RubleAmount,
)
from hermes_finance.domain.coverage_goals import CoverageGoalsResult
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.coverage_goals import coverage_and_goals
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.expenses import create_expense_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

FORECAST_VERSION = "v1"
WARN_NO_DIVIDEND_MONTHS = "Нет закрытых месяцев для оценки дивидендного компонента"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "coverage_goals.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(
        session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
    )
    return month.id, account.id, instrument.id


def create_flow(
    session: Session, month_id: int, account_id: int, instrument_id: int, **overrides: object
):
    values: dict[str, object] = {
        "reporting_month_id": month_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "flow_type": ExpectedCashFlowType.COUPON,
        "expected_date": date(2030, 6, 1),
        "gross_amount": "1000.00",
        "expected_tax_amount": "130.00",
        "expected_net_amount": "870.00",
        "source": "synthetic calendar",
        "source_as_of_date": date(2030, 5, 12),
        "forecast_version": FORECAST_VERSION,
    }
    values.update(overrides)
    return create_expected_cash_flow(session, **values)


def build_month(session: Session, year: int, month: int) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 1)
    )
    return reporting_month.id


def add_dividend(session: Session, month_id: int, account_id: int, net_amount: str) -> None:
    stock = create_instrument(session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK)
    create_investment_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=stock.id,
        flow_type=InvestmentCashFlowType.DIVIDEND,
        event_date=date(2030, 1, 10),
        gross_amount=net_amount,
        tax_amount="0.00",
        commission_amount="0.00",
        net_amount=net_amount,
        source="synthetic",
    )


# --- full scenario: coverage + progress from forecast and goal ---


def test_full_scenario_coverage_and_progress(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        # forecast: coupon net 870.00 -> monthly 72.50
        create_flow(session, month_id, account_id, instrument_id)
        # mandatory expenses 5000.00 + comfortable 2000.00 (ignored)
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Rent",
            amount="5000.00",
            expense_type=ExpenseType.MANDATORY,
        )
        create_expense_entry(
            session,
            reporting_month_id=month_id,
            category="Fun",
            amount="2000.00",
            expense_type=ExpenseType.COMFORTABLE,
        )

        result = coverage_and_goals(session, month_id, FORECAST_VERSION)
        assert isinstance(result, CoverageGoalsResult)
        assert result.forecast_monthly == RubleAmount(7_250)  # 72.50 RUB
        # 72.50 / 5000.00 * 100 = 1.45%
        assert result.coverage_pct == Decimal("1.45")
        assert result.mandatory_expenses == RubleAmount(500_000)
        assert result.passive_income_minus_mandatory_expenses == RubleAmount(-492_750)
        # goal seeded 100000.00 -> 72.50 / 100000.00 * 100 = 0.07%
        assert result.goal_target == RubleAmount(10_000_000)
        assert result.goal_progress_pct == Decimal("0.07")
        assert result.is_approximate is False
        # forecast has no closed months -> honest dividend-history warning
        assert result.warnings == (WARN_NO_DIVIDEND_MONTHS,)
    finally:
        session.close()
        database.engine.dispose()


# --- zero mandatory expenses ---


def test_zero_expenses_coverage_is_none(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)
        result = coverage_and_goals(session, month_id, FORECAST_VERSION)
        assert result.coverage_pct is None
        assert result.passive_income_minus_mandatory_expenses == RubleAmount(7_250)
        assert "Обязательные расходы равны нулю — покрытие не рассчитывается" in result.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- actual average from closed months (C03) ---


def test_actual_average_from_closed_months(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _instrument_id = build_environment(session)
        closed_id = build_month(session, 2030, 1)
        add_dividend(session, closed_id, account_id, "500.00")
        close_reporting_month(session, closed_id)

        result = coverage_and_goals(session, month_id, FORECAST_VERSION)
        # actual average = 500.00 (single closed month)
        assert result.actual_average == RubleAmount(50_000)
    finally:
        session.close()
        database.engine.dispose()


# --- approximate forecast propagates ---


def test_approximate_forecast_propagates_flag(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            gross_amount="1000.00",
            expected_tax_amount=None,
            expected_net_amount=None,
        )
        result = coverage_and_goals(session, month_id, FORECAST_VERSION)
        assert result.is_approximate is True
        assert result.forecast_monthly == RubleAmount(8_333)  # 100000/12 = 8333.33 -> 8333
        assert result.goal_progress_pct == Decimal("0.08")
    finally:
        session.close()
        database.engine.dispose()


# --- forecast warnings flow through ---


def test_forecast_warnings_flow_through(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _account_id, _instrument_id = build_environment(session)
        # no expected flows, no closed months
        result = coverage_and_goals(session, month_id, FORECAST_VERSION)
        assert "Нет ожидаемых выплат в календаре прогноза" in result.warnings
        assert "Нет закрытых месяцев для оценки дивидендного компонента" in result.warnings
    finally:
        session.close()
        database.engine.dispose()
