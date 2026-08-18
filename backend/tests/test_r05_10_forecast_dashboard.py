"""R05-10 integration coverage for C04 and dashboard payout projections."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.api.dashboard import dashboard_to_out
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType, RubleAmount
from hermes_finance.market_data.payout import PayoutEventKind
from hermes_finance.persistence import (
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    AppSettings,
    Base,
    ExpectedCashFlow,
    Goal,
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
from hermes_finance.services.dashboard import build_dashboard
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.forecast_passive_income import forecast_passive_income
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.monthly_summary import monthly_summary
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

APPLIED_AT = datetime(2030, 5, 12, 12, 0, tzinfo=UTC)
UID = "44444444-4444-4444-4444-444444444444"


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "r05-10.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def environment(session: Session) -> tuple[int, int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(
        session, name="Synthetic Brokerage", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
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


def provider_payout(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    snapshot_id: int,
    event_kind: PayoutEventKind,
    identity_key: str,
    per_unit_amount: str,
    payment_date: date = date(2030, 6, 15),
    is_approximate: bool = True,
):
    return create_applied_payout(
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
        fetched_at=APPLIED_AT,
        applied_at=APPLIED_AT,
        is_approximate=is_approximate,
    )


def manual_flow(
    session: Session,
    *,
    month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: ExpectedCashFlowType,
    amount: str,
    expected_date: date = date(2030, 6, 15),
):
    return create_expected_cash_flow(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=flow_type,
        expected_date=expected_date,
        gross_amount=amount,
        expected_tax_amount="0.00",
        expected_net_amount=amount,
        source="synthetic manual",
        source_as_of_date=date(2030, 5, 12),
        forecast_version="v1",
    )


def counts(session: Session) -> tuple[int, int, int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(ExpectedCashFlow)) or 0,
        session.scalar(select(func.count()).select_from(AppliedProviderPayout)) or 0,
        session.scalar(select(func.count()).select_from(AppliedPayoutReconciliation)) or 0,
        session.scalar(select(func.count()).select_from(AppSettings)) or 0,
        session.scalar(select(func.count()).select_from(Goal)) or 0,
    )


def test_provider_payouts_feed_c04_and_dashboard_without_recalculation(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = environment(session)
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.INTEREST,
            amount="20.00",
        )
        manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.OTHER,
            amount="30.00",
        )
        session.commit()
        coupon = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.COUPON,
            identity_key="n:11",
            per_unit_amount="25.00",
        )
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.DIVIDEND,
            identity_key="r:2030-07-05",
            per_unit_amount="10.00",
            payment_date=date(2030, 7, 5),
        )
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.REDEMPTION,
            identity_key="mty:1",
            per_unit_amount="1000.00",
            payment_date=date(2030, 8, 1),
        )
        session.commit()

        first = forecast_passive_income(session, month_id, "v1")
        assert first.breakdown.expected_coupon_net == RubleAmount(5_000)
        assert first.breakdown.expected_deposit_interest == RubleAmount(2_000)
        assert first.breakdown.other_expected_capital_income == RubleAmount(3_000)
        assert first.breakdown.expected_dividend_component == RubleAmount(0)
        assert first.annual_total == RubleAmount(10_000)
        assert first.is_approximate is True
        assert coupon.total_amount_kopecks == 5_000

        update_position_snapshot(session, snapshot_id, quantity="9.000000")
        second = forecast_passive_income(session, month_id, "v1")
        assert second.breakdown.expected_coupon_net == RubleAmount(5_000)
        assert second.annual_total == first.annual_total

        before = counts(session)
        dashboard = build_dashboard(session, month_id, forecast_version="v1")
        after = counts(session)
        assert after == before
        assert not session.new and not session.dirty and not session.deleted
        assert {(item.source_kind, item.flow_type) for item in dashboard.expected_payments} == {
            ("manual", "interest"),
            ("manual", "other"),
            ("provider", "coupon"),
            ("provider", "dividend"),
            ("provider", "redemption"),
        }
        provider_items = [
            item for item in dashboard.expected_payments if item.source_kind == "provider"
        ]
        assert all(
            item.gross_amount is None and item.expected_tax_amount is None
            for item in provider_items
        )
        redemption = next(item for item in provider_items if item.flow_type == "redemption")
        assert redemption.expected_net_amount == RubleAmount(200_000)
        assert dashboard.summary.forecast.breakdown.expected_coupon_net == RubleAmount(5_000)
        serialized = dashboard_to_out(dashboard).model_dump(mode="json")
        provider_api_items = {
            item["flow_type"]: item
            for item in serialized["expected_payments"]
            if item["source_kind"] == "provider"
        }
        assert set(provider_api_items) == {"coupon", "dividend", "redemption"}
        for item in provider_api_items.values():
            assert item["gross_amount"] is None
            assert item["expected_tax_amount"] is None
            assert item["provider"] == "t_invest"
            assert item["provider_identity_key"]
            assert item["provider_lifecycle"] == "active"
        manual_api_items = {
            item["flow_type"]: item
            for item in serialized["expected_payments"]
            if item["source_kind"] == "manual"
        }
        assert manual_api_items["interest"]["gross_amount"]["amount"] == "20.00"
        assert manual_api_items["interest"]["expected_tax_amount"]["amount"] == "0.00"

        close_reporting_month(session, month_id)
        closed = forecast_passive_income(session, month_id, "v1")
        assert closed.annual_total == second.annual_total
        before_closed_dashboard = counts(session)
        closed_dashboard = build_dashboard(session, month_id, forecast_version="v1")
        closed_serialized = dashboard_to_out(closed_dashboard).model_dump(mode="json")
        assert closed_dashboard.summary.forecast.annual_total == second.annual_total
        assert len(closed_serialized["expected_payments"]) == 5
        assert counts(session) == before_closed_dashboard
        assert not session.new and not session.dirty and not session.deleted
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("decision", "expected_coupon"),
    [
        (PayoutCountingDecision.KEEP_BOTH, 15_000),
        (PayoutCountingDecision.COUNT_MANUAL, 10_000),
        (PayoutCountingDecision.COUNT_PROVIDER, 5_000),
    ],
)
def test_c04_inherits_reconciliation_counting_decisions(
    tmp_path: Path, decision: PayoutCountingDecision, expected_coupon: int
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            amount="100.00",
        )
        session.commit()
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.COUPON,
            identity_key="n:11",
            per_unit_amount="25.00",
        )
        set_applied_payout_reconciliation(
            session,
            payout.id,
            expected_cash_flow_id=manual.id,
            counting_decision=decision,
        )
        session.commit()

        result = forecast_passive_income(session, month_id, "v1")
        assert result.breakdown.expected_coupon_net == RubleAmount(expected_coupon)
        assert counts(session) == (1, 1, 1, 0, 0)
    finally:
        session.close()
        database.engine.dispose()


def test_unresolved_duplicate_is_manual_only_for_c04_and_dashboard(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            amount="100.00",
        )
        session.commit()
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.COUPON,
            identity_key="n:11",
            per_unit_amount="25.00",
        )
        session.commit()

        result = forecast_passive_income(session, month_id, "v1")
        dashboard = build_dashboard(session, month_id, forecast_version="v1")
        assert result.breakdown.expected_coupon_net == RubleAmount(10_000)
        assert [(item.source_kind, item.id) for item in dashboard.expected_payments] == [
            ("manual", manual.id)
        ]
        assert dashboard.expected_payments[0].gross_amount == RubleAmount(10_000)
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
def test_cancelled_or_dismissed_provider_is_absent_from_c04_and_dashboard(
    tmp_path: Path,
    lifecycle: AppliedPayoutLifecycle,
    revision_kind: AppliedPayoutRevisionKind,
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = environment(session)
        manual = manual_flow(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type=ExpectedCashFlowType.COUPON,
            amount="100.00",
        )
        session.commit()
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.COUPON,
            identity_key="n:11",
            per_unit_amount="25.00",
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

        result = forecast_passive_income(session, month_id, "v1")
        dashboard = build_dashboard(session, month_id, forecast_version="v1")
        assert result.breakdown.expected_coupon_net == RubleAmount(0)
        assert dashboard.expected_payments == ()
    finally:
        session.close()
        database.engine.dispose()


def test_active_applied_payout_is_read_without_refresh_row(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = environment(session)
        payout = provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.COUPON,
            identity_key="n:11",
            per_unit_amount="25.00",
        )
        session.commit()

        result = forecast_passive_income(session, month_id, "v1")
        dashboard = build_dashboard(session, month_id, forecast_version="v1")
        assert result.breakdown.expected_coupon_net == RubleAmount(5_000)
        assert [(item.source_kind, item.id) for item in dashboard.expected_payments] == [
            ("provider", payout.id)
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_redemption_does_not_change_coverage_or_goal_metrics(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot_id = environment(session)
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.COUPON,
            identity_key="n:11",
            per_unit_amount="25.00",
        )
        session.commit()
        without_redemption = build_dashboard(session, month_id, forecast_version="v1")
        baseline_coverage = without_redemption.summary.coverage
        provider_payout(
            session,
            month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            snapshot_id=snapshot_id,
            event_kind=PayoutEventKind.REDEMPTION,
            identity_key="mty:1",
            per_unit_amount="1000.00",
            payment_date=date(2030, 8, 1),
        )
        session.commit()

        with_redemption = build_dashboard(session, month_id, forecast_version="v1")
        coverage = with_redemption.summary.coverage
        assert (
            with_redemption.summary.forecast.annual_total
            == without_redemption.summary.forecast.annual_total
        )
        assert coverage.forecast_monthly == baseline_coverage.forecast_monthly
        assert coverage.coverage_pct == baseline_coverage.coverage_pct
        assert coverage.goal_progress_pct == baseline_coverage.goal_progress_pct
        assert any(item.flow_type == "redemption" for item in with_redemption.expected_payments)
    finally:
        session.close()
        database.engine.dispose()


def test_read_paths_have_no_provider_or_mutation_calls() -> None:
    runtime_sources = (
        inspect.getsource(forecast_passive_income),
        inspect.getsource(monthly_summary),
        inspect.getsource(build_dashboard),
        inspect.getsource(merged_payout_calendar),
    )
    source = "\n".join(runtime_sources)
    forbidden = (
        "TInvest",
        "T-Invest",
        "httpx",
        "requests.",
        "fetch(",
        "TInvestPayoutProvider",
        "resolve_payout_provider",
        "session.commit(",
        "session.add(",
        "session.delete(",
        "session.flush(",
    )
    for marker in forbidden:
        assert marker not in source, marker
