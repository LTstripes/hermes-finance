"""R06-05 owner-confirmed broker snapshot quantity apply tests."""

from __future__ import annotations

import inspect
import logging
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

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
from hermes_finance.broker_data.reconciliation.dto import (
    AccountMappingInput,
    OwnerMappingInput,
    PositionRowStatus,
)
from hermes_finance.broker_data.reconciliation.preview import build_reconciliation_preview
from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource
from hermes_finance.persistence import Account, Base, CashBalance, Instrument, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.broker_reconciliation import load_hermes_state_for_month
from hermes_finance.services.broker_snapshot_apply import (
    AccruedInterestDecision,
    AverageCostDecision,
    BrokerSnapshotApplyAction,
    BrokerSnapshotApplyFailureCode,
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
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import (
    create_position_snapshot,
    get_position_snapshot_by_key,
    update_position_snapshot,
)
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)

PROVIDER_ACCOUNT = "PA-SECRET-ALFA-999"
PROVIDER_INSTRUMENT = "PO-SECRET-ALFA-42"
ISIN = "RU000A0JX0J2"
SOURCE_AS_OF = datetime(2030, 6, 15, 11, 0, tzinfo=timezone.utc)


class FakeSnapshotProvider:
    def __init__(self, snapshot: BrokerSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0
        self.error: Exception | None = None

    def fetch_snapshot(self) -> BrokerSnapshot:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.snapshot


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "broker-apply.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _provenance(eligible: bool = True) -> SnapshotProvenance:
    return SnapshotProvenance(
        provider=ALFA_PRO_PROVIDER,
        api_doc_version="v2.1",
        captured_at=datetime(2030, 6, 15, 12, 0, tzinfo=timezone.utc),
        timestamp_provenance=TimestampProvenance.LOCAL_OBSERVATION,
        auth_status=2,
        ready_to_sign=True,
        channels_invoked=("#Data.Query",),
        entity_query_status=("ClientAccountEntity:ok",),
        eligible_for_apply=eligible,
    )


def _position(
    *,
    quantity: Decimal | None,
    provider_account_id: str = PROVIDER_ACCOUNT,
    provider_instrument_id: str = PROVIDER_INSTRUMENT,
    isin: str | None = ISIN,
) -> BrokerPosition:
    return BrokerPosition(
        provider_account_id=provider_account_id,
        provider_subaccount_id="SUB-SECRET",
        provider_section_id="SEC-SECRET",
        provider_instrument_id=provider_instrument_id,
        isin=isin,
        ticker="FAKE",
        display_name="Provider Display",
        quantity=quantity,
        broker_unit_price=Decimal("9999.99"),
        market_value=Decimal("111111.11"),
        accounting_price=Decimal("8888.88"),
        accrued_interest_nkd=Decimal("77.70"),
        unrealized_result=Decimal("1234.56"),
        is_money=False,
        mapped_fields=("quantity=TorgPos", "broker_unit_price=Price", "accounting_price=UchPrice"),
    )


def complete_snapshot(
    *,
    quantity: Decimal | None = Decimal("15"),
    extra_positions: tuple[BrokerPosition, ...] = (),
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    eligible: bool = True,
    extra_accounts: tuple[BrokerAccount, ...] = (),
) -> BrokerSnapshot:
    positions = (_position(quantity=quantity), *extra_positions)
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=status,
        source_as_of=SOURCE_AS_OF,
        accounts=(BrokerAccount(provider_account_id=PROVIDER_ACCOUNT), *extra_accounts),
        subaccounts=(),
        sections=(),
        positions=positions,
        cash_balances=(
            BrokerCashBalance(
                provider_account_id=PROVIDER_ACCOUNT,
                provider_subaccount_id=None,
                currency="RUB",
                amount=Decimal("50000.00"),
                section_group=None,
                mapped_fields=(),
            ),
        ),
        warnings=(),
        provenance=_provenance(eligible=eligible),
        message=None,
    )


def mapping_for(account_id: int) -> OwnerMappingInput:
    return OwnerMappingInput(
        accounts=(
            AccountMappingInput(
                hermes_account_id=account_id,
                provider_account_id=PROVIDER_ACCOUNT,
            ),
        )
    )


def keep_all() -> dict[str, object]:
    return {
        "average_cost": keep_existing_average_cost(),
        "market_price": keep_existing_market_price(),
        "accrued_interest": keep_existing_accrued_interest(),
    }


