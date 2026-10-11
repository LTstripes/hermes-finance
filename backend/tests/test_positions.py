from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.database import Database, create_database
from hermes_finance.domain import AccountType, InstrumentType, PriceSource, RubleAmount
from hermes_finance.persistence import Base, Instrument, PositionQuoteProvenance
from hermes_finance.services.accounts import create_account
from hermes_finance.services.concurrency import ConcurrencyError
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import (
    PositionSnapshotNotFoundError,
    apply_snapshot_market_quote,
    create_position_snapshot,
    delete_position_snapshot,
    get_position_snapshot,
    get_position_snapshot_by_key,
    list_position_snapshots,
    stage_create_position_snapshot,
    update_position_snapshot,
)
from hermes_finance.services.reporting_months import create_reporting_month


def _native_source(session):
    from datetime import UTC

    from hermes_finance.persistence import MyBrokerImport

    row = MyBrokerImport(
        document_sha256="a" * 64,
        covered_from=date(2030, 5, 1),
        covered_to=date(2030, 5, 31),
        parser_version="synthetic",
        confirmation_digest="b" * 64,
        normalized_json='{"positions":[],"trades":[],"money":[]}',
        mappings_json="[]",
        accepted_at=datetime.now(UTC),
    )
    session.add(row)
    session.flush()
    return row.id


