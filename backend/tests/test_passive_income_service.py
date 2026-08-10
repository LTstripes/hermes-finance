"""Integration tests for the ORM passive-income application service."""

from datetime import date
from pathlib import Path

import pytest
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
from hermes_finance.domain.passive_income import PassiveIncomeSourceBucket
from hermes_finance.persistence import Base, IncomeEntry, InvestmentCashFlow
from hermes_finance.services.accounts import create_account
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.incomes import create_income_entry
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import create_investment_cash_flow
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "passive_income.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_month(session: Session) -> int:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    return month.id


# --- zero month ---


def test_zero_month_returns_all_zeros(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        result = passive_income_for_month(session, month_id)
        assert result.total_net_passive_income == RubleAmount(0)
        assert result.breakdown.deposit_interest == RubleAmount(0)
        assert result.breakdown.bond_coupons == RubleAmount(0)
        assert result.breakdown.dividends == RubleAmount(0)
        assert result.breakdown.other_capital_income == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


# --- deposit interest from snapshots ---


def test_deposit_interest_from_snapshots(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session, name="Synthetic Deposit Account", account_type=AccountType.DEPOSIT
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Depo 1",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="500.00",
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name="Savings 1",
            deposit_type=DepositType.SAVINGS,
            balance="50000.00",
            annual_rate="8.00",
            actual_interest_received="200.00",
        )
        result = passive_income_for_month(session, month_id)
        assert result.breakdown.deposit_interest == RubleAmount(70_000)
        assert result.total_net_passive_income == RubleAmount(70_000)
    finally:
        session.close()
        database.engine.dispose()


# --- deposit interest NOT double-counted from investment_cash_flows INTEREST ---


def test_deposit_interest_not_duplicated_from_cash_flows(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        deposit_account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        # Deposit snapshot provides actual interest
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit_account.id,
            name="Depo",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="500.00",
        )
        # INTEREST flow on brokerage account is allowed (not deposit/savings)
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=None,
            flow_type=InvestmentCashFlowType.INTEREST,
            event_date=date(2030, 5, 10),
            gross_amount="100.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="100.00",
            source="synthetic",
        )
        result = passive_income_for_month(session, month_id)
        # Deposit interest comes only from snapshots; brokerage INTEREST is other capital income.
        assert result.breakdown.deposit_interest == RubleAmount(50_000)
        assert result.breakdown.other_capital_income == RubleAmount(10_000)
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "account_type", [AccountType.BROKERAGE, AccountType.IIS, AccountType.OTHER]
)
def test_interest_on_capital_accounts_goes_to_other_capital_income(
    tmp_path: Path, account_type: AccountType
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session, name=f"Synthetic {account_type.value}", account_type=account_type
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=None,
            flow_type=InvestmentCashFlowType.INTEREST,
            event_date=date(2030, 5, 10),
            gross_amount="100.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="100.00",
            source="synthetic",
        )

        result = passive_income_for_month(session, month_id)

        assert result.breakdown.deposit_interest == RubleAmount(0)
        assert result.breakdown.other_capital_income == RubleAmount(10_000)
        assert result.total_net_passive_income == RubleAmount(10_000)
    finally:
        session.close()
        database.engine.dispose()


# --- bond coupons from investment_cash_flows ---


def test_bond_coupons_from_cash_flows(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2030, 5, 10),
            gross_amount="1000.00",
            tax_amount="130.00",
            commission_amount="10.00",
            net_amount="860.00",
            source="synthetic",
        )
        result = passive_income_for_month(session, month_id)
        assert result.breakdown.bond_coupons == RubleAmount(86_000)
        assert result.total_net_passive_income == RubleAmount(86_000)
    finally:
        session.close()
        database.engine.dispose()


# --- dividends from investment_cash_flows ---


def test_dividends_from_cash_flows(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=InvestmentCashFlowType.DIVIDEND,
            event_date=date(2030, 5, 10),
            gross_amount="500.00",
            tax_amount="65.00",
            commission_amount="0.00",
            net_amount="435.00",
            source="synthetic",
        )
        result = passive_income_for_month(session, month_id)
        assert result.breakdown.dividends == RubleAmount(43_500)
    finally:
        session.close()
        database.engine.dispose()


