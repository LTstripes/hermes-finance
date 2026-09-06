"""PERF-H2d explicit in-kind boundary coverage regressions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    InKindMovementKind,
    PerformanceAvailabilityStatus,
    PerformanceScope,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import AccountPerformanceScopeMembership, Base, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import create_cash_boundary_coverage
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.in_kind_boundary_coverage import (
    attest_in_kind_boundary_history,
    create_in_kind_boundary_coverage,
    create_in_kind_movement,
    in_kind_boundary_coverage_for_interval,
    update_in_kind_boundary_coverage,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)

START = date(2030, 1, 31)
END = date(2030, 2, 28)
MID = date(2030, 2, 15)


def _environment(
    tmp_path: Path,
    *,
    account_type: AccountType = AccountType.BROKERAGE,
    with_positions: bool = True,
):
    database = create_database(tmp_path / "h2d.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    account = create_account(session, name="Synthetic H2d Account", account_type=account_type)
    instrument = create_instrument(session, name="Synthetic H2d Bond", instrument_type="bond")
    for month in (january, february):
        if with_positions:
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="100.00",
                market_price_per_unit="100.00",
                price_date=month.snapshot_date,
            )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic H2d Deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic H2d Cash",
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
    return session, database, january, february, account, instrument


def _attest_all(session, account_id: int) -> None:
    create_cash_boundary_coverage(
        session, account_id=account_id, covered_from=START, covered_to=END
    )
    attest_in_kind_boundary_history(
        session,
        account_id=account_id,
        covered_from=START,
        covered_to=END,
        provenance_reference="synthetic-h2d-owner-attestation",
    )


def _close(session, january, february) -> None:
    close_reporting_month(session, january.id)
    close_reporting_month(session, february.id)


@pytest.mark.parametrize("account_type", [AccountType.BROKERAGE, AccountType.IIS])
def test_brokerage_or_iis_unknown_in_kind_coverage_blocks_exact_performance(
    tmp_path: Path, account_type: AccountType
) -> None:
    session, database, january, february, account, _ = _environment(
        tmp_path, account_type=account_type
    )
    try:
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        _close(session, january, february)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
        )
        assert result.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
        assert result.in_kind_boundary_coverage.status == "unknown"
        assert result.reason_codes.count("not_computable_in_kind_boundary_coverage_unknown") == 1
        assert "not_computable_in_kind_boundary_coverage_unknown" in result.xirr.reason_codes
        assert "not_computable_in_kind_boundary_coverage_unknown" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_explicit_owner_attestation_with_no_movement_is_complete(tmp_path: Path) -> None:
    session, database, january, february, account, _ = _environment(tmp_path)
    try:
        _attest_all(session, account.id)
        _close(session, january, february)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
        )
        assert result.in_kind_boundary_coverage.status == "complete"
        assert result.in_kind_boundary_coverage.known_movements == ()
        assert result.xirr.is_available
        assert result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_complete_state_rejects_non_owner_provenance(tmp_path: Path) -> None:
    session, database, _, _, account, _ = _environment(tmp_path)
    try:
        with pytest.raises(ValueError, match="explicit owner attestation"):
            create_in_kind_boundary_coverage(
                session,
                account_id=account.id,
                covered_from=START,
                covered_to=END,
                provenance_kind="provider_import",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_complete_coverage_with_known_movement_without_valuation_fails_closed(
    tmp_path: Path,
) -> None:
    session, database, january, february, account, instrument = _environment(tmp_path)
    try:
        _attest_all(session, account.id)
        movement = create_in_kind_movement(
            session,
            reporting_month_id=february.id,
            event_date=MID,
            movement_kind=InKindMovementKind.EXTERNAL_IN,
            destination_account_id=account.id,
            instrument_id=instrument.id,
            quantity="1",
            provenance_reference="synthetic-share-transfer",
        )
        _close(session, january, february)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
        )
        assert result.in_kind_boundary_coverage.status == "complete"
        assert [item.id for item in result.in_kind_boundary_coverage.known_movements] == [movement.id]
        assert result.reason_codes == ("not_computable_in_kind_movement_unvalued",)
        assert not result.xirr.is_available
        assert not result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_cash_only_account_without_position_history_has_no_in_kind_requirement(
    tmp_path: Path,
) -> None:
    session, database, january, february, account, _ = _environment(
        tmp_path, account_type=AccountType.CASH, with_positions=False
    )
    try:
        coverage = in_kind_boundary_coverage_for_interval(
            session,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
            start_date=START,
            end_date=END,
            rows_by_account={
                account.id: [
                    AccountPerformanceScopeMembership(
                        account_id=account.id,
                        effective_from=date(2029, 1, 1),
                        include_in_returns=True,
                    )
                ]
            },
        )
        assert coverage.account_ids == ()
        assert coverage.status == "complete"
    finally:
        session.close()
        database.engine.dispose()


def test_generic_account_with_position_history_requires_coverage(tmp_path: Path) -> None:
    session, database, january, february, account, _ = _environment(
        tmp_path, account_type=AccountType.OTHER
    )
    try:
        rows = {account.id: [AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=True,
        )]}
        coverage = in_kind_boundary_coverage_for_interval(
            session,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
            start_date=START,
            end_date=END,
            rows_by_account=rows,
        )
        assert coverage.account_ids == (account.id,)
        assert coverage.status == "unknown"
    finally:
        session.close()
        database.engine.dispose()


def test_other_without_position_history_with_explicit_movement_fails_closed(
    tmp_path: Path,
) -> None:
    session, database, january, february, account, instrument = _environment(
        tmp_path, account_type=AccountType.OTHER, with_positions=False
    )
    try:
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        create_in_kind_movement(
            session,
            reporting_month_id=february.id,
            event_date=MID,
            movement_kind=InKindMovementKind.EXTERNAL_IN,
            destination_account_id=account.id,
            instrument_id=instrument.id,
            quantity="1",
        )
        _close(session, january, february)
        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
        )
        assert result.in_kind_boundary_coverage.account_ids == ()
        assert result.in_kind_boundary_coverage.status == "complete"
        assert result.in_kind_boundary_coverage.reason_codes == (
            "not_computable_in_kind_movement_unvalued",
        )
        assert "not_computable_in_kind_movement_unvalued" in result.reason_codes
        assert not result.xirr.is_available
        assert not result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_out_of_scope_account_does_not_create_in_kind_requirement(tmp_path: Path) -> None:
    session, database, january, february, account, _ = _environment(tmp_path)
    try:
        out_of_scope = create_account(
            session, name="Synthetic H2d Out of Scope", account_type=AccountType.BROKERAGE
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=out_of_scope.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=False,
            )
        )
        session.commit()
        coverage = in_kind_boundary_coverage_for_interval(
            session,
            scope=PerformanceScope.PORTFOLIO,
            account_id=None,
            start_date=START,
            end_date=END,
            rows_by_account={
                account.id: [
                    AccountPerformanceScopeMembership(
                        account_id=account.id,
                        effective_from=date(2029, 1, 1),
                        include_in_returns=True,
                    )
                ],
                out_of_scope.id: [
                    AccountPerformanceScopeMembership(
                        account_id=out_of_scope.id,
                        effective_from=date(2029, 1, 1),
                        include_in_returns=False,
                    )
                ],
            },
        )
        assert coverage.account_ids == (account.id,)
    finally:
        session.close()
        database.engine.dispose()


def test_position_delta_is_not_reinterpreted_as_in_kind_movement(tmp_path: Path) -> None:
    session, database, january, february, account, _ = _environment(tmp_path)
    try:
        february_snapshot = session.scalar(
            select(PositionSnapshot).where(
                PositionSnapshot.reporting_month_id == february.id,
                PositionSnapshot.account_id == account.id,
            )
        )
        assert february_snapshot is not None
        february_snapshot.quantity = 2
        session.commit()
        _attest_all(session, account.id)
        coverage = in_kind_boundary_coverage_for_interval(
            session,
            scope=PerformanceScope.ACCOUNT,
            account_id=account.id,
            start_date=START,
            end_date=END,
            rows_by_account={
                account.id: [
                    AccountPerformanceScopeMembership(
                        account_id=account.id,
                        effective_from=date(2029, 1, 1),
                        include_in_returns=True,
                    )
                ]
            },
        )
        assert coverage.known_movements == ()
    finally:
        session.close()
        database.engine.dispose()


def test_internal_in_kind_movement_is_known_but_unvalued_at_portfolio_scope(
    tmp_path: Path,
) -> None:
    session, database, january, february, account, instrument = _environment(tmp_path)
    try:
        second = create_account(
            session, name="Synthetic H2d Destination", account_type=AccountType.BROKERAGE
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=second.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
        _attest_all(session, account.id)
        attest_in_kind_boundary_history(
            session, account_id=second.id, covered_from=START, covered_to=END
        )
        movement = create_in_kind_movement(
            session,
            reporting_month_id=february.id,
            event_date=MID,
            movement_kind=InKindMovementKind.INTERNAL_TRANSFER,
            source_account_id=account.id,
            destination_account_id=second.id,
            instrument_id=instrument.id,
            quantity="1",
        )
        coverage = in_kind_boundary_coverage_for_interval(
            session,
            scope=PerformanceScope.PORTFOLIO,
            account_id=None,
            start_date=START,
            end_date=END,
            rows_by_account={
                account.id: [
                    AccountPerformanceScopeMembership(
                        account_id=account.id,
                        effective_from=date(2029, 1, 1),
                        include_in_returns=True,
                    )
                ],
                second.id: [
                    AccountPerformanceScopeMembership(
                        account_id=second.id,
                        effective_from=date(2029, 1, 1),
                        include_in_returns=True,
                    )
                ],
            },
        )
        assert coverage.known_movements[0].id == movement.id
        assert coverage.known_movements[0].movement_kind is InKindMovementKind.INTERNAL_TRANSFER
        assert "not_computable_in_kind_movement_unvalued" in coverage.reason_codes
        _close(session, january, february)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )
        assert "not_computable_in_kind_movement_unvalued" in result.reason_codes
        assert not result.xirr.is_available
        assert not result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_in_kind_attestation_correction_requires_reopen(tmp_path: Path) -> None:
    session, database, january, february, account, _ = _environment(tmp_path)
    try:
        coverage = attest_in_kind_boundary_history(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        _close(session, january, february)
        with pytest.raises(ClosedReportingMonthError):
            update_in_kind_boundary_coverage(
                session, coverage.id, notes="closed-history correction"
            )
        reopen_reporting_month(session, january.id)
        reopen_reporting_month(session, february.id)
        update_in_kind_boundary_coverage(session, coverage.id, notes="reopened correction")
    finally:
        session.close()
        database.engine.dispose()


def test_in_kind_coverage_is_persisted_and_exposed_read_only(tmp_path: Path) -> None:
    session, database, january, february, account, _ = _environment(tmp_path)
    try:
        _attest_all(session, account.id)
        _close(session, january, february)
    finally:
        session.close()
    try:
        with TestClient(create_app(database)) as client:
            response = client.get(
                "/api/performance/availability",
                params={
                    "start_date": START.isoformat(),
                    "end_date": END.isoformat(),
                    "scope": "account",
                    "account_id": account.id,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["in_kind_boundary_coverage"]["status"] == "complete"
            assert body["in_kind_boundary_coverage"]["evidence"][0]["provenance_kind"] == (
                "owner_attestation"
            )
            assert "amount" not in body["in_kind_boundary_coverage"]
    finally:
        database.engine.dispose()
