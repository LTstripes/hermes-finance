"""Failure-path hardening for the R05-08 payout API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import PayoutEvent, PayoutEventKind, PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest, PayoutFetchResult
from hermes_finance.persistence import AppliedPayoutRevision, AppliedProviderPayout, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instrument_mappings import set_accepted_mapping
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

UID = "66666666-6666-4666-8666-666666666666"


class TogglePayoutProvider:
    def __init__(self) -> None:
        self.fail = False
        self.requests: list[PayoutFetchRequest] = []

    def fetch_payouts(self, request: PayoutFetchRequest) -> PayoutFetchResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("Authorization: Bearer raw-secret-must-not-leak")
        payment_date = date(2030, 6, 15)
        return PayoutFetchResult(
            provider=T_INVEST_PROVIDER,
            instrument_uid=request.instrument_uid,
            events=(
                PayoutEvent(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=request.instrument_uid,
                    event_kind=PayoutEventKind.COUPON,
                    identity_key="n:21",
                    status=PayoutEventStatus.OK,
                    payment_date=payment_date,
                    per_unit_amount=Decimal("12.50"),
                    currency="RUB",
                    source_method="GetBondCoupons",
                    provider_filter_basis="coupon_date",
                    provider_filter_date=payment_date,
                ),
            ),
        )


def _database(tmp_path: Path):
    database = create_database(tmp_path / "payout-api-hardening.db")
    Base.metadata.create_all(database.engine)
    return database


def _environment(session: Session, *, closed: bool = False) -> tuple[int, int, int, int]:
    month = create_reporting_month(
        session,
        year=2030,
        month=5,
        snapshot_date=date(2030, 5, 12),
    )
    account = create_account(
        session,
        name="Hardening Brokerage",
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
        quantity="4.000000",
        average_cost_per_unit="100.00",
        market_price_per_unit="101.00",
        price_date=date(2030, 5, 12),
    )
    set_accepted_mapping(
        session,
        instrument.id,
        provider=T_INVEST_PROVIDER,
        provider_instrument_id=UID,
    )
    if closed:
        close_reporting_month(session, month.id)
    return month.id, account.id, instrument.id, snapshot.id


def _context(account_id: int, instrument_id: int, snapshot_id: int) -> dict[str, object]:
    return {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "position_snapshot_id": snapshot_id,
        "forecast_version": "v1",
    }


def _selection(row: dict[str, object]) -> dict[str, object]:
    return {
        "provider": row["provider"],
        "instrument_uid": row["instrument_uid"],
        "event_kind": row["event_kind"],
        "identity_key": row["identity_key"],
        "fingerprint": row["fingerprint"],
    }


def _write_counts(session: Session) -> tuple[int, int]:
    return (
        session.scalar(select(func.count()).select_from(AppliedProviderPayout)) or 0,
        session.scalar(select(func.count()).select_from(AppliedPayoutRevision)) or 0,
    )


def test_app_startup_and_health_do_not_fetch_payouts(tmp_path: Path) -> None:
    database = _database(tmp_path)
    provider = TogglePayoutProvider()
    try:
        with TestClient(create_app(database, payout_provider=provider)) as client:
            assert provider.requests == []
            response = client.get("/api/health")
            assert response.status_code == 200
            assert provider.requests == []
    finally:
        database.engine.dispose()


def test_closed_month_apply_stops_before_refetch_and_writes_nothing(tmp_path: Path) -> None:
    database = _database(tmp_path)
    provider = TogglePayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = _environment(session, closed=True)

        app = create_app(database, payout_provider=provider)
        with TestClient(app) as client:
            preview = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=_context(account_id, instrument_id, snapshot_id),
            )
            assert preview.status_code == 200, preview.text
            [row] = preview.json()["rows"]
            assert len(provider.requests) == 1

            response = client.post(
                f"/api/months/{month_id}/payout-apply",
                json={
                    **_context(account_id, instrument_id, snapshot_id),
                    "rows": [_selection(row)],
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["success"] is False
        assert response.json()["error_code"] == "closed_month"
        assert response.json()["message"] == (
            "closed reporting month must be reopened before payout apply"
        )
        assert len(provider.requests) == 1
        with database.session_factory() as session:
            assert _write_counts(session) == (0, 0)
    finally:
        database.engine.dispose()


def test_apply_provider_exception_is_sanitized_and_writes_nothing(tmp_path: Path) -> None:
    database = _database(tmp_path)
    provider = TogglePayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = _environment(session)

        app = create_app(database, payout_provider=provider)
        with TestClient(app) as client:
            preview = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=_context(account_id, instrument_id, snapshot_id),
            )
            assert preview.status_code == 200, preview.text
            [row] = preview.json()["rows"]

            provider.fail = True
            response = client.post(
                f"/api/months/{month_id}/payout-apply",
                json={
                    **_context(account_id, instrument_id, snapshot_id),
                    "rows": [_selection(row)],
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["success"] is False
        assert response.json()["error_code"] == "provider_error"
        assert response.json()["message"] == "payout provider refresh failed"
        assert "raw-secret" not in response.text
        assert "Authorization" not in response.text
        assert len(provider.requests) == 2
        with database.session_factory() as session:
            assert _write_counts(session) == (0, 0)
    finally:
        database.engine.dispose()
