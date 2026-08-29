"""Synthetic R08-01B valuation-point and performance-coverage tests."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    CoverageStatus,
    PerformanceScope,
    ValuationPointStatus,
    ValuationQuality,
)
from hermes_finance.persistence import Account, Base, CashBalance, ReportingMonth
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month
from hermes_finance.services.valuation_points import valuation_point_for_month


def _environment(tmp_path: Path) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-01b.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 31))
    account = create_account(session, name="Synthetic Broker", account_type=AccountType.BROKERAGE)
    other_account = create_account(
        session,
        name="Synthetic Other Broker",
        account_type=AccountType.BROKERAGE,
        include_in_returns=False,
    )
    instrument = create_instrument(session, name="Synthetic Bond", instrument_type="bond")
    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity=1,
        average_cost_per_unit="1000.00",
        market_price_per_unit="1100.00",
        price_date=month.snapshot_date,
    )
    create_deposit_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic Deposit",
        deposit_type="deposit",
        balance="2000.00",
        annual_rate="10.00",
    )
    create_cash_balance(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic Broker Cash",
        amount="300.00",
    )
    return session, database, month.id, account.id, other_account.id


def test_complete_valuation_point_has_exact_total_and_provenance(tmp_path: Path) -> None:
    session, database, month_id, account_id, _ = _environment(tmp_path)
    try:
        close_reporting_month(session, month_id)
        point = valuation_point_for_month(session, month_id)

        assert point.status is ValuationPointStatus.AVAILABLE
        assert point.quality is ValuationQuality.EXACT
        assert point.valuation_date == date(2030, 5, 31)
        assert point.performance_currency == "RUB"
        assert point.total_value is not None
        assert point.total_value.kopecks == 340_000
        assert point.coverage.status is CoverageStatus.COMPLETE
        assert {item.source_kind for item in point.provenance} == {
            "position_snapshot",
            "deposit_snapshot",
            "cash_balance",
        }
        assert (
            valuation_point_for_month(
                session, month_id, scope=PerformanceScope.ACCOUNT, account_id=account_id
            ).total_value
            == point.total_value
        )
    finally:
        session.close()
        database.engine.dispose()


def test_missing_account_component_is_unknown_not_zero(tmp_path: Path) -> None:
    session, database, month_id, _account_id, other_account_id = _environment(tmp_path)
    try:
        other_account = session.get(Account, other_account_id)
        assert other_account is not None
        other_account.include_in_returns = True
        session.commit()
        close_reporting_month(session, month_id)
        point = valuation_point_for_month(session, month_id)

        assert point.status is ValuationPointStatus.UNKNOWN
        assert point.total_value is None
        assert "not_computable_scope_coverage_incomplete" in point.coverage.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_missing_valuation_component_is_unknown_not_zero(tmp_path: Path) -> None:
    session, database, month_id, account_id, _ = _environment(tmp_path)
    try:
        cash = session.scalar(
            select(CashBalance).where(
                CashBalance.reporting_month_id == month_id,
                CashBalance.account_id == account_id,
            )
        )
        assert cash is not None
        session.delete(cash)
        session.commit()
        close_reporting_month(session, month_id)
        point = valuation_point_for_month(session, month_id, account_id=account_id, scope="account")

        assert point.status is ValuationPointStatus.UNKNOWN
        assert point.total_value is None
        assert "not_computable_scope_coverage_incomplete" in point.coverage.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_unknown_historical_flow_membership_is_reported_separately_from_valuation_total(
    tmp_path: Path,
) -> None:
    session, database, month_id, account_id, _ = _environment(tmp_path)
    try:
        create_external_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            event_date=date(2030, 5, 20),
            boundary_amount="10.00",
            direction="contribution",
            kind="external_contribution",
        )
        close_reporting_month(session, month_id)
        point = valuation_point_for_month(session, month_id)

        assert point.status is ValuationPointStatus.AVAILABLE
        assert point.coverage.scope_membership_status is CoverageStatus.UNKNOWN
        assert (
            "not_computable_scope_membership_history_missing"
            in point.coverage.scope_membership_reason_codes
        )
    finally:
        session.close()
        database.engine.dispose()


def test_missing_snapshot_date_is_unavailable(tmp_path: Path) -> None:
    session, database, month_id, _account_id, _ = _environment(tmp_path)
    try:
        month = session.get(ReportingMonth, month_id)
        assert month is not None
        month.snapshot_date = None
        point = valuation_point_for_month(session, month_id)

        assert point.status is ValuationPointStatus.UNAVAILABLE
        assert point.total_value is None
        assert "not_computable_snapshot_date_missing" in point.coverage.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_account_scope_rejects_unlinked_legacy_cash_and_non_rub_cash(tmp_path: Path) -> None:
    session, database, month_id, account_id, _ = _environment(tmp_path)
    try:
        legacy = create_cash_balance(
            session,
            reporting_month_id=month_id,
            name="Legacy Unassigned Cash",
            amount="1.00",
        )
        close_reporting_month(session, month_id)
        point = valuation_point_for_month(
            session, month_id, scope=PerformanceScope.ACCOUNT, account_id=account_id
        )
        assert legacy.account_id is None
        assert point.status is ValuationPointStatus.UNKNOWN
        assert "not_computable_scope_cash_unclassified" in point.coverage.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_account_scope_rejects_non_rub_cash_without_conversion(tmp_path: Path) -> None:
    session, database, month_id, account_id, _ = _environment(tmp_path)
    try:
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Foreign Cash",
            amount="1.00",
            currency="USD",
        )
        close_reporting_month(session, month_id)
        point = valuation_point_for_month(
            session, month_id, scope=PerformanceScope.ACCOUNT, account_id=account_id
        )
        assert point.status is ValuationPointStatus.UNAVAILABLE
        assert "not_computable_currency_conversion_incomplete" in point.coverage.reason_codes
    finally:
        session.close()
        database.engine.dispose()