def build_month_account_instrument(
    session: Session,
    *,
    instrument_type: InstrumentType = InstrumentType.BOND,
    isin: str | None = ISIN,
    name: str = "Synthetic Bond",
) -> tuple[int, int, int]:
    month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
    account = create_account(session, name="Synthetic Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session,
        name=name,
        instrument_type=instrument_type,
        isin=isin,
    )
    return month.id, account.id, instrument.id


def build_matched(
    session: Session,
    *,
    quantity: str = "10",
    average_cost: str = "100.00",
    market_price: str = "150.00",
    accrued: str | None = None,
    instrument_type: InstrumentType = InstrumentType.BOND,
) -> tuple[int, int, int, PositionSnapshot]:
    month_id, account_id, instrument_id = build_month_account_instrument(
        session, instrument_type=instrument_type
    )
    snapshot = create_position_snapshot(
        session,
        reporting_month_id=month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        quantity=quantity,
        average_cost_per_unit=average_cost,
        market_price_per_unit=market_price,
        accrued_interest=accrued,
        price_date=date(2030, 6, 15),
        price_source=PriceSource.MANUAL,
    )
    return month_id, account_id, instrument_id, snapshot


def reviewed_fingerprint(
    session: Session,
    snapshot: BrokerSnapshot,
    *,
    month_id: int,
    mapping: OwnerMappingInput,
    account_id: int,
    instrument_id: int,
) -> str:
    hermes = load_hermes_state_for_month(session, month_id)
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


def selection_update(
    account_id: int,
    instrument_id: int,
    fingerprint: str,
    **decisions: object,
) -> BrokerSnapshotApplySelection:
    return BrokerSnapshotApplySelection(
        account_id=account_id,
        instrument_id=instrument_id,
        fingerprint=fingerprint,
        action=BrokerSnapshotApplyAction.UPDATE,
        **decisions,
    )


def selection_create(
    account_id: int,
    instrument_id: int,
    fingerprint: str,
    *,
    average_cost: str,
    market_price: str,
    price_date: date = date(2030, 6, 15),
    price_source: PriceSource = PriceSource.MANUAL,
    accrued: str | None = None,
) -> BrokerSnapshotApplySelection:
    accrued_decision = None
    if accrued is not None:
        accrued_decision = AccruedInterestDecision(
            action=DependentFieldAction.REPLACE,
            value=accrued,
        )
    return BrokerSnapshotApplySelection(
        account_id=account_id,
        instrument_id=instrument_id,
        fingerprint=fingerprint,
        action=BrokerSnapshotApplyAction.CREATE,
        average_cost=AverageCostDecision(action=DependentFieldAction.REPLACE, value=average_cost),
        market_price=MarketPriceDecision(
            action=DependentFieldAction.REPLACE,
            market_price_per_unit=market_price,
            price_date=price_date,
            price_source=price_source,
        ),
        accrued_interest=accrued_decision,
    )


def apply_now(
    session: Session,
    provider: FakeSnapshotProvider,
    *,
    month_id: int,
    mapping: OwnerMappingInput,
    selections: tuple[BrokerSnapshotApplySelection, ...],
):
    return apply_broker_snapshot_preview(
        session,
        provider=provider,
        reporting_month_id=month_id,
        mapping=mapping,
        selections=selections,
    )


def counts(session: Session) -> tuple[int, int, int, int]:
    return (
        session.scalar(select(func.count()).select_from(PositionSnapshot)) or 0,
        session.scalar(select(func.count()).select_from(Account)) or 0,
        session.scalar(select(func.count()).select_from(Instrument)) or 0,
        session.scalar(select(func.count()).select_from(CashBalance)) or 0,
    )


