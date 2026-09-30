"""#493 reporting-month bulk deletion must invalidate cash-boundary coverage."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from _valuation_capture import create_observed_valuation_point
from fastapi.testclient import TestClient

import hermes_finance.services.external_flows as external_flows_service
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, PerformanceScope
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
)
from hermes_finance.persistence import CashBoundaryCoverage as CashBoundaryCoverageRecord
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import (
    attest_cash_boundary_history,
    create_cash_boundary_coverage,
)
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import (
    create_external_flow,
    delete_external_flow,
)
from hermes_finance.services.in_kind_boundary_coverage import attest_in_kind_boundary_history
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.portfolio_xirr import xirr_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
    delete_reporting_month,
    reopen_reporting_month,
)

START = date(2030, 1, 31)
MID = date(2030, 2, 14)
END = date(2030, 2, 28)


def _environment(tmp_path: Path):
    database = create_database(tmp_path / "h2b-493-control.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    account = create_account(
        session, name="Synthetic H2b Account", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(session, name="Synthetic H2b Instrument", instrument_type="bond")
    for month, value in ((january, "100.00"), (february, "200.00")):
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
            name="Synthetic H2b Deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic H2b Cash",
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
    attest_in_kind_boundary_history(
        session, account_id=account.id, covered_from=START, covered_to=END
    )
    return session, database, january, february, account


def _close(session, january, february) -> None:
    close_reporting_month(session, january.id)
    close_reporting_month(session, february.id)


def _availability(session, account_id: int):
    return performance_availability_for_interval(
        session,
        start_date=START,
        end_date=END,
        scope=PerformanceScope.ACCOUNT,
        account_id=account_id,
    )


def _add_flow_valuation_boundaries(
    session, *, month_id: int, account_id: int, flow_id: int
) -> None:
    for relation, value in (("pre_external_flow", "100.00"), ("post_external_flow", "200.00")):
        create_observed_valuation_point(
            session,
            reporting_month_id=month_id,
            scope="account",
            account_id=account_id,
            observed_date=MID,
            total_value=value,
            performance_currency="RUB",
            provenance_kind="synthetic-f3-valuation",
            relation=relation,
            external_flow_id=flow_id,
        )


# ---------------------------------------------------------------------------
# #493 - reporting-month bulk deletion must invalidate cash-boundary coverage
# ---------------------------------------------------------------------------

MARCH_END = date(2030, 3, 31)
FEB_MID = date(2030, 2, 14)


def _seed_account_month_valuations(session, month, account, instrument, value: str) -> None:
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
        name="Synthetic H2b Deposit",
        deposit_type="deposit",
        balance="0.00",
        annual_rate="0.00",
    )
    create_cash_balance(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        name="Synthetic H2b Cash",
        amount="0.00",
    )


def _three_month_environment(
    tmp_path: Path,
    *,
    opening_value: str = "100.00",
    mid_value: str = "200.00",
    closing_value: str = "200.00",
):
    """January start / February intermediate flow month / March end."""

    database = create_database(tmp_path / "h2b-month-delete.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    march = create_reporting_month(session, year=2030, month=3, snapshot_date=MARCH_END)
    account = create_account(
        session, name="Synthetic H2b Month-Delete Account", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic H2b Month-Delete Instrument", instrument_type="bond"
    )
    for month, value in (
        (january, opening_value),
        (february, mid_value),
        (march, closing_value),
    ):
        _seed_account_month_valuations(session, month, account, instrument, value)
    session.add(
        AccountPerformanceScopeMembership(
            account_id=account.id,
            effective_from=date(2029, 1, 1),
            include_in_returns=True,
        )
    )
    session.commit()
    attest_in_kind_boundary_history(
        session, account_id=account.id, covered_from=START, covered_to=MARCH_END
    )
    return session, database, january, february, march, account, instrument


def _close_three(session, january, february, march) -> None:
    close_reporting_month(session, january.id)
    close_reporting_month(session, february.id)
    close_reporting_month(session, march.id)


def _long_interval_availability(session, account_id: int):
    return performance_availability_for_interval(
        session,
        start_date=START,
        end_date=MARCH_END,
        scope=PerformanceScope.ACCOUNT,
        account_id=account_id,
    )


def _add_account_flow_boundaries(
    session,
    *,
    month_id: int,
    account_id: int,
    flow_id: int,
    pre_value: str,
    post_value: str,
    observed_date: date = FEB_MID,
) -> None:
    for relation, value in (("pre_external_flow", pre_value), ("post_external_flow", post_value)):
        create_observed_valuation_point(
            session,
            reporting_month_id=month_id,
            scope="account",
            account_id=account_id,
            observed_date=observed_date,
            total_value=value,
            performance_currency="RUB",
            provenance_kind="synthetic-493-boundary",
            relation=relation,
            external_flow_id=flow_id,
        )


@pytest.mark.parametrize(
    ("direction", "kind", "amount", "opening", "mid", "closing", "pre", "post"),
    [
        (
            "contribution",
            "external_contribution",
            "100.00",
            "100.00",
            "200.00",
            "200.00",
            "100.00",
            "200.00",
        ),
        (
            "withdrawal",
            "external_withdrawal",
            "100.00",
            "200.00",
            "100.00",
            "100.00",
            "200.00",
            "100.00",
        ),
    ],
)
def test_deleting_intermediate_month_invalidates_complete_cash_coverage(
    tmp_path: Path,
    direction: str,
    kind: str,
    amount: str,
    opening: str,
    mid: str,
    closing: str,
    pre: str,
    post: str,
) -> None:
    """Bulk month deletion must not leave stale COMPLETE coverage (#493)."""

    session, database, january, february, march, account, _instrument = _three_month_environment(
        tmp_path, opening_value=opening, mid_value=mid, closing_value=closing
    )
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=FEB_MID,
            boundary_amount=amount,
            direction=direction,
            kind=kind,
            scope_membership="stable_in_scope",
        )
        _add_account_flow_boundaries(
            session,
            month_id=february.id,
            account_id=account.id,
            flow_id=flow.id,
            pre_value=pre,
            post_value=post,
        )
        coverage = attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=MARCH_END,
            provenance_reference="synthetic-493-attestation",
        )
        _close_three(session, january, february, march)

        before = _long_interval_availability(session, account.id)
        assert before.cash_boundary_coverage.status == "complete"
        assert before.xirr.is_available
        assert before.twrr.is_available
        twrr_before = twrr_for_interval(
            session,
            start_date=START,
            end_date=MARCH_END,
            scope="account",
            account_id=account.id,
        )
        assert twrr_before.is_available
        assert twrr_before.return_rate == 0

        reopen_reporting_month(session, february.id)
        delete_reporting_month(session, february.id)
        session.refresh(coverage)

        assert coverage.coverage_state == "unknown"
        after = _long_interval_availability(session, account.id)
        assert after.cash_boundary_coverage.status == "unknown"
        assert not after.xirr.is_available
        assert not after.twrr.is_available
        assert "not_computable_external_flows_incomplete" in after.xirr.reason_codes
        assert "not_computable_external_flows_incomplete" in after.twrr.reason_codes

        twrr_after = twrr_for_interval(
            session,
            start_date=START,
            end_date=MARCH_END,
            scope="account",
            account_id=account.id,
        )
        xirr_after = xirr_for_interval(
            session,
            start_date=START,
            end_date=MARCH_END,
            scope="account",
            account_id=account.id,
        )
        assert not twrr_after.is_available
        assert not xirr_after.is_available
        assert session.get(type(february), february.id) is None
    finally:
        session.close()
        database.engine.dispose()


