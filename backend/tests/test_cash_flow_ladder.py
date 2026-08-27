"""R07-05 treasury ladder read-model tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.persistence import Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.applied_payouts import (
    PayoutCountingDecision,
    create_applied_payout,
    set_applied_payout_reconciliation,
)
from hermes_finance.services.cash_flow_ladder import (
    CashFlowLadderSource,
    build_cash_flow_ladder,
)
from hermes_finance.services.deposits import create_deposit_snapshot
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

APPLIED_AT = datetime(2030, 5, 12, 12, 0, tzinfo=UTC)
UID = "44444444-4444-4444-4444-444444444444"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "cash-flow-ladder.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(session: Session) -> tuple[int, int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
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
        quantity="2.000000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    return month.id, account.id, instrument.id, snapshot.id


def expected_flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: ExpectedCashFlowType,
    expected_date: date,
    amount: str,
) -> object:
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        expected_date=expected_date,
        gross_amount=amount,
        source="synthetic owner forecast",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )


def test_ladder_has_twelve_months_and_keeps_redemption_out_of_passive_income(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, _ = build_environment(session)
        deposit = create_deposit_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            name="Synthetic deposit",
            deposit_type="deposit",
            balance="120000.00",
            annual_rate="12.00",
        )
        expected_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2030, 5, 13),
            amount="100.00",
        )
        expected_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.REDEMPTION,
            expected_date=date(2030, 7, 1),
            amount="10000.00",
        )

        result = build_cash_flow_ladder(session, month_id)

        assert len(result.months) == 12
        assert [(item.year, item.month) for item in result.months] == [
            (2030, month) for month in range(5, 13)
        ] + [(2031, month) for month in range(1, 5)]
        may = result.months[0]
        july = result.months[2]
        assert may.coupon.kopecks == 10_000
        assert may.deposit_interest.kopecks == deposit.expected_monthly_interest_kopecks
        assert july.redemption_principal.kopecks == 1_000_000
        assert july.passive_income.kopecks == deposit.expected_monthly_interest_kopecks
        assert july.total_cash_flow.kopecks == 1_000_000 + deposit.expected_monthly_interest_kopecks
        assert all(month.is_approximate for month in result.months)
        assert result.upcoming_14_days.items[0].source_kind is CashFlowLadderSource.DEPOSIT_FORECAST
        assert any("приблизительная" in warning for warning in result.warnings)
    finally:
        session.close()
        database.engine.dispose()


def test_ladder_reuses_duplicate_resolution_and_exposes_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        manual = expected_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            expected_date=date(2030, 6, 15),
            amount="100.00",
        )
        provider = create_applied_payout(
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
            per_unit_amount="50.00",
            currency="RUB",
            provider_status=None,
            fetched_at=APPLIED_AT,
            applied_at=APPLIED_AT,
        )
        session.commit()

        unresolved = build_cash_flow_ladder(session, month_id)
        assert [(event.source_kind, event.source_id) for event in unresolved.months[1].items] == [
            (CashFlowLadderSource.MANUAL, manual.id)
        ]

        set_applied_payout_reconciliation(
            session,
            provider.id,
            expected_cash_flow_id=manual.id,
            counting_decision=PayoutCountingDecision.KEEP_BOTH,
        )
        session.commit()
        resolved = build_cash_flow_ladder(session, month_id)
        june = resolved.months[1]
        assert june.coupon.kopecks == 20_000
        assert {event.source_kind for event in june.items} == {
            CashFlowLadderSource.MANUAL,
            CashFlowLadderSource.PROVIDER,
        }
        provider_event = next(
            event for event in june.items if event.source_kind is CashFlowLadderSource.PROVIDER
        )
        assert provider_event.provider_identity_key == "n:11"
        assert provider_event.reconciliation_id is not None
        assert provider_event.counting_decision == PayoutCountingDecision.KEEP_BOTH.value
    finally:
        session.close()
        database.engine.dispose()
