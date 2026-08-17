"""R05-05 payout preview/diff service tests."""

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
    PayoutFetchResult,
)
from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedPayoutRevision,
    AppliedProviderPayout,
    Base,
    ExpectedCashFlow,
    PositionSnapshot,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    PayoutCountingDecision,
    create_applied_payout,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.payout_preview import (
    MANUAL_DUPLICATE_DATE_WINDOW_DAYS,
    PayoutPreviewStatus,
    build_payout_preview,
)
from hermes_finance.services.positions import (
    create_position_snapshot,
    update_position_snapshot,
)
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

UID = "33333333-3333-3333-3333-333333333333"
FETCHED_AT = datetime(2026, 8, 17, 7, 0, tzinfo=timezone.utc)
APPLIED_AT = datetime(2026, 8, 17, 7, 5, tzinfo=timezone.utc)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "payout-preview.db")
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


def event(
    *,
    kind: PayoutEventKind = PayoutEventKind.COUPON,
    identity_key: str | None = "n:11",
    status: PayoutEventStatus = PayoutEventStatus.OK,
    payment_date: date | None = date(2030, 6, 15),
    amount: Decimal | None = Decimal("35.4"),
    currency: str | None = "RUB",
    provider_status: str | None = None,
    filter_date: date | None = date(2030, 6, 15),
) -> PayoutEvent:
    if kind is PayoutEventKind.COUPON:
        method = "GetBondCoupons"
        basis = "coupon_date"
    elif kind is PayoutEventKind.DIVIDEND:
        method = "GetDividends"
        basis = "record_date"
    else:
        method = "GetBondEvents"
        basis = "event_date"
    if filter_date is None:
        basis_value = None
    else:
        basis_value = basis
    return PayoutEvent(
        provider="t_invest",
        instrument_uid=UID,
        event_kind=kind,
        identity_key=identity_key,
        status=status,
        payment_date=payment_date,
        per_unit_amount=amount,
        currency=currency,
        source_method=method,
        provider_filter_basis=basis_value,
        provider_filter_date=filter_date,
        provider_status=provider_status,
    )


def coverage(
    kind: PayoutEventKind,
    *,
    start: date,
    end: date,
    successful: bool = True,
    structurally_valid: bool = True,
) -> PayoutCoverage:
    if kind is PayoutEventKind.COUPON:
        method = "GetBondCoupons"
        basis = "coupon_date"
    elif kind is PayoutEventKind.DIVIDEND:
        method = "GetDividends"
        basis = "record_date"
    else:
        method = "GetBondEvents"
        basis = "event_date"
    return PayoutCoverage(
        provider="t_invest",
        method=method,
        instrument_uid=UID,
        event_kind=kind,
        requested_from=start,
        requested_to=end,
        provider_filter_basis=basis,
        successful=successful,
        structurally_valid=structurally_valid,
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


def apply_payout(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    kind: PayoutEventKind = PayoutEventKind.COUPON,
    identity_key: str = "n:11",
    payment_date: date = date(2030, 6, 15),
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
        event_kind=kind,
        identity_key=identity_key,
        payment_date=payment_date,
        per_unit_amount=amount,
        currency="RUB",
        fetched_at=FETCHED_AT,
        applied_at=APPLIED_AT,
        provider_status=provider_status,
        is_approximate=True,
    )
    session.commit()
    return payout


def manual_flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    kind: ExpectedCashFlowType = ExpectedCashFlowType.COUPON,
    expected_date: date,
    amount: str = "999.99",
    version: str = "v1",
) -> ExpectedCashFlow:
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=kind,
        expected_date=expected_date,
        gross_amount=amount,
        expected_tax_amount=None,
        expected_net_amount=amount,
        source="owner manual",
        source_as_of_date=date(2030, 5, 12),
        forecast_version=version,
        notes="manual candidate",
    )


