"""Synthetic evidence for the post-hardening false-exact closure audit.

These tests intentionally assert the currently observed unsafe behavior. They
are audit reproducer evidence, not acceptance regressions to keep unchanged.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "backend" / "tests"))

import test_r08_h2b_cash_boundary as h2b  # noqa: E402
import test_r08_h2c_transfer_transit as h2c  # noqa: E402

from hermes_finance.persistence import ObservedValuationPoint  # noqa: E402
from hermes_finance.services.cash_boundary_coverage import (  # noqa: E402
    attest_cash_boundary_history,
)
from hermes_finance.services.external_flows import (  # noqa: E402
    create_external_flow,
    update_external_flow,
)
from hermes_finance.services.performance_availability import (  # noqa: E402
    performance_availability_for_interval,
)
from hermes_finance.services.portfolio_twrr import portfolio_twrr_for_interval  # noqa: E402
from hermes_finance.services.reporting_months import reopen_reporting_month  # noqa: E402
from hermes_finance.services.valuation_boundaries import (  # noqa: E402
    create_observed_valuation_point,
)


def test_audit_reverse_date_transfer_skips_required_twrr_transit_boundary(
    tmp_path: Path,
) -> None:
    """Reverse settlement dates bypass transit even with a required closing date."""

    session, database, month_ids, accounts = h2c._environment(
        tmp_path,
        end_date=h2c.MID_CLOSING,
    )
    try:
        _link, source, destination = h2c._transfer(
            session,
            month_ids,
            accounts,
            source_date=date(2030, 2, 15),
            destination_date=date(2030, 2, 10),
        )
        h2c._close(session, month_ids)

        availability = performance_availability_for_interval(
            session,
            start_date=h2c.START,
            end_date=h2c.MID_CLOSING,
            scope="portfolio",
        )
        twrr = portfolio_twrr_for_interval(
            session,
            start_date=h2c.START,
            end_date=h2c.MID_CLOSING,
        )

        assert source.event_date > destination.event_date
        assert destination.event_date < h2c.MID_CLOSING < source.event_date
        assert availability.xirr.is_available
        assert availability.twrr.is_available
        assert twrr.is_available
        assert twrr.return_rate is not None
        assert "not_computable_transfer_in_transit_unvalued" not in availability.xirr.reason_codes
        assert "not_computable_transfer_in_transit_unvalued" not in availability.twrr.reason_codes
    finally:
        session.close()
        database.engine.dispose()


def test_audit_flow_correction_keeps_old_observed_twrr_boundary_exact(
    tmp_path: Path,
) -> None:
    """Reattestation after a flow correction does not revise TWRR evidence."""

    session, database, january, february, account = h2b._environment(tmp_path)
    try:
        flow = create_external_flow(
            session,
            reporting_month_id=february.id,
            account_id=account.id,
            event_date=h2b.MID,
            boundary_amount="100.00",
            direction="contribution",
            kind="external_contribution",
            scope_membership="stable_in_scope",
        )
        attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=h2b.START,
            covered_to=h2b.END,
        )
        for relation, value in (
            ("pre_external_flow", "100.00"),
            ("post_external_flow", "200.00"),
        ):
            create_observed_valuation_point(
                session,
                reporting_month_id=february.id,
                scope="portfolio",
                observed_date=h2b.MID,
                total_value=value,
                performance_currency="RUB",
                provenance_kind="synthetic-post-hardening-correction",
                relation=relation,
                external_flow_id=flow.id,
            )
        h2b._close(session, january, february)

        initial = portfolio_twrr_for_interval(
            session,
            start_date=h2b.START,
            end_date=h2b.END,
        )
        assert initial.is_available
        assert initial.return_rate == 0

        reopen_reporting_month(session, february.id)
        update_external_flow(session, flow.id, boundary_amount="125.00")
        reopen_reporting_month(session, january.id)
        attest_cash_boundary_history(
            session,
            account_id=account.id,
            covered_from=h2b.START,
            covered_to=h2b.END,
            provenance_reference="synthetic-post-hardening-re-attestation",
        )
        h2b._close(session, january, february)

        availability = performance_availability_for_interval(
            session,
            start_date=h2b.START,
            end_date=h2b.END,
            scope="portfolio",
        )
        after = portfolio_twrr_for_interval(
            session,
            start_date=h2b.START,
            end_date=h2b.END,
        )
        points = list(
            session.scalars(
                select(ObservedValuationPoint)
                .where(ObservedValuationPoint.external_flow_id == flow.id)
                .order_by(ObservedValuationPoint.id)
            )
        )

        assert availability.twrr.is_available
        assert after.is_available
        assert after.return_rate is not None
        assert after.return_rate < 0
        assert [point.total_value_kopecks for point in points] == [10_000, 20_000]
        assert flow.boundary_amount_kopecks == 12_500
    finally:
        session.close()
        database.engine.dispose()
