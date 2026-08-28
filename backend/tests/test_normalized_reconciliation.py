"""R07-08A normalized reconciliation contract tests using synthetic data only."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState
from hermes_finance.broker_data.dto import (
    ALFA_PRO_PROVIDER,
    BrokerAccount,
    BrokerPosition,
    BrokerSnapshot,
    SnapshotProvenance,
    SnapshotStatus,
    TimestampProvenance,
)
from hermes_finance.broker_data.reconciliation import (
    AccountMappingInput,
    HermesAccountView,
    HermesInstrumentView,
    HermesPositionView,
    HermesStateView,
    InstrumentMappingInput,
    NormalizedRowState,
    OwnerMappingInput,
    build_normalized_reconciliation,
)
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.main import create_app
from hermes_finance.persistence import Base, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import create_reporting_month

SYN_PROVIDER_ACCOUNT = "SYN-ACCOUNT-001"
SYN_PROVIDER_INSTRUMENT = "SYN-INSTRUMENT-001"
SYN_ISIN = "RU000SYN00001"


class _StaticSnapshotProvider:
    def __init__(self, snapshot: BrokerSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def fetch_snapshot(self) -> BrokerSnapshot:
        self.calls += 1
        return self.snapshot


def _provenance(
    *,
    compatibility_state: AlfaCompatibilityState = AlfaCompatibilityState.COMPATIBLE,
    eligible_for_apply: bool = True,
) -> SnapshotProvenance:
    return SnapshotProvenance(
        provider=ALFA_PRO_PROVIDER,
        api_doc_version="synthetic",
        captured_at=datetime(2026, 8, 28, 10, 0, tzinfo=UTC),
        timestamp_provenance=TimestampProvenance.LOCAL_OBSERVATION,
        auth_status=2,
        ready_to_sign=True,
        channels_invoked=("synthetic",),
        entity_query_status=("synthetic:ok",),
        eligible_for_apply=eligible_for_apply,
        compatibility_state=compatibility_state,
        compatibility_fingerprint="a" * 64,
    )


def _snapshot(
    *,
    quantity: Decimal | None = Decimal("10"),
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    compatibility_state: AlfaCompatibilityState = AlfaCompatibilityState.COMPATIBLE,
    eligible_for_apply: bool = True,
    include_position: bool = True,
) -> BrokerSnapshot:
    positions = (
        (
            BrokerPosition(
                provider_account_id=SYN_PROVIDER_ACCOUNT,
                provider_subaccount_id=None,
                provider_section_id=None,
                provider_instrument_id=SYN_PROVIDER_INSTRUMENT,
                isin=SYN_ISIN,
                ticker="SYN",
                display_name="Synthetic provider position",
                quantity=quantity,
                broker_unit_price=Decimal("101.25"),
                market_value=Decimal("1012.50"),
                accounting_price=Decimal("99.50"),
                accrued_interest_nkd=Decimal("1.25"),
                unrealized_result=Decimal("17.50"),
                is_money=False,
                mapped_fields=("quantity=TorgPos",),
            ),
        )
        if include_position
        else ()
    )
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=status,
        source_as_of=datetime(2026, 8, 28, 10, 0, tzinfo=UTC),
        accounts=(BrokerAccount(provider_account_id=SYN_PROVIDER_ACCOUNT),),
        subaccounts=(),
        sections=(),
        positions=positions,
        cash_balances=(),
        warnings=(),
        provenance=_provenance(
            compatibility_state=compatibility_state,
            eligible_for_apply=eligible_for_apply,
        ),
    )


def _hermes(*, quantity: Decimal | None = Decimal("10"), include_position: bool = True):
    positions = (
        (
            HermesPositionView(
                1,
                10,
                quantity if quantity is not None else Decimal("0"),
                10000,
                125,
                101250,
                1750,
            ),
        )
        if include_position
        else ()
    )
    return HermesStateView(
        month_id=1,
        month_status="draft",
        accounts=(HermesAccountView(1, "Synthetic brokerage", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Synthetic equity", "stock", SYN_ISIN, "SYN"),),
        positions=positions,
        cash_balances=(),
    )


def _mapping() -> OwnerMappingInput:
    return OwnerMappingInput(
        accounts=(
            AccountMappingInput(
                hermes_account_id=1,
                provider_account_id=SYN_PROVIDER_ACCOUNT,
            ),
        ),
        instruments=(
            InstrumentMappingInput(
                hermes_instrument_id=10,
                provider_instrument_id=SYN_PROVIDER_INSTRUMENT,
            ),
        ),
    )


def test_normalized_matched_and_quantity_differs_states() -> None:
    matched = build_normalized_reconciliation(
        snapshot=_snapshot(), hermes=_hermes(), mapping=_mapping()
    )
    assert matched.rows[0].state is NormalizedRowState.MATCHED
    assert matched.rows[0].quantity_difference == Decimal("0")
    assert matched.rows[0].comparison_only_fields
    assert matched.eligible_for_apply is False
    assert matched.read_only is True

    differs = build_normalized_reconciliation(
        snapshot=_snapshot(quantity=Decimal("12")),
        hermes=_hermes(),
        mapping=_mapping(),
    )
    assert differs.rows[0].state is NormalizedRowState.DIFFERS
    assert differs.rows[0].quantity_difference == Decimal("-2")
    assert differs.rows[0].provider_accounting_price == Decimal("99.50")


def test_normalized_missing_local_and_missing_provider_states() -> None:
    missing_local = build_normalized_reconciliation(
        snapshot=_snapshot(),
        hermes=_hermes(include_position=False),
        mapping=_mapping(),
    )
    assert missing_local.rows[0].state is NormalizedRowState.MISSING_LOCAL
    assert missing_local.rows[0].hermes_quantity is None

    missing_provider = build_normalized_reconciliation(
        snapshot=_snapshot(include_position=False),
        hermes=_hermes(),
        mapping=_mapping(),
    )
    assert missing_provider.rows[0].state is NormalizedRowState.MISSING_PROVIDER
    assert missing_provider.rows[0].provider_quantity is None


def test_normalized_unresolved_mapping_is_retained_with_reason() -> None:
    result = build_normalized_reconciliation(
        snapshot=_snapshot(), hermes=_hermes(), mapping=OwnerMappingInput()
    )
    assert result.rows[0].state is NormalizedRowState.UNRESOLVED
    assert result.rows[0].reason is not None
    assert "mapping" in result.rows[0].reason
    provider_row = next(row for row in result.rows if row.provider_quantity is not None)
    assert provider_row.state is NormalizedRowState.UNRESOLVED
    assert provider_row.provider_quantity == Decimal("10")


def test_normalized_stale_snapshot_fails_closed() -> None:
    result = build_normalized_reconciliation(
        snapshot=_snapshot(status=SnapshotStatus.STALE),
        hermes=_hermes(),
        mapping=_mapping(),
    )
    assert result.stale is True
    assert result.rows == ()
    assert result.eligible_for_apply is False
    assert any("stale" in warning for warning in result.warnings)


def test_normalized_unknown_compatibility_fails_closed() -> None:
    result = build_normalized_reconciliation(
        snapshot=_snapshot(compatibility_state=AlfaCompatibilityState.UNKNOWN),
        hermes=_hermes(),
        mapping=_mapping(),
    )
    assert result.compatibility_state is AlfaCompatibilityState.UNKNOWN
    assert result.rows == ()
    assert result.status.value == "non_applicable"
    assert result.eligible_for_apply is False


def _api_context(tmp_path: Path):
    database = create_database(tmp_path / "normalized-reconciliation.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=date(2026, 8, 28))
    account = create_account(
        session, name="Synthetic brokerage", account_type=AccountType.BROKERAGE
    )
    instrument = create_instrument(
        session, name="Synthetic equity", instrument_type=InstrumentType.STOCK, isin=SYN_ISIN
    )
    position = create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="10",
        average_cost_per_unit="99.50",
        market_price_per_unit="100",
        price_date=date(2026, 8, 28),
        price_source=PriceSource.MANUAL,
    )
    session.commit()
    session.close()
    return database, month.id, account.id, instrument.id, position.id


def test_normalized_api_is_explicit_read_only_and_reuses_fingerprints(tmp_path: Path) -> None:
    database, month_id, account_id, instrument_id, position_id = _api_context(tmp_path)
    provider = _StaticSnapshotProvider(_snapshot())
    application = create_app(database, broker_snapshot_provider=provider)
    mapping = {
        "accounts": [
            {"hermes_account_id": account_id, "provider_account_id": SYN_PROVIDER_ACCOUNT}
        ],
        "instruments": [],
    }
    assert provider.calls == 0
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{month_id}/broker-reconciliation-preview", json=mapping
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert provider.calls == 1
    assert body["read_only"] is True
    assert body["eligible_for_apply"] is False
    assert body["rows"][0]["state"] == "matched"
    assert body["rows"][0]["account_name"] == "Synthetic brokerage"
    assert body["rows"][0]["instrument_isin"] == SYN_ISIN
    assert len(body["rows"][0]["fingerprint"]) == 64
    assert body["rows"][0]["price_comparable"] == "non_comparable"
    assert "provider_accounting_price" in body["rows"][0]["comparison_only_fields"]
    assert body["diagnostics"]["compatibility_state"] == "compatible"
    assert body["diagnostics"]["safe_artifact"] is True
    assert "101.25" not in body["diagnostic_report"]

    session = database.session_factory()
    try:
        assert session.get(PositionSnapshot, position_id).quantity == Decimal("10.000000")
    finally:
        session.close()


def test_normalized_api_stale_expected_row_fails_closed_without_mutation(tmp_path: Path) -> None:
    database, month_id, account_id, instrument_id, _position_id = _api_context(tmp_path)
    provider = _StaticSnapshotProvider(_snapshot())
    application = create_app(database, broker_snapshot_provider=provider)
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{month_id}/reconciliation-preview",
            json={
                "accounts": [
                    {
                        "hermes_account_id": account_id,
                        "provider_account_id": SYN_PROVIDER_ACCOUNT,
                    }
                ],
                "instruments": [],
                "expected_rows": [
                    {
                        "hermes_account_id": account_id,
                        "instrument_id": instrument_id,
                        "fingerprint": "0" * 64,
                    }
                ],
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert provider.calls == 1
    assert body["stale"] is True
    assert body["status"] == "non_applicable"
    assert body["eligible_for_apply"] is False
    assert body["rows"][0]["state"] == "unresolved"
    assert "stale" in body["rows"][0]["reason"]
