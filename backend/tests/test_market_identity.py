"""Provider-neutral market identity DTO, MOEX codec, and storage shape."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import MarketIdentity, market_identity_key
from hermes_finance.market_data.moex_identity import (
    InvalidMoexIdentityError,
    decode_moex_venue,
    encode_moex_venue,
    market_identity_from_moex,
    moex_parts_from_identity,
)
from hermes_finance.persistence import Base, InstrumentMarketMapping
from hermes_finance.services.instruments import create_instrument


def test_generic_identity_does_not_require_moex_fields() -> None:
    identity = MarketIdentity(
        provider="synthetic_provider",
        provider_instrument_id="opaque-security-id",
        provider_venue_id=None,
    )
    assert market_identity_key(identity) == (
        "synthetic_provider",
        "opaque-security-id",
        None,
    )
    assert not hasattr(identity, "engine")
    assert not hasattr(identity, "market")
    assert not hasattr(identity, "boardid")
    assert not hasattr(identity, "secid")


def test_moex_codec_round_trip_and_canonical_venue() -> None:
    identity = market_identity_from_moex(
        engine="STOCK",
        market="Shares",
        boardid="tqbr",
        secid="sber",
        isin="ru0009029540",
    )
    assert identity.provider == "moex_iss"
    assert identity.provider_instrument_id == "SBER"
    assert identity.provider_venue_id == "stock/shares/TQBR"
    assert identity.isin == "RU0009029540"
    parts = moex_parts_from_identity(identity)
    assert (parts.engine, parts.market, parts.boardid, parts.secid) == (
        "stock",
        "shares",
        "TQBR",
        "SBER",
    )
    assert encode_moex_venue(engine="stock", market="shares", boardid="TQBR") == (
        "stock/shares/TQBR"
    )
    assert decode_moex_venue(" STOCK / SHARES / tqbr ") == ("stock", "shares", "TQBR")


@pytest.mark.parametrize(
    "venue",
    ["", "stock/shares", "stock/shares/TQBR/extra", "stock//TQBR", "/shares/TQBR"],
)
def test_moex_venue_decode_is_strict(venue: str) -> None:
    with pytest.raises(InvalidMoexIdentityError):
        decode_moex_venue(venue)


def test_generic_identity_can_be_stored_without_venue(tmp_path: Path) -> None:
    database = create_database(tmp_path / "generic_identity.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        instrument = create_instrument(
            session, name="Synthetic Opaque", instrument_type=InstrumentType.STOCK
        )
        row = InstrumentMarketMapping(
            instrument_id=instrument.id,
            provider="synthetic_provider",
            provider_instrument_id="opaque-security-id",
            provider_venue_id=None,
            excluded=False,
            updated_at=datetime.now(UTC),
        )
        session.add(row)
        session.commit()
        loaded = session.get(InstrumentMarketMapping, instrument.id)
        assert loaded is not None
        assert loaded.provider == "synthetic_provider"
        assert loaded.provider_instrument_id == "opaque-security-id"
        assert loaded.provider_venue_id is None
        assert loaded.excluded is False
    finally:
        session.close()
        database.engine.dispose()


def test_partial_identity_is_rejected_by_database(tmp_path: Path) -> None:
    database = create_database(tmp_path / "partial_identity.db")
    Base.metadata.create_all(database.engine)
    session = database.session_factory()
    try:
        instrument = create_instrument(
            session, name="Synthetic Partial", instrument_type=InstrumentType.STOCK
        )
        session.add(
            InstrumentMarketMapping(
                instrument_id=instrument.id,
                provider="synthetic_provider",
                provider_instrument_id=None,
                provider_venue_id=None,
                excluded=True,
                updated_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.close()
        database.engine.dispose()