@pytest.mark.parametrize(
    "kind,basis",
    [
        (InstrumentType.STOCK, "not_applicable"),
        (InstrumentType.BOND, "unknown"),
        (InstrumentType.BOND, "included"),
        (InstrumentType.BOND, "excluded"),
    ],
)
def test_native_total_net_unknown_roundtrip_readers_and_write_guards(tmp_path, kind, basis):
    from sqlalchemy.exc import IntegrityError

    from hermes_finance.api.investment_flows import _response
    from hermes_finance.api.json_export import build_raw_source_data
    from hermes_finance.api.positions import _response_from_snapshot
    from hermes_finance.domain import PerformanceScope, RubleAmount
    from hermes_finance.services.dashboard import _account_results, _instrument_class_results
    from hermes_finance.services.goals import get_or_create_main_goal
    from hermes_finance.services.investment_cash_flows import (
        delete_investment_cash_flow,
        update_investment_cash_flow,
    )
    from hermes_finance.services.reporting_months import (
        ClosedReportingMonthError,
        close_reporting_month,
        get_reporting_month,
    )
    from hermes_finance.services.settings import get_or_create_settings
    from hermes_finance.services.source_native import stage_native_payout, stage_native_position
    from hermes_finance.services.valuation_points import valuation_point_for_month

    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session, instrument_type=kind)
        from hermes_finance.services.iis import create_iis_profile
        from hermes_finance.services.salary_tax_context import upsert_salary_tax_year_context

        create_iis_profile(session, account_id=account_id, iis_type="A", opened_at=date(2030, 1, 1))
        upsert_salary_tax_year_context(
            session, tax_year=2030, effective_from_month=5, opening_taxable_gross="0.00"
        )
        source_id = _native_source(session)
        args = dict(
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="3",
            market_value=RubleAmount(1000001),
            price_date=date(2030, 5, 12),
            source_import_id=source_id,
            source_row_key="c" * 64,
            asset_kind=kind.value,
            bond_nkd_basis=basis,
        )
        row = stage_native_position(session, **args)
        payout_args = dict(
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            flow_type="dividend" if kind is InstrumentType.STOCK else "coupon",
            event_date=date(2030, 5, 10),
            net_amount=RubleAmount(30001),
            source_import_id=source_id,
            source_row_key="d" * 64,
        )
        flow = stage_native_payout(session, **payout_args)
        second = create_instrument(session, name="Synthetic manual", instrument_type=kind)
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=second.id,
            quantity=1,
            average_cost_per_unit="5.00",
            market_price_per_unit="6.00",
            price_date=date(2030, 5, 12),
        )
        session.commit()
        session.expire_all()
        out = _response_from_snapshot(row).model_dump(mode="json")
        assert out["market_value"]["amount"] == "10000.01"
        assert all(
            out[f] is None
            for f in (
                "market_price_per_unit",
                "average_cost_per_unit",
                "cost_basis",
                "unrealized_result",
                "accrued_interest",
            )
        )
        assert out["bond_nkd_basis"] == basis
        payout = _response(flow).model_dump(mode="json")
        assert payout["net_amount"]["amount"] == "300.01"
        assert all(payout[f] is None for f in ("gross_amount", "tax_amount", "commission_amount"))
        assert _account_results(session, month_id)[0].unrealized_result is None
        cls = _instrument_class_results(session, month_id)[0]
        assert (
            cls.market_value.kopecks == 1000601
            and cls.cost_basis is None
            and cls.unrealized_result is None
        )
        settings = get_or_create_settings(session)
        get_or_create_main_goal(session)
        raw = build_raw_source_data(
            session, get_reporting_month(session, month_id), settings=settings
        ).model_dump(mode="json")
        assert raw["position_snapshots"][0]["cost_basis"] is None
        assert raw["investment_cash_flows"][0]["tax_amount"] is None
        point = valuation_point_for_month(
            session, month_id, scope=PerformanceScope.ACCOUNT, account_id=account_id
        )
        from hermes_finance.domain import ValuationReasonCode

        assert (
            ValuationReasonCode.UNSUPPORTED_POSITION_VALUATION.value in point.coverage.reason_codes
        )
        from unittest.mock import patch

        from hermes_finance.services import portfolio_xirr

        with patch.object(
            portfolio_xirr,
            "historical_xirr_evidence",
            side_effect=AssertionError("fallback must not promote source-native"),
        ):
            result = portfolio_xirr.xirr_for_interval(
                session,
                start_date=date(2030, 5, 12),
                end_date=date(2030, 6, 12),
                scope=PerformanceScope.ACCOUNT,
                account_id=account_id,
            )
            assert result.annualized_rate is None and result.quality.value != "exact"
            assert "source_native_exact_basis_unproven" in result.reason_codes
        from fastapi.testclient import TestClient

        from hermes_finance.main import create_app

        with TestClient(create_app(database)) as client:
            response = client.get(f"/api/positions?month_id={month_id}")
            assert response.status_code == 200 and response.json()[0]["cost_basis"] is None
            response = client.get(f"/api/investment-flows?month_id={month_id}")
            assert response.status_code == 200 and response.json()[0]["tax_amount"] is None
            response = client.get(f"/api/months/{month_id}/dashboard")
            assert response.status_code == 200, response.text
            assert response.json()["result_by_account"][0]["unrealized_result"] is None
            assert (
                response.json()["summary"]["iis"][0]["portfolio_result_without_tax_benefit"] is None
            )
            response = client.post(f"/api/months/{month_id}/export/json")
            assert response.status_code == 200, response.text
            response = client.post(f"/api/months/{month_id}/export/markdown")
            assert response.status_code == 200, response.text
            assert "300,01" in response.text and "—" in response.text
        for op in (
            lambda: update_position_snapshot(session, row.id, quantity=4),
            lambda: apply_snapshot_market_quote(
                session,
                row,
                market_price_per_unit_kopecks=1,
                price_date=date(2030, 5, 12),
                price_source=PriceSource.MANUAL,
            ),
            lambda: delete_position_snapshot(session, row.id),
            lambda: update_investment_cash_flow(session, flow.id, net_amount="1.00"),
            lambda: delete_investment_cash_flow(session, flow.id),
        ):
            with pytest.raises(ValueError, match="source-owned"):
                op()
        with pytest.raises(ValueError, match="already has"):
            stage_native_payout(session, **payout_args)
        with pytest.raises(IntegrityError):
            stage_native_position(session, **args)
        session.rollback()
        close_reporting_month(session, month_id)
        from hermes_finance.services.ai_analysis_bundle import assemble_ai_analysis_bundle

        bundle = assemble_ai_analysis_bundle(
            session, generated_at=datetime(2030, 5, 31, tzinfo=timezone.utc)
        )
        native = next(
            p for p in bundle["current_portfolio"]["positions"] if p["cost_basis"]["value"] is None
        )
        assert native["accrued_interest"]["value"] is None
        assert native["market_price_per_unit"]["value"] is None
        assert native["valuation_provenance"]["source_kind"] == "statement"
        assert (
            bundle["iis_and_tax"]["iis_accounts"][0]["portfolio_result_without_tax_benefit"][
                "value"
            ]
            is None
        )
        with pytest.raises(ClosedReportingMonthError):
            stage_native_position(session, **args)
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "change,error",
    [
        ({"market_value": RubleAmount(2**63)}, ValueError),
        ({"quantity": 1.5}, TypeError),
        ({"quantity": "0.0000001"}, ValueError),
        ({"quantity": "1000000000000"}, ValueError),
        ({"quantity": "999999999999.999999"}, ValueError),
        ({"asset_kind": "stock"}, ValueError),
        ({"bond_nkd_basis": "not_applicable"}, ValueError),
        ({"source_row_key": "missing"}, ValueError),
        ({"price_date": date(2030, 5, 13)}, ValueError),
    ],
)
def test_native_position_refuses_unproved_identity_precision_and_date(tmp_path, change, error):
    from hermes_finance.domain import RubleAmount
    from hermes_finance.services.source_native import stage_native_position

    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        args = dict(
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="3",
            market_value=RubleAmount(1000001),
            price_date=date(2030, 5, 12),
            source_import_id=_native_source(session),
            source_row_key="c" * 64,
            asset_kind="bond",
            bond_nkd_basis="unknown",
        )
        with pytest.raises(error):
            stage_native_position(session, **(args | change))
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("kind", list(InstrumentType))
def test_new_position_freezes_snapshot_type_independently_of_catalogue(
    tmp_path: Path, kind: InstrumentType
) -> None:
    from hermes_finance.services.reporting_months import (
        ClosedReportingMonthError,
        close_reporting_month,
        reopen_reporting_month,
    )

    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session, instrument_type=kind)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit="110.00",
            price_date=date(2030, 5, 12),
        )
        expected = None if kind is InstrumentType.OTHER else kind.value
        assert snapshot.historical_instrument_type == expected
        close_reporting_month(session, month_id)
        instrument = session.get(Instrument, instrument_id)
        instrument.instrument_type = "stock" if kind is not InstrumentType.STOCK else "bond"
        session.commit()
        session.expire_all()
        assert get_position_snapshot(session, snapshot.id).historical_instrument_type == expected
        close_reporting_month(session, month_id)  # idempotent close cannot recapture type
        with pytest.raises(ClosedReportingMonthError):
            update_position_snapshot(session, snapshot.id, historical_instrument_type="gold")
        reopen_reporting_month(session, month_id)
        # Reopen alone, quantity/notes and quote updates preserve historical identity.
        update_position_snapshot(session, snapshot.id, quantity=2, notes="synthetic correction")
        apply_snapshot_market_quote(
            session,
            snapshot,
            market_price_per_unit_kopecks=12000,
            price_date=date(2030, 5, 13),
            price_source=PriceSource.MANUAL,
        )
        session.commit()
        assert snapshot.historical_instrument_type == expected
        update_position_snapshot(
            session,
            snapshot.id,
            historical_instrument_type="gold",
            expected_updated_at=snapshot.updated_at,
        )
        close_reporting_month(session, month_id)
        assert snapshot.historical_instrument_type == "gold"
    finally:
        session.close()
        database.engine.dispose()


