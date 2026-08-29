"""Synthetic R08-02 whole-portfolio XIRR coverage."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    XirrAvailabilityStatus,
    XirrCashFlow,
    XirrQuality,
    XirrReasonCode,
    calculate_xirr,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import AccountPerformanceScopeMembership, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import create_external_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.portfolio_xirr import portfolio_xirr_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

START = date(2030, 1, 31)
MID = date(2031, 1, 31)
END = date(2032, 1, 31)


def _history(
    tmp_path: Path,
    *,
    opening: str = "1000.00",
    closing: str = "1100.00",
    include_opening: bool = True,
    include_closing: bool = True,
    close_months: bool = True,
) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-02.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    opening_month = create_reporting_month(
        session,
        year=2030,
        month=1,
        snapshot_date=START,
    )
    closing_month = create_reporting_month(
        session,
        year=2032,
        month=1,
        snapshot_date=END,
    )
    account = create_account(
        session,
        name="Synthetic XIRR Account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic XIRR Bond",
        instrument_type="bond",
    )
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()

    boundary_rows = (
        (opening_month.id, opening, include_opening, "Synthetic opening"),
        (closing_month.id, closing, include_closing, "Synthetic closing"),
    )
    for month_id, amount, included, label in boundary_rows:
        if not included:
            continue
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit="0.00",
            market_price_per_unit=amount,
            price_date=START if month_id == opening_month.id else END,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name=f"{label} deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month_id,
            account_id=account.id,
            name=f"{label} cash",
            amount="0.00",
        )

    if close_months:
        close_reporting_month(session, opening_month.id)
        close_reporting_month(session, closing_month.id)
    return session, database, opening_month.id, closing_month.id, account.id


def _assert_rate(result: object, expected: str) -> None:
    assert result.availability is XirrAvailabilityStatus.AVAILABLE
    assert result.quality is XirrQuality.EXACT
    assert result.annualized_rate is not None
    assert abs(result.annualized_rate - Decimal(expected)) < Decimal("1e-24")


def test_xirr_solver_matches_independent_positive_and_negative_vectors() -> None:
    positive = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 110_000),
        )
    )
    _assert_rate(positive, "0.10")

    negative = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 90_000),
        )
    )
    _assert_rate(negative, "-0.10")


def test_xirr_solver_handles_multiple_contributions_and_withdrawal() -> None:
    contributions = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, -50_000),
            XirrCashFlow(END, 176_000),
        )
    )
    _assert_rate(contributions, "0.10")

    withdrawal = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 20_000),
            XirrCashFlow(END, 99_000),
        )
    )
    _assert_rate(withdrawal, "0.10")


def test_xirr_solver_coalesces_same_day_flows_and_rejects_missing_root() -> None:
    same_day = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(START, 10_000),
            XirrCashFlow(MID, 99_000),
        )
    )
    _assert_rate(same_day, "0.10")

    no_root = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(END, -1),
        )
    )
    assert no_root.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert no_root.reason_codes == (XirrReasonCode.NO_VALID_ROOT.value,)


def test_xirr_solver_fails_closed_for_multiple_roots_and_convergence_limit() -> None:
    multiple_roots = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(MID, 600_000),
            XirrCashFlow(END, -800_000),
        )
    )
    assert multiple_roots.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert multiple_roots.reason_codes == (XirrReasonCode.MULTIPLE_ROOTS.value,)

    convergence = calculate_xirr(
        (
            XirrCashFlow(START, -100_000),
            XirrCashFlow(END, 110_000),
        ),
        max_iterations=1,
    )
    assert convergence.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
    assert convergence.reason_codes == (XirrReasonCode.CONVERGENCE_FAILED.value,)


def test_portfolio_xirr_applies_contribution_and_withdrawal_signs(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, account_id = _history(
        tmp_path,
        closing="1760.00",
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="500.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        _assert_rate(result, "0.10")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_withdrawal_is_positive_investor_receipt(tmp_path: Path) -> None:
    session, database, opening_month_id, closing_month_id, account_id = _history(
        tmp_path,
        closing="990.00",
        close_months=False,
    )
    try:
        create_external_flow(
            session,
            reporting_month_id=closing_month_id,
            account_id=account_id,
            event_date=MID,
            boundary_amount="200.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        close_reporting_month(session, opening_month_id)
        close_reporting_month(session, closing_month_id)
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        _assert_rate(result, "0.10")
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_keeps_no_valid_root_unavailable(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, closing="0.00")
    try:
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert result.reason_codes == (XirrReasonCode.NO_VALID_ROOT.value,)
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_keeps_incomplete_opening_unavailable(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, include_opening=False)
    try:
        result = portfolio_xirr_for_interval(
            session,
            start_date=START,
            end_date=END,
        )
        assert result.availability is XirrAvailabilityStatus.NOT_COMPUTABLE
        assert result.value is None
        assert "not_computable_scope_coverage_incomplete" in result.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_xirr_api_exposes_annualized_value_and_period(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, closing="1100.00")
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/xirr",
                params={"start_date": START.isoformat(), "end_date": END.isoformat()},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["metric"] == "xirr"
        assert body["scope"] == "portfolio"
        assert body["availability"] == "available"
        assert body["quality"] == "exact"
        assert body["annualized"] is True
        assert body["value_unit"] == "percentage_points"
        assert abs(Decimal(body["value"]) - Decimal("4.880884817015154699145351366")) < Decimal(
            "1e-20"
        )
        assert body["period"] == {
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
        }
        assert body["reason_codes"] == []
    finally:
        database.engine.dispose()


def test_portfolio_xirr_api_exposes_honest_unavailable_state(tmp_path: Path) -> None:
    session, database, _, _, _ = _history(tmp_path, closing="0.00")
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/xirr",
                params={"start_date": START.isoformat(), "end_date": END.isoformat()},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["value"] is None
        assert body["availability"] == "not_computable"
        assert body["quality"] == "unavailable"
        assert body["reason_codes"] == [XirrReasonCode.NO_VALID_ROOT.value]
    finally:
        database.engine.dispose()
