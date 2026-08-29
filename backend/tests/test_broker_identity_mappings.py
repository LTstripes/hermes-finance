"""ADR 0016 Slice A: persistent broker identity registry and preview reuse."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState, AlfaDiagnosticReport
from hermes_finance.broker_data.dto import (
    ALFA_PRO_PROVIDER,
    BrokerAccount,
    BrokerPosition,
    BrokerSnapshot,
    SnapshotProvenance,
    SnapshotStatus,
    TimestampProvenance,
)
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, BrokerIdentityMapping, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_identity_mappings import (
    BrokerIdentityMappingConflictError,
    BrokerIdentitySubjectKind,
    IdentityClassification,
    confirm_mapping,
    list_effective_mappings,
    remap_mapping,
    revoke_mapping,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

SYN_ACCOUNT = "SYN-ACCOUNT-001"
SYN_ACCOUNT_B = "SYN-ACCOUNT-002"
SYN_INSTRUMENT = "SYN-INSTRUMENT-001"
SYN_INSTRUMENT_B = "SYN-INSTRUMENT-002"
SYN_ISIN = "SYN000000001"
SYN_ISIN_B = "SYN000000002"
SYN_ISIN_OTHER = "SYN000000099"


class _StaticSnapshotProvider:
    def __init__(self, snapshot: BrokerSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def fetch_snapshot(self) -> BrokerSnapshot:
        self.calls += 1
        return self.snapshot


def _provenance() -> SnapshotProvenance:
    return SnapshotProvenance(
        provider=ALFA_PRO_PROVIDER,
        api_doc_version="synthetic",
        captured_at=datetime(2026, 8, 31, 12, tzinfo=UTC),
        timestamp_provenance=TimestampProvenance.LOCAL_OBSERVATION,
        auth_status=2,
        ready_to_sign=True,
        channels_invoked=("synthetic",),
        entity_query_status=("synthetic:ok",),
        eligible_for_apply=True,
        compatibility_state=AlfaCompatibilityState.COMPATIBLE,
        compatibility_fingerprint="a" * 64,
    )


def _position(
    *,
    account_id: str = SYN_ACCOUNT,
    instrument_id: str = SYN_INSTRUMENT,
    isin: str | None = SYN_ISIN,
    quantity: str = "10",
) -> BrokerPosition:
    return BrokerPosition(
        provider_account_id=account_id,
        provider_subaccount_id=None,
        provider_section_id=None,
        provider_instrument_id=instrument_id,
        isin=isin,
        ticker="SYN",
        display_name="Synthetic provider position",
        quantity=Decimal(quantity),
        broker_unit_price=Decimal("101.25"),
        market_value=None,
        accounting_price=Decimal("99.50"),
        accrued_interest_nkd=Decimal("1.25"),
        unrealized_result=Decimal("17.50"),
        is_money=False,
        mapped_fields=("quantity=TorgPos",),
    )


def _snapshot(
    *,
    accounts: tuple[str, ...] = (SYN_ACCOUNT,),
    positions: tuple[BrokerPosition, ...] | None = None,
) -> BrokerSnapshot:
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=SnapshotStatus.COMPLETE,
        source_as_of=datetime(2026, 8, 31, 11, tzinfo=UTC),
        accounts=tuple(BrokerAccount(provider_account_id=item) for item in accounts),
        subaccounts=(),
        sections=(),
        positions=positions if positions is not None else (_position(),),
        cash_balances=(),
        warnings=(),
        provenance=_provenance(),
        diagnostics=AlfaDiagnosticReport(
            api_doc_version="synthetic",
            snapshot_status="complete",
            eligible_for_apply=True,
            compatibility_state=AlfaCompatibilityState.COMPATIBLE,
            compatibility_fingerprint="a" * 64,
        ),
    )


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
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    instrument_row = confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
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
        provider=ALFA_PRO_PROVIDER,
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
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    try:
        confirm_mapping(
            session,
            provider=ALFA_PRO_PROVIDER,
            subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
            provider_identity=SYN_ACCOUNT,
            hermes_target_id=ids["account_id"] + 999,
        )
        raise AssertionError("conflicting account confirm must fail closed")
    except BrokerIdentityMappingConflictError:
        pass
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
    )
    try:
        confirm_mapping(
            session,
            provider=ALFA_PRO_PROVIDER,
            subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
            provider_identity=SYN_INSTRUMENT_B,
            hermes_target_id=ids["instrument_id"],
        )
        raise AssertionError("reverse instrument uniqueness must fail closed")
    except BrokerIdentityMappingConflictError:
        pass
    session.close()


def test_unique_isin_does_not_silently_persist(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    provider = _StaticSnapshotProvider(_snapshot())
    application = create_app(database, broker_snapshot_provider=provider)
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    instrument = body["instruments"][0]
    assert instrument["status"] == "matched"
    assert instrument["classification"] == IdentityClassification.DETERMINISTIC_ISIN.value
    session = database.session_factory()
    assert list_effective_mappings(session, provider=ALFA_PRO_PROVIDER) == []
    session.close()


def test_preview_reuses_effective_mappings_without_request_body(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
        observed_isin=SYN_ISIN,
    )
    session.close()
    provider = _StaticSnapshotProvider(_snapshot())
    application = create_app(database, broker_snapshot_provider=provider)
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["accounts"][0]["classification"] == IdentityClassification.REUSED.value
    assert body["accounts"][0]["status"] == "matched"
    assert body["instruments"][0]["classification"] == IdentityClassification.REUSED.value
    assert body["instruments"][0]["status"] == "matched"
    assert body["positions"][0]["status"] in {"matched", "provider_only"}


def test_new_instrument_stays_unmatched_and_unpersisted(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
    )
    session.close()
    snapshot = _snapshot(
        positions=(
            _position(),
            _position(instrument_id=SYN_INSTRUMENT_B, isin=SYN_ISIN_OTHER, quantity="3"),
        )
    )
    application = create_app(database, broker_snapshot_provider=_StaticSnapshotProvider(snapshot))
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
    body = response.json()
    by_id = {row["provider_instrument_id"]: row for row in body["instruments"]}
    assert by_id[SYN_INSTRUMENT]["classification"] == IdentityClassification.REUSED.value
    assert by_id[SYN_INSTRUMENT_B]["classification"] == IdentityClassification.NEW.value
    assert by_id[SYN_INSTRUMENT_B]["status"] == "unmatched"
    session = database.session_factory()
    effective = list_effective_mappings(session, provider=ALFA_PRO_PROVIDER)
    assert {row.provider_identity for row in effective} == {SYN_ACCOUNT, SYN_INSTRUMENT}
    session.close()


def test_changed_provider_account_identity_is_absent_not_silent_remap(
    tmp_path: Path,
) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    session.close()
    snapshot = _snapshot(
        accounts=(SYN_ACCOUNT_B,),
        positions=(_position(account_id=SYN_ACCOUNT_B),),
    )
    application = create_app(database, broker_snapshot_provider=_StaticSnapshotProvider(snapshot))
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
    body = response.json()
    by_id = {row["provider_account_id"]: row for row in body["accounts"]}
    assert by_id[SYN_ACCOUNT]["classification"] == (
        IdentityClassification.PROVIDER_IDENTITY_ABSENT.value
    )
    assert by_id[SYN_ACCOUNT_B]["classification"] == IdentityClassification.NEW.value
    assert by_id[SYN_ACCOUNT_B]["hermes_account_id"] is None


def test_conflicting_isin_fails_closed_and_keeps_effective_mapping(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
        observed_isin=SYN_ISIN,
    )
    session.close()
    snapshot = _snapshot(positions=(_position(isin=SYN_ISIN_OTHER),))
    application = create_app(database, broker_snapshot_provider=_StaticSnapshotProvider(snapshot))
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
    body = response.json()
    instrument = body["instruments"][0]
    assert instrument["classification"] == IdentityClassification.CONFLICT.value
    assert instrument["status"] == "conflict"
    session = database.session_factory()
    [row] = [
        item
        for item in list_effective_mappings(session, provider=ALFA_PRO_PROVIDER)
        if item.subject_kind == "instrument"
    ]
    assert row.hermes_target_id == ids["instrument_id"]
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
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    instrument_row = confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
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

    snapshot = _snapshot()
    application = create_app(database, broker_snapshot_provider=_StaticSnapshotProvider(snapshot))
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
        listed = client.get("/api/broker-identity-mappings", params={"provider": ALFA_PRO_PROVIDER})
    body = response.json()
    assert body["accounts"][0]["classification"] == IdentityClassification.NEW.value
    assert body["instruments"][0]["classification"] == IdentityClassification.REUSED.value
    assert body["instruments"][0]["hermes_instrument_id"] == ids["instrument_b_id"]
    statuses = {row["mapping_id"]: row["status"] for row in listed.json()}
    assert statuses[instrument_row.id] == "superseded"
    assert statuses[remapped.id] == "effective"


def test_request_mapping_disagreeing_with_registry_is_conflict(tmp_path: Path) -> None:
    database, ids = _context(tmp_path, second_instrument=True)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
    )
    session.close()
    application = create_app(
        database, broker_snapshot_provider=_StaticSnapshotProvider(_snapshot())
    )
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={
                "accounts": [],
                "instruments": [
                    {
                        "hermes_instrument_id": ids["instrument_b_id"],
                        "provider_instrument_id": SYN_INSTRUMENT,
                    }
                ],
            },
        )
    body = response.json()
    assert body["instruments"][0]["classification"] == IdentityClassification.CONFLICT.value
    assert body["instruments"][0]["status"] == "conflict"


def test_duplicate_resolved_positions_remain_conflict(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    session = database.session_factory()
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.ACCOUNT,
        provider_identity=SYN_ACCOUNT,
        hermes_target_id=ids["account_id"],
    )
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT,
        hermes_target_id=ids["instrument_id"],
    )
    session.close()
    snapshot = _snapshot(positions=(_position(quantity="10"), _position(quantity="4")))
    application = create_app(database, broker_snapshot_provider=_StaticSnapshotProvider(snapshot))
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-reconciliation-preview",
            json={"accounts": [], "instruments": []},
        )
    body = response.json()
    assert body["accounts"][0]["classification"] == IdentityClassification.REUSED.value
    assert any(row["state"] == "unresolved" for row in body["rows"])
    assert any("duplicate" in (row["reason"] or "") for row in body["rows"])


def test_confirm_api_rejects_isin_conflict_without_writing(tmp_path: Path) -> None:
    database, ids = _context(tmp_path)
    application = create_app(database)
    with TestClient(application) as client:
        response = client.post(
            "/api/broker-identity-mappings",
            json={
                "provider": ALFA_PRO_PROVIDER,
                "subject_kind": "instrument",
                "provider_identity": SYN_INSTRUMENT,
                "hermes_target_id": ids["instrument_id"],
                "observed_isin": SYN_ISIN_OTHER,
            },
        )
    assert response.status_code == 409, response.text
    session = database.session_factory()
    assert list_effective_mappings(session, provider=ALFA_PRO_PROVIDER) == []
    session.close()