def test_legacy_unknown_is_not_repaired_by_close_reopen_or_ordinary_updates(tmp_path: Path) -> None:
    from hermes_finance.services.reporting_months import (
        close_reporting_month,
        reopen_reporting_month,
    )

    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit="110.00",
            price_date=date(2030, 5, 12),
        )
        # Synthetic legacy row, as left by migration/import.
        snapshot.historical_instrument_type = None
        session.commit()
        close_reporting_month(session, month_id)
        reopen_reporting_month(session, month_id)
        update_position_snapshot(session, snapshot.id, market_price_per_unit="120.00")
        close_reporting_month(session, month_id)
        assert snapshot.historical_instrument_type is None
        reopen_reporting_month(session, month_id)
        update_position_snapshot(session, snapshot.id, historical_instrument_type="bond")
        close_reporting_month(session, month_id)
        assert snapshot.historical_instrument_type == "bond"
        reopen_reporting_month(session, month_id)
        update_position_snapshot(session, snapshot.id, historical_instrument_type=None)
        close_reporting_month(session, month_id)
        assert snapshot.historical_instrument_type is None
    finally:
        session.close()
        database.engine.dispose()


def test_initial_identity_uses_persisted_catalogue_not_stale_session_object(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        stale = session.get(Instrument, instrument_id)
        assert stale.instrument_type == "bond"
        with database.session_factory() as catalogue_session:
            catalogue_session.get(Instrument, instrument_id).instrument_type = "gold"
            catalogue_session.commit()
        row = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=1,
            average_cost_per_unit="100.00",
            market_price_per_unit="110.00",
            price_date=date(2030, 5, 12),
        )
        assert row.historical_instrument_type == "gold"
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("corrected_type", ["bond", None])
def test_class_only_correction_preserves_non_roundtripping_legacy_valuations(
    tmp_path: Path, corrected_type: str | None
) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        row = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=3,
            average_cost_per_unit=3333,
            market_price_per_unit=6667,
            price_date=date(2030, 5, 12),
        )
        # Legacy import stores original totals alongside rounded per-unit prices.
        row.historical_instrument_type = None
        row.market_value_kopecks = 20000
        row.cost_basis_kopecks = 10000
        row.unrealized_result_kopecks = 10000
        session.commit()
        updated = update_position_snapshot(
            session,
            row.id,
            historical_instrument_type=corrected_type,
            expected_updated_at=row.updated_at,
        )
        assert updated.historical_instrument_type == corrected_type
        assert (
            updated.market_value_kopecks,
            updated.cost_basis_kopecks,
            updated.unrealized_result_kopecks,
        ) == (20000, 10000, 10000)
    finally:
        session.close()
        database.engine.dispose()


