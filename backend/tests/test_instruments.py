from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType, RubleAmount
from hermes_finance.persistence import Base
from hermes_finance.services.instruments import (
    InstrumentNotFoundError,
    create_instrument,
    delete_instrument,
    get_instrument,
    list_instruments,
    update_instrument,
)


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "instruments.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


@pytest.mark.parametrize("instrument_type", list(InstrumentType))
def test_instrument_types_are_persisted(instrument_type: InstrumentType, tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session, name=f"Synthetic {instrument_type.value}", instrument_type=instrument_type
        )
        assert instrument.instrument_type == instrument_type.value
    finally:
        session.close()
        database.engine.dispose()


def test_isin_is_unique_only_when_provided(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        first = create_instrument(
            session,
            name="Synthetic Bond",
            instrument_type=InstrumentType.BOND,
            isin="RU000A0JXTQ7",
        )
        without_isin = create_instrument(
            session, name="Synthetic Stock", instrument_type=InstrumentType.STOCK
        )
        assert first.isin == "RU000A0JXTQ7"
        assert without_isin.isin is None

        with pytest.raises(ValueError, match="isin must be unique"):
            create_instrument(
                session,
                name="Synthetic Duplicate",
                instrument_type=InstrumentType.BOND,
                isin="RU000A0JXTQ7",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_isin_is_normalized_to_uppercase(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Synthetic Fund",
            instrument_type=InstrumentType.FUND,
            isin="  ru000a0jxtq7  ",
        )
        assert instrument.isin == "RU000A0JXTQ7"
        with pytest.raises(ValueError, match="isin must be unique"):
            create_instrument(
                session,
                name="Synthetic Case Duplicate",
                instrument_type=InstrumentType.FUND,
                isin="Ru000A0JXTQ7",
            )
    finally:
        session.close()
        database.engine.dispose()


def test_instrument_crud_updates_fields_and_deletes(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="  Synthetic Bond  ",
            instrument_type=InstrumentType.BOND,
            ticker="SU29011RMFS5",
            moex_secid="SU29011RMFS5",
            currency="usd",
            nominal_value=RubleAmount.from_api("1000.00"),
            is_active=False,
            manual_price_allowed=False,
        )
        assert instrument.name == "Synthetic Bond"
        assert instrument.ticker == "SU29011RMFS5"
        assert instrument.currency == "USD"
        assert instrument.nominal_value_kopecks == 100_000
        assert instrument.is_active is False
        assert instrument.manual_price_allowed is False

        updated = update_instrument(
            session,
            instrument.id,
            name="Synthetic Bond Updated",
            instrument_type=InstrumentType.OTHER,
            ticker="UPDATED",
            nominal_value=RubleAmount.from_api("1500.50"),
            is_active=True,
            notes="synthetic note",
        )
        assert updated.name == "Synthetic Bond Updated"
        assert updated.instrument_type == InstrumentType.OTHER.value
        assert updated.ticker == "UPDATED"
        assert updated.nominal_value_kopecks == 150_050
        assert updated.is_active is True
        assert updated.notes == "synthetic note"
        assert get_instrument(session, instrument.id).name == "Synthetic Bond Updated"
        assert len(list_instruments(session)) == 1

        delete_instrument(session, instrument.id)
        with pytest.raises(InstrumentNotFoundError):
            get_instrument(session, instrument.id)
    finally:
        session.close()
        database.engine.dispose()


def test_instrument_validation_rejects_invalid_type_empty_name_and_negative_nominal(
    tmp_path: Path,
) -> None:
    session, database = session_for(tmp_path)
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            create_instrument(session, name="  ", instrument_type=InstrumentType.OTHER)
        with pytest.raises(ValueError, match="unsupported instrument type"):
            create_instrument(session, name="Synthetic", instrument_type="crypto")
        with pytest.raises(ValueError, match="nominal_value must not be negative"):
            create_instrument(
                session,
                name="Synthetic",
                instrument_type=InstrumentType.BOND,
                nominal_value=RubleAmount.from_api("-1.00"),
            )
    finally:
        session.close()
        database.engine.dispose()
