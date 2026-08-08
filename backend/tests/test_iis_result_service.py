"""Integration tests for the ORM IIS account-result service (C09).

Covers MASTER_SPEC §10.16 end to end against a real SQLite database:
- account validation (missing account, non-IIS account);
- unrealized from position snapshots is month-scoped;
- coupons/dividends/realized PnL and tax benefits are summed across all
  time; deposits and redemptions never appear in the result;
- received benefits feed portfolio_result_with_tax_benefit; planned and
  submitted stay breakdown-only; rejected benefits are ignored entirely;
- two IIS accounts are fully independent.

All amounts are exact integer kopecks (RubleAmount); every fixture value is
synthetic (2031/2032).
"""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    InstrumentType,
    InvestmentCashFlowType,
    RubleAmount,
    TaxBenefitStatus,
)
from hermes_finance.domain.iis_result import IisResultBreakdown
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import AccountNotFoundError, create_account
from hermes_finance.services.iis import create_iis_profile, create_tax_benefit
from hermes_finance.services.iis_result import iis_result
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "iis_result.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session, *, year: int = 2031, month: int = 1) -> int:
    reporting_month = create_reporting_month(
        session, year=year, month=month, snapshot_date=date(year, month, 10)
    )
    return reporting_month.id


def build_iis_account(session: Session, *, name: str = "Synthetic IIS Account") -> int:
    account = create_account(session, name=name, account_type=AccountType.IIS)
    create_iis_profile(session, account_id=account.id, iis_type="A", opened_at=date(2031, 1, 1))
    return account.id


def add_snapshot(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    market_price_per_unit_kopecks: int = 125_000,
    price_date: date = date(2031, 1, 15),
) -> None:
    # quantity 10 x (125000 - 100000 kop) = 250000 kopecks unrealized by
    # default; market_price_per_unit_kopecks overrides the market side.
    create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=10,
        average_cost_per_unit=100_000,
        market_price_per_unit=market_price_per_unit_kopecks,
        price_date=price_date,
    )


def add_flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    flow_type: InvestmentCashFlowType,
    net_kopecks: int,
    instrument_id: int | None = None,
    event_date: date = date(2031, 1, 15),
) -> None:
    # The flow service requires net = gross - tax - commission. The service
    # under test reads ONLY net_amount_kopecks, so for a negative net the
    # commission field carries the magnitude (gross 0); for a positive net
    # commission is 0. Signs are exact either way.
    commission_kopecks = max(-net_kopecks, 0)
    gross_kopecks = max(net_kopecks, 0)
    create_investment_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        event_date=event_date,
        gross_amount=RubleAmount(gross_kopecks),
        tax_amount=RubleAmount(0),
        commission_amount=RubleAmount(commission_kopecks),
        net_amount=RubleAmount(net_kopecks),
        source="synthetic",
    )


def add_benefit(
    session: Session,
    *,
    account_id: int,
    benefit_type: str,
    status: TaxBenefitStatus,
    amount_kopecks: int,
    received_at: date | None = None,
) -> None:
    create_tax_benefit(
        session,
        account_id=account_id,
        tax_year=2031,
        benefit_type=benefit_type,
        status=status,
        amount=RubleAmount(amount_kopecks),
        received_at=received_at,
    )


def _zero_breakdown() -> IisResultBreakdown:
    return IisResultBreakdown(
        unrealized=RubleAmount(0),
        coupons=RubleAmount(0),
        dividends=RubleAmount(0),
        realized_pnl=RubleAmount(0),
        received_tax_benefits=RubleAmount(0),
        planned_tax_benefits=RubleAmount(0),
        submitted_tax_benefits=RubleAmount(0),
    )


# --- account validation ---


def test_missing_account_raises_account_not_found(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        with pytest.raises(AccountNotFoundError):
            iis_result(session, account_id=999_999, reporting_month_id=month_id)
    finally:
        session.close()
        database.engine.dispose()


def test_account_without_iis_profile_raises(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        plain = create_account(
            session, name="Synthetic Plain Brokerage", account_type=AccountType.BROKERAGE
        )
        with pytest.raises(ValueError, match="not an IIS account"):
            iis_result(session, account_id=plain.id, reporting_month_id=month_id)
    finally:
        session.close()
        database.engine.dispose()


# --- full scenario ---


def test_full_scenario_matches_hand_computed_kopecks(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, year=2031, month=1)
        account_id = build_iis_account(session)
        bond = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        stock = create_instrument(
            session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK
        )
        # two snapshots -> 250000 + 250000 = 500000 kopecks unrealized
        add_snapshot(session, month_id=month_id, account_id=account_id, instrument_id=bond.id)
        add_snapshot(session, month_id=month_id, account_id=account_id, instrument_id=stock.id)
        # income flows: coupon 30000, dividend 20000 kopecks
        add_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.COUPON,
            net_kopecks=30_000,
            instrument_id=bond.id,
        )
        add_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.DIVIDEND,
            net_kopecks=20_000,
            instrument_id=stock.id,
        )
        # realized PnL: profit 150000 - loss 155000 = -5000 kopecks
        add_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.REALIZED_PROFIT,
            net_kopecks=150_000,
        )
        add_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.REALIZED_LOSS,
            net_kopecks=-155_000,
        )
        # tax benefits: received (dated), planned, submitted, rejected
        add_benefit(
            session,
            account_id=account_id,
            benefit_type="type_a",
            status=TaxBenefitStatus.RECEIVED,
            amount_kopecks=40_000,
            received_at=date(2031, 1, 20),
        )
        add_benefit(
            session,
            account_id=account_id,
            benefit_type="type_b",
            status=TaxBenefitStatus.PLANNED,
            amount_kopecks=60_000,
        )
        add_benefit(
            session,
            account_id=account_id,
            benefit_type="type_c",
            status=TaxBenefitStatus.SUBMITTED,
            amount_kopecks=10_000,
        )
        add_benefit(
            session,
            account_id=account_id,
            benefit_type="type_d",
            status=TaxBenefitStatus.REJECTED,
            amount_kopecks=99_999,
        )
        # deposits and redemptions must NOT affect the result
        add_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.DEPOSIT,
            net_kopecks=500_000,
        )
        add_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.REDEMPTION,
            net_kopecks=1_000_000,
            instrument_id=bond.id,
        )

        result = iis_result(session, account_id=account_id, reporting_month_id=month_id)
        # without = 500000 + 30000 + 20000 + (150000 - 155000) = 545000
        assert result.portfolio_result_without_tax_benefit == RubleAmount(545_000)
        # with = 545000 + 40000 = 585000
        assert result.portfolio_result_with_tax_benefit == RubleAmount(585_000)
        assert result.breakdown == IisResultBreakdown(
            unrealized=RubleAmount(500_000),
            coupons=RubleAmount(30_000),
            dividends=RubleAmount(20_000),
            realized_pnl=RubleAmount(-5_000),
            received_tax_benefits=RubleAmount(40_000),
            planned_tax_benefits=RubleAmount(60_000),
            submitted_tax_benefits=RubleAmount(10_000),
        )
    finally:
        session.close()
        database.engine.dispose()


