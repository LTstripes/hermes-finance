"""R05-04 applied provider-payout persistence primitives."""

from __future__ import annotations

import inspect
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.market_data.payout import PayoutDomainError, PayoutEventKind
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
    AppliedPayoutAlreadyExistsError,
    AppliedPayoutRevisionError,
    PayoutCountingDecision,
    append_applied_payout_revision,
    assert_no_raw_provider_payload_columns,
    clear_applied_payout_reconciliation,
    compute_applied_total_kopecks,
    create_applied_payout,
    delete_applied_payout_revision,
    get_applied_payout_by_identity,
    get_applied_payout_reconciliation,
    list_applied_payout_revisions,
    overwrite_applied_payout_revision,
    set_applied_payout_reconciliation,
    update_applied_payout_revision,
)
from hermes_finance.services.expected_cash_flows import (
    create_expected_cash_flow,
    update_expected_cash_flow,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.reporting_months import (
    ClosedReportingMonthError,
    close_reporting_month,
    create_reporting_month,
)

BOND_UID = "33333333-3333-3333-3333-333333333333"
FETCHED_AT = datetime(2026, 8, 17, 10, 0, tzinfo=timezone.utc)
APPLIED_AT = datetime(2026, 8, 17, 10, 5, tzinfo=timezone.utc)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "applied-payouts.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int, int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    first_account = create_account(
        session, name="Synthetic Broker A", account_type=AccountType.BROKERAGE
    )
    second_account = create_account(
        session, name="Synthetic Broker B", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
    )
    first_snapshot = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=first_account.id,
        instrument_id=instrument.id,
        quantity="3.125000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=second_account.id,
        instrument_id=instrument.id,
        quantity="10.000000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    return month.id, first_account.id, second_account.id, instrument.id, first_snapshot.id


def create_payout(
    session: Session,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    **overrides: object,
) -> AppliedProviderPayout:
    values: dict[str, object] = {
        "reporting_month_id": month_id,
        "account_id": account_id,
        "instrument_id": instrument_id,
        "source_position_snapshot_id": snapshot_id,
        "provider": "t_invest",
        "provider_instrument_uid": BOND_UID,
        "event_kind": PayoutEventKind.COUPON,
        "identity_key": "n:11",
        "payment_date": date(2030, 6, 15),
        "per_unit_amount": Decimal("35.400000000"),
        "currency": "RUB",
        "fetched_at": FETCHED_AT,
        "applied_at": APPLIED_AT,
        "is_approximate": True,
    }
    values.update(overrides)
    return create_applied_payout(session, **values)


