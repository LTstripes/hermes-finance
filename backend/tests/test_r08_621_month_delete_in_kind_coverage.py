"""#621: bulk month deletion retires intersecting in-kind attestations."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import hermes_finance.services.external_flows as external_flows_service
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InKindMovementKind
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
    InKindBoundaryCoverage,
    InKindMovement,
    ReportingMonth,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import create_cash_boundary_coverage
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.in_kind_boundary_coverage import (
    attest_in_kind_boundary_history,
    create_in_kind_movement,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
    reopen_reporting_month,
)

START = date(2030, 1, 31)
EVENT = date(2030, 2, 14)
END = date(2030, 3, 31)


def _environment(tmp_path: Path):
    database = create_database(tmp_path / "month-delete-in-kind.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=date(2030, 2, 28))
    march = create_reporting_month(session, year=2030, month=3, snapshot_date=END)
    instrument = create_instrument(session, name="Synthetic #621 Bond", instrument_type="bond")
    return session, database, january, february, march, instrument


def _coverage(session, account_id: int):
    return attest_in_kind_boundary_history(
        session,
        account_id=account_id,
        covered_from=START,
        covered_to=END,
        provenance_reference="synthetic-621-attestation",
    )


def _movement(session, month_id: int, kind: InKindMovementKind, source_id, destination_id):
    return create_in_kind_movement(
        session,
        reporting_month_id=month_id,
        event_date=EVENT,
        movement_kind=kind,
        source_account_id=source_id,
        destination_account_id=destination_id,
        provenance_reference="synthetic-621-movement",
    )


@pytest.mark.parametrize(
    ("kind", "source", "destination", "affected"),
    [
        (InKindMovementKind.EXTERNAL_IN, None, "a", {"a"}),
        (InKindMovementKind.EXTERNAL_OUT, "a", None, {"a"}),
        (InKindMovementKind.INTERNAL_TRANSFER, "a", "b", {"a", "b"}),
    ],
)
def test_month_delete_invalidates_only_intersecting_account_and_date(
    tmp_path: Path, kind, source, destination, affected
) -> None:
    session, database, january, february, march, _ = _environment(tmp_path)
    try:
        accounts = {
            name: create_account(
                session, name=f"Synthetic #621 {name}", account_type=AccountType.BROKERAGE
            )
            for name in ("a", "b", "unrelated")
        }
        covered = {name: _coverage(session, account.id) for name, account in accounts.items()}
        later = attest_in_kind_boundary_history(
            session,
            account_id=accounts["a"].id,
            covered_from=date(2030, 4, 1),
            covered_to=date(2030, 4, 30),
        )
        movement = _movement(
            session,
            february.id,
            kind,
            accounts[source].id if source else None,
            accounts[destination].id if destination else None,
        )
        month_id, movement_id = february.id, movement.id
        for month in (january, february, march):
            close_reporting_month(session, month.id)
        reopen_reporting_month(session, month_id)
        delete_reporting_month(session, month_id)

        for name, row in covered.items():
            session.refresh(row)
            assert row.coverage_state == ("unknown" if name in affected else "complete")
        session.refresh(later)
        assert later.coverage_state == "complete"
        # Set-based deletion leaves already-loaded ORM objects in this session.
        verify = database.session_factory()
        try:
            assert verify.get(InKindMovement, movement_id) is None
            assert verify.get(ReportingMonth, month_id) is None
        finally:
            verify.close()
    finally:
        session.close()
        database.engine.dispose()


def test_public_performance_stays_unavailable_after_in_kind_month_delete(tmp_path: Path) -> None:
    session, database, january, february, march, instrument = _environment(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic #621 Performance", account_type=AccountType.BROKERAGE
        )
        for month, value in ((january, "100.00"), (march, "200.00")):
            create_position_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit=value,
                market_price_per_unit=value,
                price_date=month.snapshot_date,
            )
            create_deposit_snapshot(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic #621 Deposit",
                deposit_type="deposit",
                balance="0.00",
                annual_rate="0.00",
            )
            create_cash_balance(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                name="Synthetic #621 Cash",
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
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        coverage = _coverage(session, account.id)
        _movement(session, february.id, InKindMovementKind.EXTERNAL_IN, None, account.id)
        for month in (january, february, march):
            close_reporting_month(session, month.id)
        account_id, month_id, coverage_id = account.id, february.id, coverage.id
        session.close()

        params = {
            "start_date": START.isoformat(),
            "end_date": END.isoformat(),
            "scope": "account",
            "account_id": account_id,
        }
        with TestClient(create_app(database)) as client:
            before = client.get("/api/performance/twrr", params=params)
            assert before.status_code == 200, before.text
            assert "not_computable_in_kind_movement_unvalued" in before.json()["reason_codes"]

            reopen = client.post(f"/api/months/{month_id}/reopen")
            assert reopen.status_code == 200, reopen.text
            deleted = client.delete(f"/api/months/{month_id}")
            assert deleted.status_code == 204, deleted.text

            for metric in ("twrr", "xirr"):
                after = client.get(f"/api/performance/{metric}", params=params)
                assert after.status_code == 200, after.text
                body = after.json()
                assert body["availability"] == "not_computable"
                assert body["quality"] == "unavailable"
                assert body["value"] is None
                assert "not_computable_in_kind_boundary_coverage_unknown" in body["reason_codes"]

        verify = database.session_factory()
        try:
            assert verify.get(InKindBoundaryCoverage, coverage_id).coverage_state == "unknown"
        finally:
            verify.close()
    finally:
        session.close()
        database.engine.dispose()


def test_failed_month_delete_rolls_back_in_kind_invalidation_and_child_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database, _january, february, _march, _ = _environment(tmp_path)
    try:
        account = create_account(
            session, name="Synthetic #621 Rollback", account_type=AccountType.BROKERAGE
        )
        coverage = _coverage(session, account.id)
        movement = _movement(
            session, february.id, InKindMovementKind.EXTERNAL_OUT, account.id, None
        )
        month_id, coverage_id, movement_id = february.id, coverage.id, movement.id

        def fail_after_bulk_delete(_session):
            raise RuntimeError("synthetic #621 deletion failure")

        monkeypatch.setattr(
            external_flows_service,
            "refresh_external_transfer_link_statuses",
            fail_after_bulk_delete,
        )
        with pytest.raises(RuntimeError, match="synthetic #621 deletion failure"):
            delete_reporting_month(session, month_id)

        verify = database.session_factory()
        try:
            assert verify.get(InKindBoundaryCoverage, coverage_id).coverage_state == "complete"
            assert verify.get(InKindMovement, movement_id) is not None
            assert verify.get(ReportingMonth, month_id) is not None
        finally:
            verify.close()
    finally:
        session.close()
        database.engine.dispose()
