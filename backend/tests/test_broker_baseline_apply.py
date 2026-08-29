"""ADR 0016 Slice B: owner-approved Alfa baseline apply, provenance and freshness."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState, AlfaDiagnosticReport
from hermes_finance.broker_data.dto import (
    ALFA_PRO_PROVIDER,
    BrokerAccount,
    BrokerCashBalance,
    BrokerPosition,
    BrokerSnapshot,
    SnapshotProvenance,
    SnapshotStatus,
    TimestampProvenance,
)
from hermes_finance.broker_data.reconciliation.dto import AccountMappingInput, OwnerMappingInput
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Base,
    BrokerBaselineApply,
    BrokerBaselineApplyItem,
    BrokerIdentityMapping,
    CashBalance,
    PositionSnapshot,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_baseline_apply import (
    BrokerBaselineApplyFailureCode,
    apply_owner_approved_baseline,
)
from hermes_finance.services.broker_identity_mappings import (
    BrokerIdentitySubjectKind,
    compose_owner_mapping,
    confirm_mapping,
    list_effective_mappings,
)
from hermes_finance.services.broker_reconciliation import load_hermes_state_for_month
from hermes_finance.services.broker_snapshot_apply import (
    AccruedInterestDecision,
    AverageCostDecision,
    BrokerSnapshotApplyAction,
    BrokerSnapshotApplyItemAction,
    BrokerSnapshotApplySelection,
    DependentFieldAction,
    MarketPriceDecision,
    apply_broker_snapshot_preview,
    keep_existing_accrued_interest,
    keep_existing_average_cost,
    keep_existing_market_price,
    position_apply_fingerprint,
)
from hermes_finance.services.cash import create_cash_balance
from hermes_finance.services.freshness_provenance import (
    FreshnessFamilyId,
    FreshnessReasonCode,
    FreshnessStatus,
    build_freshness_provenance_summary,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import get_position_snapshot_by_key
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

SYN_ACCOUNT = "SYN-ACCOUNT-001"
SYN_ACCOUNT_B = "SYN-ACCOUNT-002"
SYN_INSTRUMENT = "SYN-INSTRUMENT-001"
SYN_INSTRUMENT_B = "SYN-INSTRUMENT-002"
SYN_ISIN = "SYN000000001"
SYN_ISIN_B = "SYN000000002"
SOURCE_AS_OF = datetime(2026, 8, 31, 11, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 8, 31, 12, tzinfo=UTC)
BASELINE_DATE = date(2026, 8, 31)
LOCAL_AVERAGE = "100.00"
LOCAL_MARKET = "150.00"
BROKER_PRICE = "101.25"
BROKER_UCH = "99.50"
BROKER_NKD = "1.25"
BROKER_PNL = "17.50"


class FakeSnapshotProvider:
    def __init__(self, snapshot: BrokerSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def fetch_snapshot(self) -> BrokerSnapshot:
        self.calls += 1
        return self.snapshot


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "broker-baseline.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _provenance() -> SnapshotProvenance:
    return SnapshotProvenance(
        provider=ALFA_PRO_PROVIDER,
        api_doc_version="synthetic",
        captured_at=CAPTURED_AT,
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
    is_money: bool = False,
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
        broker_unit_price=Decimal(BROKER_PRICE),
        market_value=None,
        accounting_price=Decimal(BROKER_UCH),
        accrued_interest_nkd=Decimal(BROKER_NKD),
        unrealized_result=Decimal(BROKER_PNL),
        is_money=is_money,
        mapped_fields=("quantity=TorgPos", "broker_unit_price=Price", "accounting_price=UchPrice"),
    )


def _snapshot(
    *,
    accounts: tuple[str, ...] = (SYN_ACCOUNT,),
    positions: tuple[BrokerPosition, ...] | None = None,
    quantity: str = "10",
) -> BrokerSnapshot:
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=SnapshotStatus.COMPLETE,
        source_as_of=SOURCE_AS_OF,
        accounts=tuple(BrokerAccount(provider_account_id=item) for item in accounts),
        subaccounts=(),
        sections=(),
        positions=positions if positions is not None else (_position(quantity=quantity),),
        cash_balances=(
            BrokerCashBalance(
                provider_account_id=SYN_ACCOUNT,
                provider_subaccount_id=None,
                currency="RUB",
                amount=Decimal("50000.00"),
                section_group=None,
                mapped_fields=(),
            ),
        ),
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


def _context(session: Session, *, second_instrument: bool = False) -> dict[str, int]:
    month = create_reporting_month(session, year=2026, month=8, snapshot_date=BASELINE_DATE)
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
    create_cash_balance(session, reporting_month_id=month.id, name="RUB cash", amount="1000.00")
    return {
        "month_id": month.id,
        "account_id": account.id,
        "instrument_id": instrument.id,
        "instrument_b_id": extra.id if extra is not None else 0,
    }


def account_mapping(account_id: int, provider_account_id: str = SYN_ACCOUNT) -> OwnerMappingInput:
    return OwnerMappingInput(
        accounts=(
            AccountMappingInput(
                hermes_account_id=account_id,
                provider_account_id=provider_account_id,
            ),
        )
    )


def keep_all() -> dict[str, object]:
    return {
        "average_cost": keep_existing_average_cost(),
        "market_price": keep_existing_market_price(),
        "accrued_interest": keep_existing_accrued_interest(),
    }


def reviewed_fingerprint(
    session: Session,
    snapshot: BrokerSnapshot,
    *,
    month_id: int,
    request: OwnerMappingInput,
    account_id: int,
    instrument_id: int,
) -> str:
    hermes = load_hermes_state_for_month(session, month_id)
    mapping = compose_owner_mapping(session, provider=snapshot.provider, request=request)
    preview = build_reconciliation_preview(snapshot=snapshot, hermes=hermes, mapping=mapping)
    matches = [
        row
        for row in preview.positions
        if row.account_id == account_id and row.instrument_id == instrument_id
    ]
    assert len(matches) == 1
    local = get_position_snapshot_by_key(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
    )
    return position_apply_fingerprint(
        preview=preview,
        row=matches[0],
        mapping=mapping,
        snapshot=local,
    )


def selection_create(
    account_id: int,
    instrument_id: int,
    fingerprint: str,
) -> BrokerSnapshotApplySelection:
    return BrokerSnapshotApplySelection(
        account_id=account_id,
        instrument_id=instrument_id,
        fingerprint=fingerprint,
        action=BrokerSnapshotApplyAction.CREATE,
        average_cost=AverageCostDecision(action=DependentFieldAction.REPLACE, value=LOCAL_AVERAGE),
        market_price=MarketPriceDecision(
            action=DependentFieldAction.REPLACE,
            market_price_per_unit=LOCAL_MARKET,
            price_date=BASELINE_DATE,
            price_source=PriceSource.MANUAL,
        ),
        accrued_interest=AccruedInterestDecision(action=DependentFieldAction.REPLACE, value="0.00"),
    )


def selection_update(
    account_id: int,
    instrument_id: int,
    fingerprint: str,
) -> BrokerSnapshotApplySelection:
    return BrokerSnapshotApplySelection(
        account_id=account_id,
        instrument_id=instrument_id,
        fingerprint=fingerprint,
        action=BrokerSnapshotApplyAction.UPDATE,
        **keep_all(),
    )


def apply_baseline(
    session: Session,
    provider: FakeSnapshotProvider,
    *,
    month_id: int,
    mapping: OwnerMappingInput,
    selections: tuple[BrokerSnapshotApplySelection, ...],
    baseline_date: date = BASELINE_DATE,
):
    return apply_owner_approved_baseline(
        session,
        provider=provider,
        reporting_month_id=month_id,
        baseline_date=baseline_date,
        mapping=mapping,
        selections=selections,
    )


def persisted_text(database_path: Path) -> str:
    connection = sqlite3.connect(database_path)
    try:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        blobs: list[str] = []
        for (name,) in tables:
            for row in connection.execute(f'SELECT * FROM "{name}"'):
                blobs.extend("" if cell is None else str(cell) for cell in row)
        return "\n".join(blobs)
    finally:
        connection.close()


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _effective_count(session: Session) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(BrokerIdentityMapping)
            .where(BrokerIdentityMapping.status == "effective")
        )
        or 0
    )


def test_e1_first_baseline_persists_quantity_mappings_and_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot()
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    provider = FakeSnapshotProvider(snapshot)
    cash_before = session.scalar(select(func.count()).select_from(CashBalance))
    result = apply_baseline(
        session,
        provider,
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert result.success is True
    assert result.baseline_date == BASELINE_DATE
    assert result.provenance_id is not None
    assert result.source_as_of == SOURCE_AS_OF
    assert len(result.items) == 1
    item = result.items[0]
    assert item.action is BrokerSnapshotApplyItemAction.CREATED
    assert item.quantity == Decimal("10")
    assert item.average_cost_per_unit_kopecks == 10_000
    assert item.market_price_per_unit_kopecks == 15_000
    assert item.accrued_interest_kopecks == 0
    position = session.get(PositionSnapshot, item.position_snapshot_id)
    assert position is not None
    assert Decimal(position.quantity) == Decimal("10")
    assert position.average_cost_per_unit_kopecks == 10_000
    assert position.price_source == PriceSource.MANUAL.value
    effective = list_effective_mappings(session, provider=ALFA_PRO_PROVIDER)
    assert {
        (row.subject_kind, row.provider_identity, row.hermes_target_id) for row in effective
    } == {
        ("account", SYN_ACCOUNT, ids["account_id"]),
        ("instrument", SYN_INSTRUMENT, ids["instrument_id"]),
    }
    header = session.get(BrokerBaselineApply, result.provenance_id)
    assert header is not None
    assert header.provider == ALFA_PRO_PROVIDER
    assert header.baseline_date == BASELINE_DATE
    assert _aware(header.source_as_of) == SOURCE_AS_OF
    assert _aware(header.captured_at) == CAPTURED_AT
    assert header.compatibility_fingerprint == "a" * 64
    rows = list(
        session.scalars(
            select(BrokerBaselineApplyItem).where(
                BrokerBaselineApplyItem.baseline_apply_id == header.id
            )
        )
    )
    assert len(rows) == 1
    assert rows[0].action == "created"
    assert Decimal(rows[0].quantity) == Decimal("10")
    assert session.scalar(select(func.count()).select_from(CashBalance)) == cash_before
    cash = session.scalar(select(CashBalance))
    assert cash is not None
    assert cash.amount_kopecks == 100_000
    text = persisted_text(tmp_path / "broker-baseline.db")
    assert BROKER_PRICE not in text
    assert BROKER_UCH not in text
    assert BROKER_NKD not in text
    assert BROKER_PNL not in text
    session.close()


def test_e2_reused_mapping_updates_quantity_only(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    first = _snapshot(quantity="10")
    mapping = account_mapping(ids["account_id"])
    first_fp = reviewed_fingerprint(
        session,
        first,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    created = apply_baseline(
        session,
        FakeSnapshotProvider(first),
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], first_fp),),
    )
    assert created.success is True
    empty = OwnerMappingInput()
    second = _snapshot(quantity="12")
    second_fp = reviewed_fingerprint(
        session,
        second,
        month_id=ids["month_id"],
        request=empty,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    result = apply_baseline(
        session,
        FakeSnapshotProvider(second),
        month_id=ids["month_id"],
        mapping=empty,
        selections=(selection_update(ids["account_id"], ids["instrument_id"], second_fp),),
    )
    assert result.success is True
    assert result.items[0].action is BrokerSnapshotApplyItemAction.UPDATED
    assert result.items[0].quantity == Decimal("12")
    position = session.get(PositionSnapshot, result.items[0].position_snapshot_id)
    assert position is not None
    assert Decimal(position.quantity) == Decimal("12")
    assert position.average_cost_per_unit_kopecks == 10_000
    assert position.market_price_per_unit_kopecks == 15_000
    assert _effective_count(session) == 2
    session.close()


def test_e7_identical_rerun_is_unchanged_and_records_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot(quantity="10")
    mapping = account_mapping(ids["account_id"])
    first_fp = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    first = apply_baseline(
        session,
        FakeSnapshotProvider(snapshot),
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], first_fp),),
    )
    assert first.success is True
    position = session.get(PositionSnapshot, first.items[0].position_snapshot_id)
    assert position is not None
    updated_at = position.updated_at
    empty = OwnerMappingInput()
    second_fp = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=empty,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    second = apply_baseline(
        session,
        FakeSnapshotProvider(snapshot),
        month_id=ids["month_id"],
        mapping=empty,
        selections=(selection_update(ids["account_id"], ids["instrument_id"], second_fp),),
    )
    assert second.success is True
    assert second.items[0].action is BrokerSnapshotApplyItemAction.UNCHANGED
    session.refresh(position)
    assert position.updated_at == updated_at
    assert Decimal(position.quantity) == Decimal("10")
    assert position.average_cost_per_unit_kopecks == 10_000
    assert session.scalar(select(func.count()).select_from(BrokerBaselineApply)) == 2
    rerun = session.get(BrokerBaselineApply, second.provenance_id)
    assert rerun is not None
    item = session.scalar(
        select(BrokerBaselineApplyItem).where(BrokerBaselineApplyItem.baseline_apply_id == rerun.id)
    )
    assert item is not None
    assert item.action == "unchanged"
    assert _effective_count(session) == 2
    session.close()


def test_e8_closed_month_refuses_without_registry_or_quantity_write(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
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
    close_reporting_month(session, ids["month_id"])
    snapshot = _snapshot()
    mapping = OwnerMappingInput()
    fingerprint = "stale-not-used"
    provider = FakeSnapshotProvider(snapshot)
    before_mappings = _effective_count(session)
    result = apply_baseline(
        session,
        provider,
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert result.success is False
    assert result.error_code is BrokerBaselineApplyFailureCode.CLOSED_MONTH
    assert provider.calls == 0
    assert _effective_count(session) == before_mappings
    assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(BrokerBaselineApply)) == 0
    session.close()


def test_baseline_date_mismatch_is_fail_closed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot()
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    provider = FakeSnapshotProvider(snapshot)
    result = apply_baseline(
        session,
        provider,
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
        baseline_date=date(2026, 8, 30),
    )
    assert result.success is False
    assert result.error_code is BrokerBaselineApplyFailureCode.BASELINE_DATE_MISMATCH
    assert provider.calls == 0
    assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
    assert _effective_count(session) == 0
    assert session.scalar(select(func.count()).select_from(BrokerBaselineApply)) == 0
    session.close()


def test_is_money_rows_cannot_be_applied(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot(positions=(_position(is_money=True),))
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    result = apply_baseline(
        session,
        FakeSnapshotProvider(snapshot),
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert result.success is False
    assert result.error_code is BrokerBaselineApplyFailureCode.VALIDATION_ERROR
    assert result.message is not None
    assert "IsMoney" in result.message
    assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
    assert _effective_count(session) == 0
    r06 = apply_broker_snapshot_preview(
        session,
        provider=FakeSnapshotProvider(snapshot),
        reporting_month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert r06.success is False
    session.close()


def test_identity_conflict_rolls_back_quantity_and_new_mapping(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session, second_instrument=True)
    confirm_mapping(
        session,
        provider=ALFA_PRO_PROVIDER,
        subject_kind=BrokerIdentitySubjectKind.INSTRUMENT,
        provider_identity=SYN_INSTRUMENT_B,
        hermes_target_id=ids["instrument_id"],
        observed_isin=SYN_ISIN,
    )
    snapshot = _snapshot()
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    result = apply_baseline(
        session,
        FakeSnapshotProvider(snapshot),
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert result.success is False
    assert result.error_code is BrokerBaselineApplyFailureCode.IDENTITY_CONFLICT
    assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
    assert session.scalar(select(func.count()).select_from(BrokerBaselineApply)) == 0
    remaining = list_effective_mappings(session, provider=ALFA_PRO_PROVIDER)
    assert len(remaining) == 1
    assert remaining[0].provider_identity == SYN_INSTRUMENT_B
    session.close()


def test_new_unmapped_instrument_is_not_created(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot(
        positions=(_position(instrument_id=SYN_INSTRUMENT_B, isin=SYN_ISIN_B),),
    )
    mapping = account_mapping(ids["account_id"])
    hermes = load_hermes_state_for_month(session, ids["month_id"])
    composed = compose_owner_mapping(session, provider=ALFA_PRO_PROVIDER, request=mapping)
    preview = build_reconciliation_preview(snapshot=snapshot, hermes=hermes, mapping=composed)
    assert preview.positions == ()
    assert all(row.status.value != "matched" for row in preview.instruments)
    assert session.scalar(select(func.count()).select_from(PositionSnapshot)) == 0
    session.close()


def test_quantity_apply_without_baseline_does_not_write_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot()
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    result = apply_broker_snapshot_preview(
        session,
        provider=FakeSnapshotProvider(snapshot),
        reporting_month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert result.success is True
    assert session.scalar(select(func.count()).select_from(BrokerBaselineApply)) == 0
    assert _effective_count(session) == 0
    session.close()


def test_freshness_reads_persisted_source_as_of_not_confirmed_at(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot()
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    result = apply_baseline(
        session,
        FakeSnapshotProvider(snapshot),
        month_id=ids["month_id"],
        mapping=mapping,
        selections=(selection_create(ids["account_id"], ids["instrument_id"], fingerprint),),
    )
    assert result.success is True
    summary = build_freshness_provenance_summary(
        session,
        ids["month_id"],
        today=date(2026, 8, 31),
        generated_at=datetime(2026, 8, 31, 18, tzinfo=UTC),
    )
    family = next(
        item for item in summary.families if item.family_id is FreshnessFamilyId.ALFA_PRO_POSITIONS
    )
    assert family.status is FreshnessStatus.NOT_APPLICABLE
    assert family.providers == (ALFA_PRO_PROVIDER,)
    assert ALFA_PRO_PROVIDER in summary.providers
    codes = {reason.code for reason in family.reasons}
    assert FreshnessReasonCode.ALFA_PRO_BASELINE_PRESENT in codes
    assert FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_FRESHNESS_CLASSIFIED in codes
    assert FreshnessReasonCode.ALFA_PRO_OBSERVATION_NOT_PERSISTED not in codes
    assert len(family.items) == 1
    item = family.items[0]
    assert item.source_datetime == SOURCE_AS_OF
    assert item.import_apply_time == _aware(result.confirmed_at)
    assert item.import_apply_time != item.source_datetime
    assert item.freshness_status is FreshnessStatus.NOT_APPLICABLE
    session.close()


def test_baseline_apply_api_creates_provenance(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    ids = _context(session)
    snapshot = _snapshot()
    mapping = account_mapping(ids["account_id"])
    fingerprint = reviewed_fingerprint(
        session,
        snapshot,
        month_id=ids["month_id"],
        request=mapping,
        account_id=ids["account_id"],
        instrument_id=ids["instrument_id"],
    )
    session.close()
    application = create_app(database, broker_snapshot_provider=FakeSnapshotProvider(snapshot))
    with TestClient(application) as client:
        response = client.post(
            f"/api/months/{ids['month_id']}/broker-baseline-apply",
            json={
                "baseline_date": "2026-08-31",
                "mapping": {
                    "accounts": [
                        {
                            "hermes_account_id": ids["account_id"],
                            "provider_account_id": SYN_ACCOUNT,
                        }
                    ],
                    "instruments": [],
                },
                "selections": [
                    {
                        "account_id": ids["account_id"],
                        "instrument_id": ids["instrument_id"],
                        "fingerprint": fingerprint,
                        "action": "create",
                        "average_cost": {"action": "replace", "value": LOCAL_AVERAGE},
                        "market_price": {
                            "action": "replace",
                            "market_price_per_unit": LOCAL_MARKET,
                            "price_date": "2026-08-31",
                            "price_source": "manual",
                        },
                        "accrued_interest": {"action": "replace", "value": "0.00"},
                    }
                ],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["baseline_date"] == "2026-08-31"
    assert body["provenance_id"] is not None
    assert body["items"][0]["action"] == "created"
    with TestClient(application) as client:
        preview = client.post(
            f"/api/months/{ids['month_id']}/broker-snapshot-preview",
            json={"accounts": [], "instruments": []},
        )
        freshness = client.get(f"/api/months/{ids['month_id']}/freshness-provenance")
    assert preview.status_code == 200
    assert any(row["classification"] == "reused" for row in preview.json()["accounts"])
    family = next(
        item for item in freshness.json()["families"] if item["family_id"] == "alfa_pro_positions"
    )
    assert family["status"] == "not_applicable"
    assert family["providers"] == ["alfa_pro"]
