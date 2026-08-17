"""Hardening regressions for R05-06 payout apply."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from test_payout_apply import (
    FakeProvider,
    apply,
    build_environment,
    event,
    fetch_result,
    preview_row,
    selection_from_row,
    session_for,
)

from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFailure
from hermes_finance.persistence import AppliedPayoutRevision, AppliedProviderPayout
from hermes_finance.services.payout_apply import PayoutApplyFailureCode


def test_ambiguous_fresh_identity_rejects_old_selection(tmp_path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        initial = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=initial,
        )
        ambiguous = PayoutEvent(
            provider="t_invest",
            instrument_uid=row.instrument_uid,
            event_kind=PayoutEventKind.COUPON,
            identity_key=None,
            status=PayoutEventStatus.AMBIGUOUS_IDENTITY,
            payment_date=date(2030, 6, 15),
            per_unit_amount=Decimal("35.4"),
            currency="RUB",
            source_method="GetBondCoupons",
            provider_filter_basis="coupon_date",
            provider_filter_date=date(2030, 6, 15),
        )
        result = apply(
            session,
            FakeProvider(fetch_result(ambiguous)),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PREVIEW_CHANGED
        assert session.scalar(select(func.count()).select_from(AppliedProviderPayout)) == 0
        assert session.scalar(select(func.count()).select_from(AppliedPayoutRevision)) == 0
    finally:
        session.close()
        database.engine.dispose()


def test_returned_provider_failure_message_is_not_echoed(tmp_path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        initial = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=initial,
        )
        fresh = fetch_result(
            failures=(
                PayoutFailure(
                    PayoutEventStatus.ERROR,
                    "Authorization: Bearer MUST-NOT-LEAK raw body secret",
                    method="GetBondCoupons",
                ),
            )
        )
        result = apply(
            session,
            FakeProvider(fresh),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PROVIDER_ERROR
        assert result.message == "payout provider refresh failed"
        assert "Bearer" not in result.message
        assert "secret" not in result.message
    finally:
        session.close()
        database.engine.dispose()
