"""PERF-H2b affirmative cash-boundary history coverage regressions."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, PerformanceAvailabilityStatus, PerformanceScope
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
    ObservedValuationPoint,
)
from hermes_finance.persistence import CashBoundaryCoverage as CashBoundaryCoverageRecord
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import (
    attest_cash_boundary_history,
    create_cash_boundary_coverage,
    revoke_cash_boundary_coverage,
)
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import (
    create_external_flow,
    delete_external_flow,
    update_external_flow,
)
from hermes_finance.services.in_kind_boundary_coverage import attest_in_kind_boundary_history
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
    reopen_reporting_month,
)
from hermes_finance.services.valuation_boundaries import create_observed_valuation_point

START = date(2030, 1, 31)
MID = date(2030, 2, 14)
END = date(2030, 2, 28)


def _environment(tmp_path: Path):
    database = create_database(tmp_path / "h2b.db")
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


@pytest.mark.parametrize("persist_unknown", [False, True])
def test_missing_or_unknown_cash_history_blocks_xirr_and_twrr(
    tmp_path: Path, persist_unknown: bool
) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        if persist_unknown:
            create_cash_boundary_coverage(
                session,
                account_id=account.id,
                covered_from=START,
                covered_to=END,
                coverage_state="unknown",
            )
        _close(session, january, february)
        result = _availability(session, account.id)

        assert result.availability is PerformanceAvailabilityStatus.NOT_COMPUTABLE
        assert result.cash_boundary_coverage.status == "unknown"
        assert result.cash_boundary_coverage.missing_or_incomplete_account_ids == (account.id,)
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
        assert "not_computable_external_flows_incomplete" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_owner_complete_zero_crossing_coverage_allows_both_metrics(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        coverage = attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=END,
            provenance_reference="synthetic-owner-attestation",
        )
        _close(session, january, february)
        result = _availability(session, account.id)

        assert coverage.coverage_state == "complete"
        assert result.cash_boundary_coverage.status == "complete"
        assert result.xirr.is_available
        assert result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_canonical_contribution_invalidates_prior_complete_coverage(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=MID,
            boundary_amount="25.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        _close(session, january, february)
        result = _availability(session, account.id)

        assert [item.id for item in result.external_flows.flows] == [flow.id]
        assert result.external_flows.flows[0].boundary_amount_kopecks == 2_500
        assert result.cash_boundary_coverage.status == "unknown"
        assert not result.xirr.is_available
        assert not result.twrr.is_available
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
        assert "not_computable_external_flows_incomplete" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_unsupported_persisted_provenance_does_not_unlock_exact_metrics(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        session.add(
            CashBoundaryCoverageRecord(
                account_id=account.id,
                covered_from=START,
                covered_to=END,
                coverage_state="complete",
                provenance_kind="provider_import",
            )
        )
        session.commit()
        _close(session, january, february)
        result = _availability(session, account.id)

        assert result.cash_boundary_coverage.status == "unknown"
        assert result.cash_boundary_coverage.evidence[0].provenance_kind == "provider_import"
        assert result.cash_boundary_coverage.missing_or_incomplete_account_ids == (account.id,)
        assert not result.xirr.is_available
        assert not result.twrr.is_available
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
        assert "not_computable_external_flows_incomplete" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_partial_interval_coverage_remains_unknown(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=MID
        )
        _close(session, january, february)
        result = _availability(session, account.id)

        assert result.cash_boundary_coverage.status == "unknown"
        assert not result.xirr.is_available
        assert "not_computable_external_flows_incomplete" in result.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_coverage_correction_and_revoke_require_reopen(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        coverage = create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        _close(session, january, february)

        with pytest.raises(ClosedReportingMonthError):
            revoke_cash_boundary_coverage(session, coverage.id)
        with pytest.raises(ClosedReportingMonthError):
            create_cash_boundary_coverage(
                session, account_id=account.id, covered_from=START, covered_to=END
            )
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("mutation", ["delete", "correction"])
def test_material_flow_mutation_invalidates_complete_coverage_until_reaffirmed(
    tmp_path: Path, mutation: str
) -> None:
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
            provenance_reference="synthetic-f3-initial-attestation",
        )
        _close(session, january, february)
        initial = _availability(session, account.id)
        assert initial.xirr.is_available
        assert initial.twrr.is_available

        reopen_reporting_month(session, february.id)
        if mutation == "delete":
            for point in session.scalars(
                select(ObservedValuationPoint).where(
                    ObservedValuationPoint.external_flow_id == flow.id
                )
            ):
                session.delete(point)
            session.flush()
            delete_external_flow(session, flow.id)
        else:
            update_external_flow(session, flow.id, boundary_amount="125.00")
        close_reporting_month(session, february.id)

        after_mutation = _availability(session, account.id)
        assert coverage.coverage_state == "unknown"
        assert after_mutation.cash_boundary_coverage.status == "unknown"
        assert not after_mutation.xirr.is_available
        assert not after_mutation.twrr.is_available
        assert "not_computable_external_flows_incomplete" in after_mutation.xirr.reason_codes
        assert "not_computable_external_flows_incomplete" in after_mutation.twrr.reason_codes

        # Closing again is not an attestation; only an explicit reaffirmation
        # while the month is reopened can restore exact performance.
        reopen_reporting_month(session, january.id)
        reopen_reporting_month(session, february.id)
        reaffirmed = attest_cash_boundary_history(
            session,
            provenance_reference="synthetic-f3-reaffirmation",
            account_id=account.id,
            covered_from=START,
            covered_to=END,
        )
        _close(session, january, february)
        restored = _availability(session, account.id)
        assert reaffirmed.coverage_state == "complete"
        assert reaffirmed.provenance_kind == "owner_attestation"
        assert restored.cash_boundary_coverage.status == "complete"
        assert restored.xirr.is_available
        assert restored.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_metadata_only_flow_update_preserves_complete_coverage(tmp_path: Path) -> None:
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
        attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=START,
            covered_to=END,
            provenance_reference="synthetic-f3-metadata-attestation",
        )
        _close(session, january, february)

        reopen_reporting_month(session, february.id)
        update_external_flow(session, flow.id, notes="corrected owner note")
        close_reporting_month(session, february.id)

        result = _availability(session, account.id)
        assert result.cash_boundary_coverage.status == "complete"
        assert result.xirr.is_available
        assert result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_coverage_api_persists_owner_provenance_and_availability_exposes_it(
    tmp_path: Path,
) -> None:
    session, database, january, february, account = _environment(tmp_path)
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            created = client.post(
                "/api/cash-boundary-coverages",
                json={
                    "account_id": account.id,
                    "covered_from": START.isoformat(),
                    "covered_to": END.isoformat(),
                    "provenance_reference": "synthetic-api-attestation",
                },
            )
            assert created.status_code == 201, created.text
            assert created.json()["coverage_state"] == "complete"

            closed_session = database.session_factory()
            _close(closed_session, january, february)
            closed_session.close()
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
            assert body["cash_boundary_coverage"]["status"] == "complete"
            assert body["cash_boundary_coverage"]["evidence"][0]["provenance_kind"] == (
                "owner_attestation"
            )
            assert body["xirr"]["availability"] == "available"
    finally:
        database.engine.dispose()


def test_out_of_scope_account_does_not_require_cash_coverage(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        out_of_scope = create_account(
            session, name="Synthetic Out of Scope", account_type=AccountType.BROKERAGE
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=out_of_scope.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=False,
            )
        )
        session.commit()
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        _close(session, january, february)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )

        assert result.cash_boundary_coverage.account_ids == (account.id,)
        assert result.cash_boundary_coverage.missing_or_incomplete_account_ids == ()
    finally:
        session.close()
        database.engine.dispose()


def test_one_missing_in_scope_account_blocks_portfolio_cash_completeness(tmp_path: Path) -> None:
    session, database, january, february, account = _environment(tmp_path)
    try:
        second = create_account(
            session, name="Synthetic Second In Scope", account_type=AccountType.BROKERAGE
        )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=second.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
        create_cash_boundary_coverage(
            session, account_id=account.id, covered_from=START, covered_to=END
        )
        _close(session, january, february)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope=PerformanceScope.PORTFOLIO
        )

        assert result.cash_boundary_coverage.account_ids == (account.id, second.id)
        assert result.cash_boundary_coverage.missing_or_incomplete_account_ids == (second.id,)
        assert not result.xirr.is_available
        assert not result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()
