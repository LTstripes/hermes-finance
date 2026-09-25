"""Synthetic tests for observed external-flow valuation-boundary evidence."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from _valuation_capture import create_observed_valuation_point
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import (
    AccountType,
    PerformanceAvailabilityStatus,
    ValuationBoundaryRelation,
)
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    AccountPerformanceScopeMembership,
    Base,
    ExternalFlowBoundaryGroup,
    ExternalFlowBoundaryGroupMember,
    ObservedValuationPoint,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.cash_boundary_coverage import (
    attest_cash_boundary_history,
    create_cash_boundary_coverage,
)
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.external_flows import (
    create_external_flow,
    create_external_transfer_link,
    delete_external_flow,
    update_external_flow,
)
from hermes_finance.services.in_kind_boundary_coverage import attest_in_kind_boundary_history
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)
from hermes_finance.services.portfolio_twrr import twrr_for_interval
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month
from hermes_finance.services.valuation_boundaries import (
    create_external_flow_boundary_group,
    delete_external_flow_boundary_group,
    list_observed_valuation_points,
)
from hermes_finance.services.valuation_material_signature import material_signature_for_boundary

START = date(2030, 1, 31)
FLOW_DATE = date(2030, 2, 15)
END = date(2030, 2, 28)


def _environment(tmp_path: Path) -> tuple[Session, object, int, int, int]:
    database = create_database(tmp_path / "r08-03a.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    january = create_reporting_month(session, year=2030, month=1, snapshot_date=START)
    february = create_reporting_month(session, year=2030, month=2, snapshot_date=END)
    account = create_account(
        session,
        name="Synthetic Boundary Account",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session, name="Synthetic Boundary Instrument", instrument_type="bond"
    )
    for month, price in ((january, "100.00"), (february, "100.00")):
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit=price,
            price_date=month.snapshot_date,
        )
        create_deposit_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic Boundary Deposit",
            deposit_type="deposit",
            balance="0.00",
            annual_rate="0.00",
        )
        create_cash_balance(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            name="Synthetic Boundary Cash",
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
        session,
        account_id=account.id,
        covered_from=START,
        covered_to=END,
    )
    attest_in_kind_boundary_history(
        session, account_id=account.id, covered_from=START, covered_to=END
    )
    return session, database, january.id, february.id, account.id


def _close_interval(session: Session, january_id: int, february_id: int) -> None:
    close_reporting_month(session, january_id)
    close_reporting_month(session, february_id)


def _flow(session: Session, february_id: int, account_id: int, *, amount: str = "100.00"):
    return create_external_flow(
        session,
        reporting_month_id=february_id,
        account_id=account_id,
        event_date=FLOW_DATE,
        boundary_amount=amount,
        direction="contribution",
        kind="external_contribution",
        scope_membership="stable_in_scope",
    )


def _capture_side(
    session: Session,
    *,
    february_id: int,
    account_id: int,
    flow_id: int,
    observed_date: date,
    relation: str,
    expected_material_signature: str | None = None,
) -> ObservedValuationPoint:
    if expected_material_signature is None:
        expected_material_signature = material_signature_for_boundary(
            session, external_flow_id=flow_id
        )
    assert expected_material_signature is not None
    return create_observed_valuation_point(
        session,
        reporting_month_id=february_id,
        scope="account",
        account_id=account_id,
        observed_date=observed_date,
        total_value="1100.00" if relation == "pre_external_flow" else "1200.00",
        performance_currency="RUB",
        provenance_kind="synthetic_capture",
        relation=relation,
        external_flow_id=flow_id,
        expected_material_signature=expected_material_signature,
    )


@pytest.mark.parametrize("correction", ["amount", "date", "delete"])
def test_inflight_capture_rejects_material_correction_and_fresh_capture_works(
    tmp_path: Path, correction: str
) -> None:
    capture, database, january_id, february_id, account_id = _environment(tmp_path)
    writer = database.session_factory()
    try:
        flow = _flow(capture, february_id, account_id)
        flow_id = flow.id
        original = material_signature_for_boundary(capture, external_flow_id=flow_id)
        assert original is not None
        # Deterministic interleaving: capture records A, correction commits B,
        # then each side tries to publish A in a separate transaction.
        if correction == "amount":
            update_external_flow(writer, flow_id, boundary_amount="125.00")
        elif correction == "date":
            update_external_flow(
                writer,
                flow_id,
                event_date=date(2030, 2, 14),
                scope_membership="stable_in_scope",
            )
        else:
            delete_external_flow(writer, flow_id)
        current_date = date(2030, 2, 14) if correction == "date" else FLOW_DATE
        for relation in ("pre_external_flow", "post_external_flow"):
            with pytest.raises(ValueError, match="not found|changed materially"):
                _capture_side(
                    capture,
                    february_id=february_id,
                    account_id=account_id,
                    flow_id=flow_id,
                    observed_date=current_date,
                    relation=relation,
                    expected_material_signature=original,
                )
            capture.rollback()
        assert list_observed_valuation_points(capture, external_flow_id=flow_id) == []
        if correction == "delete":
            return
        current = material_signature_for_boundary(capture, external_flow_id=flow_id)
        assert current is not None and current != original
        for relation in ("pre_external_flow", "post_external_flow"):
            point = _capture_side(
                capture,
                february_id=february_id,
                account_id=account_id,
                flow_id=flow_id,
                observed_date=current_date,
                relation=relation,
                expected_material_signature=current,
            )
            assert point.material_signature == current
        attest_cash_boundary_history(
            capture, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(capture, january_id, february_id)
        result = performance_availability_for_interval(
            capture, start_date=START, end_date=END, scope="account", account_id=account_id
        )
        assert result.twrr.is_available
    finally:
        writer.close()
        capture.close()
        database.engine.dispose()


def test_metadata_edit_preserves_observed_material_signature(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        signature = material_signature_for_boundary(session, external_flow_id=flow.id)
        for relation in ("pre_external_flow", "post_external_flow"):
            _capture_side(
                session,
                february_id=february_id,
                account_id=account_id,
                flow_id=flow.id,
                observed_date=FLOW_DATE,
                relation=relation,
                expected_material_signature=signature,
            )
        update_external_flow(session, flow.id, source="metadata_edit", notes="synthetic")
        assert material_signature_for_boundary(session, external_flow_id=flow.id) == signature
        assert len(list_observed_valuation_points(session, external_flow_id=flow.id)) == 2
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope="account", account_id=account_id
        )
        assert result.twrr.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_read_rejects_stale_persisted_material_signature(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        old_signature = material_signature_for_boundary(session, external_flow_id=flow.id)
        update_external_flow(session, flow.id, boundary_amount="125.00")
        for relation in ("pre_external_flow", "post_external_flow"):
            point = _capture_side(
                session,
                february_id=february_id,
                account_id=account_id,
                flow_id=flow.id,
                observed_date=FLOW_DATE,
                relation=relation,
            )
            point.material_signature = old_signature
        session.commit()
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope="account", account_id=account_id
        )
        assert not result.twrr.is_available
        assert "not_computable_valuation_boundary_missing" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_group_capture_rejects_changed_member_and_accepts_fresh_pair(tmp_path: Path) -> None:
    capture, database, january_id, february_id, account_id = _environment(tmp_path)
    writer = database.session_factory()
    try:
        flow = _flow(capture, february_id, account_id)
        group = create_external_flow_boundary_group(
            capture,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[flow.id],
            scope="account",
            account_id=account_id,
        )
        old = material_signature_for_boundary(capture, boundary_group_id=group.id)
        update_external_flow(writer, flow.id, boundary_amount="125.00")
        for relation in ("pre_external_flow", "post_external_flow"):
            with pytest.raises(ValueError, match="changed materially"):
                create_observed_valuation_point(
                    capture,
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=FLOW_DATE,
                    total_value="1100.00",
                    performance_currency="RUB",
                    provenance_kind="synthetic_group_capture",
                    relation=relation,
                    boundary_group_id=group.id,
                    expected_material_signature=old,
                )
            capture.rollback()
        current = material_signature_for_boundary(capture, boundary_group_id=group.id)
        assert current is not None and current != old
        for relation in ("pre_external_flow", "post_external_flow"):
            point = create_observed_valuation_point(
                capture,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=FLOW_DATE,
                total_value="1100.00",
                performance_currency="RUB",
                provenance_kind="synthetic_group_capture",
                relation=relation,
                boundary_group_id=group.id,
                expected_material_signature=current,
            )
            assert point.material_signature == current
        attest_cash_boundary_history(
            capture, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(capture, january_id, february_id)
        result = performance_availability_for_interval(
            capture, start_date=START, end_date=END, scope="account", account_id=account_id
        )
        assert result.twrr.is_available
    finally:
        writer.close()
        capture.close()
        database.engine.dispose()


def test_pre_and_post_must_bind_same_current_material_state(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        pre = _capture_side(
            session,
            february_id=february_id,
            account_id=account_id,
            flow_id=flow.id,
            observed_date=FLOW_DATE,
            relation="pre_external_flow",
        )
        old = pre.material_signature
        # Simulate a corrupt writer bypassing the normal invalidation path.
        session.execute(
            text("UPDATE external_flows SET boundary_amount_kopecks = 12500 WHERE id = :id"),
            {"id": flow.id},
        )
        session.commit()
        current = material_signature_for_boundary(session, external_flow_id=flow.id)
        assert current is not None and current != old
        with pytest.raises(ValueError, match="PRE and POST must attest"):
            _capture_side(
                session,
                february_id=february_id,
                account_id=account_id,
                flow_id=flow.id,
                observed_date=FLOW_DATE,
                relation="post_external_flow",
                expected_material_signature=current,
            )
        session.rollback()
        assert len(list_observed_valuation_points(session, external_flow_id=flow.id)) == 1
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END, scope="account", account_id=account_id
        )
        assert not result.twrr.is_available
        assert "not_computable_valuation_boundary_missing" in result.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_explicit_flow_pre_post_observations_make_twrr_boundary_available(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            observed_date=FLOW_DATE,
            total_value="1100.00",
            performance_currency="RUB",
            coverage="complete",
            quality="exact",
            provenance_kind="synthetic_observation",
            relation=ValuationBoundaryRelation.PRE_EXTERNAL_FLOW,
            external_flow_id=flow.id,
        )
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            observed_date=FLOW_DATE,
            total_value="1200.00",
            performance_currency="RUB",
            coverage="complete",
            quality="exact",
            provenance_kind="synthetic_observation",
            relation=ValuationBoundaryRelation.POST_EXTERNAL_FLOW,
            external_flow_id=flow.id,
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert result.twrr.is_available
        assert len(result.external_flow_boundaries) == 1
        boundary = result.external_flow_boundaries[0]
        assert boundary.flow_ids == (flow.id,)
        assert boundary.reason_codes == ()
        assert boundary.pre_external_flow is not None
        assert boundary.post_external_flow is not None
        assert boundary.pre_external_flow.total_value.kopecks == 110_000
        assert boundary.post_external_flow.total_value.kopecks == 120_000
    finally:
        session.close()
        database.engine.dispose()


def test_same_day_group_is_deterministic_and_uses_group_observations(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        first = _flow(session, february_id, account_id, amount="100.00")
        second = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[second.id, first.id],
            scope="account",
            account_id=account_id,
        )
        for relation, observed_date, value in (
            (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, FLOW_DATE, "1100.00"),
            (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, FLOW_DATE, "1150.00"),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=observed_date,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic_group_observation",
                relation=relation,
                boundary_group_id=group.id,
            )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.twrr.is_available
        assert [boundary.boundary_group_id for boundary in result.external_flow_boundaries] == [
            group.id
        ]
        assert result.external_flow_boundaries[0].flow_ids == tuple(sorted((first.id, second.id)))
    finally:
        session.close()
        database.engine.dispose()


def test_group_member_date_change_invalidates_and_rejects_new_group_observations(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        second_flow = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[flow.id, second_flow.id],
            scope="account",
            account_id=account_id,
        )
        for relation, value in (
            (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, "1100.00"),
            (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, "1200.00"),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=FLOW_DATE,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic_group_observation",
                relation=relation,
                boundary_group_id=group.id,
            )

        changed_date = date(2030, 2, 14)
        update_external_flow(
            session,
            flow.id,
            event_date=changed_date,
            scope_membership="stable_in_scope",
        )
        update_external_flow(
            session,
            second_flow.id,
            event_date=changed_date,
            scope_membership="stable_in_scope",
        )

        assert list_observed_valuation_points(session, boundary_group_id=group.id) == []
        with pytest.raises(
            ValueError, match="all boundary-group flows must share the same event date"
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=FLOW_DATE,
                total_value="1150.00",
                performance_currency="RUB",
                provenance_kind="synthetic_stale_group_observation",
                relation=ValuationBoundaryRelation.PRE_EXTERNAL_FLOW,
                boundary_group_id=group.id,
            )

        with pytest.raises(ValueError, match="already belongs to a boundary group"):
            create_external_flow_boundary_group(
                session,
                reporting_month_id=february_id,
                boundary_date=changed_date,
                flow_ids=[flow.id, second_flow.id],
                scope="account",
                account_id=account_id,
            )
        delete_external_flow_boundary_group(session, group.id)
        replacement = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=changed_date,
            flow_ids=[flow.id, second_flow.id],
            scope="account",
            account_id=account_id,
        )
        for relation, value in (
            (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, "1100.00"),
            (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, "1150.00"),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=changed_date,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic_recreated_group_observation",
                relation=relation,
                boundary_group_id=replacement.id,
            )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)
        result = twrr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        assert result.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_availability_rejects_persisted_observations_for_stale_group(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[flow.id],
            scope="account",
            account_id=account_id,
        )
        update_external_flow(
            session,
            flow.id,
            event_date=date(2030, 2, 14),
            scope_membership="stable_in_scope",
        )
        # Simulate stale persisted rows from an older writer or imported database.
        session.add_all(
            (
                ObservedValuationPoint(
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=FLOW_DATE,
                    total_value_kopecks=110_000,
                    performance_currency="RUB",
                    coverage_status="complete",
                    quality="exact",
                    provenance_kind="synthetic_legacy_stale_group",
                    relation="pre_external_flow",
                    boundary_group_id=group.id,
                ),
                ObservedValuationPoint(
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=FLOW_DATE,
                    total_value_kopecks=120_000,
                    performance_currency="RUB",
                    coverage_status="complete",
                    quality="exact",
                    provenance_kind="synthetic_legacy_stale_group",
                    relation="post_external_flow",
                    boundary_group_id=group.id,
                ),
            )
        )
        session.commit()
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        availability = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        twrr = twrr_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not availability.twrr.is_available
        assert "not_computable_valuation_boundary_order_unknown" in availability.twrr.reason_codes
        assert not twrr.is_available
        assert "not_computable_valuation_boundary_order_unknown" in twrr.reason_codes
        assert availability.external_flow_boundaries[0].reason_codes == (
            "not_computable_valuation_boundary_order_unknown",
        )
    finally:
        session.close()
        database.engine.dispose()


def test_boundary_group_membership_change_requires_explicit_recreation(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        first = _flow(session, february_id, account_id)
        second = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="50.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        third = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="25.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        original = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[first.id, second.id],
            scope="account",
            account_id=account_id,
        )
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            observed_date=FLOW_DATE,
            total_value="1100.00",
            performance_currency="RUB",
            provenance_kind="synthetic_old_membership_observation",
            relation=ValuationBoundaryRelation.PRE_EXTERNAL_FLOW,
            boundary_group_id=original.id,
        )

        delete_external_flow_boundary_group(session, original.id)
        assert list_observed_valuation_points(session, boundary_group_id=original.id) == []
        replacement = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[third.id, first.id, second.id],
            scope="account",
            account_id=account_id,
        )
        for relation, value in (
            (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, "1100.00"),
            (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, "1125.00"),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=FLOW_DATE,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic_recreated_membership_observation",
                relation=relation,
                boundary_group_id=replacement.id,
            )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert result.twrr.is_available
        assert result.external_flow_boundaries[0].flow_ids == tuple(
            sorted((first.id, second.id, third.id))
        )
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_same_day_boundary_groups_are_order_unknown(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        first = _flow(session, february_id, account_id, amount="100.00")
        second = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        first_group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[first.id],
            scope="account",
            account_id=account_id,
        )
        # Bypass the write-service uniqueness guard to model persisted
        # corruption that the read path must reject conservatively.
        second_group = ExternalFlowBoundaryGroup(
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            boundary_date=FLOW_DATE,
        )
        session.add(second_group)
        session.flush()
        session.add(
            ExternalFlowBoundaryGroupMember(
                boundary_group_id=second_group.id,
                external_flow_id=second.id,
            )
        )
        session.commit()
        for group_id, value_pair in (
            (first_group.id, ("1100.00", "1200.00")),
            (second_group.id, ("1200.00", "1150.00")),
        ):
            for relation, total_value in zip(
                (
                    ValuationBoundaryRelation.PRE_EXTERNAL_FLOW,
                    ValuationBoundaryRelation.POST_EXTERNAL_FLOW,
                ),
                value_pair,
            ):
                create_observed_valuation_point(
                    session,
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=FLOW_DATE,
                    total_value=total_value,
                    performance_currency="RUB",
                    provenance_kind="synthetic_multiple_group_corruption",
                    relation=relation,
                    boundary_group_id=group_id,
                )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_order_unknown",)
        assert len(result.external_flow_boundaries) == 2
    finally:
        session.close()
        database.engine.dispose()


def test_scope_specific_boundary_groups_can_share_one_external_flow(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        account_group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[flow.id],
            scope="account",
            account_id=account_id,
        )
        portfolio_group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[flow.id],
            scope="portfolio",
        )
        for scope, selected_account_id, group_id in (
            ("account", account_id, account_group.id),
            ("portfolio", None, portfolio_group.id),
        ):
            for relation, total_value in (
                (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, "1100.00"),
                (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, "1200.00"),
            ):
                create_observed_valuation_point(
                    session,
                    reporting_month_id=february_id,
                    scope=scope,
                    account_id=selected_account_id,
                    observed_date=FLOW_DATE,
                    total_value=total_value,
                    performance_currency="RUB",
                    provenance_kind=f"synthetic_{scope}_group_observation",
                    relation=relation,
                    boundary_group_id=group_id,
                )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        account_result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )
        portfolio_result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )

        assert account_result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert account_result.twrr.is_available
        assert [
            boundary.boundary_group_id for boundary in account_result.external_flow_boundaries
        ] == [account_group.id]
        assert portfolio_result.availability is PerformanceAvailabilityStatus.AVAILABLE
        assert portfolio_result.twrr.is_available
        assert [
            boundary.boundary_group_id for boundary in portfolio_result.external_flow_boundaries
        ] == [portfolio_group.id]
    finally:
        session.close()
        database.engine.dispose()


def test_invalid_selected_scope_group_membership_remains_fail_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        selected_flow = _flow(session, february_id, account_id)
        unselected_flow = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="25.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_out_of_scope",
        )
        group = create_external_flow_boundary_group(
            session,
            reporting_month_id=february_id,
            boundary_date=FLOW_DATE,
            flow_ids=[selected_flow.id],
            scope="account",
            account_id=account_id,
        )
        session.add(
            ExternalFlowBoundaryGroupMember(
                boundary_group_id=group.id,
                external_flow_id=unselected_flow.id,
            )
        )
        session.commit()
        with pytest.raises(
            ValueError, match="out-of-scope flows cannot create valuation boundaries"
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=FLOW_DATE,
                total_value="1100.00",
                performance_currency="RUB",
                provenance_kind="synthetic_invalid_group_membership",
                relation=ValuationBoundaryRelation.PRE_EXTERNAL_FLOW,
                boundary_group_id=group.id,
            )
        session.add_all(
            (
                ObservedValuationPoint(
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=FLOW_DATE,
                    total_value_kopecks=110_000,
                    performance_currency="RUB",
                    coverage_status="complete",
                    quality="exact",
                    provenance_kind="synthetic_persisted_invalid_membership",
                    relation="pre_external_flow",
                    boundary_group_id=group.id,
                ),
                ObservedValuationPoint(
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=FLOW_DATE,
                    total_value_kopecks=120_000,
                    performance_currency="RUB",
                    coverage_status="complete",
                    quality="exact",
                    provenance_kind="synthetic_persisted_invalid_membership",
                    relation="post_external_flow",
                    boundary_group_id=group.id,
                ),
            )
        )
        session.commit()
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.twrr.is_available
        assert result.twrr.reason_codes == (
            "not_computable_scope_coverage_incomplete",
            "not_computable_valuation_boundary_order_unknown",
        )
        assert len(result.external_flow_boundaries) == 1
        boundary = result.external_flow_boundaries[0]
        assert boundary.flow_ids == tuple(sorted((selected_flow.id, unselected_flow.id)))
        assert boundary.reason_codes == ("not_computable_valuation_boundary_order_unknown",)
        assert not boundary.is_available
    finally:
        session.close()
        database.engine.dispose()


def test_partial_or_unrelated_boundary_evidence_remains_fail_closed(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            observed_date=FLOW_DATE,
            total_value="1100.00",
            performance_currency="RUB",
            provenance_kind="synthetic_partial_observation",
            relation="pre_external_flow",
            external_flow_id=flow.id,
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.twrr.is_available
        assert result.twrr.reason_codes == ("not_computable_valuation_boundary_missing",)
        assert result.external_flow_boundaries[0].post_external_flow is None
    finally:
        session.close()
        database.engine.dispose()


def test_same_day_flows_without_explicit_group_are_order_unknown(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        _flow(session, february_id, account_id)
        create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="50.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.twrr.is_available
        assert "not_computable_valuation_boundary_order_unknown" in result.twrr.reason_codes
        assert len(result.external_flow_boundaries) == 2
        assert [boundary.flow_ids for boundary in result.external_flow_boundaries] == sorted(
            [boundary.flow_ids for boundary in result.external_flow_boundaries]
        )
    finally:
        session.close()
        database.engine.dispose()


def test_observed_boundary_requires_exact_flow_date(tmp_path: Path) -> None:
    session, database, _january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        for relation, observed_date in (
            (ValuationBoundaryRelation.PRE_EXTERNAL_FLOW, date(2030, 2, 14)),
            (ValuationBoundaryRelation.POST_EXTERNAL_FLOW, date(2030, 2, 16)),
        ):
            with pytest.raises(ValueError, match="must equal the flow boundary date"):
                create_observed_valuation_point(
                    session,
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=observed_date,
                    total_value="1100.00",
                    performance_currency="RUB",
                    provenance_kind="synthetic_invalid_boundary_date",
                    relation=relation,
                    external_flow_id=flow.id,
                )
    finally:
        session.close()
        database.engine.dispose()


def test_availability_rejects_non_boundary_observation_dates(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        session.add_all(
            (
                ObservedValuationPoint(
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=date(2030, 2, 14),
                    total_value_kopecks=110_000,
                    performance_currency="RUB",
                    coverage_status="complete",
                    quality="exact",
                    provenance_kind="synthetic_persisted_legacy",
                    relation="pre_external_flow",
                    external_flow_id=flow.id,
                ),
                ObservedValuationPoint(
                    reporting_month_id=february_id,
                    scope="account",
                    account_id=account_id,
                    observed_date=date(2030, 2, 16),
                    total_value_kopecks=120_000,
                    performance_currency="RUB",
                    coverage_status="complete",
                    quality="exact",
                    provenance_kind="synthetic_persisted_legacy",
                    relation="post_external_flow",
                    external_flow_id=flow.id,
                ),
            )
        )
        session.commit()
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="account",
            account_id=account_id,
        )

        assert not result.twrr.is_available
        assert result.twrr.reason_codes == (
            "not_computable_valuation_boundary_missing",
            "not_computable_valuation_boundary_order_unknown",
        )
        boundary = result.external_flow_boundaries[0]
        assert not boundary.is_available
        assert boundary.reason_codes == (
            "not_computable_valuation_boundary_missing",
            "not_computable_valuation_boundary_order_unknown",
        )
        assert boundary.pre_external_flow is not None
        assert boundary.post_external_flow is not None
        assert boundary.pre_external_flow.observed_date == date(2030, 2, 14)
        assert boundary.post_external_flow.observed_date == date(2030, 2, 16)
    finally:
        session.close()
        database.engine.dispose()


def test_portfolio_internal_transfer_does_not_create_boundary_group_requirement(
    tmp_path: Path,
) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        destination = create_account(
            session,
            name="Synthetic Boundary Destination",
            account_type=AccountType.BROKERAGE,
        )
        instrument = create_instrument(
            session,
            name="Synthetic Destination Instrument",
            instrument_type="bond",
        )
        for month_id, snapshot_date in ((january_id, START), (february_id, END)):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=destination.id,
                instrument_id=instrument.id,
                quantity=1,
                average_cost_per_unit="100.00",
                market_price_per_unit="100.00",
                price_date=snapshot_date,
            )
            create_deposit_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=destination.id,
                name="Synthetic Destination Deposit",
                deposit_type="deposit",
                balance="0.00",
                annual_rate="0.00",
            )
            create_cash_balance(
                session,
                reporting_month_id=month_id,
                account_id=destination.id,
                name="Synthetic Destination Cash",
                amount="0.00",
            )
        session.add(
            AccountPerformanceScopeMembership(
                account_id=destination.id,
                effective_from=date(2029, 1, 1),
                include_in_returns=True,
            )
        )
        session.commit()
        create_cash_boundary_coverage(
            session,
            account_id=destination.id,
            covered_from=START,
            covered_to=END,
        )
        attest_in_kind_boundary_history(
            session, account_id=destination.id, covered_from=START, covered_to=END
        )
        source_flow = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=account_id,
            event_date=FLOW_DATE,
            boundary_amount="100.00",
            direction="withdrawal",
            kind="external_withdrawal",
            scope_membership="stable_in_scope",
        )
        destination_flow = create_external_flow(
            session,
            reporting_month_id=february_id,
            account_id=destination.id,
            event_date=FLOW_DATE,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        create_external_transfer_link(
            session,
            transfer_key="synthetic-boundary-transfer",
            flow_ids=[source_flow.id, destination_flow.id],
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        attest_cash_boundary_history(
            session, account_id=destination.id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)

        result = performance_availability_for_interval(
            session,
            start_date=START,
            end_date=END,
            scope="portfolio",
        )

        assert result.twrr.is_available
        assert result.external_flow_boundaries == ()
    finally:
        session.close()
        database.engine.dispose()


def test_availability_api_exposes_observed_boundary_evidence(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            observed_date=FLOW_DATE,
            total_value="1100.00",
            performance_currency="RUB",
            provenance_kind="synthetic_api_observation",
            relation="pre_external_flow",
            external_flow_id=flow.id,
        )
        create_observed_valuation_point(
            session,
            reporting_month_id=february_id,
            scope="account",
            account_id=account_id,
            observed_date=FLOW_DATE,
            total_value="1200.00",
            performance_currency="RUB",
            provenance_kind="synthetic_api_observation",
            relation="post_external_flow",
            external_flow_id=flow.id,
        )
        attest_cash_boundary_history(
            session, account_id=account_id, covered_from=START, covered_to=END
        )
        _close_interval(session, january_id, february_id)
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
                    "account_id": account_id,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["twrr"]["availability"] == "available"
            assert body["external_flow_boundaries"][0]["availability"] == "available"
            assert body["external_flow_boundaries"][0]["pre_external_flow"]["total_value"] == {
                "amount": "1100.00",
                "currency": "RUB",
            }
            assert body["external_flow_boundaries"][0]["post_external_flow"]["relation"] == (
                "post_external_flow"
            )
            assert "return" not in body
            assert "percentage" not in body
    finally:
        database.engine.dispose()


def test_observed_boundary_cannot_be_written_after_month_close(tmp_path: Path) -> None:
    session, database, january_id, february_id, account_id = _environment(tmp_path)
    try:
        flow = _flow(session, february_id, account_id)
        _close_interval(session, january_id, february_id)
        with pytest.raises(ValueError, match="closed reporting month"):
            create_observed_valuation_point(
                session,
                reporting_month_id=february_id,
                scope="account",
                account_id=account_id,
                observed_date=FLOW_DATE,
                total_value="100.00",
                performance_currency="RUB",
                provenance_kind="synthetic_closed_write",
                relation="pre_external_flow",
                external_flow_id=flow.id,
            )
    finally:
        session.close()
        database.engine.dispose()
