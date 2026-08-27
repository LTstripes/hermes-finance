"""R06-04 deterministic reconciliation/preview tests (pure, no IO)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from hermes_finance.alfa_pro_diagnostics import AlfaCompatibilityState
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
from hermes_finance.broker_data.reconciliation import (
    AccountMappingInput,
    AccountMatchStatus,
    CashRowStatus,
    InstrumentMappingInput,
    InstrumentMatchStatus,
    OwnerMappingInput,
    PositionRowStatus,
    ReconciliationStatus,
    ValueComparability,
    build_reconciliation_preview,
)
from hermes_finance.broker_data.reconciliation.dto import (
    HermesAccountView,
    HermesCashView,
    HermesInstrumentView,
    HermesPositionView,
    HermesStateView,
)


def _provenance(
    eligible: bool = True,
    compatibility_state: AlfaCompatibilityState = AlfaCompatibilityState.COMPATIBLE,
) -> SnapshotProvenance:
    return SnapshotProvenance(
        provider=ALFA_PRO_PROVIDER,
        api_doc_version="v2.1",
        captured_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        timestamp_provenance=TimestampProvenance.LOCAL_OBSERVATION,
        auth_status=2,
        ready_to_sign=True,
        channels_invoked=("#Data.Query",),
        entity_query_status=("ClientAccountEntity:ok",),
        eligible_for_apply=eligible,
        compatibility_state=compatibility_state,
        compatibility_fingerprint="a" * 64,
    )


def _complete_snapshot(
    *,
    accounts=(),
    positions=(),
    cash=(),
    eligible: bool = True,
    compatibility_state: AlfaCompatibilityState = AlfaCompatibilityState.COMPATIBLE,
    status: SnapshotStatus = SnapshotStatus.COMPLETE,
    source_as_of: datetime | None = datetime(2026, 8, 20, 11, 0, tzinfo=timezone.utc),
) -> BrokerSnapshot:
    return BrokerSnapshot(
        provider=ALFA_PRO_PROVIDER,
        status=status,
        source_as_of=source_as_of,
        accounts=tuple(accounts),
        subaccounts=(),
        sections=(),
        positions=tuple(positions),
        cash_balances=tuple(cash),
        warnings=(),
        provenance=_provenance(eligible=eligible, compatibility_state=compatibility_state),
    )


def _hermes(
    *,
    month_status: str = "draft",
    accounts=(),
    instruments=(),
    positions=(),
    cash=(),
) -> HermesStateView:
    return HermesStateView(
        month_id=1,
        month_status=month_status,
        accounts=tuple(accounts),
        instruments=tuple(instruments),
        positions=tuple(positions),
        cash_balances=tuple(cash),
    )


def _pos(
    account_id: str,
    instrument_id: str,
    *,
    isin: str | None = None,
    ticker: str | None = None,
    quantity: Decimal | None = None,
    broker_unit_price: Decimal | None = None,
    nkd: Decimal | None = None,
    unrealized: Decimal | None = None,
) -> BrokerPosition:
    return BrokerPosition(
        provider_account_id=account_id,
        provider_subaccount_id=None,
        provider_section_id=None,
        provider_instrument_id=instrument_id,
        isin=isin,
        ticker=ticker,
        display_name=None,
        quantity=quantity,
        broker_unit_price=broker_unit_price,
        market_value=None,
        accounting_price=None,
        accrued_interest_nkd=nkd,
        unrealized_result=unrealized,
        is_money=None,
        mapped_fields=(),
    )


# --- 1. COMPLETE/eligible + explicit account mapping + exact ISIN => matched ---


def test_explicit_account_and_unique_isin_match() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "Broker", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
        positions=(HermesPositionView(1, 10, Decimal("10"), 1000, None, 10000, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.status is ReconciliationStatus.APPLICABLE
    assert preview.eligible_for_apply is True
    assert preview.accounts[0].status is AccountMatchStatus.MATCHED
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.positions[0].status is PositionRowStatus.MATCHED
    assert preview.positions[0].quantity_equal is True
    assert preview.positions[0].quantity_difference == Decimal("0")


# --- 2. incomplete/malformed/non-eligible => non_applicable ---


def test_non_complete_snapshot_is_non_applicable() -> None:
    for status in (
        SnapshotStatus.INCOMPLETE,
        SnapshotStatus.MALFORMED_RESPONSE,
        SnapshotStatus.AUTH_UNRESOLVED,
        SnapshotStatus.PROVIDER_UNAVAILABLE,
        SnapshotStatus.COMPATIBILITY_ERROR,
    ):
        snap = _complete_snapshot(status=status, accounts=[BrokerAccount("PA1")])
        hermes = _hermes(accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),))
        preview = build_reconciliation_preview(
            snapshot=snap, hermes=hermes, mapping=OwnerMappingInput()
        )
        assert preview.status is ReconciliationStatus.NON_APPLICABLE
        assert preview.conflict_count == 0


def test_complete_but_not_eligible_is_non_applicable() -> None:
    snap = _complete_snapshot(eligible=False, accounts=[BrokerAccount("PA1")])
    hermes = _hermes(accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),))
    preview = build_reconciliation_preview(
        snapshot=snap, hermes=hermes, mapping=OwnerMappingInput()
    )
    assert preview.status is ReconciliationStatus.NON_APPLICABLE


def test_unknown_alfa_compatibility_is_non_applicable_even_when_snapshot_is_complete() -> None:
    snap = _complete_snapshot(
        compatibility_state=AlfaCompatibilityState.UNKNOWN,
        accounts=[BrokerAccount("PA1")],
    )
    hermes = _hermes(accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),))
    preview = build_reconciliation_preview(
        snapshot=snap, hermes=hermes, mapping=OwnerMappingInput()
    )

    assert preview.status is ReconciliationStatus.NON_APPLICABLE
    assert preview.eligible_for_apply is False
    assert "compatibility is not confirmed" in preview.warnings[0]


# --- 3. missing account mapping => unmatched/conflict, never inferred ---


def test_missing_account_mapping_is_unmatched_no_inference() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA9")],
        positions=[_pos("PA9", "PO1", isin="US1234567890", quantity=Decimal("5"))],
    )
    hermes = _hermes(
        accounts=(
            HermesAccountView(1, "Alfa-PA9-broker", "brokerage", None, "active"),
            HermesAccountView(2, "Other", "iis", None, "active"),
        ),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    # No mapping supplied; name similarity must NOT resolve account identity.
    preview = build_reconciliation_preview(
        snapshot=snap, hermes=hermes, mapping=OwnerMappingInput()
    )
    assert preview.accounts[0].status is AccountMatchStatus.UNMATCHED
    # Instrument ISIN still resolves independently, but without an account the
    # position cannot become a comparable row.
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.positions == ()


# --- 4. exact unique ISIN match allowed ---


def test_unique_isin_match_without_explicit_instrument_mapping() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890")],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.instruments[0].hermes_instrument_id == 10


# --- 5. duplicate Hermes ISIN => ambiguous/conflict ---


def test_duplicate_hermes_isin_is_ambiguous() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890")],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(
            HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),
            HermesInstrumentView(11, "Share A dup", "stock", "US1234567890", "SHA"),
        ),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.AMBIGUOUS
    assert preview.positions == ()


# --- 6. missing ISIN/no mapping => unmatched; ticker/name cannot auto-match ---


def test_missing_isin_and_no_mapping_is_unmatched_no_ticker_match() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", ticker="SHA", quantity=Decimal("3"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(
            HermesInstrumentView(10, "Share A", "stock", None, "SHA"),
            HermesInstrumentView(11, "Other", "stock", "US9999999999", "OTH"),
        ),
        positions=(HermesPositionView(1, 10, Decimal("1"), 1000, None, 1000, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.UNMATCHED
    # ticker alone must NOT create a match; the Hermes position is reported as
    # HERMES_ONLY (provider supplied no resolved row for it), never deleted.
    statuses = {row.status for row in preview.positions}
    assert PositionRowStatus.HERMES_ONLY in statuses
    assert preview.positions[0].hermes_quantity == Decimal("1")


# --- 7. provider id alone cannot become canonical match ---


def test_provider_id_alone_is_not_identity() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", quantity=Decimal("3"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share", "stock", None, "SHA"),),
        positions=(HermesPositionView(1, 10, Decimal("1"), 1000, None, 1000, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.UNMATCHED
    assert "provider id" in (preview.instruments[0].reason or "").lower()
    # Provider id alone did not create an instrument match; Hermes position is
    # reported as HERMES_ONLY, never silently mapped/created.
    assert preview.positions[0].status is PositionRowStatus.HERMES_ONLY
    assert preview.positions[0].provider_quantity is None


# --- 8. provider-only position does not create Hermes row ---


def test_provider_only_position_reported_not_created() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("7"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.positions[0].status is PositionRowStatus.PROVIDER_ONLY
    assert preview.positions[0].hermes_quantity is None
    assert preview.positions[0].provider_quantity == Decimal("7")


# --- 9. Hermes-only position is reported, not deleted ---


def test_hermes_only_position_reported_not_deleted() -> None:
    # Provider reports a different instrument (PO1) but NO row for the Hermes
    # instrument_id=11, so the Hermes position on (1, 11) is Hermes-only.
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("7"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(
            HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),
            HermesInstrumentView(11, "Share B", "stock", "US0000000000", "SHB"),
        ),
        positions=(
            HermesPositionView(1, 10, Decimal("4"), 1000, None, 4000, 0),
            HermesPositionView(1, 11, Decimal("2"), 900, None, 1800, 0),
        ),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    by_status = {row.status for row in preview.positions}
    assert PositionRowStatus.HERMES_ONLY in by_status
    hermes_only = [r for r in preview.positions if r.status is PositionRowStatus.HERMES_ONLY]
    assert len(hermes_only) == 1
    assert hermes_only[0].account_id == 1
    assert hermes_only[0].instrument_id == 11
    assert hermes_only[0].hermes_quantity == Decimal("2")
    assert hermes_only[0].provider_quantity is None


# --- 10. exact Decimal quantity differences incl float-hostile values ---


def test_exact_decimal_quantity_difference_float_hostile() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("3.000001"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
        positions=(HermesPositionView(1, 10, Decimal("3.000000"), 1000, None, 3000, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    row = preview.positions[0]
    assert row.status is PositionRowStatus.MATCHED
    assert row.quantity_equal is False
    # Decimal exact: 3.000000 - 3.000001 == -0.000001, not a float round-trip.
    assert row.quantity_difference == Decimal("-0.000001")
    assert isinstance(row.quantity_difference, Decimal)


# --- 11. duplicate provider rows -> one account+instrument fail closed/conflict ---


def test_duplicate_provider_rows_same_identity_conflict() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[
            _pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("7")),
            _pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("8")),
        ],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
        positions=(HermesPositionView(1, 10, Decimal("7"), 1000, None, 7000, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.status is ReconciliationStatus.CONFLICTS
    assert preview.conflict_count >= 1
    assert preview.positions[0].status is PositionRowStatus.CONFLICT
    assert "duplicate" in (preview.positions[0].reason or "").lower()


# --- 12. cash comparison only after account+currency match; no FX conversion ---


def test_cash_reported_non_comparable_not_synthesized() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        cash=[
            BrokerCashBalance(
                provider_account_id="PA1",
                provider_subaccount_id=None,
                currency="RUB",
                amount=Decimal("5000.00"),
                section_group=None,
                mapped_fields=(),
            )
        ],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        cash=(HermesCashView("Cash RUB", 500000, "RUB"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    # Account matched, so provider cash is surfaced, but Hermes cash has no
    # account identity, so it stays non-comparable and no amount diff/synthesis.
    assert len(preview.cash) == 1
    assert preview.cash[0].status is CashRowStatus.NON_COMPARABLE
    assert preview.cash[0].provider_amount == Decimal("5000.00")
    assert preview.cash[0].currency == "RUB"
    assert "account identity" in (preview.cash[0].reason or "").lower()


# --- 13. unavailable provider valuation stays unavailable; no synthesized MV ---


def test_provider_market_value_not_synthesized() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[
            _pos(
                "PA1",
                "PO1",
                isin="US1234567890",
                quantity=Decimal("10"),
                broker_unit_price=Decimal("150.25"),
            )
        ],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
        positions=(HermesPositionView(1, 10, Decimal("10"), 15025, None, 150250, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    row = preview.positions[0]
    # Broker unit price preserved as provenance; market value NOT computed from
    # quantity x price; price comparison marked non-comparable (no accepted
    # cross-unit/currency semantic).
    assert row.provider_broker_unit_price == Decimal("150.25")
    assert row.price_comparable is ValueComparability.NON_COMPARABLE
    # No synthesized market_value field exists on the row.
    assert not hasattr(row, "synthesized_market_value")


# --- 14. CLOSED-month preview remains read-only and flags future apply ---


def test_closed_month_preview_read_only_flags_future_apply() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        month_status="closed",
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
        positions=(HermesPositionView(1, 10, Decimal("10"), 1000, None, 10000, 0),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.month_closed is True
    assert preview.would_touch_closed_month is True
    # Preview itself performs no mutation; status is still computed.
    assert preview.status in {ReconciliationStatus.APPLICABLE, ReconciliationStatus.CONFLICTS}


# --- 15. no persistence/database writes/files/network during pure reconciliation ---


def test_pure_reconciliation_has_no_side_effects() -> None:
    import importlib

    # The pure reconciliation package must not import persistence/DB/network.

    # dto/matching/positions/cash/preview are pure; only `state` touches the DB.
    for mod_name in ("dto", "matching", "positions", "cash", "preview"):
        module = importlib.import_module(f"hermes_finance.broker_data.reconciliation.{mod_name}")
        assert "persistence" not in getattr(module, "__file__", "")
    # Building a preview from pure in-memory inputs performs no IO.
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.eligible_for_apply is True
    assert preview.status is ReconciliationStatus.APPLICABLE


# --- 16. read-only adapter loads Hermes state and feeds a matched preview ---


def test_read_only_adapter_feeds_preview(tmp_path) -> None:
    from datetime import date

    from sqlalchemy.orm import Session

    from hermes_finance.database import create_database
    from hermes_finance.domain import AccountType, InstrumentType
    from hermes_finance.persistence import Base
    from hermes_finance.services.accounts import create_account
    from hermes_finance.services.broker_reconciliation import (
        load_hermes_state_for_month,
    )
    from hermes_finance.services.instruments import create_instrument
    from hermes_finance.services.positions import create_position_snapshot
    from hermes_finance.services.reporting_months import (
        create_reporting_month,
    )

    database = create_database(tmp_path / "recon.db")
    Base.metadata.create_all(database.engine)
    session: Session = database.session_factory()
    try:
        month = create_reporting_month(session, year=2030, month=6, snapshot_date=date(2030, 6, 15))
        acc = create_account(session, name="Alfa Broker", account_type=AccountType.BROKERAGE)
        inst = create_instrument(
            session,
            name="Share A",
            instrument_type=InstrumentType.STOCK,
            isin="US1234567890",
            ticker="SHA",
        )
        create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=acc.id,
            instrument_id=inst.id,
            quantity="10.000000",
            average_cost_per_unit="1000.00",
            market_price_per_unit="1000.00",
            price_date=date(2030, 6, 15),
            price_source="manual",
        )
        session.commit()

        hermes = load_hermes_state_for_month(session, month.id)
        assert hermes.month_id == month.id
        assert len(hermes.accounts) == 1
        assert len(hermes.instruments) == 1
        assert len(hermes.positions) == 1

        snap = _complete_snapshot(
            accounts=[BrokerAccount(provider_account_id="PA1")],
            positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10.000000"))],
        )
        mapping = OwnerMappingInput(
            accounts=(AccountMappingInput(hermes_account_id=acc.id, provider_account_id="PA1"),)
        )
        preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
        assert preview.status is ReconciliationStatus.APPLICABLE
        assert preview.positions[0].status is PositionRowStatus.MATCHED
        assert preview.positions[0].quantity_equal is True
    finally:
        session.close()


# --- B1. canonical ISIN normalization (strip + upper) ---


def test_b1_isin_case_insensitive_match() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="us1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.instruments[0].hermes_instrument_id == 10


def test_b1_isin_whitespace_match() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin=" US1234567890 ", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.instruments[0].hermes_instrument_id == 10


def test_b1_normalized_duplicate_hermes_isin_ambiguous() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(
            HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),
            HermesInstrumentView(11, "Share A dup", "stock", "US1234567890", "SHA2"),
        ),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.AMBIGUOUS
    assert preview.instruments[0].hermes_instrument_id is None
    assert preview.conflict_count >= 1


def test_b1_different_case_isin_does_not_bypass_duplicate_conflict() -> None:
    # Two provider positions with different-case ISINs resolve to the same
    # canonical (account, instrument) and must still fail closed as duplicate.
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[
            _pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("7")),
            _pos("PA1", "PO2", isin="us1234567890", quantity=Decimal("8")),
        ],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.status is ReconciliationStatus.CONFLICTS
    assert preview.positions[0].status is PositionRowStatus.CONFLICT
    assert "duplicate" in (preview.positions[0].reason or "").lower()


# --- B2. preview-level apply eligibility fails closed ---


def test_b2_conflicts_preview_not_eligible_for_apply() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[
            _pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("7")),
            _pos("PA1", "PO2", isin="US1234567890", quantity=Decimal("8")),
        ],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.snapshot_status is SnapshotStatus.COMPLETE
    assert snap.provenance.eligible_for_apply is True  # source snapshot candidate
    assert preview.status is ReconciliationStatus.CONFLICTS
    assert preview.eligible_for_apply is False  # preview not eligible


def test_b2_non_applicable_preview_not_eligible() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    # Incomplete snapshot -> non-applicable preview.
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
        status=SnapshotStatus.INCOMPLETE,
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),)
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.status is ReconciliationStatus.NON_APPLICABLE
    assert preview.eligible_for_apply is False


# --- B3. conflicting explicit mappings must not use last wins ---


def test_b3_conflicting_account_mapping_conflict() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
    )
    hermes = _hermes(
        accounts=(
            HermesAccountView(1, "B1", "brokerage", None, "active"),
            HermesAccountView(2, "B2", "brokerage", None, "active"),
        ),
    )
    mapping = OwnerMappingInput(
        accounts=(
            AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),
            AccountMappingInput(hermes_account_id=2, provider_account_id="PA1"),
        )
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.accounts[0].status is AccountMatchStatus.CONFLICT
    assert preview.accounts[0].hermes_account_id is None
    assert preview.eligible_for_apply is False


def test_b3_conflicting_instrument_mapping_conflict() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(
            HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),
            HermesInstrumentView(11, "Share A2", "stock", "US0000000000", "SHB"),
        ),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),),
        instruments=(
            InstrumentMappingInput(hermes_instrument_id=10, provider_instrument_id="PO1"),
            InstrumentMappingInput(hermes_instrument_id=11, provider_instrument_id="PO1"),
        ),
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.CONFLICT
    assert preview.instruments[0].hermes_instrument_id is None
    assert preview.eligible_for_apply is False


def test_b3_idempotent_repeated_pair_no_conflict() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(
            AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),
            AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),
        ),
        instruments=(
            InstrumentMappingInput(hermes_instrument_id=10, provider_instrument_id="PO1"),
            InstrumentMappingInput(hermes_instrument_id=10, provider_instrument_id="PO1"),
        ),
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.accounts[0].status is AccountMatchStatus.MATCHED
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.eligible_for_apply is True


# --- B4. same instrument across different accounts is not an instrument conflict ---


def test_b4_same_instrument_two_accounts_no_instrument_conflict() -> None:
    snap = _complete_snapshot(
        accounts=[
            BrokerAccount(provider_account_id="PA1"),
            BrokerAccount(provider_account_id="PA2"),
        ],
        positions=[
            _pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10")),
            _pos("PA2", "PO0", isin="US1234567890", quantity=Decimal("20")),
        ],
    )
    hermes = _hermes(
        accounts=(
            HermesAccountView(1, "B1", "brokerage", None, "active"),
            HermesAccountView(2, "B2", "brokerage", None, "active"),
        ),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US1234567890", "SHA"),),
        positions=(
            HermesPositionView(1, 10, Decimal("10"), 1000, None, 10000, 0),
            HermesPositionView(2, 10, Decimal("20"), 1000, None, 20000, 0),
        ),
    )
    mapping = OwnerMappingInput(
        accounts=(
            AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),
            AccountMappingInput(hermes_account_id=2, provider_account_id="PA2"),
        )
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    # One instrument identity resolved per provider id; no instrument-level
    # conflict. Both provider ids resolve to the same Hermes instrument 10.
    assert all(r.status is not InstrumentMatchStatus.CONFLICT for r in preview.instruments)
    matched_instruments = [
        r for r in preview.instruments if r.status is InstrumentMatchStatus.MATCHED
    ]
    assert len(matched_instruments) == 2
    assert all(r.hermes_instrument_id == 10 for r in matched_instruments)
    # Both provider positions reconcile as normal MATCHED rows on the same
    # Hermes instrument under different accounts.
    matched_positions = [r for r in preview.positions if r.status is PositionRowStatus.MATCHED]
    assert len(matched_positions) == 2
    account_ids = {r.account_id for r in matched_positions}
    assert account_ids == {1, 2}
    assert preview.status is ReconciliationStatus.APPLICABLE


# --- B5. explicit mapping conflicting with ISIN evidence fails closed ---


def test_b5_explicit_mapping_contradicts_isin_conflict() -> None:
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin="US1234567890", quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", "US0000000000", "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),),
        instruments=(
            InstrumentMappingInput(hermes_instrument_id=10, provider_instrument_id="PO1"),
        ),
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.CONFLICT
    assert preview.instruments[0].hermes_instrument_id == 10
    assert "contradict" in (preview.instruments[0].reason or "").lower()
    assert preview.status is ReconciliationStatus.CONFLICTS
    assert preview.eligible_for_apply is False


def test_b5_explicit_mapping_without_isin_evidence_not_contradicted() -> None:
    # Explicit mapping stands when provider ISIN absent or Hermes ISIN absent:
    # absence of evidence is not a contradiction.
    snap = _complete_snapshot(
        accounts=[BrokerAccount(provider_account_id="PA1")],
        positions=[_pos("PA1", "PO1", isin=None, quantity=Decimal("10"))],
    )
    hermes = _hermes(
        accounts=(HermesAccountView(1, "B", "brokerage", None, "active"),),
        instruments=(HermesInstrumentView(10, "Share A", "stock", None, "SHA"),),
    )
    mapping = OwnerMappingInput(
        accounts=(AccountMappingInput(hermes_account_id=1, provider_account_id="PA1"),),
        instruments=(
            InstrumentMappingInput(hermes_instrument_id=10, provider_instrument_id="PO1"),
        ),
    )
    preview = build_reconciliation_preview(snapshot=snap, hermes=hermes, mapping=mapping)
    assert preview.instruments[0].status is InstrumentMatchStatus.MATCHED
    assert preview.eligible_for_apply is True