def preview(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int | None,
    result: PayoutFetchResult,
    version: str = "v1",
):
    return build_payout_preview(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot_id,
        forecast_version=version,
        fetch_result=result,
    )


def test_new_ok_event_is_default_selectable_with_exact_total(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event(amount=Decimal("35.400000000"))),
        )
        row = result.rows[0]
        assert row.status is PayoutPreviewStatus.NEW
        assert row.selectable is True
        assert row.default_selected is True
        assert row.quantity == Decimal("3.125000")
        assert row.per_unit_amount == Decimal("35.400000000")
        assert row.total_amount_kopecks == 11063
        assert row.fingerprint is not None
    finally:
        session.close()
        database.engine.dispose()


def test_same_identity_is_unchanged_or_revised_without_rekey(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        same = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]
        assert same.status is PayoutPreviewStatus.UNCHANGED
        assert same.applied_payout_id == payout.id
        assert same.selectable is False

        revised_amount = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event(amount=Decimal("36.1"))),
        ).rows[0]
        assert revised_amount.status is PayoutPreviewStatus.REVISED
        assert revised_amount.identity_key == "n:11"
        assert revised_amount.applied_payout_id == payout.id

        revised_date = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                event(
                    payment_date=date(2030, 6, 16),
                    filter_date=date(2030, 6, 16),
                )
            ),
        ).rows[0]
        assert revised_date.status is PayoutPreviewStatus.REVISED
        assert revised_date.identity_key == "n:11"

        update_position_snapshot(session, snapshot_id, quantity="4.000000")
        revised_quantity = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]
        assert revised_quantity.status is PayoutPreviewStatus.REVISED
        assert revised_quantity.identity_key == "n:11"
        assert revised_quantity.total_amount_kopecks == 14160
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("provider_event", "expected"),
    [
        (
            event(
                status=PayoutEventStatus.TENTATIVE,
                payment_date=date(2030, 6, 15),
                amount=Decimal("35.4"),
            ),
            PayoutPreviewStatus.TENTATIVE,
        ),
        (
            event(
                status=PayoutEventStatus.AMBIGUOUS_IDENTITY,
                identity_key=None,
            ),
            PayoutPreviewStatus.AMBIGUOUS_IDENTITY,
        ),
        (
            event(
                status=PayoutEventStatus.UNSUPPORTED,
                currency="USD",
            ),
            PayoutPreviewStatus.UNSUPPORTED,
        ),
        (
            event(
                status=PayoutEventStatus.UNAVAILABLE,
                identity_key=None,
                payment_date=None,
                amount=None,
                currency=None,
                filter_date=None,
            ),
            PayoutPreviewStatus.UNAVAILABLE,
        ),
        (
            event(
                status=PayoutEventStatus.ERROR,
                identity_key=None,
                payment_date=None,
                amount=None,
                currency=None,
                filter_date=None,
            ),
            PayoutPreviewStatus.ERROR,
        ),
    ],
)
def test_provider_non_ok_statuses_stay_conservative(
    tmp_path: Path,
    provider_event: PayoutEvent,
    expected: PayoutPreviewStatus,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        row = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(provider_event),
        ).rows[0]
        assert row.status is expected
        assert row.selectable is False
        assert row.default_selected is False
    finally:
        session.close()
        database.engine.dispose()


def test_manual_duplicate_detection_uses_type_version_and_three_day_window(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        assert MANUAL_DUPLICATE_DATE_WINDOW_DAYS == 3
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        near_left = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 12),
            amount="1.00",
        )
        near_right = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 18),
            amount="99999.99",
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 19),
            amount="35.40",
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            kind=ExpectedCashFlowType.DIVIDEND,
            expected_date=date(2030, 6, 15),
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
            version="v2",
        )

        row = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]
        assert row.status is PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE
        assert row.manual_candidate_ids == (near_left.id, near_right.id)
        assert row.selectable is True
        assert row.default_selected is False
    finally:
        session.close()
        database.engine.dispose()


