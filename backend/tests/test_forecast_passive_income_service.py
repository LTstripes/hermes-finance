"""Integration tests for the ORM forecast passive-income application service (C04)."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    ExpectedCashFlowType,
    InstrumentType,
    InvestmentCashFlowType,
    RubleAmount,
)
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

WARN_NO_DIVIDEND_MONTHS = "Нет закрытых месяцев для оценки дивидендного компонента"
WARN_NO_EXPECTED_FLOWS = "Нет ожидаемых выплат в календаре прогноза"

FORECAST_VERSION = "v1"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "forecast-passive-income.db")
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


def add_dividend(
    session: Session,
    month_id: int,
    account_id: int,
    year: int,
    month: int,
    net_amount: str,
) -> None:
    stock = create_instrument(
        session,
        name=f"Synthetic Stock {year}-{month}",
        instrument_type=InstrumentType.STOCK,
    )
    create_investment_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=stock.id,
        flow_type=InvestmentCashFlowType.DIVIDEND,
        event_date=date(year, month, 10),
        gross_amount=net_amount,
        tax_amount="0.00",
        commission_amount="0.00",
        net_amount=net_amount,
        source="synthetic",
    )


# --- no closed months, no flows ---


def test_no_closed_months_and_no_flows_returns_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _account_id, _instrument_id = build_environment(session)
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        assert result.annual_total == RubleAmount(0)
        assert result.monthly_total == RubleAmount(0)
        assert result.breakdown.expected_deposit_interest == RubleAmount(0)
        assert result.breakdown.expected_coupon_net == RubleAmount(0)
        assert result.breakdown.expected_dividend_component == RubleAmount(0)
        assert result.breakdown.other_expected_capital_income == RubleAmount(0)
        assert result.is_approximate is False
        assert WARN_NO_DIVIDEND_MONTHS in result.warnings
        assert WARN_NO_EXPECTED_FLOWS in result.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- coupon with known tax ---


def test_coupon_with_known_tax(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        # gross 1000.00 - tax 130.00 = net 870.00
        assert result.annual_total == RubleAmount(87_000)
        assert result.monthly_total == RubleAmount(7_250)
        assert result.breakdown.expected_coupon_net == RubleAmount(87_000)
        assert result.is_approximate is False
        assert WARN_NO_EXPECTED_FLOWS not in result.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- coupon with unknown tax ---


def test_coupon_with_unknown_tax_is_approximate(tmp_path: Path) -> None:
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
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        # unknown tax -> net = gross, marked approximate
        assert result.annual_total == RubleAmount(100_000)
        assert result.monthly_total == RubleAmount(8_333)  # 100000/12 = 8333.33 -> 8333
        assert result.is_approximate is True
    finally:
        session.close()
        database.engine.dispose()


# --- redemption flow in calendar must not increase passive income ---


def test_redemption_flow_does_not_increase_annual(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            flow_type=ExpectedCashFlowType.REDEMPTION,
            expected_date=date(2030, 7, 1),
            gross_amount="10000.00",
            expected_tax_amount="0.00",
            expected_net_amount="10000.00",
        )
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        assert result.annual_total == RubleAmount(87_000)
        assert result.breakdown.expected_coupon_net == RubleAmount(87_000)
        assert result.is_approximate is False
    finally:
        session.close()
        database.engine.dispose()


# --- dividend expected flow in calendar must not affect annual (actuals only) ---


def test_dividend_expected_flow_does_not_affect_annual(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            flow_type=ExpectedCashFlowType.DIVIDEND,
            expected_date=date(2030, 7, 1),
            gross_amount="500.00",
            expected_tax_amount="65.00",
            expected_net_amount="435.00",
        )
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        assert result.annual_total == RubleAmount(87_000)
        assert result.breakdown.expected_dividend_component == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


# --- dividend component from closed months only ---


def test_dividend_component_uses_closed_months_only(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _instrument_id = build_environment(session)
        closed_id = build_month(session, 2030, 1)
        add_dividend(session, closed_id, account_id, 2030, 1, "500.00")
        close_reporting_month(session, closed_id)
        draft_id = build_month(session, 2030, 2)
        add_dividend(session, draft_id, account_id, 2030, 2, "500.00")
        # draft month intentionally left open -> excluded

        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        # 500.00 * 12 = 6000.00; monthly = 6000.00 / 12 = 500.00
        assert result.breakdown.expected_dividend_component == RubleAmount(600_000)
        assert result.annual_total == RubleAmount(600_000)
        assert result.monthly_total == RubleAmount(50_000)
        assert result.dividend_average == RubleAmount(50_000)
        assert "Дивидендный компонент оценён по 1 месяцев из 12" in result.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- three closed months average ---


def test_three_closed_months_average_dividend_component(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _instrument_id = build_environment(session)
        for i, net in enumerate(("500.00", "1000.00", "1500.00"), start=1):
            closed_id = build_month(session, 2030, i)
            add_dividend(session, closed_id, account_id, 2030, i, net)
            close_reporting_month(session, closed_id)

        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        # avg = (500.00 + 1000.00 + 1500.00) / 3 = 1000.00; component = 1000.00 * 12
        assert result.dividend_average == RubleAmount(100_000)
        assert result.breakdown.expected_dividend_component == RubleAmount(1_200_000)
        assert result.annual_total == RubleAmount(1_200_000)
        assert result.monthly_total == RubleAmount(100_000)
        assert "Дивидендный компонент оценён по 3 месяцев из 12" in result.warnings
    finally:
        session.close()
        database.engine.dispose()


# --- two coupon flows sum ---


def test_two_coupon_flows_sum(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)  # 870.00
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            expected_date=date(2030, 7, 1),
            gross_amount="500.00",
            expected_tax_amount="65.00",
            expected_net_amount="435.00",
        )
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        # 870.00 + 435.00 = 1305.00
        assert result.breakdown.expected_coupon_net == RubleAmount(130_500)
        assert result.annual_total == RubleAmount(130_500)
        assert result.monthly_total == RubleAmount(10_875)
    finally:
        session.close()
        database.engine.dispose()


# --- calendar window: flows after snapshot + 1 year are excluded ---


def test_flow_after_one_year_window_is_not_counted(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)  # 2030-06-01, in window
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            expected_date=date(2031, 5, 13),  # after snapshot (2030-05-12) + 1 year
            gross_amount="2000.00",
            expected_tax_amount="260.00",
            expected_net_amount="1740.00",
        )
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        assert result.breakdown.expected_coupon_net == RubleAmount(87_000)
        assert result.annual_total == RubleAmount(87_000)
    finally:
        session.close()
        database.engine.dispose()


# --- monthly = annual / 12 rounding through the service ---


@pytest.mark.parametrize(
    ("net_amount", "expected_annual", "expected_monthly"),
    [
        ("0.01", 1, 0),  # 1/12 = 0.0833 -> 0
        ("0.06", 6, 1),  # 6/12 = 0.5 -> 1 (HALF_UP)
        ("100.00", 10_000, 833),  # 10000/12 = 833.33 -> 833
    ],
)
def test_monthly_total_rounds_half_up(
    tmp_path: Path, net_amount: str, expected_annual: int, expected_monthly: int
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            gross_amount=net_amount,
            expected_tax_amount="0.00",
            expected_net_amount=net_amount,
        )
        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        assert result.annual_total == RubleAmount(expected_annual)
        assert result.monthly_total == RubleAmount(expected_monthly)
    finally:
        session.close()
        database.engine.dispose()


def test_monthly_total_rounds_with_dividend_component(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            gross_amount="100.00",
            expected_tax_amount="0.00",
            expected_net_amount="100.00",
        )
        closed_id = build_month(session, 2030, 1)
        add_dividend(session, closed_id, account_id, 2030, 1, "500.00")
        close_reporting_month(session, closed_id)

        result = forecast_passive_income(
            session, reporting_month_id=month_id, forecast_version=FORECAST_VERSION
        )
        # annual = 10000 + 600000 = 610000; monthly = 610000/12 = 50833.33 -> 50833
        assert result.breakdown.expected_coupon_net == RubleAmount(10_000)
        assert result.breakdown.expected_dividend_component == RubleAmount(600_000)
        assert result.annual_total == RubleAmount(610_000)
        assert result.monthly_total == RubleAmount(50_833)
    finally:
        session.close()
        database.engine.dispose()
