"""Synthetic R08-03 TWRR contract/recon tests.

These tests verify the exact-vs-blocked boundary exposed by R08-01B/C. They
intentionally do not call or define a production TWRR calculator.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, PerformanceAvailabilityStatus
from hermes_finance.persistence import AccountPerformanceScopeMembership, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

START = date(2030, 1, 31)
END = date(2030, 2, 28)


def _environment(
    tmp_path: Path,
    *,
    closing_market_price: str = "100.00",
) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-03.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    account = create_account(
        session,
        name="Synthetic TWRR Account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic TWRR Instrument",
        instrument_type="bond",
    )

    for month, market_price in (
        (january, "100.00"),
        (february, closing_market_price),
    ):
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit=market_price,
            price_date=month.snapshot_date,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic TWRR Deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic TWRR Cash",
            amount="0.00",
        )

    session.add(
        AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()
    return session, database, january.id, february.id, account.id


def _close_interval(session: Session, start_month_id: int, end_month_id: int) -> None:
    close_reporting_month(session, start_month_id)
    close_reporting_month(session, end_month_id)


@pytest.mark.parametrize(
    ("closing_market_price", "expected_closing_kopecks"),
    [("100.00", 10_000), ("90.00", 9_000)],
)
def test_flow_free_flat_or_loss_interval_is_twrr_ready(
    tmp_path: Path,
    closing_market_price: str,
    expected_closing_kopecks: int,
) -> None:
    session, database, january_id, february_id, account_id = _environment(
        tmp_path,
        closing_market_price=closing_market_price,
    )
    try:
        _close_interval(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert result.external_flows.flows == ()
        assert result.twrr.is_available
        assert result.opening_valuation.point is not None
        assert result.opening_valuation.point.total_value is not None
        assert result.opening_valuation.point.total_value.kopecks == 10_000
        assert result.closing_valuation.point is not None
        assert result.closing_valuation.point.total_value is not None
        assert result.closing_valuation.point.total_value.kopecks == expected_closing_kopecks
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_interior_external_flows_require_a_boundary_for_each(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        first = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=date(2030, 2, 10),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        second = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=date(2030, 2, 20),
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        _close_interval(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_missing",)
        assert [flow.id for flow in result.external_flows.flows] == [first.id, second.id]
    finally:
        session.close()
        database.engine.dispose()


def test_same_day_endpoint_flow_has_unknown_order_without_pre_post_relation(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        create_external_flow(
            session,
            reporting_month_id=january_id,
            account_id=account_id,
            event_date=START,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _close_interval(session, january_id, february_id)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.xirr.is_available
        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_order_unknown",)
        assert result.opening_valuation.point is not None
        assert result.opening_valuation.point.coverage.reason_codes == (
            "not_computable_valuation_boundary_order_unknown",
        )
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_flow_reference_vector_is_exact_only_with_observed_boundaries() -> None:
    """Audit the normative two-flow vector without adding production TWRR code."""

    factors = (
        Decimal("1100.00") / Decimal("1000.00"),
        Decimal("1200.00") / (Decimal("1100.00") + Decimal("100.00")),
        Decimal("1320.00") / Decimal("1200.00"),
        Decimal("1270.00") / (Decimal("1320.00") - Decimal("50.00")),
        Decimal("1333.50") / Decimal("1270.00"),
    )
    chained_factor = Decimal("1")
    for factor in factors:
        chained_factor *= factor

    assert factors == (
        Decimal("1.10"),
        Decimal("1.00"),
        Decimal("1.10"),
        Decimal("1.00"),
        Decimal("1.05"),
    )
    assert chained_factor == Decimal("1.2705")
    assert chained_factor - Decimal("1") == Decimal("0.2705")