def test_month_deletion_invalidates_only_affected_account_coverage(tmp_path: Path) -> None:
    session, database, january, february, march, account_a, instrument = _three_month_environment(
        tmp_path
    )
    try:
        account_b = create_account(
            session, name="Synthetic Unaffected Account", account_type=AccountType.BROKERAGE
        )
        for month, value in ((january, "100.00"), (february, "100.00"), (march, "110.00")):
            _seed_account_month_valuations(session, month, account_b, instrument, value)
        session.add(
            AccountPerformanceScopeMembership(
                account_id=account_b.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
        attest_in_kind_boundary_history(
            session, account_id=account_b.id, covered_from=START, covered_to=MARCH_END
        )

        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account_a.id,
            event_date=FEB_MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _add_account_flow_boundaries(
            session,
            month_id=february.id,
            account_id=account_a.id,
            flow_id=flow.id,
            pre_value="100.00",
            post_value="200.00",
        )
        coverage_a = attest_cash_boundary_history(
            session,
            account_id=account_a.id,
            covered_from=START,
            covered_to=MARCH_END,
            provenance_reference="synthetic-493-account-a",
        )
        coverage_b = attest_cash_boundary_history(
            session,
            account_id=account_b.id,
            covered_from=START,
            covered_to=MARCH_END,
            provenance_reference="synthetic-493-account-b",
        )
        _close_three(session, january, february, march)

        reopen_reporting_month(session, february.id)
        delete_reporting_month(session, february.id)
        session.refresh(coverage_a)
        session.refresh(coverage_b)

        assert coverage_a.coverage_state == "unknown"
        assert coverage_b.coverage_state == "complete"
        assert _long_interval_availability(session, account_a.id).cash_boundary_coverage.status == (
            "unknown"
        )
        assert _long_interval_availability(session, account_b.id).cash_boundary_coverage.status == (
            "complete"
        )
    finally:
        session.close()
        database.engine.dispose()


def test_month_deletion_preserves_unrelated_interval_coverage(tmp_path: Path) -> None:
    session, database, january, february, march, account, _instrument = _three_month_environment(
        tmp_path
    )
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=FEB_MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _add_account_flow_boundaries(
            session,
            month_id=february.id,
            account_id=account.id,
            flow_id=flow.id,
            pre_value="100.00",
            post_value="200.00",
        )
        affected = attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=MARCH_END,
            provenance_reference="synthetic-493-affected-interval",
        )
        # Unrelated later interval that does not contain the deleted flow date.
        unrelated = create_cash_boundary_coverage(
            session,
            account_id=account.id,
            covered_from=date(2030, 4, 1),
            covered_to=date(2030, 4, 30),
            provenance_reference="synthetic-493-unrelated-interval",
        )
        _close_three(session, january, february, march)

        reopen_reporting_month(session, february.id)
        delete_reporting_month(session, february.id)
        session.refresh(affected)
        session.refresh(unrelated)

        assert affected.coverage_state == "unknown"
        assert unrelated.coverage_state == "complete"
    finally:
        session.close()
        database.engine.dispose()


def test_failed_month_deletion_rolls_back_coverage_and_financial_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, database, january, february, march, account, _instrument = _three_month_environment(
        tmp_path
    )
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=FEB_MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _add_account_flow_boundaries(
            session,
            month_id=february.id,
            account_id=account.id,
            flow_id=flow.id,
            pre_value="100.00",
            post_value="200.00",
        )
        coverage = attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=MARCH_END,
            provenance_reference="synthetic-493-rollback",
        )
        flow_id = flow.id
        coverage_id = coverage.id
        february_id = february.id

        def boom(session_arg):
            raise RuntimeError("synthetic month-deletion failure")

        monkeypatch.setattr(
            external_flows_service,
            "refresh_external_transfer_link_statuses",
            boom,
        )
        with pytest.raises(RuntimeError, match="synthetic month-deletion failure"):
            delete_reporting_month(session, february_id)

        # Use a fresh session so we observe durable DB state after rollback.
        verify = database.session_factory()
        try:
            restored_coverage = verify.get(CashBoundaryCoverageRecord, coverage_id)
            restored_flow = verify.get(type(flow), flow_id)
            restored_month = verify.get(type(february), february_id)
            assert restored_coverage is not None
            assert restored_coverage.coverage_state == "complete"
            assert restored_flow is not None
            assert restored_month is not None
        finally:
            verify.close()
    finally:
        session.close()
        database.engine.dispose()