# --- unrealized is month-scoped ---


def test_unrealized_is_month_scoped(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_1 = build_month(session, year=2031, month=1)
        month_2 = build_month(session, year=2031, month=2)
        account_id = build_iis_account(session)
        bond = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        add_snapshot(session, month_id=month_1, account_id=account_id, instrument_id=bond.id)
        # second-month snapshot with a higher market price
        add_snapshot(
            session,
            month_id=month_2,
            account_id=account_id,
            instrument_id=bond.id,
            market_price_per_unit_kopecks=150_000,
            price_date=date(2031, 2, 15),
        )

        result_1 = iis_result(session, account_id=account_id, reporting_month_id=month_1)
        assert result_1.breakdown.unrealized == RubleAmount(250_000)
        result_2 = iis_result(session, account_id=account_id, reporting_month_id=month_2)
        assert result_2.breakdown.unrealized == RubleAmount(500_000)
    finally:
        session.close()
        database.engine.dispose()


# --- cash flows are all-time ---


def test_cash_flows_are_all_time(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_1 = build_month(session, year=2031, month=1)
        month_2 = build_month(session, year=2031, month=2)
        account_id = build_iis_account(session)
        bond = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        # coupon flow created in 2031-02 must count for the 2031-01 report
        add_flow(
            session,
            month_id=month_2,
            account_id=account_id,
            flow_type=InvestmentCashFlowType.COUPON,
            net_kopecks=30_000,
            instrument_id=bond.id,
            event_date=date(2031, 2, 15),
        )

        result = iis_result(session, account_id=account_id, reporting_month_id=month_1)
        assert result.breakdown.coupons == RubleAmount(30_000)
        assert result.portfolio_result_without_tax_benefit == RubleAmount(30_000)
    finally:
        session.close()
        database.engine.dispose()


# --- two IIS accounts are independent ---


def test_two_iis_accounts_are_independent(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, year=2031, month=1)
        account_a = build_iis_account(session, name="Synthetic IIS Account A")
        account_b = build_iis_account(session, name="Synthetic IIS Account B")
        bond = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        # account B has its own snapshot, coupon flow and received benefit
        add_snapshot(session, month_id=month_id, account_id=account_b, instrument_id=bond.id)
        add_flow(
            session,
            month_id=month_id,
            account_id=account_b,
            flow_type=InvestmentCashFlowType.COUPON,
            net_kopecks=30_000,
            instrument_id=bond.id,
        )
        add_benefit(
            session,
            account_id=account_b,
            benefit_type="type_a",
            status=TaxBenefitStatus.RECEIVED,
            amount_kopecks=40_000,
            received_at=date(2031, 1, 20),
        )

        # account A sees nothing from B
        result_a = iis_result(session, account_id=account_a, reporting_month_id=month_id)
        assert result_a.portfolio_result_without_tax_benefit == RubleAmount(0)
        assert result_a.portfolio_result_with_tax_benefit == RubleAmount(0)
        assert result_a.breakdown == _zero_breakdown()

        # account B still sees its own values: 250000 + 30000 = 280000,
        # with benefit 280000 + 40000 = 320000
        result_b = iis_result(session, account_id=account_b, reporting_month_id=month_id)
        assert result_b.portfolio_result_without_tax_benefit == RubleAmount(280_000)
        assert result_b.portfolio_result_with_tax_benefit == RubleAmount(320_000)
        assert result_b.breakdown.unrealized == RubleAmount(250_000)
        assert result_b.breakdown.coupons == RubleAmount(30_000)
        assert result_b.breakdown.received_tax_benefits == RubleAmount(40_000)
    finally:
        session.close()
        database.engine.dispose()


# --- non-IIS account with flows still rejected ---


def test_non_iis_account_with_flows_raises(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session, year=2031, month=1)
        brokerage = create_account(
            session,
            name="Synthetic Brokerage With Flows",
            account_type=AccountType.BROKERAGE,
        )
        bond = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        add_flow(
            session,
            month_id=month_id,
            account_id=brokerage.id,
            flow_type=InvestmentCashFlowType.COUPON,
            net_kopecks=30_000,
            instrument_id=bond.id,
        )
        with pytest.raises(ValueError, match="not an IIS account"):
            iis_result(session, account_id=brokerage.id, reporting_month_id=month_id)
    finally:
        session.close()
        database.engine.dispose()