def session_for(tmp_path: Path) -> tuple[Session, Database]:
    database = create_database(tmp_path / "positions.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def build_environment(
    session: Session, *, instrument_type: InstrumentType = InstrumentType.BOND
) -> tuple[int, int, int]:
    month = create_reporting_month(session, year=2030, month=5, snapshot_date=date(2030, 5, 12))
    account = create_account(session, name="Synthetic Broker", account_type=AccountType.BROKERAGE)
    instrument = create_instrument(
        session, name="Synthetic Instrument", instrument_type=instrument_type
    )
    return month.id, account.id, instrument.id


def _run_concurrent_position_updates(
    database: Database,
    snapshot_id: int,
    expected_updated_at: datetime,
    updates: tuple[dict[str, object], dict[str, object]],
) -> list[str]:
    ready = Barrier(3)

    def run(update: dict[str, object]) -> str:
        session = database.session_factory()
        try:
            snapshot = get_position_snapshot(session, snapshot_id)
            assert snapshot.updated_at == expected_updated_at
            ready.wait(timeout=5)
            try:
                update_position_snapshot(
                    session,
                    snapshot_id,
                    expected_updated_at=expected_updated_at,
                    **update,
                )
            except ConcurrencyError:
                session.rollback()
                return "conflict"
            return "success"
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, update) for update in updates]
        ready.wait(timeout=5)
        return [future.result(timeout=10) for future in futures]


def test_position_metrics_are_computed_and_recomputed_on_price_change(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=10,
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            price_date=date(2030, 5, 12),
        )
        assert snapshot.quantity == Decimal("10.000000")
        assert snapshot.average_cost_per_unit_kopecks == 10_000
        assert snapshot.market_price_per_unit_kopecks == 15_000
        assert snapshot.market_value_kopecks == 150_000
        assert snapshot.cost_basis_kopecks == 100_000
        assert snapshot.unrealized_result_kopecks == 50_000

        updated = update_position_snapshot(session, snapshot.id, market_price_per_unit="200.00")
        assert updated.market_value_kopecks == 200_000
        assert updated.unrealized_result_kopecks == 100_000
    finally:
        session.close()
        database.engine.dispose()


