"""Regression for PERF-H2a #320 — stable portfolio membership and flow-level consistency.

Covers the 8 required vectors from the issue:

1. false->true mid-interval => not_computable_scope_membership_changed
2. true->false mid-interval => same, no synthetic loss
3. transition strictly before start => available
4. transition effective on end date => unavailable (closed interval)
5. flow stable_in_scope while effective false => fail closed
6. flow stable_out_of_scope while effective true => fail closed
7. stable portfolio remains available
8. account-scope unchanged
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, PerformanceAvailabilityStatus, PerformanceScope
from hermes_finance.persistence import AccountPerformanceScopeMembership, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import create_cash_boundary_coverage
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

START = date(2030, 1, 31)
END = date(2030, 2, 28)
MID = date(2030, 2, 15)


def _env(tmp_path: Path):
    database = create_database(tmp_path / "h2a.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    jan = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    feb = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    acc_a = create_account(session, name="Account A", account_type=AccountType.BROKERAGE)
    acc_b = create_account(session, name="Account B", account_type=AccountType.BROKERAGE)
    instr = create_instrument(session, name="Synthetic Bond", instrument_type="bond")
    for month in (jan, feb):
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=acc_a.id,
            instrument_id=instr.id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit="100.00",
            price_date=month.snapshot_date,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=acc_a.id,
            name="Deposit A",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session, reporting_month_id=month.id, account_id=acc_a.id, name="Cash A", amount="0.00"
        )
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=acc_b.id,
            instrument_id=instr.id,
            quantity=1,
            average_cost_per_unit="50.00",
            market_price_per_unit="50.00",
            price_date=month.snapshot_date,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=acc_b.id,
            name="Deposit B",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session, reporting_month_id=month.id, account_id=acc_b.id, name="Cash B", amount="0.00"
        )
    for account in (acc_a, acc_b):
        create_cash_boundary_coverage(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=END,
        )
    return session, database, jan, feb, acc_a, acc_b


def test_portfolio_false_to_true_mid_interval_is_not_computable(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id,
                effective_from=date(2029, 1, 1),
                effective_to=date(2030, 2, 14),
                include_in_returns=False,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2030, 2, 15), include_in_returns=True
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert result.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
        assert "not_computable_scope_membership_changed" in result.reason_codes
        assert "not_computable_scope_membership_changed" in result.xirr.reason_codes
        assert "not_computable_scope_membership_changed" in result.twrr.reason_codes
        assert "not_computable_scope_membership_changed" in result.scope_membership.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_true_to_false_mid_interval_no_synthetic_loss(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id,
                effective_from=date(2029, 1, 1),
                effective_to=date(2030, 2, 14),
                include_in_returns=True,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2030, 2, 15), include_in_returns=False
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert result.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
        assert "not_computable_scope_membership_changed" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_transition_strictly_before_start_is_available(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id,
                effective_from=date(2029, 1, 1),
                effective_to=date(2030, 1, 14),
                include_in_returns=False,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2030, 1, 15), include_in_returns=True
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert result.reason_codes == ()
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_transition_on_end_date_is_not_computable(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id,
                effective_from=date(2029, 1, 1),
                effective_to=date(2030, 2, 27),
                include_in_returns=False,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2030, 2, 28), include_in_returns=True
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert result.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
        assert "not_computable_scope_membership_changed" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_transition_on_start_date_is_not_computable(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id,
                effective_from=date(2029, 1, 1),
                effective_to=date(2030, 1, 30),
                include_in_returns=False,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2030, 1, 31), include_in_returns=True
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert "not_computable_scope_membership_changed" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_flow_stable_in_scope_contradicts_effective_false(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2029, 1, 1), include_in_returns=False
            )
        )
        session.commit()
        create_external_flow(
            session,
            reporting_month_id=feb.id,
            account_id=acc_b.id,
            event_date=MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert "not_computable_scope_coverage_incomplete" in result.reason_codes
        assert "not_computable_scope_coverage_incomplete" in result.external_flows.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_flow_stable_out_of_scope_contradicts_effective_true(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.commit()
        create_external_flow(
            session,
            reporting_month_id=feb.id,
            account_id=acc_b.id,
            event_date=MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_out_of_scope",
        )
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert "not_computable_scope_coverage_incomplete" in result.reason_codes
        assert "not_computable_scope_coverage_incomplete" in result.external_flows.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_stable_portfolio_remains_available(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert result.xirr.is_available
        assert result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_account_scope_unchanged_by_other_account_membership_change(tmp_path: Path) -> None:
    session, database, jan, feb, acc_a, acc_b = _env(tmp_path)
    try:
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_a.id, effective_from=date(2029, 1, 1), include_in_returns=True
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id,
                effective_from=date(2029, 1, 1),
                effective_to=date(2030, 2, 14),
                include_in_returns=False,
            )
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=acc_b.id, effective_from=date(2030, 2, 15), include_in_returns=True
            )
        )
        session.commit()
        close_reporting_month(session, jan.id)
        close_reporting_month(session, feb.id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=acc_a.id,
        )
        assert result.availability is PerformanceAvailabilityStatus.AVAILABLE
    finally:
        session.close()
        database.engine.dispose()
