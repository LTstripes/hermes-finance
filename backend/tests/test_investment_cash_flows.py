from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, InvestmentCashFlowType
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.investment_cash_flows import (
    InvestmentCashFlowNotFoundError,
    create_investment_cash_flow,
    delete_investment_cash_flow,
    get_investment_cash_flow,
    list_investment_cash_flows,
    list_passive_income_cash_flows,
    update_investment_cash_flow,
)
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "investment-cash-flows.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    brokerage = create_account(
        session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
    )
    deposit = create_account(session, name="Synthetic Deposit", account_type=AccountType.DEPOSIT)
    instrument = create_instrument(
        session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
    )
    return month.id, brokerage.id, deposit.id, instrument.id


def create_flow(
    session: Session, month_id: int, account_id: int, instrument_id: int, **overrides: object
):
    values: dict[str, object] = {
        "reporting_month_id": month_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "flow_type": InvestmentCashFlowType.COUPON,
        "event_date": date(2030, 5, 12),
        "gross_amount": "1000.00",
        "tax_amount": "130.00",
        "commission_amount": "10.00",
        "net_amount": "860.00",
        "source": "synthetic",
    }
    values.update(overrides)
    return create_investment_cash_flow(session, **values)


def test_coupon_counts_as_passive_income_and_redemption_does_not(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, brokerage_id, _, instrument_id = build_environment(session)
        coupon = create_flow(session, month_id, brokerage_id, instrument_id)
        redemption = create_flow(
            session,
            month_id,
            brokerage_id,
            instrument_id,
            flow_type=InvestmentCashFlowType.REDEMPTION,
            event_date=date(2030, 5, 13),
            gross_amount="10000.00",
            tax_amount="0.00",
            commission_amount="0.00",
            net_amount="10000.00",
        )
        passive = list_passive_income_cash_flows(session, month_id)
        assert [flow.id for flow in passive] == [coupon.id]
        assert redemption.id not in [flow.id for flow in passive]
    finally:
        session.close()
        database.engine.dispose()


def test_net_must_equal_gross_minus_tax_and_commission(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, brokerage_id, _, instrument_id = build_environment(session)
        with pytest.raises(ValueError, match="net_amount must equal"):
            create_flow(
                session,
                month_id,
                brokerage_id,
                instrument_id,
                gross_amount="100.00",
                tax_amount="10.00",
                commission_amount="5.00",
                net_amount="86.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_tax_and_commission_entries_can_have_negative_net(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, brokerage_id, _, instrument_id = build_environment(session)
        tax = create_flow(
            session,
            month_id,
            brokerage_id,
            instrument_id,
            flow_type=InvestmentCashFlowType.TAX,
            gross_amount="0.00",
            tax_amount="13.00",
            commission_amount="0.00",
            net_amount="-13.00",
        )
        commission = create_flow(
            session,
            month_id,
            brokerage_id,
            instrument_id,
            flow_type=InvestmentCashFlowType.COMMISSION,
            event_date=date(2030, 5, 13),
            gross_amount="0.00",
            tax_amount="0.00",
            commission_amount="5.00",
            net_amount="-5.00",
        )
        assert tax.net_amount_kopecks == -1_300
        assert commission.net_amount_kopecks == -500
        assert list_passive_income_cash_flows(session, month_id) == []
    finally:
        session.close()
        database.engine.dispose()


def test_deposit_interest_must_not_duplicate_deposit_snapshot(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, _, deposit_id, instrument_id = build_environment(session)
        with pytest.raises(ValueError, match="deposit_snapshots.actual_interest_received"):
            create_flow(
                session,
                month_id,
                deposit_id,
                instrument_id,
                flow_type=InvestmentCashFlowType.INTEREST,
                gross_amount="100.00",
                tax_amount="0.00",
                commission_amount="0.00",
                net_amount="100.00",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_investment_cash_flow_crud_and_nullable_instrument(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, brokerage_id, _, instrument_id = build_environment(session)
        flow = create_investment_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=brokerage_id,
            instrument_id=None,
            flow_type=InvestmentCashFlowType.COUPON,
            event_date=date(2030, 5, 12),
            gross_amount="1000.00",
            tax_amount="130.00",
            commission_amount="10.00",
            net_amount="860.00",
            currency="usd",
            source="synthetic",
            notes="synthetic note",
        )
        assert flow.instrument_id is None
        assert flow.currency == "USD"
        updated = update_investment_cash_flow(
            session,
            flow.id,
            gross_amount="2000.00",
            tax_amount="260.00",
            commission_amount="20.00",
            net_amount="1720.00",
            notes="updated",
        )
        assert updated.net_amount_kopecks == 172_000
        assert updated.notes == "updated"
        assert len(list_investment_cash_flows(session)) == 1
        delete_investment_cash_flow(session, flow.id)
        with pytest.raises(InvestmentCashFlowNotFoundError):
            get_investment_cash_flow(session, flow.id)
    finally:
        session.close()
        database.engine.dispose()