def test_concurrent_quantity_and_price_updates_have_one_atomic_winner(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=10,
            average_cost_per_unit="50.00",
            market_price_per_unit="100.00",
            price_date=date(2030, 5, 12),
        )
        snapshot_id = snapshot.id
        expected_updated_at = snapshot.updated_at
        session.close()

        outcomes = _run_concurrent_position_updates(
            database,
            snapshot_id,
            expected_updated_at,
            (
                {"quantity": 20},
                {"market_price_per_unit": "300.00"},
            ),
        )

        assert sorted(outcomes) == ["conflict", "success"]
        verification_session = database.session_factory()
        try:
            stored = get_position_snapshot(verification_session, snapshot_id)
            stored_state = (
                Decimal(stored.quantity),
                stored.market_price_per_unit_kopecks,
                stored.market_value_kopecks,
                stored.cost_basis_kopecks,
                stored.unrealized_result_kopecks,
            )
            assert stored_state in {
                (Decimal("20.000000"), 10_000, 200_000, 100_000, 100_000),
                (Decimal("10.000000"), 30_000, 300_000, 50_000, 250_000),
            }
        finally:
            verification_session.close()
    finally:
        session.close()
        database.engine.dispose()


def test_concurrent_same_field_position_updates_have_one_winner(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=10,
            average_cost_per_unit="50.00",
            market_price_per_unit="100.00",
            price_date=date(2030, 5, 12),
        )
        snapshot_id = snapshot.id
        expected_updated_at = snapshot.updated_at
        session.close()

        outcomes = _run_concurrent_position_updates(
            database,
            snapshot_id,
            expected_updated_at,
            ({"quantity": 20}, {"quantity": 30}),
        )

        assert sorted(outcomes) == ["conflict", "success"]
        verification_session = database.session_factory()
        try:
            stored = get_position_snapshot(verification_session, snapshot_id)
            assert (
                Decimal(stored.quantity),
                stored.market_value_kopecks,
                stored.cost_basis_kopecks,
                stored.unrealized_result_kopecks,
            ) in {
                (Decimal("20.000000"), 200_000, 100_000, 100_000),
                (Decimal("30.000000"), 300_000, 150_000, 150_000),
            }
        finally:
            verification_session.close()
    finally:
        session.close()
        database.engine.dispose()


def test_position_accrued_interest_and_fractional_quantity(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity="0.5",
            average_cost_per_unit="100.00",
            market_price_per_unit="150.00",
            accrued_interest="10.00",
            price_date=date(2030, 5, 12),
        )
        assert snapshot.quantity == Decimal("0.500000")
        assert snapshot.market_value_kopecks == 7_500 + 1_000
        assert snapshot.cost_basis_kopecks == 5_000
        assert snapshot.unrealized_result_kopecks == 3_500
    finally:
        session.close()
        database.engine.dispose()


def test_position_uniqueness_per_month_account_instrument(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=1,
            average_cost_per_unit="10.00",
            market_price_per_unit="10.00",
            price_date=date(2030, 5, 12),
        )
        with pytest.raises(ValueError, match="already exists"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=2,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_position_crud_lists_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=3,
            average_cost_per_unit="50.00",
            market_price_per_unit="60.00",
            price_source=PriceSource.MOEX,
            manual_adjustment=True,
            notes="synthetic note",
            price_date=date(2030, 5, 12),
        )
        assert snapshot.price_source == PriceSource.MOEX.value
        assert snapshot.manual_adjustment is True
        assert snapshot.notes == "synthetic note"
        assert len(list_position_snapshots(session)) == 1

        delete_position_snapshot(session, snapshot.id)
        with pytest.raises(PositionSnapshotNotFoundError):
            get_position_snapshot(session, snapshot.id)
    finally:
        session.close()
        database.engine.dispose()