def table_names(database_path: Path) -> set[str]:
    connection = sqlite3.connect(database_path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {row[0] for row in rows}
    finally:
        connection.close()


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


# --- 1. matched existing quantity update with explicit keep-existing ---


def test_matched_quantity_update_keeps_existing_local_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        create_cash_balance(session, reporting_month_id=month_id, name="RUB cash", amount="1000.00")
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        provider = FakeSnapshotProvider(reviewed)
        before = counts(session)
        result = apply_now(
            session,
            provider,
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        assert provider.calls == 1
        assert len(result.items) == 1
        item = result.items[0]
        assert item.action is BrokerSnapshotApplyItemAction.UPDATED
        assert item.position_snapshot_id == snapshot.id
        assert item.quantity == Decimal("15")
        assert item.average_cost_per_unit_kopecks == 10_000
        assert item.market_price_per_unit_kopecks == 15_000
        assert item.accrued_interest_kopecks is None
        assert item.market_value_kopecks == 225_000
        assert item.cost_basis_kopecks == 150_000
        assert item.unrealized_result_kopecks == 75_000
        assert item.price_source == PriceSource.MANUAL.value
        assert counts(session) == before
        cash = session.scalar(select(CashBalance))
        assert cash is not None
        assert cash.amount_kopecks == 100_000
    finally:
        session.close()
        database.engine.dispose()


# --- 2. quantity update + owner replacement average cost ---


def test_quantity_update_replaces_average_cost(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                selection_update(
                    account_id,
                    instrument_id,
                    fingerprint,
                    average_cost=AverageCostDecision(
                        action=DependentFieldAction.REPLACE, value="120.00"
                    ),
                    market_price=keep_existing_market_price(),
                    accrued_interest=keep_existing_accrued_interest(),
                ),
            ),
        )
        assert result.success is True
        item = result.items[0]
        assert item.quantity == Decimal("15")
        assert item.average_cost_per_unit_kopecks == 12_000
        assert item.market_price_per_unit_kopecks == 15_000
        assert item.cost_basis_kopecks == 180_000
        assert item.market_value_kopecks == 225_000
        assert item.unrealized_result_kopecks == 45_000
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.average_cost_per_unit_kopecks == 12_000
    finally:
        session.close()
        database.engine.dispose()


# --- 3. quantity update + owner replacement market price/date/source ---


def test_quantity_update_replaces_market_price_date_source(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                selection_update(
                    account_id,
                    instrument_id,
                    fingerprint,
                    average_cost=keep_existing_average_cost(),
                    market_price=MarketPriceDecision(
                        action=DependentFieldAction.REPLACE,
                        market_price_per_unit="200.00",
                        price_date=date(2030, 6, 16),
                        price_source=PriceSource.MOEX,
                    ),
                    accrued_interest=keep_existing_accrued_interest(),
                ),
            ),
        )
        assert result.success is True
        item = result.items[0]
        assert item.market_price_per_unit_kopecks == 20_000
        assert item.price_date == date(2030, 6, 16)
        assert item.price_source == PriceSource.MOEX.value
        assert item.market_value_kopecks == 300_000
        assert item.cost_basis_kopecks == 150_000
        assert item.unrealized_result_kopecks == 150_000
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.price_date == date(2030, 6, 16)
    finally:
        session.close()
        database.engine.dispose()


# --- 4. derived Hermes values recompute with existing formulas ---


