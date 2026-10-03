"""Cross-session reread regression for R05-06 payout apply."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier, Event, current_thread

import pytest
from sqlalchemy import select
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

from hermes_finance.persistence import AppliedProviderPayout
from hermes_finance.services import payout_apply
from hermes_finance.services.payout_apply import PayoutApplyFailureCode
from hermes_finance.services.positions import update_position_snapshot


def _revised_case(session):
    month_id, account_id, instrument_id, snapshot_id = build_environment(session)
    scope = dict(
        month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        snapshot_id=snapshot_id,
    )
    initial = fetch_result(event())
    row = preview_row(session, result=initial, **scope)
    assert apply(
        session, FakeProvider(initial), selections=(selection_from_row(row),), **scope
    ).success
    revised = fetch_result(event(amount=Decimal("40.00")))
    row = preview_row(session, result=revised, **scope)
    assert row.status.value == "revised"
    selection = selection_from_row(row)
    session.rollback()
    return scope, revised, selection


def test_overlapping_revised_applies_append_at_most_one_revision(tmp_path, monkeypatch):
    """S14: both fetched the same revision; waiter reaches writer before winner commits."""
    session, database = session_for(tmp_path)
    try:
        scope, revised, selection = _revised_case(session)
        fetched = Barrier(2)
        waiter_at_writer = Event()
        winner_at_plan = Event()
        original_guard = payout_apply.require_editable_reporting_month
        original_plan = payout_apply._build_apply_plan
        # Observe the production writer entrypoint, including mutation guards.
        from hermes_finance.services import applied_payouts

        def guarded(db_session, month_id):
            if current_thread().name.endswith("_1") and winner_at_plan.is_set():
                waiter_at_writer.set()
            return original_guard(db_session, month_id)

        def plan(*args):
            value = original_plan(*args)
            if current_thread().name.endswith("_0"):
                winner_at_plan.set()
                assert waiter_at_writer.wait(10), "waiter never reached the writer"
            return value

        monkeypatch.setattr(payout_apply, "require_editable_reporting_month", guarded)
        monkeypatch.setattr(applied_payouts, "require_editable_reporting_month", guarded)
        monkeypatch.setattr(payout_apply, "_build_apply_plan", plan)

        class RacingProvider(FakeProvider):
            def fetch_payouts(self, request):
                with database.engine.connect() as observer:
                    # Production pre-fetch guard released its reservation:
                    # a real unrelated writer can acquire and release it.
                    observer.exec_driver_sql("BEGIN IMMEDIATE")
                    observer.rollback()
                value = super().fetch_payouts(request)
                fetched.wait(timeout=10)
                if current_thread().name.endswith("_1"):
                    assert winner_at_plan.wait(10)
                return value

        providers = [RacingProvider(revised), RacingProvider(revised)]

        def run(index):
            with database.session_factory() as isolated:
                return apply(isolated, providers[index], selections=(selection,), **scope)

        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="payout_race") as pool:
            first = pool.submit(run, 0)
            second = pool.submit(run, 1)
            results = [first.result(timeout=20), second.result(timeout=20)]
        assert [result.success for result in results] == [True, False]
        assert results[1].error_code in {
            PayoutApplyFailureCode.PREVIEW_CHANGED,
            PayoutApplyFailureCode.VALIDATION_ERROR,
        }
        assert counts(session) == (1, 2, 0)
        session.expire_all()
        current = session.scalar(select(AppliedProviderPayout))
        assert current is not None
        assert Decimal(current.per_unit_amount) == Decimal("40.00")
        assert current.total_amount_kopecks == 12500
        assert all(provider.calls == 1 for provider in providers)
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("original_commits_first", [True, False])
def test_lost_reply_reload_fresh_preview_reconfirm(original_commits_first, tmp_path):
    """No request attribution: a new explicit preview is safe in either commit order."""
    session, database = session_for(tmp_path)
    try:
        scope, revised, selection = _revised_case(session)
        fetched = Event()
        release_original = Event()

        class PausedProvider(FakeProvider):
            def fetch_payouts(self, request):
                value = super().fetch_payouts(request)
                fetched.set()
                assert release_original.wait(10)
                return value

        def original_request():
            with database.session_factory() as isolated:
                return apply(isolated, PausedProvider(revised), selections=(selection,), **scope)

        with ThreadPoolExecutor(max_workers=1) as pool:
            original = pool.submit(original_request)
            assert fetched.wait(10)
            # The client has lost its reply and reloaded. A separate session
            # explicitly previews and confirms, never reuses durable request state.
            with database.session_factory() as reloaded:
                fresh = preview_row(reloaded, result=revised, **scope)
                reconfirmed = selection_from_row(fresh)
                reloaded.rollback()
                if original_commits_first:
                    release_original.set()
                    assert original.result(timeout=10).success
                new_result = apply(
                    reloaded, FakeProvider(revised), selections=(reconfirmed,), **scope
                )
                if not original_commits_first:
                    assert new_result.success
                    release_original.set()
                    assert not original.result(timeout=10).success
                else:
                    assert not new_result.success
        assert counts(session) == (1, 2, 0)
    finally:
        session.close()
        database.engine.dispose()


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