def test_existing_reconciliation_is_surfaced_without_overriding_diff_status(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
        )
        link = set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=manual.id,
            counting_decision=PayoutCountingDecision.COUNT_MANUAL,
        )
        session.commit()

        row = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]
        assert row.status is PayoutPreviewStatus.UNCHANGED
        assert row.manual_candidate_ids == (manual.id,)
        assert row.reconciliation is not None
        assert row.reconciliation.reconciliation_id == link.id
        assert row.reconciliation.expected_cash_flow_id == manual.id
        assert row.reconciliation.counting_decision == "count_manual"
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("kind", "identity_key", "payment_date", "filter_date"),
    [
        (
            PayoutEventKind.COUPON,
            "n:11",
            date(2030, 6, 15),
            date(2030, 6, 15),
        ),
        (
            PayoutEventKind.DIVIDEND,
            "r:2030-06-05",
            date(2030, 6, 20),
            date(2030, 6, 5),
        ),
        (
            PayoutEventKind.REDEMPTION,
            "mty-date:2030-06-10",
            date(2030, 6, 20),
            date(2030, 6, 10),
        ),
    ],
)
def test_missing_from_provider_requires_reconstructable_covered_filter_key(
    tmp_path: Path,
    kind: PayoutEventKind,
    identity_key: str,
    payment_date: date,
    filter_date: date,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            kind=kind,
            identity_key=identity_key,
            payment_date=payment_date,
        )
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                coverage_items=(
                    coverage(
                        kind,
                        start=filter_date,
                        end=filter_date,
                    ),
                )
            ),
        )
        row = result.rows[0]
        assert row.status is PayoutPreviewStatus.MISSING_FROM_PROVIDER
        assert row.applied_payout_id == payout.id
        assert row.selectable is False
        assert row.total_amount_kopecks == payout.total_amount_kopecks
        assert row.quantity == payout.quantity
    finally:
        session.close()
        database.engine.dispose()


def test_mty_number_does_not_guess_event_date_for_missing(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            kind=PayoutEventKind.REDEMPTION,
            identity_key="mty:1",
            payment_date=date(2030, 6, 20),
        )
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                coverage_items=(
                    coverage(
                        PayoutEventKind.REDEMPTION,
                        start=date(2030, 6, 1),
                        end=date(2030, 6, 30),
                    ),
                )
            ),
        )
        assert result.rows == ()
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("successful", "structurally_valid"),
    [(False, False), (True, False)],
)
def test_bad_coverage_never_proves_missing(
    tmp_path: Path,
    successful: bool,
    structurally_valid: bool,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                coverage_items=(
                    coverage(
                        PayoutEventKind.COUPON,
                        start=date(2030, 6, 1),
                        end=date(2030, 6, 30),
                        successful=successful,
                        structurally_valid=structurally_valid,
                    ),
                )
            ),
        )
        assert result.rows == ()
    finally:
        session.close()
        database.engine.dispose()


def test_ambiguous_row_on_same_filter_date_blocks_false_missing(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        ambiguous = event(
            identity_key=None,
            status=PayoutEventStatus.AMBIGUOUS_IDENTITY,
            payment_date=date(2030, 6, 15),
            filter_date=date(2030, 6, 15),
        )
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                ambiguous,
                coverage_items=(
                    coverage(
                        PayoutEventKind.COUPON,
                        start=date(2030, 6, 1),
                        end=date(2030, 6, 30),
                    ),
                ),
            ),
        )
        assert [row.status for row in result.rows] == [
            PayoutPreviewStatus.AMBIGUOUS_IDENTITY
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_identity_change_yields_old_missing_plus_new_event(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            identity_key="n:11",
        )
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                event(identity_key="n:12"),
                coverage_items=(
                    coverage(
                        PayoutEventKind.COUPON,
                        start=date(2030, 6, 1),
                        end=date(2030, 6, 30),
                    ),
                ),
            ),
        )
        by_status = {row.status: row for row in result.rows}
        assert by_status[PayoutPreviewStatus.NEW].identity_key == "n:12"
        assert by_status[PayoutPreviewStatus.MISSING_FROM_PROVIDER].identity_key == "n:11"
    finally:
        session.close()
        database.engine.dispose()