def test_position_validation_rejects_bad_inputs(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        with pytest.raises(ValueError, match="must be positive"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=-1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
        with pytest.raises(ValueError, match="unsupported price source"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_source="yahoo",
                price_date=date(2030, 5, 12),
            )
        with pytest.raises(ValueError, match="must not be negative"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="-1.00",
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_stock_quantity_must_be_positive_whole_number(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(
            session, instrument_type=InstrumentType.STOCK
        )
        with pytest.raises(ValueError, match="positive whole number"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity="0.5",
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
        with pytest.raises(ValueError, match="must be positive"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=0,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_generic_create_rejects_t_invest_source(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        with pytest.raises(ValueError, match="quote apply"):
            create_position_snapshot(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
                quantity=1,
                average_cost_per_unit="10.00",
                market_price_per_unit="10.00",
                price_source=PriceSource.T_INVEST,
                price_date=date(2030, 5, 12),
            )
    finally:
        session.close()
        database.engine.dispose()


def test_generic_update_cannot_fabricate_or_corrupt_t_invest(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=2,
            average_cost_per_unit="100.00",
            market_price_per_unit="110.00",
            price_date=date(2030, 5, 12),
        )
        with pytest.raises(ValueError, match="quote apply"):
            update_position_snapshot(session, snapshot.id, price_source=PriceSource.T_INVEST)

        apply_snapshot_market_quote(
            session,
            snapshot,
            market_price_per_unit_kopecks=21550,
            price_date=date(2030, 5, 13),
            price_source=PriceSource.T_INVEST,
        )
        applied_at = datetime(2030, 5, 13, 12, 0, tzinfo=timezone.utc)
        session.add(
            PositionQuoteProvenance(
                position_snapshot_id=snapshot.id,
                reporting_month_id=month_id,
                provider="t_invest",
                provider_instrument_id="11111111-1111-1111-1111-111111111111",
                provider_venue_id=None,
                quote_kind="last",
                raw_price="215.50",
                raw_price_basis="R",
                normalized_price_kopecks=21550,
                price_date=date(2030, 5, 13),
                fetched_at_utc=applied_at,
                target_date=date(2030, 5, 13),
                freshness="ok",
                applied_at_utc=applied_at,
            )
        )
        session.commit()
        first = session.scalar(select(PositionQuoteProvenance))
        assert first is not None
        first_id = first.id
        first_price = first.normalized_price_kopecks

        updated = update_position_snapshot(session, snapshot.id, quantity=3)
        assert updated.price_source == PriceSource.T_INVEST.value
        assert updated.market_price_per_unit_kopecks == 21550
        assert updated.quantity == Decimal("3")

        with pytest.raises(ValueError, match="keeping t_invest"):
            update_position_snapshot(
                session,
                snapshot.id,
                market_price_per_unit="250.00",
                price_source=PriceSource.T_INVEST,
            )
        with pytest.raises(ValueError, match="keeping t_invest"):
            update_position_snapshot(session, snapshot.id, market_price_per_unit="250.00")

        manual = update_position_snapshot(
            session,
            snapshot.id,
            market_price_per_unit="250.00",
            price_source=PriceSource.MANUAL,
        )
        assert manual.price_source == PriceSource.MANUAL.value
        assert manual.market_price_per_unit_kopecks == 25000
        leftover = session.scalar(select(PositionQuoteProvenance))
        assert leftover is not None
        assert leftover.id == first_id
        assert leftover.normalized_price_kopecks == first_price
        assert leftover.provider_instrument_id == "11111111-1111-1111-1111-111111111111"
    finally:
        session.close()
        database.engine.dispose()


def test_stage_create_does_not_commit_while_public_create_does(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month_id, account_id, instrument_id = build_environment(session)
        staged = stage_create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=2,
            average_cost_per_unit="10.00",
            market_price_per_unit="12.00",
            price_date=date(2030, 5, 12),
        )
        assert staged.id is not None
        session.rollback()
        assert (
            get_position_snapshot_by_key(
                session,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
            )
            is None
        )

        created = create_position_snapshot(
            session,
            reporting_month_id=month_id,
            account_id=account_id,
            instrument_id=instrument_id,
            quantity=2,
            average_cost_per_unit="10.00",
            market_price_per_unit="12.00",
            price_date=date(2030, 5, 12),
        )
        other = database.session_factory()
        try:
            visible = get_position_snapshot_by_key(
                other,
                reporting_month_id=month_id,
                account_id=account_id,
                instrument_id=instrument_id,
            )
            assert visible is not None
            assert visible.id == created.id
        finally:
            other.close()
    finally:
        session.close()
        database.engine.dispose()
