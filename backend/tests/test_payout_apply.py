"""R05-06 selective payout apply / preview_changed tests."""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.market_data.payout import (
    PayoutCoverage,
    PayoutEvent,
    PayoutEventKind,
    PayoutEventStatus,
)
from hermes_finance.market_data.payout_protocol import (
    PayoutFailure,
    PayoutFetchRequest,
    PayoutFetchResult,
)
from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    Base,
    ExpectedCashFlow,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    AppliedPayoutRevisionKind,
    PayoutCountingDecision,
    append_applied_payout_revision,
    create_applied_payout,
    get_applied_payout_reconciliation,
    list_applied_payout_revisions,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.payout_apply import (
    ManualDuplicateDecision,
    PayoutApplyFailureCode,
    PayoutApplySelection,
    apply_payout_preview,
)
from hermes_finance.services.payout_preview import build_payout_preview
from hermes_finance.services.positions import (
    create_position_snapshot,
    update_position_snapshot,
)
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

UID = "33333333-3333-3333-3333-333333333333"
FETCHED_AT = datetime(2030, 5, 12, 12, 0, tzinfo=timezone.utc)
APPLIED_AT = datetime(2030, 5, 12, 12, 5, tzinfo=timezone.utc)
REQUEST = PayoutFetchRequest(
    instrument_uid=UID,
    calendar_from=date(2030, 6, 1),
    calendar_to=date(2030, 6, 30),
)


class FakeProvider:
    def __init__(self, result: PayoutFetchResult) -> None:
        self.result = result
        self.calls = 0
        self.requests: list[PayoutFetchRequest] = []
        self.error: Exception | None = None

    def fetch_payouts(self, request: PayoutFetchRequest) -> PayoutFetchResult:
        self.calls += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "payout-apply.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(
    session: Session,
    *,
    quantity: str = "3.125000",
) -> tuple[int, int, int, int]:
    month = create_reporting_month(
        session,
        year=2030,
        month=5,
        snapshot_date=date(2030, 5, 12),
    )
    account = create_account(
        session,
        name="Synthetic Broker",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Synthetic Bond",
        instrument_type=InstrumentType.BOND,
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity=quantity,
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    return month.id, account.id, instrument.id, snapshot.id


def second_scope(
    session: Session,
    *,
    month_id: int,
) -> tuple[int, int, int]:
    account = create_account(
        session,
        name="Second Broker",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Second Bond",
        instrument_type=InstrumentType.BOND,
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="2.000000",
        average_cost_per_unit="99.00",
        market_price_per_unit="100.00",
        price_date=date(2030, 5, 12),
    )
    return account.id, instrument.id, snapshot.id


def event(
    *,
    identity_key: str = "n:11",
    payment_date: date = date(2030, 6, 15),
    amount: Decimal | None = Decimal("35.4"),
    status: PayoutEventStatus = PayoutEventStatus.OK,
    provider_status: str | None = None,
    currency: str | None = "RUB",
) -> PayoutEvent:
    return PayoutEvent(
        provider="t_invest",
        instrument_uid=UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key=identity_key,
        status=status,
        payment_date=payment_date,
        per_unit_amount=amount,
        currency=currency,
        source_method="GetBondCoupons",
        provider_filter_basis="coupon_date",
        provider_filter_date=payment_date,
        provider_status=provider_status,
    )


def fetch_result(
    *events: PayoutEvent,
    coverage_items: tuple[PayoutCoverage, ...] = (),
    failures: tuple[PayoutFailure, ...] = (),
) -> PayoutFetchResult:
    return PayoutFetchResult(
        provider="t_invest",
        instrument_uid=UID,
        events=events,
        coverage=coverage_items,
        failures=failures,
    )


def coupon_coverage() -> PayoutCoverage:
    return PayoutCoverage(
        provider="t_invest",
        method="GetBondCoupons",
        instrument_uid=UID,
        event_kind=PayoutEventKind.COUPON,
        requested_from=date(2030, 6, 1),
        requested_to=date(2030, 6, 30),
        provider_filter_basis="coupon_date",
        successful=True,
        structurally_valid=True,
    )


def manual_flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    expected_date: date,
    amount: str = "999.99",
) -> ExpectedCashFlow:
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=ExpectedCashFlowType.COUPON,
        expected_date=expected_date,
        gross_amount=amount,
        expected_tax_amount=None,
        expected_net_amount=amount,
        source="owner manual",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
        notes="manual candidate",
    )


