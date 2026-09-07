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
    END, START, _close_two_months, _environment,
)

from hermes_finance.api.portfolio_twrr import _response as twrr_response
from hermes_finance.api.portfolio_xirr import _response as xirr_response
from hermes_finance.persistence import InKindBoundaryCoverage, PositionSnapshot
from hermes_finance.services.accounts import update_account
from hermes_finance.services.in_kind_boundary_coverage import revoke_in_kind_boundary_coverage
from hermes_finance.services.performance_availability import performance_availability_for_interval
from hermes_finance.services.portfolio_twrr import portfolio_twrr_for_interval
from hermes_finance.services.portfolio_xirr import portfolio_xirr_for_interval
from hermes_finance.services.positions import update_position_snapshot


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
        result = performance_availability_for_interval(session, start_date=START, end_date=END)
        assert coverage.coverage_state == "unknown"
        assert result.in_kind_boundary_coverage.account_ids == ()
        assert result.xirr.is_available and result.twrr.is_available
        for payload in (
            xirr_response(portfolio_xirr_for_interval(session, start_date=START, end_date=END)),
            twrr_response(portfolio_twrr_for_interval(session, start_date=START, end_date=END)),
        ):
            assert payload.availability == "available"
            assert payload.quality == "exact"
            assert payload.value == "0"
            assert payload.reason_codes == []
    finally:
        session.close()
        database.engine.dispose()
