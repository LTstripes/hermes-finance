"""Cross-session reread regression for R05-06 payout apply."""

from __future__ import annotations

from test_payout_apply import (
    FakeProvider,
    apply,
    build_environment,
    counts,
    event,
    fetch_result,
    preview_row,
    selection_from_row,
    session_for,
)

from hermes_finance.services.payout_apply import PayoutApplyFailureCode
from hermes_finance.services.positions import update_position_snapshot


def test_apply_rereads_snapshot_changed_by_another_session(tmp_path) -> None:
    session, database = session_for(tmp_path)
    other = None
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )

        # Keep the preview-producing Session alive so its identity map still has
        # the old PositionSnapshot, then commit a real local change elsewhere.
        other = database.session_factory()
        update_position_snapshot(other, snapshot_id, quantity="4.000000")
        other.commit()

        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )

        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        if other is not None:
            other.close()
        session.close()
        database.engine.dispose()
