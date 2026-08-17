"""Scope guard regression for R05-06 payout apply."""

from __future__ import annotations

from test_payout_apply import (
    APPLIED_AT,
    FETCHED_AT,
    FakeProvider,
    build_environment,
    event,
    fetch_result,
    preview_row,
    selection_from_row,
    session_for,
)

from hermes_finance.market_data.payout_protocol import PayoutFetchRequest
from hermes_finance.services.payout_apply import PayoutApplyFailureCode, apply_payout_preview


def test_selection_instrument_must_match_provider_request_before_fetch(tmp_path) -> None:
    session, database = session_for(tmp_path)
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
        provider = FakeProvider(current)
        wrong_request = PayoutFetchRequest(
            instrument_uid="44444444-4444-4444-4444-444444444444",
            calendar_from=row.payment_date,
            calendar_to=row.payment_date,
        )
        result = apply_payout_preview(
            session,
            provider=provider,
            provider_request=wrong_request,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            position_snapshot_id=snapshot_id,
            forecast_version="v1",
            selections=(selection_from_row(row),),
            fetched_at=FETCHED_AT,
            applied_at=APPLIED_AT,
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.VALIDATION_ERROR
        assert provider.calls == 0
    finally:
        session.close()
        database.engine.dispose()
