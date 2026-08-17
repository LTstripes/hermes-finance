"""R05-07 merged payout calendar read-model tests."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    Base,
    ExpectedCashFlow,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    AppliedPayoutLifecycle,
    AppliedPayoutRevisionKind,
    PayoutCountingDecision,
    append_applied_payout_revision,
    create_applied_payout,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.expected_cash_flows import (
    calendar_expected_cash_flows,
    create_expected_cash_flow,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.payout_calendar import (
    PayoutCalendarSource,
    merged_payout_calendar,
)
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

APPLIED_AT = datetime(2030, 5, 12, 12, 0, tzinfo=UTC)
UID = "44444444-4444-4444-4444-444444444444"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "payout-calendar.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session, *, quantity: str = "2.000000") -> tuple[int, int, int, int]:
    month = create_reporting_month(
        session,
        year=2030,
        month=5,
        snapshot_date=date(2030, 5, 12),
    )
    account = create_account(
        session,
        name="Synthetic Brokerage",
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


def manual_flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: ExpectedCashFlowType = ExpectedCashFlowType.COUPON,
    expected_date: date = date(2030, 6, 15),
    amount: str = "100.00",
    forecast_version: str = "v1",
):
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        expected_date=expected_date,
        gross_amount=amount,
        expected_tax_amount=None,
        expected_net_amount=None,
        source="owner manual",
        source_as_of_date=date(2030, 5, 12),
        forecast_version=forecast_version,
    )


def provider_payout(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    event_kind: PayoutEventKind = PayoutEventKind.COUPON,
    identity_key: str = "n:11",
    payment_date: date = date(2030, 6, 15),
    per_unit_amount: str = "25.00",
):
    payout = create_applied_payout(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        source_position_snapshot_id=snapshot_id,
        provider="t_invest",
        provider_instrument_uid=UID,
        event_kind=event_kind,
        identity_key=identity_key,
        payment_date=payment_date,
        per_unit_amount=per_unit_amount,
        currency="RUB",
        provider_status=None,
        fetched_at=APPLIED_AT,
        applied_at=APPLIED_AT,
    )
    session.commit()
    return payout


def sources(calendar) -> list[PayoutCalendarSource]:
    return [item.source_kind for month in calendar for item in month.items]


def item_ids(calendar) -> list[tuple[PayoutCalendarSource, int]]:
    return [(item.source_kind, item.source_id) for month in calendar for item in month.items]


def counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(ExpectedCashFlow)) or 0,
        session.scalar(select(func.count()).select_from(AppliedProviderPayout)) or 0,
        session.scalar(select(func.count()).select_from(AppliedPayoutReconciliation)) or 0,
    )


def test_manual_only_output_matches_existing_calendar_totals(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, _ = build_environment(session)
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 1),
            amount="870.00",
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.DIVIDEND,
            expected_date=date(2030, 6, 20),
            amount="500.00",
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.REDEMPTION,
            expected_date=date(2030, 7, 1),
            amount="10000.00",
        )

        legacy = calendar_expected_cash_flows(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        merged = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )

        assert [(m.year, m.month) for m in merged] == [(m.year, m.month) for m in legacy]
        assert [m.passive_net.kopecks for m in merged] == [m.passive_net.kopecks for m in legacy]
        assert [m.total_net.kopecks for m in merged] == [m.total_net.kopecks for m in legacy]
        assert all(source is PayoutCalendarSource.MANUAL for source in sources(merged))
    finally:
        session.close()
        database.engine.dispose()


def test_provider_coupon_dividend_and_redemption_use_frozen_totals(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        coupon = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            per_unit_amount="25.00",
        )
        dividend = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.DIVIDEND,
            identity_key="r:2030-06-20",
            payment_date=date(2030, 7, 5),
            per_unit_amount="10.00",
        )
        redemption = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.REDEMPTION,
            identity_key="mty:1",
            payment_date=date(2030, 8, 1),
            per_unit_amount="1000.00",
        )

        calendar = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        june, july, august = calendar
        assert june.coupon.kopecks == coupon.total_amount_kopecks == 5_000
        assert july.dividend.kopecks == dividend.total_amount_kopecks == 2_000
        assert august.redemption.kopecks == redemption.total_amount_kopecks == 200_000
        assert august.passive_net.kopecks == 0
        assert august.total_net.kopecks == 200_000
        provider_item = june.items[0]
        assert provider_item.source_kind is PayoutCalendarSource.PROVIDER
        assert provider_item.provider == "t_invest"
        assert provider_item.provider_identity_key == "n:11"
        assert provider_item.account_name == "Synthetic Brokerage"
        assert provider_item.instrument_name == "Synthetic Bond"
    finally:
        session.close()
        database.engine.dispose()


def test_later_snapshot_quantity_change_does_not_recalculate_applied_total(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(
            session, quantity="2.000000"
        )
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            per_unit_amount="25.00",
        )
        assert payout.total_amount_kopecks == 5_000
        update_position_snapshot(session, snapshot_id, quantity="9.000000")

        [june] = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert june.coupon.kopecks == 5_000
        assert june.items[0].expected_net_amount.kopecks == 5_000
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("decision", "expected_sources", "expected_total"),
    [
        (
            PayoutCountingDecision.KEEP_BOTH,
            [PayoutCalendarSource.MANUAL, PayoutCalendarSource.PROVIDER],
            15_000,
        ),
        (
            PayoutCountingDecision.COUNT_MANUAL,
            [PayoutCalendarSource.MANUAL],
            10_000,
        ),
        (
            PayoutCountingDecision.COUNT_PROVIDER,
            [PayoutCalendarSource.PROVIDER],
            5_000,
        ),
    ],
)
def test_explicit_reconciliation_controls_counting(
    tmp_path: Path,
    decision: PayoutCountingDecision,
    expected_sources: list[PayoutCalendarSource],
    expected_total: int,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        link = set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=manual.id,
            counting_decision=decision,
        )
        session.commit()

        [june] = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert sources((june,)) == expected_sources
        assert june.total_net.kopecks == expected_total
        assert all(item.reconciliation_id == link.id for item in june.items)
        assert all(item.counting_decision == decision.value for item in june.items)
    finally:
        session.close()
        database.engine.dispose()


def test_unresolved_duplicate_defaults_to_manual_only_without_writes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        before = counts(session)

        [june] = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert item_ids((june,)) == [(PayoutCalendarSource.MANUAL, manual.id)]
        assert counts(session) == before
        assert session.new == set()
        assert session.dirty == set()
        assert session.deleted == set()
    finally:
        session.close()
        database.engine.dispose()


def test_new_extra_manual_candidate_makes_existing_resolution_conservative(tmp_path: Path) -> None:
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
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=first.id,
            counting_decision=PayoutCountingDecision.KEEP_BOTH,
        )
        session.commit()
        second = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 16),
            amount="1.00",
        )

        [june] = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert item_ids((june,)) == [
            (PayoutCalendarSource.MANUAL, first.id),
            (PayoutCalendarSource.MANUAL, second.id),
        ]
        assert june.total_net.kopecks == 10_100
    finally:
        session.close()
        database.engine.dispose()


def test_unrelated_manual_flow_does_not_suppress_provider(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            expected_date=date(2030, 6, 15),
            amount="20.00",
        )
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )

        [june] = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert set(item_ids((june,))) == {
            (PayoutCalendarSource.MANUAL, manual.id),
            (PayoutCalendarSource.PROVIDER, payout.id),
        }
        assert june.interest.kopecks == 2_000
        assert june.coupon.kopecks == 5_000
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("lifecycle", "revision_kind"),
    [
        (AppliedPayoutLifecycle.CANCELLED, AppliedPayoutRevisionKind.CANCEL),
        (AppliedPayoutLifecycle.DISMISSED, AppliedPayoutRevisionKind.DISMISS),
    ],
)
def test_inactive_provider_is_not_countable_and_count_provider_does_not_resurrect_manual(
    tmp_path: Path,
    lifecycle: AppliedPayoutLifecycle,
    revision_kind: AppliedPayoutRevisionKind,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=manual.id,
            counting_decision=PayoutCountingDecision.COUNT_PROVIDER,
        )
        append_applied_payout_revision(
            session,
            payout.id,
            revision_kind=revision_kind,
            fetched_at=APPLIED_AT,
            applied_at=APPLIED_AT,
            lifecycle=lifecycle,
        )
        session.commit()

        calendar = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert calendar == ()
    finally:
        session.close()
        database.engine.dispose()


def test_active_applied_payout_remains_countable_without_provider_refresh(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )

        [june] = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert item_ids((june,)) == [(PayoutCalendarSource.PROVIDER, payout.id)]
    finally:
        session.close()
        database.engine.dispose()


def test_horizon_boundary_and_item_ordering_are_deterministic(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        inside = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2031, 5, 11),
        )
        outside = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            expected_date=date(2031, 5, 12),
        )
        provider = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            identity_key="n:12",
            payment_date=date(2030, 6, 1),
        )
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            expected_date=date(2030, 6, 1),
            amount="1.00",
        )

        calendar = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert [(m.year, m.month) for m in calendar] == [(2030, 6), (2031, 5)]
        june, may = calendar
        assert item_ids((june,)) == [
            (PayoutCalendarSource.MANUAL, manual.id),
            (PayoutCalendarSource.PROVIDER, provider.id),
        ]
        assert item_ids((may,)) == [(PayoutCalendarSource.MANUAL, inside.id)]
        assert outside.id not in [source_id for _, source_id in item_ids(calendar)]
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_reads_are_repeatable_and_write_nothing(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            expected_date=date(2030, 6, 1),
        )
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            payment_date=date(2030, 7, 1),
        )
        close_reporting_month(session, month_id)
        before = counts(session)

        first = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        second = merged_payout_calendar(
            session,
            reporting_month_id=month_id,
            forecast_version="v1",
        )
        assert first == second
        assert counts(session) == before
        assert session.new == set()
        assert session.dirty == set()
        assert session.deleted == set()
    finally:
        session.close()
        database.engine.dispose()


def test_calendar_module_has_no_provider_network_or_write_surface() -> None:
    from hermes_finance.services import payout_calendar as module

    source = inspect.getsource(module)
    assert "TInvestClient" not in source
    assert "httpx" not in source
    assert "fetch_payouts(" not in source
    assert "session.add(" not in source
    assert "session.delete(" not in source
    assert "session.flush(" not in source
    assert "session.commit(" not in source
