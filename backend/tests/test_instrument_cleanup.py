from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from hermes_finance.database import Database, create_database
from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.main import create_app
from hermes_finance.persistence import (
    Base,
    BrokerIdentityMapping,
    Instrument,
    InstrumentMarketMapping,
)
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instruments import (
    InstrumentDeletionBlockedError,
    create_instrument,
    delete_instrument,
    get_instrument_cleanup,
)
from hermes_finance.services.positions import create_position_snapshot
from hermes_finance.services.reporting_months import (
    close_reporting_month,
    create_reporting_month,
)


def session_for(tmp_path: Path) -> tuple[Session, Database]:
    database = create_database(tmp_path / "instrument_cleanup.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _instrument(session: Session, *, name: str = "Synthetic bond") -> Instrument:
    return create_instrument(
        session,
        name=name,
        instrument_type=InstrumentType.BOND,
        is_active=False,
    )


def _instrument_with_position(session: Session, *, closed: bool) -> tuple[Instrument, int]:
    instrument = _instrument(session)
    account = create_account(session, name="Synthetic brokerage", account_type="brokerage")
    month = create_reporting_month(
        session,
        year=2026,
        month=8,
        snapshot_date=date(2026, 8, 31),
    )
    create_position_snapshot(
        session,
        reporting_month_id=month.id,
        account_id=account.id,
        instrument_id=instrument.id,
        quantity="1",
        average_cost_per_unit=RubleAmount.from_api("1000.00"),
        market_price_per_unit=RubleAmount.from_api("1010.00"),
        price_date=date(2026, 8, 31),
    )
    if closed:
        close_reporting_month(session, month.id)
    return instrument, month.id


def test_unused_inactive_duplicate_is_deletable_without_fuzzy_merge(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        canonical = create_instrument(
            session,
            name="Canonical bond",
            instrument_type=InstrumentType.BOND,
            isin="RU000A123456",
        )
        duplicate = Instrument(
            name="Accidental duplicate",
            instrument_type=InstrumentType.BOND.value,
            isin="ru000a123456",
            currency="RUB",
            is_active=False,
            manual_price_allowed=True,
        )
        session.add(duplicate)
        session.commit()

        cleanup = get_instrument_cleanup(session, duplicate.id)

        assert cleanup.can_delete is True
        assert cleanup.reason_code == "unused_duplicate"
        assert cleanup.references == ()
        assert [
            (item.instrument_id, item.name, item.basis) for item in cleanup.active_duplicates
        ] == [(canonical.id, "Canonical bond", "isin")]

        delete_instrument(session, duplicate.id)
        assert session.get(Instrument, duplicate.id) is None
        assert session.get(Instrument, canonical.id) is not None
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    ("closed", "reason_code", "lifecycle"),
    [
        (False, "draft_referenced", "draft"),
        (True, "historical_referenced", "historical"),
    ],
)
def test_position_reference_is_classified_and_delete_is_blocked(
    tmp_path: Path,
    closed: bool,
    reason_code: str,
    lifecycle: str,
) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument, month_id = _instrument_with_position(session, closed=closed)

        cleanup = get_instrument_cleanup(session, instrument.id)

        assert cleanup.can_delete is False
        assert cleanup.reason_code == reason_code
        assert cleanup.active_duplicates == ()
        assert len(cleanup.references) == 1
        assert cleanup.references[0].kind == "position"
        assert cleanup.references[0].lifecycle == lifecycle
        assert cleanup.references[0].month_labels == ("август 2026",)
        assert "Нельзя удалить" in cleanup.message
        assert "август 2026" in cleanup.message
        if closed:
            assert "закрыт" in cleanup.message
        else:
            assert "черновик" in cleanup.message

        with pytest.raises(InstrumentDeletionBlockedError, match="Нельзя удалить"):
            delete_instrument(session, instrument.id)

        assert session.get(Instrument, instrument.id) is not None
        assert session.query(Instrument).filter_by(id=instrument.id).count() == 1
        assert month_id > 0
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize("mapping_kind", ["market", "broker"])
def test_provider_mappings_are_protected_even_when_fk_would_cascade(
    tmp_path: Path,
    mapping_kind: str,
) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _instrument(session)
        confirmed_at = datetime(2026, 8, 31, tzinfo=UTC)
        if mapping_kind == "market":
            mapping = InstrumentMarketMapping(
                instrument_id=instrument.id,
                provider="moex_iss",
                provider_instrument_id="SU26248",
                provider_venue_id="stock/bonds/TQOB",
                updated_at=confirmed_at,
            )
        else:
            mapping = BrokerIdentityMapping(
                provider="alfa_pro",
                subject_kind="instrument",
                provider_identity="synthetic-provider-instrument",
                hermes_instrument_id=instrument.id,
                status="effective",
                confirmed_at=confirmed_at,
            )
        session.add(mapping)
        session.commit()

        cleanup = get_instrument_cleanup(session, instrument.id)

        assert cleanup.can_delete is False
        assert cleanup.reason_code == "provider_mapped"
        assert len(cleanup.references) == 1
        assert cleanup.references[0].lifecycle == "provider"
        assert cleanup.references[0].kind == f"{mapping_kind}_mapping"
        assert "сопостав" in cleanup.message

        with pytest.raises(InstrumentDeletionBlockedError, match="Нельзя удалить"):
            delete_instrument(session, instrument.id)

        assert session.get(Instrument, instrument.id) is not None
    finally:
        session.close()
        database.engine.dispose()


def test_cleanup_api_returns_owner_reason_and_never_raw_fk_error(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    instrument, _month_id = _instrument_with_position(session, closed=True)
    session.close()
    try:
        with TestClient(create_app(database)) as client:
            preview = client.get(f"/api/instruments/{instrument.id}/cleanup")
            assert preview.status_code == 200
            preview_body = preview.json()
            assert preview_body["can_delete"] is False
            assert preview_body["status"] == "protected"
            assert preview_body["reason_code"] == "historical_referenced"
            assert preview_body["references"][0]["kind"] == "position"
            assert preview_body["references"][0]["lifecycle"] == "historical"
            assert preview_body["references"][0]["month_labels"] == ["август 2026"]

            deleted = client.delete(f"/api/instruments/{instrument.id}")

        assert deleted.status_code == 409
        error = deleted.json()["error"]
        assert error["code"] == "instrument_deletion_blocked"
        assert "Нельзя удалить" in error["message"]
        assert "foreign" not in error["message"].lower()
        with database.session_factory() as verify_session:
            assert verify_session.get(Instrument, instrument.id) is not None
    finally:
        database.engine.dispose()