def test_position_gone_surfaces_applied_state_without_deleting_it(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
        )
        result = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=None,
            result=fetch_result(),
        )
        row = result.rows[0]
        assert row.status is PayoutPreviewStatus.POSITION_GONE
        assert row.applied_payout_id == payout.id
        assert row.position_snapshot_id == payout.source_position_snapshot_id
        assert row.quantity == payout.quantity
        assert session.get(AppliedProviderPayout, payout.id) is not None
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_preview_is_repeatable_and_read_only(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        payout = apply_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
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
        close_reporting_month(session, month_id)

        before = (
            session.scalar(select(func.count()).select_from(AppliedProviderPayout)),
            session.scalar(select(func.count()).select_from(AppliedPayoutRevision)),
            session.scalar(select(func.count()).select_from(AppliedPayoutReconciliation)),
            session.scalar(select(func.count()).select_from(ExpectedCashFlow)),
            session.scalar(select(func.count()).select_from(PositionSnapshot)),
        )
        first = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        )
        second = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        )
        after = (
            session.scalar(select(func.count()).select_from(AppliedProviderPayout)),
            session.scalar(select(func.count()).select_from(AppliedPayoutRevision)),
            session.scalar(select(func.count()).select_from(AppliedPayoutReconciliation)),
            session.scalar(select(func.count()).select_from(ExpectedCashFlow)),
            session.scalar(select(func.count()).select_from(PositionSnapshot)),
        )
        assert first == second
        assert before == after
        assert not session.dirty
        assert not session.new
        assert not session.deleted
    finally:
        session.close()
        database.engine.dispose()


def test_preview_fingerprint_changes_for_material_owner_or_provider_state(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        first = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]
        changed_amount = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event(amount=Decimal("36.1"))),
        ).rows[0]
        changed_date = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(
                event(
                    payment_date=date(2030, 6, 16),
                    filter_date=date(2030, 6, 16),
                )
            ),
        ).rows[0]
        update_position_snapshot(session, snapshot_id, quantity="4.000000")
        changed_quantity = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            expected_date=date(2030, 6, 15),
        )
        changed_manual = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(event()),
        ).rows[0]

        fingerprints = {
            first.fingerprint,
            changed_amount.fingerprint,
            changed_date.fingerprint,
            changed_quantity.fingerprint,
            changed_manual.fingerprint,
        }
        assert None not in fingerprints
        assert len(fingerprints) == 5
        assert changed_manual.manual_candidate_ids == (manual.id,)
    finally:
        session.close()
        database.engine.dispose()


def test_provider_failures_are_sanitized_nonselectable_output(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        failure = PayoutFailure(
            PayoutEventStatus.ERROR,
            "T-Invest payout request failed due to a network error",
            method="GetBondCoupons",
        )
        row = preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            result=fetch_result(failures=(failure,)),
        ).rows[0]
        assert row.status is PayoutPreviewStatus.ERROR
        assert row.message == "T-Invest payout request failed due to a network error"
        assert row.source_method == "GetBondCoupons"
        assert row.selectable is False
        assert row.fingerprint is None
    finally:
        session.close()
        database.engine.dispose()


def test_preview_module_has_no_provider_network_or_write_calls() -> None:
    from hermes_finance.services import payout_preview as module

    source = inspect.getsource(module)
    assert "TInvestClient" not in source
    assert "fetch_payouts(" not in source
    assert "httpx" not in source
    assert "session.add(" not in source
    assert "session.delete(" not in source
    assert "session.flush(" not in source
    assert "session.commit(" not in source
