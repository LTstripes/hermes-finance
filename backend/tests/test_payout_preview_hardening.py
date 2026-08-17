"""R05-05 hardening regressions for preview fingerprints and diff edges."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchResult
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    append_applied_payout_revision,
    create_applied_payout,
)
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.payout_preview import PayoutPreviewStatus, build_payout_preview
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

UID = "44444444-4444-4444-4444-444444444444"


def _context(tmp_path: Path) -> tuple[Session, object, int, int, int, int]:
    database = create_database(tmp_path / "payout-preview-hardening.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(
        session,
        year=2031,
        month=4,
        snapshot_date=date(2031, 4, 10),
    )
    account = create_account(
        session,
        name="Hardening Broker",
        account_type=AccountType.BROKERAGE,
    )
    instrument = create_instrument(
        session,
        name="Hardening Bond",
        instrument_type=InstrumentType.BOND,
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="2.500000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2031, 4, 10),
    )
    return session, database, month.id, account.id, instrument.id, snapshot.id


def _event(
    *,
    amount: str = "35.4",
    provider_status: str | None = None,
) -> PayoutEvent:
    return PayoutEvent(
        provider="t_invest",
        instrument_uid=UID,
        event_kind=PayoutEventKind.COUPON,
        identity_key="n:11",
        status=PayoutEventStatus.OK,
        payment_date=date(2031, 5, 15),
        per_unit_amount=Decimal(amount),
        currency="RUB",
        source_method="GetBondCoupons",
        provider_filter_basis="coupon_date",
        provider_filter_date=date(2031, 5, 15),
        provider_status=provider_status,
    )


def _preview(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    event: PayoutEvent,
):
    return build_payout_preview(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        position_snapshot_id=snapshot_id,
        forecast_version="v1",
        fetch_result=PayoutFetchResult(
            provider="t_invest",
            instrument_uid=UID,
            events=(event,),
        ),
    ).rows[0]


def _apply(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    amount: str = "35.4",
    provider_status: str | None = None,
):
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
        payment_date=date(2031, 5, 15),
        per_unit_amount=amount,
        currency="RUB",
        fetched_at=datetime(2026, 8, 17, 8, 0, tzinfo=UTC),
        applied_at=datetime(2026, 8, 17, 8, 5, tzinfo=UTC),
        provider_status=provider_status,
    )
    session.commit()
    return payout


def test_fingerprint_changes_when_current_applied_state_changes(tmp_path: Path) -> None:
    session, database, month_id, account_id, instrument_id, snapshot_id = _context(tmp_path)
    try:
        payout = _apply(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            amount="35.4",
            provider_status="announced",
        )
        provider_event = _event(amount="36.1", provider_status="announced")
        before = _preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event=provider_event,
        )
        assert before.status is PayoutPreviewStatus.REVISED
        assert before.fingerprint is not None

        append_applied_payout_revision(
            session,
            payout.id,
            revision_kind="revise",
            fetched_at=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
            applied_at=datetime(2026, 8, 17, 9, 5, tzinfo=UTC),
            per_unit_amount="35.8",
        )
        session.commit()

        after = _preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event=provider_event,
        )
        assert after.status is PayoutPreviewStatus.REVISED
        assert after.fingerprint is not None
        assert after.fingerprint != before.fingerprint
    finally:
        session.close()
        database.engine.dispose()


def test_single_manual_duplicate_candidate_is_reported(tmp_path: Path) -> None:
    session, database, month_id, account_id, instrument_id, snapshot_id = _context(tmp_path)
    try:
        manual = create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2031, 5, 16),
            gross_amount="1.00",
            expected_tax_amount=None,
            expected_net_amount="1.00",
            source="owner manual",
            source_as_of_date=date(2031, 4, 10),
            forecast_version="v1",
        )
        row = _preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event=_event(),
        )
        assert row.status is PayoutPreviewStatus.POSSIBLE_MANUAL_DUPLICATE
        assert row.manual_candidate_ids == (manual.id,)
        assert row.selectable is True
        assert row.default_selected is False
    finally:
        session.close()
        database.engine.dispose()


def test_provider_status_change_marks_same_identity_revised(tmp_path: Path) -> None:
    session, database, month_id, account_id, instrument_id, snapshot_id = _context(tmp_path)
    try:
        payout = _apply(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            provider_status="old-provider-state",
        )
        row = _preview(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event=_event(provider_status="new-provider-state"),
        )
        assert row.status is PayoutPreviewStatus.REVISED
        assert row.applied_payout_id == payout.id
        assert row.identity_key == "n:11"
    finally:
        session.close()
        database.engine.dispose()