def test_month_deletion_public_api_blocks_stale_exact_twrr(tmp_path: Path) -> None:
    """Public endpoints must not leak stale exact performance after month delete."""

    session, database, january, february, march, account, _instrument = _three_month_environment(
        tmp_path
    )
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=FEB_MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _add_account_flow_boundaries(
            session,
            month_id=february.id,
            account_id=account.id,
            flow_id=flow.id,
            pre_value="100.00",
            post_value="200.00",
        )
        attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=MARCH_END,
            provenance_reference="synthetic-493-api",
        )
        _close_three(session, january, february, march)
        february_id = february.id
        account_id = account.id
        session.close()

        with TestClient(create_app(database)) as client:
            before = client.get(
                "/api/performance/twrr",
                params={
                    "start_date": START.isoformat(),
                    "end_date": MARCH_END.isoformat(),
                    "scope": "account",
                    "account_id": account_id,
                },
            )
            assert before.status_code == 200, before.text
            assert before.json()["availability"] == "available"
            assert before.json()["quality"] == "exact"
            assert before.json()["value"] == "0"

            reopen = client.post(f"/api/months/{february_id}/reopen")
            assert reopen.status_code == 200, reopen.text
            deleted = client.delete(f"/api/months/{february_id}")
            assert deleted.status_code == 204, deleted.text

            after_twrr = client.get(
                "/api/performance/twrr",
                params={
                    "start_date": START.isoformat(),
                    "end_date": MARCH_END.isoformat(),
                    "scope": "account",
                    "account_id": account_id,
                },
            )
            assert after_twrr.status_code == 200, after_twrr.text
            twrr_body = after_twrr.json()
            assert twrr_body["availability"] == "not_computable"
            assert twrr_body["quality"] == "unavailable"
            assert twrr_body["value"] is None
            assert "not_computable_external_flows_incomplete" in twrr_body["reason_codes"]

            after_availability = client.get(
                "/api/performance/availability",
                params={
                    "start_date": START.isoformat(),
                    "end_date": MARCH_END.isoformat(),
                    "scope": "account",
                    "account_id": account_id,
                },
            )
            assert after_availability.status_code == 200, after_availability.text
            availability_body = after_availability.json()
            assert availability_body["cash_boundary_coverage"]["status"] == "unknown"
            assert availability_body["twrr"]["availability"] == "not_computable"
            assert availability_body["xirr"]["availability"] == "not_computable"
    finally:
        database.engine.dispose()


def test_per_row_external_flow_delete_invalidation_unchanged_with_month_path(
    tmp_path: Path,
) -> None:
    """Control: ordinary per-row ExternalFlow deletion still invalidates coverage."""

    session, database, january, february, account = _environment(tmp_path)
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _add_flow_valuation_boundaries(
            session, month_id=february.id, account_id=account.id, flow_id=flow.id
        )
        coverage = attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=END,
            provenance_reference="synthetic-493-per-row-control",
        )
        _close(session, january, february)
        assert _availability(session, account.id).xirr.is_available

        reopen_reporting_month(session, february.id)
        delete_external_flow(session, flow.id)
        session.refresh(coverage)

        assert coverage.coverage_state == "unknown"
        after = _availability(session, account.id)
        assert after.cash_boundary_coverage.status == "unknown"
        assert not after.xirr.is_available
        assert not after.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()
