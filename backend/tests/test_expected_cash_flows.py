from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.expected_cash_flows import (
    ExpectedCashFlowNotFoundError,
    create_expected_cash_flow,
    delete_expected_cash_flow,
    get_expected_cash_flow,
    list_expected_cash_flows,
    list_expected_passive_income_cash_flows,
    update_expected_cash_flow,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.reporting_months import create_reporting_month


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "expected-cash-flows.db")
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
        "forecast_version": "v1",
    }
    values.update(overrides)
    return create_expected_cash_flow(session, **values)


def test_known_tax_derives_exact_net_and_unknown_tax_is_approximate(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        known = create_flow(session, month_id, account_id, instrument_id)
        unknown = create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            expected_date=date(2030, 7, 1),
            gross_amount="500.00",
            expected_tax_amount=None,
            expected_net_amount=None,
        )
        assert known.expected_net_amount_kopecks == 87_000
        assert known.is_approximate is False
        assert unknown.expected_tax_amount_kopecks is None
        assert unknown.expected_net_amount_kopecks == 50_000
        assert unknown.is_approximate is True
    finally:
        session.close()
        database.engine.dispose()


def test_redemption_is_in_calendar_but_not_forecast_passive_income(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        coupon = create_flow(session, month_id, account_id, instrument_id)
        redemption = create_flow(
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
        calendar = list_expected_cash_flows(
            session, reporting_month_id=month_id, forecast_version="v1"
        )
        passive = list_expected_passive_income_cash_flows(
            session, reporting_month_id=month_id, forecast_version="v1"
        )
        assert [flow.id for flow in calendar] == [coupon.id, redemption.id]
        assert [flow.id for flow in passive] == [coupon.id]
    finally:
        session.close()
        database.engine.dispose()


def test_calendar_is_limited_to_next_twelve_months_from_snapshot(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        in_window = create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            expected_date=date(2031, 5, 11),
        )
        at_boundary = create_flow(
            session,
            month_id,
            account_id,
            instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            expected_date=date(2031, 5, 12),
        )
        calendar = list_expected_cash_flows(
            session, reporting_month_id=month_id, forecast_version="v1"
        )
        assert [flow.id for flow in calendar] == [in_window.id]
        assert at_boundary.id not in [flow.id for flow in calendar]
    finally:
        session.close()
        database.engine.dispose()


def test_forecast_version_cannot_mix_source_as_of_dates(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_flow(session, month_id, account_id, instrument_id)
        with pytest.raises(ValueError, match="one source_as_of_date"):
            create_flow(
                session,
                month_id,
                account_id,
                instrument_id,
                flow_type=ExpectedCashFlowType.INTEREST,
                expected_date=date(2030, 7, 1),
                source_as_of_date=date(2030, 5, 13),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_expected_cash_flow_crud_validation_and_delete(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        flow = create_flow(session, month_id, account_id, instrument_id, is_confirmed=True)
        updated = update_expected_cash_flow(
            session,
            flow.id,
            gross_amount="2000.00",
            expected_tax_amount="260.00",
            expected_net_amount="1740.00",
            notes="updated",
        )
        assert updated.expected_net_amount_kopecks == 174_000
        assert updated.notes == "updated"
        with pytest.raises(ValueError, match="expected_net_amount must equal"):
            update_expected_cash_flow(
                session,
                flow.id,
                gross_amount="2000.00",
                expected_tax_amount="260.00",
                expected_net_amount="1741.00",
            )
        delete_expected_cash_flow(session, flow.id)
        with pytest.raises(ExpectedCashFlowNotFoundError):
            get_expected_cash_flow(session, flow.id)
    finally:
        session.close()
        database.engine.dispose()