def seed_applied(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    amount: str = "35.4",
    provider_status: str | None = None,
) -> AppliedProviderPayout:
    payout = create_applied_payout(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        source_position_snapshot_id=snapshot_id,
        provider="t_invest",
        provider_instrument_uid=UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key="n:11",
        payment_date=date(2030, 6, 15),
        per_unit_amount=amount,
        currency="RUB",
        provider_status=provider_status,
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )
    session.commit()
    return payout


def preview_row(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    result: PayoutFetchResult,
    identity_key: str = "n:11",
):
    preview = build_payout_preview(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot_id,
        forecast_version="v1",
        fetch_result=result,
    )
    return next(row for row in preview.rows if row.identity_key == identity_key)


def selection_from_row(row, *, decision: ManualDuplicateDecision | None = None):
    assert row.event_kind is not None
    assert row.identity_key is not None
    assert row.fingerprint is not None
    return PayoutApplySelection(
        provider=row.provider,
        instrument_uid=row.instrument_uid,
        event_kind=row.event_kind,
        identity_key=row.identity_key,
        fingerprint=row.fingerprint,
        manual_duplicate_decision=decision,
    )


def apply(
    session: Session,
    provider: FakeProvider,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    selections: tuple[PayoutApplySelection, ...],
):
    return apply_payout_preview(
        session,
        provider=provider,
        provider_request=REQUEST,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot_id,
        forecast_version="v1",
        selections=selections,
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
    )


def counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(AppliedProviderPayout)) or 0,
        session.scalar(select(func.count()).select_from(AppliedPayoutRevision)) or 0,
        session.scalar(select(func.count()).select_from(AppliedPayoutReconciliation)) or 0,
    )