def test_derived_values_use_existing_hermes_formulas(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, _ = build_matched(
            session, quantity="0.5", accrued="10.00"
        )
        reviewed = complete_snapshot(quantity=Decimal("2.5"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        item = result.items[0]
        # market_value = qty * 15000 + 1000; cost_basis = qty * 10000
        assert item.market_value_kopecks == 38_500
        assert item.cost_basis_kopecks == 25_000
        assert item.unrealized_result_kopecks == 13_500
        assert item.accrued_interest_kopecks == 1_000
    finally:
        session.close()
        database.engine.dispose()


# --- 5. missing dependent owner decisions => validation error / zero writes ---


def test_missing_dependent_decisions_is_validation_error(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                BrokerSnapshotApplySelection(
                    account_id=account_id,
                    instrument_id=instrument_id,
                    fingerprint=fingerprint,
                    action=BrokerSnapshotApplyAction.UPDATE,
                ),
            ),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.VALIDATION_ERROR
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()


# --- 6. provider Price/UchPrice/NKD/unrealized never overwrite local fields ---


def test_provider_price_uchprice_nkd_unrealized_never_write(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session, accrued="3.00")
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.average_cost_per_unit_kopecks == 10_000
        assert stored.market_price_per_unit_kopecks == 15_000
        assert stored.accrued_interest_kopecks == 300
        assert stored.unrealized_result_kopecks == 75_300
        assert stored.average_cost_per_unit_kopecks != 888_888
        assert stored.market_price_per_unit_kopecks != 999_999
    finally:
        session.close()
        database.engine.dispose()


# --- 7. provider-only resolved create with all required owner inputs ---


def test_provider_only_create_with_required_owner_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_month_account_instrument(session)
        reviewed = complete_snapshot(quantity=Decimal("8"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        before = counts(session)
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                selection_create(
                    account_id,
                    instrument_id,
                    fingerprint,
                    average_cost="50.00",
                    market_price="60.00",
                    accrued="1.00",
                ),
            ),
        )
        assert result.success is True
        item = result.items[0]
        assert item.action is BrokerSnapshotApplyItemAction.CREATED
        assert item.quantity == Decimal("8")
        assert item.average_cost_per_unit_kopecks == 5_000
        assert item.market_price_per_unit_kopecks == 6_000
        assert item.accrued_interest_kopecks == 100
        assert item.market_value_kopecks == 48_100
        assert item.cost_basis_kopecks == 40_000
        assert item.unrealized_result_kopecks == 8_100
        after = counts(session)
        assert after[0] == before[0] + 1
        assert after[1:] == before[1:]
    finally:
        session.close()
        database.engine.dispose()


# --- 8. provider-only missing required local input => zero writes ---


def test_provider_only_missing_local_input_zero_writes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_month_account_instrument(session)
        reviewed = complete_snapshot(quantity=Decimal("8"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                BrokerSnapshotApplySelection(
                    account_id=account_id,
                    instrument_id=instrument_id,
                    fingerprint=fingerprint,
                    action=BrokerSnapshotApplyAction.CREATE,
                    market_price=MarketPriceDecision(
                        action=DependentFieldAction.REPLACE,
                        market_price_per_unit="60.00",
                        price_date=date(2030, 6, 15),
                        price_source=PriceSource.MANUAL,
                    ),
                ),
            ),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.VALIDATION_ERROR
        assert (
            get_position_snapshot_by_key(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
            )
            is None
        )
    finally:
        session.close()
        database.engine.dispose()


# --- 9. provider-only unresolved account/instrument => non-applyable ---


def test_unresolved_identity_is_non_applyable(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_month_account_instrument(session, isin=None)
        reviewed = complete_snapshot(quantity=Decimal("8"))
        empty_mapping = OwnerMappingInput()
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=empty_mapping,
            selections=(
                selection_create(
                    account_id,
                    instrument_id,
                    "deadbeef" * 8,
                    average_cost="50.00",
                    market_price="60.00",
                ),
            ),
        )
        assert result.success is False
        assert result.error_code in {
            BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED,
            BrokerSnapshotApplyFailureCode.VALIDATION_ERROR,
        }
        assert (
            get_position_snapshot_by_key(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
            )
            is None
        )
        assert counts(session)[1:] == (1, 1, 0)
    finally:
        session.close()
        database.engine.dispose()


# --- 10. zero/missing provider position never deletes/creates zero row ---


def test_zero_provider_quantity_never_deletes_or_creates_zero(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("0"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.VALIDATION_ERROR
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()


def test_hermes_only_missing_provider_row_never_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = BrokerSnapshot(
            provider=ALFA_PRO_PROVIDER,
            status=SnapshotStatus.COMPLETE,
            source_as_of=SOURCE_AS_OF,
            accounts=(BrokerAccount(provider_account_id=PROVIDER_ACCOUNT),),
            subaccounts=(),
            sections=(),
            positions=(),
            cash_balances=(),
            warnings=(),
            provenance=_provenance(),
        )
        mapping = mapping_for(account_id)
        hermes = load_hermes_state_for_month(session, month_id)
        preview = build_reconciliation_preview(snapshot=reviewed, hermes=hermes, mapping=mapping)
        hermes_only = [
            row for row in preview.positions if row.status is PositionRowStatus.HERMES_ONLY
        ]
        assert len(hermes_only) == 1
        fingerprint = position_apply_fingerprint(
            preview=preview,
            row=hermes_only[0],
            mapping=mapping,
            snapshot=snapshot,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.VALIDATION_ERROR
        assert session.get(PositionSnapshot, snapshot.id) is not None
    finally:
        session.close()
        database.engine.dispose()


# --- 11. transient account mapping only; no new mapping persistence ---


def test_no_persistent_mapping_tables_or_provider_ids(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, _ = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        names = table_names(tmp_path / "broker-apply.db")
        assert not any("alfa" in name.lower() for name in names)
        assert not any("broker_map" in name.lower() for name in names)
        assert not any("provider_map" in name.lower() for name in names)
        blob = persisted_text(tmp_path / "broker-apply.db")
        assert PROVIDER_ACCOUNT not in blob
        assert PROVIDER_INSTRUMENT not in blob
        assert "SUB-SECRET" not in blob
    finally:
        session.close()
        database.engine.dispose()


# --- 12. fresh provider quantity change => preview_changed / zero writes ---


def test_fresh_provider_quantity_change_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        provider = FakeSnapshotProvider(complete_snapshot(quantity=Decimal("16")))
        result = apply_now(
            session,
            provider,
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
        assert provider.calls == 1
    finally:
        session.close()
        database.engine.dispose()


# --- 13. fresh identity/mapping change => preview_changed ---


def test_fresh_mapping_change_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        other = create_account(session, name="Other Broker", account_type=AccountType.BROKERAGE)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        changed = OwnerMappingInput(
            accounts=(
                AccountMappingInput(
                    hermes_account_id=other.id,
                    provider_account_id=PROVIDER_ACCOUNT,
                ),
            )
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=changed,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()


# --- 14. local PositionSnapshot changed after preview => preview_changed ---


def test_local_position_change_after_preview_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        update_position_snapshot(session, snapshot.id, quantity="11")
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("11.000000")
    finally:
        session.close()
        database.engine.dispose()


# --- 15. provider status becomes incomplete/non-eligible => zero writes ---


def test_incomplete_provider_status_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        stale = complete_snapshot(quantity=Decimal("15"), status=SnapshotStatus.INCOMPLETE)
        result = apply_now(
            session,
            FakeSnapshotProvider(stale),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()


def test_non_eligible_snapshot_is_preview_changed(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        stale = complete_snapshot(quantity=Decimal("15"), eligible=False)
        result = apply_now(
            session,
            FakeSnapshotProvider(stale),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PREVIEW_CHANGED
        assert session.get(PositionSnapshot, snapshot.id).quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()


# --- 16-17. multi-row atomic commit and second-row rollback ---


def test_multi_row_selected_set_commits_atomically(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, first_id = build_month_account_instrument(session)
        second = create_instrument(
            session,
            name="Second Bond",
            instrument_type=InstrumentType.BOND,
            isin="RU000A0JX0K0",
        )
        first_snap = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=first_id,
            quantity="10",
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            price_date=date(2030, 6, 15),
        )
        second_snap = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=second.id,
            quantity="4",
            average_cost_per_unit="80.00",
            market_price_per_unit="90.00",
            price_date=date(2030, 6, 15),
        )
        reviewed = complete_snapshot(
            quantity=Decimal("15"),
            extra_positions=(
                _position(
                    quantity=Decimal("7"),
                    provider_instrument_id="PO-SECOND",
                    isin="RU000A0JX0K0",
                ),
            ),
        )
        mapping = mapping_for(account_id)
        first_fp = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=first_id,
        )
        second_fp = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=second.id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                selection_update(account_id, first_id, first_fp, **keep_all()),
                selection_update(account_id, second.id, second_fp, **keep_all()),
            ),
        )
        assert result.success is True
        assert len(result.items) == 2
        assert session.get(PositionSnapshot, first_snap.id).quantity == Decimal("15")
        assert session.get(PositionSnapshot, second_snap.id).quantity == Decimal("7")
    finally:
        session.close()
        database.engine.dispose()


def test_second_row_failure_rolls_back_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hermes_finance.services import broker_snapshot_apply as module

    session, database = session_for(tmp_path)
    try:
        month_id, account_id, first_id = build_month_account_instrument(session)
        second = create_instrument(
            session,
            name="Second Bond",
            instrument_type=InstrumentType.BOND,
            isin="RU000A0JX0K0",
        )
        first_snap = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=first_id,
            quantity="10",
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            price_date=date(2030, 6, 15),
        )
        second_snap = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=second.id,
            quantity="4",
            average_cost_per_unit="80.00",
            market_price_per_unit="90.00",
            price_date=date(2030, 6, 15),
        )
        reviewed = complete_snapshot(
            quantity=Decimal("15"),
            extra_positions=(
                _position(
                    quantity=Decimal("7"),
                    provider_instrument_id="PO-SECOND",
                    isin="RU000A0JX0K0",
                ),
            ),
        )
        mapping = mapping_for(account_id)
        first_fp = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=first_id,
        )
        second_fp = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=second.id,
        )
        original = module.stage_update_position_snapshot
        calls = 0

        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic second-row persistence failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "stage_update_position_snapshot", fail_second)
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(
                selection_update(account_id, first_id, first_fp, **keep_all()),
                selection_update(account_id, second.id, second_fp, **keep_all()),
            ),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PERSISTENCE_ERROR
        assert result.items == ()
        session.expire_all()
        assert session.get(PositionSnapshot, first_snap.id).quantity == Decimal("10.000000")
        assert session.get(PositionSnapshot, second_snap.id).quantity == Decimal("4.000000")
    finally:
        session.close()
        database.engine.dispose()


# --- 18. CLOSED month rejects with zero writes ---


def test_closed_month_rejects_before_provider_call(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        close_reporting_month(session, month_id)
        provider = FakeSnapshotProvider(reviewed)
        result = apply_now(
            session,
            provider,
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.CLOSED_MONTH
        assert provider.calls == 0
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()


# --- 19. no-op selection writes nothing ---


def test_noop_selection_writes_nothing(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("10"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        before = snapshot.updated_at
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        assert result.items[0].action is BrokerSnapshotApplyItemAction.UNCHANGED
        stored = session.get(PositionSnapshot, snapshot.id)
        assert stored is not None
        assert stored.quantity == Decimal("10.000000")
        assert stored.updated_at == before
    finally:
        session.close()
        database.engine.dispose()


# --- 20. exact Decimal quantity including float-hostile values ---


def test_exact_decimal_float_hostile_quantity(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, _ = build_matched(session, quantity="0.100000")
        hostile = Decimal("0.300000")
        reviewed = complete_snapshot(quantity=hostile)
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        assert result.items[0].quantity == Decimal("0.300000")
        stored = get_position_snapshot_by_key(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        assert stored is not None
        assert stored.quantity == Decimal("0.300000")
    finally:
        session.close()
        database.engine.dispose()


# --- 21. no raw provider payload/IDs persisted/logged ---


def test_no_raw_provider_payload_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    session, database = session_for(tmp_path)
    try:
        caplog.set_level(logging.DEBUG)
        month_id, account_id, instrument_id, _ = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        result = apply_now(
            session,
            FakeSnapshotProvider(reviewed),
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is True
        combined = "\n".join(record.getMessage() for record in caplog.records)
        assert PROVIDER_ACCOUNT not in combined
        assert PROVIDER_INSTRUMENT not in combined
        assert "raw_payload" not in combined
        if result.message:
            assert PROVIDER_ACCOUNT not in result.message
    finally:
        session.close()
        database.engine.dispose()


# --- 22. import/test collection makes zero network calls ---


def test_apply_module_import_does_not_touch_live_alfa() -> None:
    source = inspect.getsource(
        __import__("hermes_finance.services.broker_snapshot_apply", fromlist=["*"])
    )
    assert "AlfaProBrokerSnapshotProvider" not in source
    assert "127.0.0.1:3366" not in source
    assert "ws://" not in source
    assert "ClientPositionEntity" not in source


def test_provider_error_is_sanitized(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id, snapshot = build_matched(session)
        reviewed = complete_snapshot(quantity=Decimal("15"))
        mapping = mapping_for(account_id)
        fingerprint = reviewed_fingerprint(
            session,
            reviewed,
            month_id=month_id,
            mapping=mapping,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        provider = FakeSnapshotProvider(reviewed)
        provider.error = RuntimeError(f"frame {PROVIDER_ACCOUNT} raw_payload=secret")
        result = apply_now(
            session,
            provider,
            month_id=month_id,
            mapping=mapping,
            selections=(selection_update(account_id, instrument_id, fingerprint, **keep_all()),),
        )
        assert result.success is False
        assert result.error_code is BrokerSnapshotApplyFailureCode.PROVIDER_ERROR
        assert result.message is not None
        assert PROVIDER_ACCOUNT not in result.message
        assert "raw_payload" not in result.message
        assert session.get(PositionSnapshot, snapshot.id).quantity == Decimal("10.000000")
    finally:
        session.close()
        database.engine.dispose()