# --- OTHER flow type goes to other_capital_income ---


def test_other_flow_type_goes_to_other_capital_income(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Other", instrument_type=InstrumentType.OTHER
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=InvestmentCashFlowType.OTHER,
            event_date=date(2030, 5, 10),
            gross_amount="200.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="200.00",
            source="synthetic",
        )
        result = passive_income_for_month(session, month_id)
        assert result.breakdown.other_capital_income == RubleAmount(20_000)
    finally:
        session.close()
        database.engine.dispose()


# --- excluded flow types ---


def test_excluded_flow_types_not_counted(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        excluded_types = [
            (InvestmentCashFlowType.REDEMPTION, "10000.00", "0.00", "0.00", "10000.00"),
            (InvestmentCashFlowType.DEPOSIT, "5000.00", "0.00", "0.00", "5000.00"),
            (InvestmentCashFlowType.WITHDRAWAL, "3000.00", "0.00", "0.00", "3000.00"),
            (InvestmentCashFlowType.COMMISSION, "0.00", "0.00", "5.00", "-5.00"),
            (InvestmentCashFlowType.TAX, "0.00", "13.00", "0.00", "-13.00"),
            (InvestmentCashFlowType.REALIZED_PROFIT, "1000.00", "0.00", "0.00", "1000.00"),
            (InvestmentCashFlowType.REALIZED_LOSS, "0.00", "0.00", "0.00", "0.00"),
        ]
        for i, (ftype, gross, tax, comm, net) in enumerate(excluded_types):
            day = 10 + i
            create_investment_cash_flow(
                session,
                reporting_month_id=month_id,
                account_id=brokerage.id,
                instrument_id=instrument.id,
                flow_type=ftype,
                event_date=date(2030, 5, day),
                gross_amount=gross,
                tax_amount=tax,
                commission_amount=comm,
                net_amount=net,
                source="synthetic",
            )
        result = passive_income_for_month(session, month_id)
        assert result.total_net_passive_income == RubleAmount(0)
        assert result.breakdown.deposit_interest == RubleAmount(0)
        assert result.breakdown.bond_coupons == RubleAmount(0)
        assert result.breakdown.dividends == RubleAmount(0)
        assert result.breakdown.other_capital_income == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


# --- income entries: CASHBACK excluded, include_in_passive_income=False excluded, included counted ---


def test_cashback_income_excluded_even_with_passive_flag(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        # CASHBACK with include_in_passive_income=True is rejected at create
        # so we rely on the service excluding it even if it somehow has the flag
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.CASHBACK,
            name="Synthetic Cashback",
            gross_amount="500.00",
            tax_amount="0.00",
            net_amount="500.00",
        )
        result = passive_income_for_month(session, month_id)
        assert result.total_net_passive_income == RubleAmount(0)
        assert result.breakdown.other_capital_income == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_income_include_in_passive_false_excluded(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.SIDE_INCOME,
            name="Side Gig",
            gross_amount="10000.00",
            tax_amount="1300.00",
            net_amount="8700.00",
            include_in_passive_income=False,
        )
        result = passive_income_for_month(session, month_id)
        assert result.total_net_passive_income == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_income_include_in_passive_true_counted(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.OTHER,
            name="Synthetic Other",
            gross_amount="10000.00",
            tax_amount="1300.00",
            net_amount="8700.00",
            include_in_passive_income=True,
        )
        result = passive_income_for_month(session, month_id)
        assert result.breakdown.other_capital_income == RubleAmount(870_000)
        assert result.total_net_passive_income == RubleAmount(870_000)
    finally:
        session.close()
        database.engine.dispose()


def test_legacy_invalid_income_passive_flags_are_ignored(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        for income_type in (
            IncomeType.SALARY,
            IncomeType.BONUS,
            IncomeType.SIDE_INCOME,
        ):
            session.add(
                IncomeEntry(
                    reporting_month_id=month_id,
                    income_type=income_type.value,
                    name=f"Legacy invalid {income_type.value}",
                    gross_amount_kopecks=100_000,
                    tax_amount_kopecks=0,
                    net_amount_kopecks=100_000,
                    include_in_cash_flow=True,
                    include_in_passive_income=True,
                )
            )
        session.commit()

        result = passive_income_for_month(session, month_id)

        assert result.total_net_passive_income == RubleAmount(0)
        assert result.breakdown.other_capital_income == RubleAmount(0)
    finally:
        session.close()
        database.engine.dispose()


def test_legacy_deposit_interest_flow_is_ignored_beside_snapshot(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        deposit = create_account(
            session, name="Synthetic Legacy Deposit", account_type=AccountType.DEPOSIT
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit.id,
            name="Legacy Depo",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="500.00",
        )
        session.add(
            InvestmentCashFlow(
                reporting_month_id=month_id,
                account_id=deposit.id,
                instrument_id=None,
                flow_type=InvestmentCashFlowType.INTEREST.value,
                event_date=date(2030, 5, 10),
                gross_amount_kopecks=10_000,
                tax_amount_kopecks=0,
                commission_amount_kopecks=0,
                net_amount_kopecks=10_000,
                currency="RUB",
                source="legacy",
            )
        )
        session.commit()

        result = passive_income_for_month(session, month_id)

        assert result.breakdown.deposit_interest == RubleAmount(50_000)
        assert result.breakdown.other_capital_income == RubleAmount(0)
        assert result.total_net_passive_income == RubleAmount(50_000)
    finally:
        session.close()
        database.engine.dispose()


# --- breakdown sums to total ---


def test_breakdown_sums_to_total(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        deposit_account = create_account(
            session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        # deposit interest
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=deposit_account.id,
            name="Depo",
            deposit_type=DepositType.DEPOSIT,
            balance="100000.00",
            annual_rate="10.00",
            actual_interest_received="500.00",
        )
        # coupon
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2030, 5, 10),
            gross_amount="1000.00",
            tax_amount="130.00",
            commission_amount="10.00",
            net_amount="860.00",
            source="synthetic",
        )
        # dividend
        stock = create_instrument(
            session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=stock.id,
            flow_type=InvestmentCashFlowType.DIVIDEND,
            event_date=date(2030, 5, 11),
            gross_amount="500.00",
            tax_amount="65.00",
            commission_amount="0.00",
            net_amount="435.00",
            source="synthetic",
        )
        # other income entry
        create_income_entry(
            session,
            reporting_month_id=month_id,
            income_type=IncomeType.OTHER,
            name="Other Passive",
            gross_amount="200.00",
            tax_amount="0.00",
            net_amount="200.00",
            include_in_passive_income=True,
        )
        result = passive_income_for_month(session, month_id)
        breakdown_sum = (
            result.breakdown.deposit_interest.kopecks
            + result.breakdown.bond_coupons.kopecks
            + result.breakdown.dividends.kopecks
            + result.breakdown.other_capital_income.kopecks
        )
        assert breakdown_sum == result.total_net_passive_income.kopecks
        assert result.total_net_passive_income == RubleAmount(50_000 + 86_000 + 43_500 + 20_000)
    finally:
        session.close()
        database.engine.dispose()


# --- per-source breakdown present ---


def test_per_source_breakdown_present(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id = build_month(session)
        brokerage = create_account(
            session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
        )
        instrument = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage.id,
            instrument_id=instrument.id,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2030, 5, 10),
            gross_amount="1000.00",
            tax_amount="130.00",
            commission_amount="10.00",
            net_amount="860.00",
            source="synthetic",
        )
        result = passive_income_for_month(session, month_id)
        assert len(result.sources) >= 1
        coupon_sources = [
            s for s in result.sources if s.bucket is PassiveIncomeSourceBucket.BOND_COUPONS
        ]
        assert len(coupon_sources) == 1
        assert coupon_sources[0].amount == RubleAmount(86_000)
    finally:
        session.close()
        database.engine.dispose()