def test_two_accounts_store_the_same_provider_identity(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, first_account, second_account, instrument_id, first_snapshot = build_environment(
            session
        )
        second_snapshot = session.scalar(
            select(PositionSnapshot).where(PositionSnapshot.account_id == second_account)
        )
        assert second_snapshot is not None
        first = create_payout(session, month_id, first_account, instrument_id, first_snapshot)
        second = create_payout(session, month_id, second_account, instrument_id, second_snapshot.id)
        assert first.id != second.id
        assert first.identity_key == second.identity_key
        assert first.quantity == Decimal("3.125000")
        assert second.quantity == Decimal("10.000000")
        assert first.total_amount_kopecks != second.total_amount_kopecks
    finally:
        session.close()
        database.engine.dispose()


def test_duplicate_identity_in_same_scope_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        create_payout(session, month_id, account_id, instrument_id, snapshot_id)
        with pytest.raises(AppliedPayoutAlreadyExistsError):
            create_payout(
                session,
                month_id,
                account_id,
                instrument_id,
                snapshot_id,
                payment_date=date(2030, 7, 1),
                per_unit_amount=Decimal("40"),
            )
        assert session.scalar(select(func.count()).select_from(AppliedProviderPayout)) == 1
        assert session.scalar(select(func.count()).select_from(AppliedPayoutRevision)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_amount_date_revision_keeps_identity_and_appends_history(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        payout = create_payout(session, month_id, account_id, instrument_id, snapshot_id)
        first_applied_at = payout.first_applied_at
        first_total = payout.total_amount_kopecks
        revision = append_applied_payout_revision(
            session,
            payout.id,
            revision_kind="revise",
            payment_date=date(2030, 6, 16),
            per_unit_amount=Decimal("36.100000000"),
            fetched_at=datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc),
            applied_at=datetime(2026, 8, 17, 11, 5, tzinfo=timezone.utc),
        )
        history = list_applied_payout_revisions(session, payout.id)
        assert len(history) == 2
        assert history[0].payment_date == date(2030, 6, 15)
        assert history[0].per_unit_amount == "35.4"
        assert history[0].total_amount_kopecks == first_total
        assert history[1].id == revision.id
        assert history[1].payment_date == date(2030, 6, 16)
        assert history[1].revision_kind == "revise"
        assert payout.payment_date == date(2030, 6, 16)
        assert payout.first_applied_at == first_applied_at
        same = get_applied_payout_by_identity(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            provider="t_invest",
            provider_instrument_uid=BOND_UID,
            event_kind="coupon",
            identity_key="n:11",
        )
        assert same is not None
        assert same.id == payout.id
        assert session.scalar(select(func.count()).select_from(AppliedProviderPayout)) == 1
    finally:
        session.close()
        database.engine.dispose()


def test_quantity_and_per_unit_round_trip_without_float(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        payout = create_payout(
            session,
            month_id,
            account_id,
            instrument_id,
            snapshot_id,
            per_unit_amount="35.400000000",
        )
        expected_total = compute_applied_total_kopecks(Decimal("35.400000000"), Decimal("3.125000"))
        assert expected_total == 11063
        assert payout.quantity == Decimal("3.125000")
        assert payout.per_unit_amount == "35.4"
        assert payout.total_amount_kopecks == expected_total
        assert payout.currency == "RUB"
        assert payout.is_approximate is True
        assert payout.amount_basis == "provider_announced"
        with pytest.raises(PayoutDomainError):
            create_payout(
                session,
                month_id,
                account_id,
                instrument_id,
                snapshot_id,
                identity_key="n:12",
                per_unit_amount=35.4,
            )
    finally:
        session.close()
        database.engine.dispose()


def test_foreign_currency_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        with pytest.raises(ValueError, match="foreign currency"):
            create_payout(
                session,
                month_id,
                account_id,
                instrument_id,
                snapshot_id,
                currency="USD",
            )
        assert session.scalar(select(func.count()).select_from(AppliedProviderPayout)) == 0
    finally:
        session.close()
        database.engine.dispose()


def test_reconciliation_does_not_mutate_manual_expected_flow(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        payout = create_payout(session, month_id, account_id, instrument_id, snapshot_id)
        manual = create_expected_cash_flow(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2030, 6, 14),
            gross_amount="1100.00",
            expected_tax_amount="130.00",
            expected_net_amount="970.00",
            source="synthetic calendar",
            source_as_of_date=date(2030, 5, 12),
            forecast_version="v1",
            notes="owner entered",
        )
        before = (
            manual.id,
            manual.gross_amount_kopecks,
            manual.expected_tax_amount_kopecks,
            manual.expected_net_amount_kopecks,
            manual.expected_date,
            manual.flow_type,
            manual.source,
            manual.notes,
            manual.is_confirmed,
            manual.is_approximate,
        )
        link = set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=manual.id,
            counting_decision=PayoutCountingDecision.COUNT_MANUAL,
        )
        session.refresh(manual)
        after = (
            manual.id,
            manual.gross_amount_kopecks,
            manual.expected_tax_amount_kopecks,
            manual.expected_net_amount_kopecks,
            manual.expected_date,
            manual.flow_type,
            manual.source,
            manual.notes,
            manual.is_confirmed,
            manual.is_approximate,
        )
        assert before == after
        assert link.expected_cash_flow_id == manual.id
        assert link.counting_decision == "count_manual"
        updated = update_expected_cash_flow(
            session, manual.id, notes="still owner data", is_confirmed=True
        )
        session.refresh(link)
        assert updated.notes == "still owner data"
        assert updated.gross_amount_kopecks == 110_000
        linked = get_applied_payout_reconciliation(session, payout.id)
        assert linked is not None
        assert linked.expected_cash_flow_id == manual.id
        clear_applied_payout_reconciliation(session, payout.id)
        session.refresh(manual)
        assert manual.notes == "still owner data"
        assert session.scalar(select(func.count()).select_from(ExpectedCashFlow)) == 1
        assert session.scalar(select(func.count()).select_from(AppliedPayoutReconciliation)) == 0
    finally:
        session.close()
        database.engine.dispose()


def test_append_only_revision_helpers_refuse_overwrite(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        payout = create_payout(session, month_id, account_id, instrument_id, snapshot_id)
        first = list_applied_payout_revisions(session, payout.id)[0]
        with pytest.raises(AppliedPayoutRevisionError, match="append-only"):
            update_applied_payout_revision(session, first.id, payment_date=date(2030, 7, 1))
        with pytest.raises(AppliedPayoutRevisionError, match="append-only"):
            overwrite_applied_payout_revision(session, first.id)
        with pytest.raises(AppliedPayoutRevisionError, match="append-only"):
            delete_applied_payout_revision(session, first.id)
        with pytest.raises(AppliedPayoutRevisionError, match="first apply"):
            append_applied_payout_revision(
                session,
                payout.id,
                revision_kind="apply",
                fetched_at=FETCHED_AT,
            )
        session.refresh(first)
        assert first.payment_date == date(2030, 6, 15)
        assert first.per_unit_amount == "35.4"
        source = inspect.getsource(append_applied_payout_revision)
        assert "session.merge(" not in source
        assert "UPDATE applied_payout_revisions" not in source
    finally:
        session.close()
        database.engine.dispose()


def test_closed_month_cannot_be_written_through_payout_helpers(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        close_reporting_month(session, month_id)
        with pytest.raises(ClosedReportingMonthError):
            create_payout(session, month_id, account_id, instrument_id, snapshot_id)
    finally:
        session.close()
        database.engine.dispose()


def test_schema_has_no_raw_payload_or_token_fields() -> None:
    assert_no_raw_provider_payload_columns()
    for model in (AppliedProviderPayout, AppliedPayoutRevision, AppliedPayoutReconciliation):
        names = {column.name for column in model.__table__.columns}
        assert "token" not in names
        assert "raw_payload" not in names
        assert "response_body" not in names


def test_repository_module_has_no_provider_or_network_imports() -> None:
    from hermes_finance.services import applied_payouts as module

    source = inspect.getsource(module)
    assert "httpx" not in source
    assert "TInvestClient" not in source
    assert "fetch_payouts" not in source
    assert "socket" not in source


def test_snapshot_quantity_change_does_not_rewrite_old_revision(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        payout = create_payout(session, month_id, account_id, instrument_id, snapshot_id)
        first_quantity = payout.quantity
        first_total = payout.total_amount_kopecks
        update_position_snapshot(session, snapshot_id, quantity="4.000000")
        append_applied_payout_revision(
            session,
            payout.id,
            revision_kind="revise",
            fetched_at=datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc),
        )
        history = list_applied_payout_revisions(session, payout.id)
        assert history[0].quantity == first_quantity
        assert history[0].total_amount_kopecks == first_total
        assert history[1].quantity == Decimal("4.000000")
        assert payout.quantity == Decimal("4.000000")
        assert payout.total_amount_kopecks == compute_applied_total_kopecks(
            Decimal("35.400000000"), Decimal("4.000000")
        )
    finally:
        session.close()
        database.engine.dispose()


def test_unique_constraint_rejects_raw_duplicate_insert(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, _second, instrument_id, snapshot_id = build_environment(session)
        create_payout(session, month_id, account_id, instrument_id, snapshot_id)
        session.add(
            AppliedProviderPayout(
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                source_position_snapshot_id=snapshot_id,
                provider="t_invest",
                provider_instrument_uid=BOND_UID,
                event_kind="coupon",
                identity_key="n:11",
                lifecycle="active",
                payment_date=date(2030, 8, 1),
                quantity=Decimal("1"),
                per_unit_amount="1",
                total_amount_kopecks=100,
                currency="RUB",
                amount_basis="provider_announced",
                is_approximate=True,
                first_applied_at=APPLIED_AT,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
    finally:
        session.rollback()
        session.close()
        database.engine.dispose()
