"""Audit evidence only: assertions capture defective behavior, not desired behavior.

Run from backend: .venv/Scripts/python -m pytest ../docs/audits/evidence/test_false_exact_closure.py
Uses synthetic SQLite fixtures only. No implementation fix.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend" / "tests"))

from sqlalchemy import select
from test_r08_01c_performance_availability import (
    END,
    START,
    _close_two_months,
    _environment,
)

from hermes_finance.api.portfolio_twrr import _response as twrr_response
from hermes_finance.api.portfolio_xirr import _response as xirr_response
from hermes_finance.persistence import InKindBoundaryCoverage, PositionSnapshot
from hermes_finance.services.accounts import update_account
from hermes_finance.services.in_kind_boundary_coverage import (
    revoke_in_kind_boundary_coverage,
)
from hermes_finance.services.performance_availability import (
    performance_availability_for_interval,
)
from hermes_finance.services.portfolio_twrr import portfolio_twrr_for_interval
from hermes_finance.services.portfolio_xirr import portfolio_xirr_for_interval
from hermes_finance.services.positions import update_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    reopen_reporting_month,
)


def test_audit_same_day_internal_transfer_boundary_has_no_order_proof(tmp_path):
    from test_r08_h2c_transfer_transit import _environment as transfer_environment
    from test_r08_h2c_transfer_transit import _close, _transfer
    from hermes_finance.persistence import CashBalance
    from hermes_finance.services.cash import update_cash_balance

    session, database, months, accounts = transfer_environment(tmp_path)
    try:
        cash = session.scalar(
            select(CashBalance).where(
                CashBalance.reporting_month_id == min(months),
                CashBalance.account_id == accounts[0],
            )
        )
        update_cash_balance(session, cash.id, amount="1000.00")
        _, source, _ = _transfer(
            session, months, accounts, source_date=END, destination_date=END
        )
        # Required closing snapshot is date-only; no persisted assertion proves
        # whether both account observations fall before, between, or after legs.
        _close(session, months)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END
        )
        assert (
            "not_computable_valuation_boundary_order_unknown"
            in result.closing_valuation.reason_codes
        )
        assert result.xirr.is_available and result.twrr.is_available
        assert portfolio_xirr_for_interval(
            session, start_date=START, end_date=END
        ).is_available
        twrr = portfolio_twrr_for_interval(session, start_date=START, end_date=END)
        assert twrr.is_available and twrr.return_rate < 0
        assert twrr_response(twrr).quality == "exact"
        # Control: changing only the source day restores the H2c safety gate.
        from hermes_finance.services.external_flows import update_external_flow

        reopen_reporting_month(session, max(months))
        update_external_flow(
            session,
            source.id,
            event_date=date(2030, 2, 27),
            scope_membership="stable_in_scope",
        )
        close_reporting_month(session, max(months))
        blocked = portfolio_twrr_for_interval(session, start_date=START, end_date=END)
        assert not blocked.is_available
        assert "not_computable_transfer_in_transit_unvalued" in blocked.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_audit_deleted_flow_leaves_prior_cash_attestation_complete(tmp_path):
    from hermes_finance.persistence import CashBalance, CashBoundaryCoverage
    from hermes_finance.services.cash import update_cash_balance
    from hermes_finance.services.cash_boundary_coverage import (
        update_cash_boundary_coverage,
        revoke_cash_boundary_coverage,
    )
    from hermes_finance.services.external_flows import (
        create_external_flow,
        delete_external_flow,
    )
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        reopen_reporting_month,
    )

    session, database, january, february, account = _environment(tmp_path)
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february,
            account_id=account,
            event_date=date(2030, 2, 15),
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        cash = session.scalar(
            select(CashBalance).where(CashBalance.reporting_month_id == february)
        )
        update_cash_balance(session, cash.id, amount="400.00")
        coverage = session.scalar(select(CashBoundaryCoverage))
        update_cash_boundary_coverage(
            session, coverage.id, provenance_reference="synthetic-original-complete"
        )
        _close_two_months(session, january, february)
        before = portfolio_xirr_for_interval(session, start_date=START, end_date=END)
        assert before.is_available and before.annualized_rate == 0
        # Start a replacement/correction of the canonical event; no new owner
        # attestation confirms the now-empty event set. Close alone is not proof.
        reopen_reporting_month(session, february)
        delete_external_flow(session, flow.id)
        close_reporting_month(session, february)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END
        )
        assert coverage.coverage_state == "complete"
        assert result.xirr.is_available and result.twrr.is_available
        after = portfolio_xirr_for_interval(session, start_date=START, end_date=END)
        assert after.is_available and after.annualized_rate > 0
        assert (
            portfolio_twrr_for_interval(
                session, start_date=START, end_date=END
            ).return_rate
            > 0
        )
        assert xirr_response(after).quality == "exact"
        # Control: explicit coverage revocation does block both metrics.
        reopen_reporting_month(session, january)
        reopen_reporting_month(session, february)
        revoke_cash_boundary_coverage(session, coverage.id)
        _close_two_months(session, january, february)
        blocked = performance_availability_for_interval(
            session, start_date=START, end_date=END
        )
        assert not blocked.xirr.is_available and not blocked.twrr.is_available
        assert "not_computable_external_flows_incomplete" in blocked.xirr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_audit_quote_clock_hides_known_positions_from_in_kind_gate(tmp_path):
    session, database, january, february, account = _environment(tmp_path)
    try:
        update_account(session, account, account_type="other")
        coverage = session.scalar(select(InKindBoundaryCoverage))
        revoke_in_kind_boundary_coverage(session, coverage.id)
        # These positions belong to the requested reporting months. Quote date
        # is a distinct clock; the normal edit service accepts this later date.
        for position in session.scalars(select(PositionSnapshot)).all():
            update_position_snapshot(session, position.id, price_date=date(2030, 3, 1))
        _close_two_months(session, january, february)
        result = performance_availability_for_interval(
            session, start_date=START, end_date=END
        )
        assert coverage.coverage_state == "unknown"
        assert result.in_kind_boundary_coverage.account_ids == ()
        assert result.xirr.is_available and result.twrr.is_available
        for payload in (
            xirr_response(
                portfolio_xirr_for_interval(session, start_date=START, end_date=END)
            ),
            twrr_response(
                portfolio_twrr_for_interval(session, start_date=START, end_date=END)
            ),
        ):
            assert payload.availability == "available"
            assert payload.quality == "exact"
            assert payload.value == "0"
            assert payload.reason_codes == []
        # Control: restore quote dates only; the very same UNKNOWN row blocks.
        reopen_reporting_month(session, january)
        reopen_reporting_month(session, february)
        for position in session.scalars(select(PositionSnapshot)).all():
            update_position_snapshot(session, position.id, price_date=START)
        _close_two_months(session, january, february)
        blocked = performance_availability_for_interval(
            session, start_date=START, end_date=END
        )
        assert not blocked.xirr.is_available and not blocked.twrr.is_available
        assert (
            "not_computable_in_kind_boundary_coverage_unknown"
            in blocked.xirr.reason_codes
        )
    finally:
        session.close()
        database.engine.dispose()
