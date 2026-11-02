"""ADR 0016 Slice A: persistent provider-neutral broker identity registry."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, BrokerIdentityMapping, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import (
    BrokerIdentityMappingConflictError,
    BrokerIdentitySubjectKind,
    confirm_mapping,
    list_effective_mappings,
    remap_mapping,
    revoke_mapping,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

SYN_PROVIDER = "synthetic_broker"

SYN_ACCOUNT = "SYN-ACCOUNT-001"
SYN_ACCOUNT_B = "SYN-ACCOUNT-002"
SYN_INSTRUMENT = "SYN-INSTRUMENT-001"
SYN_INSTRUMENT_B = "SYN-INSTRUMENT-002"
SYN_ISIN = "SYN000000001"
SYN_ISIN_B = "SYN000000002"
SYN_ISIN_OTHER = "SYN000000099"


def _context(tmp_path: Path, *, second_instrument: bool = False):
    database = create_database(tmp_path / "broker-identity.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=date(2026, 8, 31))
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session,
        name="Synthetic equity",
        instrument_type=InstrumentType.STOCK,
        isin=SYN_ISIN,
    )
    extra = None
    if second_instrument:
        extra = create_instrument(
            session,
            name="Synthetic equity B",
            instrument_type=InstrumentType.STOCK,
            isin=SYN_ISIN_B,
        )
    session.commit()
    ids = {
        "month_id": month.id,
        "account_id": account.id,
        "instrument_id": instrument.id,
        "instrument_b_id": extra.id if extra is not None else None,
    }
    session.close()
    return database, ids


def test_first_confirmation_persists_effective_rows(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    account_row = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    instrument_row = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
        observed_isin=SYN_ISIN,
    )
    assert account_row.status == "effective"
    assert instrument_row.status == "effective"
    assert instrument_row.observed_isin == SYN_ISIN
    again = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    assert again.id == account_row.id
    mapping_count = session.scalar(select(func.count()).select_from(BrokerIdentityMapping))
    assert mapping_count == 2
    session.close()


def test_confirm_conflict_and_instrument_reverse_uniqueness(tmp_path: Path) -> None:
    database, ids = _context(tmp_path, second_instrument=True)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    try:
        confirm_mapping(
            session,
            provider=SYN_PROVIDER,
            subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
            provider_identity=SYN_ACCOUNT,
            hermes_target_id=ids["account_id"] + 999,
        )
        raise AssertionError("conflicting account confirm must fail closed")
    except BrokerIdentityMappingConflictError:
        pass
    confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
    )
    try:
        confirm_mapping(
            session,
            provider=SYN_PROVIDER,
            subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
            provider_identity=SYN_INSTRUMENT_B,
            hermes_target_id=ids["instrument_id"],
        )
        raise AssertionError("reverse instrument uniqueness must fail closed")
    except BrokerIdentityMappingConflictError:
        pass
    session.close()


def test_revoke_and_remap_leave_history_and_do_not_rewrite_positions(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    instrument_b = create_instrument(
        session,
        name="Synthetic equity without ISIN",
        instrument_type=InstrumentType.STOCK,
    )
    session.commit()
    ids["instrument_b_id"] = instrument_b.id
    position = create_position_snapshot(
        session,
        reporting_month_id=ids["month_id"],
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
        quantity="10",
        average_cost_per_unit="99.50",
        market_price_per_unit="100",
        price_date=date(2026, 8, 31),
        price_source=PriceSource.MANUAL,
    )
    session.commit()
    position_id = position.id
    original_qty = position.quantity
    account_row = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    instrument_row = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
    )
    revoked = revoke_mapping(session, account_row.id, reason="owner correction")
    assert revoked.status == "revoked"
    remapped = remap_mapping(
        session,
        instrument_row.id,
        hermes_target_id=ids["instrument_b_id"],
    )
    assert remapped.status == "effective"
    assert remapped.hermes_target_id == ids["instrument_b_id"]
    assert remapped.predecessor_mapping_id == instrument_row.id
    session.refresh(instrument_row)
    assert instrument_row.status == "superseded"
    assert instrument_row.successor_mapping_id == remapped.id
    stored = session.get(PositionSnapshot, position_id)
    assert stored is not None
    assert stored.quantity == original_qty
    assert stored.instrument_id == ids["instrument_id"]
    session.close()

    application = create_app(database)
    with TestClient(application) as client:
        listed = client.get("/api/broker-identity-mappings", params={"provider": SYN_PROVIDER})
    statuses = {row["mapping_id"]: row["status"] for row in listed.json()}
    assert statuses[instrument_row.id] == "superseded"
    assert statuses[remapped.id] == "effective"


def test_confirm_api_rejects_isin_conflict_without_writing(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    application = create_app(database)
    with TestClient(application) as client:
        response = client.post(
            "/api/broker-identity-mappings",
            json={
                "provider": SYN_PROVIDER,
                "subject_kind": "instrument",
                "provider_identity": SYN_INSTRUMENT,
                "hermes_target_id": ids["instrument_id"],
                "observed_isin": SYN_ISIN_OTHER,
            },
        )
    assert response.status_code == 409, response.text
    session = database.session_factory()
    assert list_effective_mappings(session, provider=SYN_PROVIDER) == []
    session.close()


def test_same_pair_confirm_rejects_contradictory_isin(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    original = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
        observed_isin=SYN_ISIN,
    )
    original_id = original.id
    original_confirmed_at = original.confirmed_at
    try:
        confirm_mapping(
            session,
            provider=SYN_PROVIDER,
            subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
            provider_identity=SYN_INSTRUMENT,
            hermes_target_id=ids["instrument_id"],
            observed_isin=SYN_ISIN_OTHER,
        )
        raise AssertionError("same-pair confirm with contradictory ISIN must fail closed")
    except BrokerIdentityMappingConflictError as error:
        assert "ISIN" in str(error)
    stored = session.get(BrokerIdentityMapping, original_id)
    assert stored is not None
    assert stored.status == "effective"
    assert stored.observed_isin == SYN_ISIN
    assert stored.confirmed_at == original_confirmed_at
    assert session.scalar(select(func.count()).select_from(BrokerIdentityMapping)) == 1
    session.close()


def test_same_target_remap_rejects_contradictory_isin(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    original = confirm_mapping(
        session,
        provider=SYN_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
        observed_isin=SYN_ISIN,
    )
    try:
        remap_mapping(
            session,
            original.id,
            hermes_target_id=ids["instrument_id"],
            observed_isin=SYN_ISIN_OTHER,
        )
        raise AssertionError("same-target remap with contradictory ISIN must fail closed")
    except BrokerIdentityMappingConflictError as error:
        assert "ISIN" in str(error)
    stored = session.get(BrokerIdentityMapping, original.id)
    assert stored is not None
    assert stored.status == "effective"
    assert stored.successor_mapping_id is None
    assert stored.observed_isin == SYN_ISIN
    assert session.scalar(select(func.count()).select_from(BrokerIdentityMapping)) == 1
    session.close()


def _assert_not_found(response) -> None:
    assert response.status_code == 404, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


def test_mapping_api_returns_404_for_missing_mapping_and_hermes_targets(
    tmp_path: Path,
) -> None:
    database, ids = _context(tmp_path)
    application = create_app(database)
    missing_mapping = 99_999
    missing_target = 99_999
    with TestClient(application) as client:
        _assert_not_found(client.get(f"/api/broker-identity-mappings/{missing_mapping}"))
        _assert_not_found(
            client.post(
                f"/api/broker-identity-mappings/{missing_mapping}/revoke",
                json={},
            )
        )
        _assert_not_found(
            client.post(
                f"/api/broker-identity-mappings/{missing_mapping}/remap",
                json={"hermes_target_id": ids["instrument_id"]},
            )
        )
        _assert_not_found(
            client.post(
                "/api/broker-identity-mappings",
                json={
                    "provider": SYN_PROVIDER,
                    "subject_kind": "account",
                    "provider_identity": SYN_ACCOUNT,
                    "hermes_target_id": missing_target,
                },
            )
        )
        _assert_not_found(
            client.post(
                "/api/broker-identity-mappings",
                json={
                    "provider": SYN_PROVIDER,
                    "subject_kind": "instrument",
                    "provider_identity": SYN_INSTRUMENT,
                    "hermes_target_id": missing_target,
                },
            )
        )
        created = client.post(
            "/api/broker-identity-mappings",
            json={
                "provider": SYN_PROVIDER,
                "subject_kind": "account",
                "provider_identity": SYN_ACCOUNT,
                "hermes_target_id": ids["account_id"],
            },
        )
        assert created.status_code == 200, created.text
        _assert_not_found(
            client.post(
                f"/api/broker-identity-mappings/{created.json()['mapping_id']}/remap",
                json={"hermes_target_id": missing_target},
            )
        )


def test_retired_snapshot_api_is_absent_and_legacy_registry_remains_readable(
    tmp_path: Path,
) -> None:
    database, ids = _context(tmp_path)
    with database.session_factory() as session:
        row = confirm_mapping(
            session,
            provider="alfa_pro",
            subject_kind="account",
            provider_identity=SYN_ACCOUNT,
            hermes_target_id=ids["account_id"],
        )
        mapping_id = row.id
    application = create_app(database)
    paths = set(application.openapi()["paths"])
    assert not any(
        "broker-snapshot" in path or "broker-baseline" in path or "broker-reconciliation" in path
        for path in paths
    )
    with TestClient(application) as client:
        for suffix in (
            "broker-snapshot-preview",
            "broker-snapshot-apply",
            "broker-baseline-apply",
            "broker-reconciliation-preview",
        ):
            response = client.post(f"/api/months/{ids['month_id']}/{suffix}", json={})
            assert response.status_code == 404
        records = client.get(
            "/api/broker-identity-mappings", params={"provider": "alfa_pro"}
        ).json()
        assert len(records) == 1
        assert records[0]["mapping_id"] == mapping_id
        assert records[0]["provider_identity"] == SYN_ACCOUNT