def test_selected_new_creates_payout_and_apply_revision(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        current = fetch_result(event(amount=Decimal("35.400000000")))
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        provider = FakeProvider(current)

        result = apply(
            session,
            provider,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )

        assert result.success is True
        assert result.error_code is None
        assert result.selected_count == 1
        assert len(result.items) == 1
        item = result.items[0]
        payout = session.get(AppliedProviderPayout, item.payout_id)
        assert payout is not None
        assert payout.identity_key == "n:11"
        assert payout.quantity == Decimal("3.125000")
        assert payout.per_unit_amount == "35.4"
        assert payout.total_amount_kopecks == 11063
        assert item.revision_kind == "apply"
        revisions = list_applied_payout_revisions(session, payout.id)
        assert [revision.revision_kind for revision in revisions] == ["apply"]
        assert revisions[0].total_amount_kopecks == 11063
        assert provider.calls == 1
        assert provider.requests == [REQUEST]
    finally:
        session.close()
        database.engine.dispose()


def test_selected_revised_preserves_payout_id_and_appends_revision(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = seed_applied(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        current = fetch_result(event(amount=Decimal("36.1"), payment_date=date(2030, 6, 16)))
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        provider = FakeProvider(current)

        result = apply(
            session,
            provider,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )

        assert result.success is True
        assert result.items[0].payout_id == payout.id
        assert result.items[0].revision_kind == "revise"
        refreshed = session.get(AppliedProviderPayout, payout.id)
        assert refreshed is not None
        assert refreshed.payment_date == date(2030, 6, 16)
        assert refreshed.per_unit_amount == "36.1"
        assert refreshed.total_amount_kopecks == 11281
        revisions = list_applied_payout_revisions(session, payout.id)
        assert [revision.revision_kind for revision in revisions] == ["apply", "revise"]
        assert revisions[0].per_unit_amount == "35.4"
        assert revisions[1].per_unit_amount == "36.1"
    finally:
        session.close()
        database.engine.dispose()


def test_revised_provider_status_can_clear_to_none(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = seed_applied(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            provider_status="OLD",
        )
        current = fetch_result(event(provider_status=None))
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        provider = FakeProvider(current)
        result = apply(
            session,
            provider,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )
        assert result.success is True
        refreshed = session.get(AppliedProviderPayout, payout.id)
        assert refreshed is not None
        assert refreshed.provider_status is None
        assert list_applied_payout_revisions(session, payout.id)[-1].provider_status is None
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_selected_rows_commit_atomically(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        current = fetch_result(
            event(identity_key="n:11", payment_date=date(2030, 6, 15)),
            event(identity_key="n:12", payment_date=date(2030, 6, 29), amount=Decimal("18.75")),
        )
        first = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
            identity_key="n:11",
        )
        second = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
            identity_key="n:12",
        )
        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(first), selection_from_row(second)),
        )
        assert result.success is True
        assert result.selected_count == 2
        assert len(result.items) == 2
        assert counts(session) == (2, 2, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_second_write_failure_rolls_back_first_payout_revision_and_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hermes_finance.services import payout_apply as module

    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
        )
        current = fetch_result(
            event(identity_key="n:11", payment_date=date(2030, 6, 15)),
            event(identity_key="n:12", payment_date=date(2030, 6, 29), amount=Decimal("18.75")),
        )
        first = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
            identity_key="n:11",
        )
        second = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
            identity_key="n:12",
        )
        original = module.create_applied_payout
        call_count = 0

        def fail_second(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("synthetic second-row persistence failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "create_applied_payout", fail_second)
        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(
                selection_from_row(
                    first,
                    decision=ManualDuplicateDecision(
                        PayoutCountingDecision.COUNT_MANUAL,
                        manual.id,
                    ),
                ),
                selection_from_row(second),
            ),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PERSISTENCE_ERROR
        assert result.items == ()
        assert counts(session) == (0, 0, 0)
        assert session.get(ExpectedCashFlow, manual.id) is not None
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_rejects_before_provider_call(tmp_path: Path) -> None:
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
        close_reporting_month(session, month_id)
        provider = FakeProvider(current)
        result = apply(
            session,
            provider,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.CLOSED_MONTH
        assert provider.calls == 0
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "fresh_event",
    [
        event(amount=Decimal("36.1")),
        event(payment_date=date(2030, 6, 16)),
        event(provider_status="CHANGED"),
    ],
)
def test_fresh_provider_material_change_is_preview_changed(
    tmp_path: Path,
    fresh_event: PayoutEvent,
) -> None:
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
        result = apply(
            session,
            FakeProvider(fetch_result(fresh_event)),
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
        session.close()
        database.engine.dispose()


def test_snapshot_quantity_change_is_preview_changed(tmp_path: Path) -> None:
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
        update_position_snapshot(session, snapshot_id, quantity="4.000000")
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
        session.close()
        database.engine.dispose()


def test_snapshot_id_from_other_scope_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        _, _, other_snapshot_id = second_scope(session, month_id=month_id)
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        result = apply_payout_preview(
            session,
            provider=FakeProvider(current),
            provider_request=REQUEST,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            position_snapshot_id=other_snapshot_id,
            forecast_version="v1",
            selections=(selection_from_row(row),),
            fetched_at=FETCHED_AT,
            applied_at=APPLIED_AT,
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_current_applied_state_change_after_preview_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = seed_applied(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        current = fetch_result(event(amount=Decimal("36.1")))
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        append_applied_payout_revision(
            session,
            payout.id,
            revision_kind=AppliedPayoutRevisionKind.REVISE,
            fetched_at=FETCHED_AT,
            applied_at=APPLIED_AT,
            per_unit_amount="35.8",
        )
        session.commit()
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
        assert len(list_applied_payout_revisions(session, payout.id)) == 2
    finally:
        session.close()
        database.engine.dispose()


def test_manual_candidate_set_change_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
        )
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 17),
            amount="1.00",
        )
        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(
                selection_from_row(
                    row,
                    decision=ManualDuplicateDecision(
                        PayoutCountingDecision.COUNT_MANUAL,
                        manual.id,
                    ),
                ),
            ),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_reconciliation_state_change_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = seed_applied(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        current = fetch_result(event(amount=Decimal("36.1")))
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
        )
        set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=manual.id,
            counting_decision=PayoutCountingDecision.COUNT_MANUAL,
        )
        session.commit()
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
        assert len(list_applied_payout_revisions(session, payout.id)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_missing_selected_identity_is_preview_changed(tmp_path: Path) -> None:
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
        result = apply(
            session,
            FakeProvider(fetch_result()),
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
        session.close()
        database.engine.dispose()


def test_fingerprint_from_other_scope_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        other_account_id, other_instrument_id, other_snapshot_id = second_scope(
            session, month_id=month_id
        )
        current = fetch_result(event())
        other_row = preview_row(
            session,
            month_id=month_id,
            account_id=other_account_id,
            instrument_id=other_instrument_id,
            snapshot_id=other_snapshot_id,
            result=current,
        )
        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(other_row),),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PREVIEW_CHANGED
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_unchanged_status_is_not_applyable(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        seed_applied(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        before = counts(session)
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
        assert result.error_code is PayoutApplyFailureCode.VALIDATION_ERROR
        assert counts(session) == before
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "status",
    [
        PayoutEventStatus.TENTATIVE,
        PayoutEventStatus.UNSUPPORTED,
        PayoutEventStatus.UNAVAILABLE,
        PayoutEventStatus.ERROR,
    ],
)
def test_non_ok_provider_status_is_not_applyable(
    tmp_path: Path,
    status: PayoutEventStatus,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        currency = "USD" if status is PayoutEventStatus.UNSUPPORTED else "RUB"
        amount = (
            Decimal("35.4")
            if status in {PayoutEventStatus.TENTATIVE, PayoutEventStatus.UNSUPPORTED}
            else None
        )
        current = fetch_result(event(status=status, amount=amount, currency=currency))
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
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
        assert result.error_code is PayoutApplyFailureCode.VALIDATION_ERROR
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_covered_missing_is_not_applyable_and_never_cancels(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = seed_applied(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        initial = fetch_result(event(amount=Decimal("36.1")))
        old_row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=initial,
        )
        fresh = fetch_result(coverage_items=(coupon_coverage(),))
        result = apply(
            session,
            FakeProvider(fresh),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(old_row),),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PREVIEW_CHANGED
        refreshed = session.get(AppliedProviderPayout, payout.id)
        assert refreshed is not None
        assert refreshed.lifecycle == "active"
        assert len(list_applied_payout_revisions(session, payout.id)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_duplicate_decision_is_required(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
        )
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
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
        assert result.error_code is PayoutApplyFailureCode.VALIDATION_ERROR
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "decision",
    [
        PayoutCountingDecision.KEEP_BOTH,
        PayoutCountingDecision.COUNT_MANUAL,
        PayoutCountingDecision.COUNT_PROVIDER,
    ],
)
def test_duplicate_decisions_persist_link_without_mutating_manual_flow(
    tmp_path: Path,
    decision: PayoutCountingDecision,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
            amount="999.99",
        )
        before = (
            manual.expected_date,
            manual.gross_amount_kopecks,
            manual.expected_tax_amount_kopecks,
            manual.expected_net_amount_kopecks,
            manual.flow_type,
            manual.source,
            manual.notes,
        )
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(
                selection_from_row(
                    row,
                    decision=ManualDuplicateDecision(decision, manual.id),
                ),
            ),
        )
        assert result.success is True
        item = result.items[0]
        assert item.counting_decision == decision.value
        assert item.expected_cash_flow_id == manual.id
        link = get_applied_payout_reconciliation(session, item.payout_id)
        assert link is not None
        assert link.expected_cash_flow_id == manual.id
        assert link.counting_decision == decision.value
        refreshed = session.get(ExpectedCashFlow, manual.id)
        assert refreshed is not None
        after = (
            refreshed.expected_date,
            refreshed.gross_amount_kopecks,
            refreshed.expected_tax_amount_kopecks,
            refreshed.expected_net_amount_kopecks,
            refreshed.flow_type,
            refreshed.source,
            refreshed.notes,
        )
        assert after == before
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_manual_candidates_require_explicit_target(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        first = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 14),
        )
        second = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 16),
            amount="1.00",
        )
        current = fetch_result(event())
        row = preview_row(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=current,
        )
        assert row.manual_candidate_ids == (first.id, second.id)
        result = apply(
            session,
            FakeProvider(current),
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(
                selection_from_row(
                    row,
                    decision=ManualDuplicateDecision(
                        PayoutCountingDecision.COUNT_PROVIDER,
                        second.id,
                    ),
                ),
            ),
        )
        assert result.success is True
        assert result.items[0].expected_cash_flow_id == second.id
    finally:
        session.close()
        database.engine.dispose()


def test_provider_exception_is_sanitized_and_writes_nothing(tmp_path: Path) -> None:
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
        provider.error = RuntimeError("Authorization: Bearer SUPER-SECRET")
        result = apply(
            session,
            provider,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            selections=(selection_from_row(row),),
        )
        assert result.success is False
        assert result.error_code is PayoutApplyFailureCode.PROVIDER_ERROR
        assert "SECRET" not in (result.message or "")
        assert "Bearer" not in (result.message or "")
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_provider_failure_result_writes_nothing(tmp_path: Path) -> None:
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
                    "T-Invest payout request failed due to a network error",
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
        assert counts(session) == (0, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_apply_module_has_no_tinvest_or_background_network_surface() -> None:
    from hermes_finance.services import payout_apply as module

    source = inspect.getsource(module)
    assert "TInvestClient" not in source
    assert "httpx" not in source
    assert "thread" not in source.lower()
    assert "retry" not in source.lower()
    assert "sleep(" not in source