"""R05-08 payout preview/apply/calendar API integration tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from t_invest_mapping_fixtures import accept_t_invest_mapping

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, ExpectedCashFlowType, InstrumentType
from hermes_finance.main import create_app
from hermes_finance.market_data.dto import T_INVEST_PROVIDER
from hermes_finance.market_data.payout import (
    PayoutEvent,
    PayoutEventKind,
    PayoutEventStatus,
)
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest, PayoutFetchResult
from hermes_finance.persistence import AppliedPayoutRevision, AppliedProviderPayout, Base
from hermes_finance.services.accounts import create_account
from hermes_finance.services.expected_cash_flows import create_expected_cash_flow
from hermes_finance.services.instrument_mappings import (
    exclude_instrument_mapping,
    set_accepted_mapping,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot, update_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

UID = "44444444-4444-4444-4444-444444444444"
OTHER_UID = "55555555-5555-5555-5555-555555555555"


class RecordingPayoutProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[PayoutFetchRequest] = []

    def fetch_payouts(self, request: PayoutFetchRequest) -> PayoutFetchResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("TOKEN=super-secret must never reach the browser")
        payment = date(2030, 6, 15)
        return PayoutFetchResult(
            provider=T_INVEST_PROVIDER,
            instrument_uid=request.instrument_uid,
            events=(
                PayoutEvent(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=request.instrument_uid,
                    event_kind=PayoutEventKind.COUPON,
                    identity_key="n:11",
                    status=PayoutEventStatus.OK,
                    payment_date=payment,
                    per_unit_amount=Decimal("25.00"),
                    currency="RUB",
                    source_method="GetBondCoupons",
                    provider_filter_basis="coupon_date",
                    provider_filter_date=payment,
                ),
            ),
        )


def database_for(tmp_path: Path):
    database = create_database(tmp_path / "payout-api.db")
    Base.metadata.create_all(database.engine)
    return database


def build_environment(
    session: Session,
    *,
    mapping: str = "t_invest",
    close_month: bool = False,
    instrument_type: InstrumentType = InstrumentType.BOND,
) -> tuple[int, int, int, int]:
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
        name="Synthetic Instrument",
        instrument_type=instrument_type,
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
    if mapping == "t_invest":
        accept_t_invest_mapping(session, instrument.id, UID, kind=instrument_type)
    elif mapping == "excluded":
        exclude_instrument_mapping(session, instrument.id)
    elif mapping == "moex":
        set_accepted_mapping(
            session,
            instrument.id,
            provider="moex_iss",
            provider_instrument_id="sber",
            provider_venue_id="stock/shares/tqbr",
        )
    elif mapping != "unmapped":
        raise AssertionError(f"unknown test mapping: {mapping}")
    if close_month:
        close_reporting_month(session, month.id)
    return month.id, account.id, instrument.id, snapshot.id


def context_payload(account_id: int, instrument_id: int, snapshot_id: int) -> dict[str, object]:
    return {
        "account_id": account_id,
        "instrument_id": instrument_id,
        "position_snapshot_id": snapshot_id,
        "forecast_version": "v1",
    }


def test_preview_uses_local_mapping_exact_horizon_and_reads_closed_month(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(
                session, close_month=True
            )
        with TestClient(create_app(database, payout_provider=provider)) as client:
            response = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            )
        assert response.status_code == 200, response.text
        assert len(provider.requests) == 1
        request = provider.requests[0]
        assert request.instrument_uid == UID
        assert request.calendar_from == date(2030, 5, 12)
        assert request.calendar_to == date(2031, 5, 11)

        body = response.json()
        assert body["provider"] == T_INVEST_PROVIDER
        assert body["instrument_uid"] == UID
        assert Decimal(body["quantity"]) == Decimal("2")
        [row] = body["rows"]
        assert row["status"] == "new"
        assert row["event_kind"] == "coupon"
        assert row["identity_key"] == "n:11"
        assert row["per_unit_amount"] == "25.00"
        assert row["total_amount"] == {"amount": "50.00", "currency": "RUB"}
        assert row["selectable"] is True
        assert row["default_selected"] is True
        assert row["fingerprint"]
    finally:
        database.engine.dispose()


@pytest.mark.parametrize(
    ("mapping", "instrument_type", "message"),
    [
        ("unmapped", InstrumentType.BOND, "no accepted payout provider mapping"),
        ("excluded", InstrumentType.BOND, "excluded from provider payout refresh"),
        ("moex", InstrumentType.STOCK, "requires an accepted t_invest mapping"),
    ],
)
def test_invalid_local_mapping_fails_before_provider_call(
    tmp_path: Path,
    mapping: str,
    instrument_type: InstrumentType,
    message: str,
) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(
                session,
                mapping=mapping,
                instrument_type=instrument_type,
            )
        with TestClient(create_app(database, payout_provider=provider)) as client:
            response = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            )
        assert response.status_code == 422
        body = response.json()["error"]
        assert body["code"] == "payout_mapping_required"
        assert message in body["message"]
        assert provider.requests == []
    finally:
        database.engine.dispose()


def test_batch_preview_checks_mapped_positions_sequentially_and_reports_skips(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, _ = build_environment(session)
            second = create_instrument(
                session, name="Second Synthetic Bond", instrument_type=InstrumentType.BOND
            )
            second_snapshot = create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=second.id,
                quantity="3",
                average_cost_per_unit="100.00",
                market_price_per_unit="101.00",
                price_date=date(2030, 5, 12),
            )
            accept_t_invest_mapping(session, second.id, OTHER_UID, kind=InstrumentType.BOND)
            unmapped = create_instrument(
                session, name="Unmapped Synthetic Bond", instrument_type=InstrumentType.BOND
            )
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=unmapped.id,
                quantity="1",
                average_cost_per_unit="100.00",
                market_price_per_unit="101.00",
                price_date=date(2030, 5, 12),
            )
            excluded = create_instrument(
                session, name="Excluded Synthetic Bond", instrument_type=InstrumentType.BOND
            )
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=excluded.id,
                quantity="1",
                average_cost_per_unit="100.00",
                market_price_per_unit="101.00",
                price_date=date(2030, 5, 12),
            )
            exclude_instrument_mapping(session, excluded.id)

        with TestClient(create_app(database, payout_provider=provider)) as client:
            response = client.post(
                f"/api/months/{month_id}/payout-batch-preview",
                json={"forecast_version": "v1"},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["summary"] == {
            "total_positions": 4,
            "eligible_positions": 2,
            "with_events": 2,
            "without_events": 0,
            "errors": 0,
            "skipped": 2,
        }
        assert [request.instrument_uid for request in provider.requests] == [UID, OTHER_UID]
        assert [item["status"] for item in body["items"]] == [
            "previewed",
            "previewed",
            "skipped",
            "skipped",
        ]
        assert body["items"][1]["position_snapshot_id"] == second_snapshot.id
    finally:
        database.engine.dispose()


def test_refresh_status_is_local_and_clears_after_explicit_apply(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        with TestClient(create_app(database, payout_provider=provider)) as client:
            preview = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            ).json()
            row = preview["rows"][0]
            applied = client.post(
                f"/api/months/{month_id}/payout-apply",
                json={
                    **context_payload(account_id, instrument_id, snapshot_id),
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
            before = client.get(f"/api/months/{month_id}/payout-refresh-status")
            with database.session_factory() as session:
                update_position_snapshot(session, snapshot_id, quantity="3")
            after = client.get(f"/api/months/{month_id}/payout-refresh-status")

        assert before.status_code == 200
        assert before.json()["positions_changed"] == 0
        assert after.status_code == 200
        assert after.json()["positions_changed"] == 1
        assert Decimal(after.json()["items"][0]["current_quantity"]) == Decimal("3")
        assert Decimal(after.json()["items"][0]["frozen_quantity"]) == Decimal("2")
        assert len(provider.requests) == 2
    finally:
        database.engine.dispose()


def test_preview_provider_exception_is_sanitized(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider(fail=True)
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        with TestClient(create_app(database, payout_provider=provider)) as client:
            response = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            )
        assert response.status_code == 200, response.text
        [row] = response.json()["rows"]
        assert row["status"] == "error"
        assert row["message"] == "Payout provider refresh failed"
        assert "super-secret" not in response.text
        assert "TOKEN=" not in response.text
    finally:
        database.engine.dispose()


def test_apply_rejects_browser_uid_substitution_before_refetch(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(session)
        app = create_app(database, payout_provider=provider)
        with TestClient(app) as client:
            preview = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            ).json()
            row = preview["rows"][0]
            payload = {
                **context_payload(account_id, instrument_id, snapshot_id),
                "rows": [
                    {
                        "provider": T_INVEST_PROVIDER,
                        "instrument_uid": OTHER_UID,
                        "event_kind": row["event_kind"],
                        "identity_key": row["identity_key"],
                        "fingerprint": row["fingerprint"],
                    }
                ],
            }
            response = client.post(f"/api/months/{month_id}/payout-apply", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["message"] == (
            "selected payout identity does not match the accepted local mapping"
        )
        assert len(provider.requests) == 1
    finally:
        database.engine.dispose()


def test_apply_success_stale_preview_guard_and_new_vs_legacy_calendar(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(session)
            create_expected_cash_flow(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                flow_type=ExpectedCashFlowType.INTEREST,
                expected_date=date(2030, 6, 1),
                gross_amount="10.00",
                expected_tax_amount=None,
                expected_net_amount=None,
                source="owner manual",
                source_as_of_date=date(2030, 5, 12),
                forecast_version="v1",
            )

        app = create_app(database, payout_provider=provider)
        with TestClient(app) as client:
            preview_response = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            )
            assert preview_response.status_code == 200, preview_response.text
            row = preview_response.json()["rows"][0]
            apply_payload = {
                **context_payload(account_id, instrument_id, snapshot_id),
                "rows": [
                    {
                        "provider": row["provider"],
                        "instrument_uid": row["instrument_uid"],
                        "event_kind": row["event_kind"],
                        "identity_key": row["identity_key"],
                        "fingerprint": row["fingerprint"],
                    }
                ],
            }
            applied = client.post(
                f"/api/months/{month_id}/payout-apply",
                json=apply_payload,
            )
            assert applied.status_code == 200, applied.text
            body = applied.json()
            assert body["success"] is True
            assert body["selected_count"] == 1
            [item] = body["items"]
            assert item["revision_kind"] == "apply"
            assert item["total_amount"] == {"amount": "50.00", "currency": "RUB"}
            assert body["error_code"] is None

            stale = client.post(
                f"/api/months/{month_id}/payout-apply",
                json=apply_payload,
            )
            assert stale.status_code == 200, stale.text
            assert stale.json()["success"] is False
            assert stale.json()["error_code"] == "preview_changed"

            merged = client.get(
                "/api/payouts/calendar",
                params={"month_id": month_id, "forecast_version": "v1"},
            )
            legacy = client.get(
                "/api/expected-flows/calendar",
                params={"month_id": month_id, "forecast_version": "v1"},
            )

        assert len(provider.requests) == 3
        assert merged.status_code == 200, merged.text
        [june] = merged.json()
        assert june["coupon"] == {"amount": "50.00", "currency": "RUB"}
        assert june["interest"] == {"amount": "10.00", "currency": "RUB"}
        assert june["total_net"] == {"amount": "60.00", "currency": "RUB"}
        assert {item["source_kind"] for item in june["items"]} == {"manual", "provider"}
        provider_item = next(item for item in june["items"] if item["source_kind"] == "provider")
        assert provider_item["provider"] == T_INVEST_PROVIDER
        assert provider_item["provider_instrument_uid"] == UID
        assert provider_item["provider_identity_key"] == "n:11"
        assert provider_item["provider_lifecycle"] == "active"

        assert legacy.status_code == 200, legacy.text
        [legacy_june] = legacy.json()
        assert legacy_june["coupon"] == {"amount": "0.00", "currency": "RUB"}
        assert legacy_june["interest"] == {"amount": "10.00", "currency": "RUB"}
        assert len(legacy_june["items"]) == 1

        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(AppliedProviderPayout)) == 1
            assert session.scalar(select(func.count()).select_from(AppliedPayoutRevision)) == 1
    finally:
        database.engine.dispose()


def test_duplicate_apply_requires_and_persists_explicit_counting_decision(tmp_path: Path) -> None:
    database = database_for(tmp_path)
    provider = RecordingPayoutProvider()
    try:
        with database.session_factory() as session:
            month_id, account_id, instrument_id, snapshot_id = build_environment(session)
            manual = create_expected_cash_flow(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                flow_type=ExpectedCashFlowType.COUPON,
                expected_date=date(2030, 6, 15),
                gross_amount="100.00",
                expected_tax_amount=None,
                expected_net_amount=None,
                source="owner manual",
                source_as_of_date=date(2030, 5, 12),
                forecast_version="v1",
            )

        with TestClient(create_app(database, payout_provider=provider)) as client:
            preview = client.post(
                f"/api/months/{month_id}/payout-preview",
                json=context_payload(account_id, instrument_id, snapshot_id),
            ).json()
            [row] = preview["rows"]
            assert row["status"] == "possible_manual_duplicate"
            assert row["manual_candidate_ids"] == [manual.id]

            base_selection = {
                "provider": row["provider"],
                "instrument_uid": row["instrument_uid"],
                "event_kind": row["event_kind"],
                "identity_key": row["identity_key"],
                "fingerprint": row["fingerprint"],
            }
            missing_decision = client.post(
                f"/api/months/{month_id}/payout-apply",
                json={
                    **context_payload(account_id, instrument_id, snapshot_id),
                    "rows": [base_selection],
                },
            )
            assert missing_decision.status_code == 200
            assert missing_decision.json()["error_code"] == "validation_error"

            applied = client.post(
                f"/api/months/{month_id}/payout-apply",
                json={
                    **context_payload(account_id, instrument_id, snapshot_id),
                    "rows": [
                        {
                            **base_selection,
                            "manual_duplicate_decision": {
                                "expected_cash_flow_id": manual.id,
                                "counting_decision": "count_manual",
                            },
                        }
                    ],
                },
            )
            assert applied.status_code == 200, applied.text
            body = applied.json()
            assert body["success"] is True
            [item] = body["items"]
            assert item["counting_decision"] == "count_manual"
            assert item["expected_cash_flow_id"] == manual.id
            assert item["reconciliation_id"] is not None

            [june] = client.get(
                "/api/payouts/calendar",
                params={"month_id": month_id, "forecast_version": "v1"},
            ).json()
            assert june["total_net"] == {"amount": "100.00", "currency": "RUB"}
            assert [item["source_kind"] for item in june["items"]] == ["manual"]
    finally:
        database.engine.dispose()
