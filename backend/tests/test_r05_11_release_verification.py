"""R05-11 release verification: 0.4-era upgrade and payout network boundary."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
from _migration_helpers import PREVIOUS_REVISION, REVISION, revision_rows, run_alembic
from _network_helpers import ForbiddenTransport
from _release_helpers import (
    STARTUP_GUARD_SCRIPT,
    manual_flow_fingerprint,
    position_fingerprint,
    run_isolated_startup_script,
)
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import func, select
from t_invest_mapping_fixtures import accept_t_invest_mapping

from hermes_finance import __version__
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest, PayoutFetchResult
from hermes_finance.persistence import (
    AppliedPayoutRevision,
    AppliedProviderPayout,
    Base,
    ExpectedCashFlow,
    InvestmentCashFlow,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month
from hermes_finance.settings import Settings

UID = "77777777-7777-4777-8777-777777777777"


class RecordingPayoutProvider:
    def __init__(self) -> None:
        self.requests: list[PayoutFetchRequest] = []

    def fetch_payouts(self, request: PayoutFetchRequest) -> PayoutFetchResult:
        self.requests.append(request)
        payment = date(2030, 6, 15)
        return PayoutFetchResult(
            provider=T_INVEST_PROVIDER,
            instrument_uid=request.instrument_uid,
            events=(
                PayoutEvent(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=request.instrument_uid,
                    event_kind=PayoutEventKind.COUPON,
                    identity_key="n:31",
                    status=PayoutEventStatus.OK,
                    payment_date=payment,
                    per_unit_amount=Decimal("12.50"),
                    currency="RUB",
                    source_method="GetBondCoupons",
                    provider_filter_basis="coupon_date",
                    provider_filter_date=payment,
                ),
            ),
        )


def test_pre_05_schema_upgrades_without_rewriting_owner_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "pre-05.db"
    upgraded = run_alembic(database_path, "upgrade", PREVIOUS_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    assert revision_rows(database_path) == [PREVIOUS_REVISION]

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO reporting_months "
            "(year, month, period_start, period_end, snapshot_date, status, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                2031,
                5,
                "2031-05-01",
                "2031-05-31",
                "2031-05-31",
                "draft",
                "manual",
                "2031-05-31 00:00:00",
                "2031-05-31 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO accounts "
            "(name, account_type, status, include_in_capital, include_in_returns) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Broker", "brokerage", "active", 1, 1),
        )
        connection.execute(
            "INSERT INTO instruments "
            "(name, instrument_type, currency, is_active, manual_price_allowed) "
            "VALUES (?, ?, ?, ?, ?)",
            ("Synthetic Bond", "bond", "RUB", 1, 1),
        )
        connection.execute(
            "INSERT INTO position_snapshots "
            "(reporting_month_id, account_id, instrument_id, quantity, "
            "average_cost_per_unit_kopecks, market_price_per_unit_kopecks, "
            "market_value_kopecks, cost_basis_kopecks, unrealized_result_kopecks, "
            "price_date, price_source, manual_adjustment, notes, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "4.000000",
                10_000,
                11_000,
                44_000,
                40_000,
                4_000,
                "2031-05-15",
                "manual",
                0,
                "pre-0.5 snapshot",
                "2031-05-15 00:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO expected_cash_flows "
            "(reporting_month_id, account_id, instrument_id, flow_type, expected_date, "
            "gross_amount_kopecks, expected_tax_amount_kopecks, expected_net_amount_kopecks, "
            "currency, source, source_as_of_date, forecast_version, is_confirmed, "
            "is_approximate, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                "coupon",
                "2031-06-15",
                80_000,
                0,
                80_000,
                "RUB",
                "owner manual",
                "2031-05-31",
                "v1",
                0,
                0,
                "keep this row",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    before_positions = position_fingerprint(database_path)
    before_flows = manual_flow_fingerprint(database_path)

    migrated = run_alembic(database_path, "upgrade", "head")
    assert migrated.returncode == 0, migrated.stderr
    assert revision_rows(database_path) == [REVISION]
    assert position_fingerprint(database_path) == before_positions
    assert manual_flow_fingerprint(database_path) == before_flows

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "applied_provider_payouts" in tables
        assert "applied_payout_revisions" in tables
        assert "applied_payout_reconciliations" in tables
        assert connection.execute("SELECT COUNT(*) FROM applied_provider_payouts").fetchone() == (
            0,
        )
        assert connection.execute("SELECT COUNT(*) FROM investment_cash_flows").fetchone() == (0,)
    finally:
        connection.close()


# Canonical current-release health gate; the equivalent R06-10 node was removed
# after exact node-level comparison proved it was a duplicate.
def test_health_version_is_current_release() -> None:
    from hermes_finance.main import app

    assert __version__ == "0.8.2"
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.8.2"}


def test_startup_and_page_reads_stay_offline(tmp_path: Path) -> None:
    database_path = tmp_path / "r05-11-startup.db"
    probed = run_isolated_startup_script("probe", str(database_path))
    assert probed.returncode == 0, probed.stdout + probed.stderr
    assert "ok" in probed.stdout
    assert STARTUP_GUARD_SCRIPT.is_file()


def test_missing_token_preview_is_sanitized_and_offline(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", raising=False)
    database = create_database(tmp_path / "r05-11-token.db")
    Base.metadata.create_all(database.engine)
    application = create_app(database)
    application.state.settings = Settings(_env_file=None)
    application.state.t_invest_http_client = httpx2.Client(transport=ForbiddenTransport())
    try:
        with database.session_factory() as session:
            month = create_reporting_month(
                session, year=2030, month=5, snapshot_date=date(2030, 5, 12)
            )
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
            accept_t_invest_mapping(session, instrument.id, UID, kind=InstrumentType.BOND)
            month_id = month.id
            payload = {
                "account_id": account.id,
                "instrument_id": instrument.id,
                "position_snapshot_id": snapshot.id,
                "forecast_version": "v1",
            }
        with TestClient(application) as client:
            preview = client.post(f"/api/months/{month_id}/payout-preview", json=payload)
        assert preview.status_code == 200, preview.text
        body = preview.json()
        messages = " ".join(str(row.get("message") or "") for row in body["rows"]).lower()
        assert "token" in messages or any(
            row.get("status") in {"unavailable", "error"} for row in body["rows"]
        )
        assert "bearer" not in preview.text.lower()
        assert "authorization" not in preview.text.lower()
        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(AppliedProviderPayout)) == 0
            assert session.scalar(select(func.count()).select_from(ExpectedCashFlow)) == 0
    finally:
        database.engine.dispose()


def test_preview_is_first_network_and_reads_stay_local_after_apply(tmp_path: Path) -> None:
    database = create_database(tmp_path / "r05-11-flow.db")
    Base.metadata.create_all(database.engine)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month = create_reporting_month(
                session, year=2030, month=5, snapshot_date=date(2030, 5, 12)
            )
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
            accept_t_invest_mapping(session, instrument.id, UID, kind=InstrumentType.BOND)
            manual = create_expected_cash_flow(
                session,
                reporting_month_id=month.id,
                account_id=account.id,
                instrument_id=instrument.id,
                flow_type=ExpectedCashFlowType.COUPON,
                expected_date=date(2030, 7, 15),
                gross_amount="10.00",
                expected_tax_amount="0.00",
                expected_net_amount="10.00",
                source="owner manual",
                source_as_of_date=date(2030, 5, 12),
                forecast_version="v1",
            )
            month_id = month.id
            snapshot_id = snapshot.id
            context = {
                "account_id": account.id,
                "instrument_id": instrument.id,
                "position_snapshot_id": snapshot.id,
                "forecast_version": "v1",
            }
            manual_id = manual.id
            manual_net = manual.expected_net_amount_kopecks

        app = create_app(database, payout_provider=provider)
        with TestClient(app) as client:
            assert provider.requests == []
            health = client.get("/api/health")
            months = client.get("/api/months")
            dashboard = client.get(f"/api/months/{month_id}/dashboard")
            calendar = client.get(
                "/api/payouts/calendar",
                params={"month_id": month_id, "forecast_version": "v1"},
            )
            assert health.status_code == 200
            assert health.json()["version"] == "0.8.2"
            assert months.status_code == 200
            assert dashboard.status_code == 200
            assert calendar.status_code == 200
            assert provider.requests == []

            preview = client.post(f"/api/months/{month_id}/payout-preview", json=context)
            assert preview.status_code == 200, preview.text
            assert len(provider.requests) == 1
            [row] = preview.json()["rows"]
            applied = client.post(
                f"/api/months/{month_id}/payout-apply",
                json={
                    **context,
                    "rows": [
                        {
                            "provider": row["provider"],
                            "instrument_uid": row["instrument_uid"],
                            "event_kind": row["event_kind"],
                            "identity_key": row["identity_key"],
                            "fingerprint": row["fingerprint"],
                        }
                    ],
                },
            )
            assert applied.status_code == 200, applied.text
            assert applied.json()["success"] is True
            after_apply = len(provider.requests)
            assert after_apply >= 2

            reread_dashboard = client.get(f"/api/months/{month_id}/dashboard")
            reread_months = client.get("/api/months")
            reread_calendar = client.get(
                "/api/payouts/calendar",
                params={"month_id": month_id, "forecast_version": "v1"},
            )
            assert reread_dashboard.status_code == 200
            assert reread_months.status_code == 200
            assert reread_calendar.status_code == 200
            assert len(provider.requests) == after_apply

        with database.session_factory() as session:
            kept = session.get(ExpectedCashFlow, manual_id)
            assert kept is not None
            assert kept.expected_net_amount_kopecks == manual_net
            assert kept.source == "owner manual"
            payout = session.scalar(select(AppliedProviderPayout))
            assert payout is not None
            assert payout.quantity == Decimal("2.000000")
            assert payout.source_position_snapshot_id == snapshot_id
            assert session.scalar(select(func.count()).select_from(AppliedPayoutRevision)) == 1
            assert session.scalar(select(func.count()).select_from(InvestmentCashFlow)) == 0
    finally:
        database.engine.dispose()
