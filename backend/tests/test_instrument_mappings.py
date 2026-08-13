"""Service tests for explicit instrument market-data mapping (R04-03)."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import AccountType, InstrumentType, MarketMappingState, PriceSource
from hermes_finance.market_data.dto import (
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
    RejectedCandidate,
)
from hermes_finance.market_data.moex_identity import market_identity_from_moex
from hermes_finance.persistence import Base, PositionSnapshot
from hermes_finance.services.accounts import create_account
from hermes_finance.services.instrument_mappings import (
    clear_accepted_mapping,
    clear_instrument_mapping_exclusion,
    exclude_instrument_mapping,
    get_instrument_mapping,
    set_accepted_mapping,
)
from hermes_finance.services.instruments import create_instrument
from hermes_finance.services.positions import create_position_snapshot, get_position_snapshot
from hermes_finance.services.reporting_months import close_reporting_month, create_reporting_month

STOCK_IDENTITY = {
    "provider": "moex_iss",
    "provider_instrument_id": "sber",
    "provider_venue_id": "stock/shares/tqbr",
}


class RecordingProvider:
    def __init__(self, result: DiscoverResult) -> None:
        self.result = result
        self.discover_calls: list[dict[str, str | None]] = []

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
    ) -> DiscoverResult:
        self.discover_calls.append(
            {"query": query, "provider_instrument_id": provider_instrument_id, "isin": isin}
        )
        return self.result

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> object:
        raise AssertionError("mapping must not fetch quotes")

    def fetch_quotes(self, items: object) -> list[object]:
        raise AssertionError("mapping must not fetch quotes")


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "instrument_mappings.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _stock(session: Session, **overrides: object):
    payload = {
        "name": "Synthetic Stock",
        "instrument_type": InstrumentType.STOCK,
        "isin": "RU0009029540",
        "moex_secid": "SBER",
    }
    payload.update(overrides)
    return create_instrument(session, **payload)


def test_missing_mapping_is_unmapped(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        view = get_instrument_mapping(session, instrument.id)
        assert view.state is MarketMappingState.UNMAPPED
        assert view.identity is None
        assert view.legacy_moex_secid == "SBER"
        assert view.instrument_isin == "RU0009029540"
    finally:
        session.close()
        database.engine.dispose()


def test_explicit_complete_identity_is_mapped(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        view = set_accepted_mapping(session, instrument.id, **STOCK_IDENTITY)
        assert view.state is MarketMappingState.MAPPED
        assert view.identity is not None
        assert view.identity.provider == "moex_iss"
        assert view.identity.provider_instrument_id == "SBER"
        assert view.identity.provider_venue_id == "stock/shares/TQBR"
        assert view.legacy_moex_secid == "SBER"
    finally:
        session.close()
        database.engine.dispose()


def test_partial_identity_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        with pytest.raises(ValueError, match="provider_venue_id is required"):
            set_accepted_mapping(
                session,
                instrument.id,
                provider="moex_iss",
                provider_instrument_id="SBER",
                provider_venue_id="   ",
            )
        assert get_instrument_mapping(session, instrument.id).state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_mapped_then_unmapped(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        set_accepted_mapping(session, instrument.id, **STOCK_IDENTITY)
        view = clear_accepted_mapping(session, instrument.id)
        assert view.state is MarketMappingState.UNMAPPED
        assert view.identity is None
        assert view.legacy_moex_secid == "SBER"
    finally:
        session.close()
        database.engine.dispose()


def test_unmapped_to_excluded_and_back(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        excluded = exclude_instrument_mapping(session, instrument.id)
        assert excluded.state is MarketMappingState.EXCLUDED
        assert excluded.identity is None
        restored = clear_instrument_mapping_exclusion(session, instrument.id)
        assert restored.state is MarketMappingState.UNMAPPED
        assert restored.identity is None
    finally:
        session.close()
        database.engine.dispose()


def test_mapped_to_excluded_preserves_identity_and_is_reversible(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        set_accepted_mapping(session, instrument.id, **STOCK_IDENTITY)
        excluded = exclude_instrument_mapping(session, instrument.id)
        assert excluded.state is MarketMappingState.EXCLUDED
        assert excluded.identity is not None
        assert excluded.identity.provider_venue_id == "stock/shares/TQBR"
        assert excluded.identity.provider_instrument_id == "SBER"
        restored = clear_instrument_mapping_exclusion(session, instrument.id)
        assert restored.state is MarketMappingState.MAPPED
        assert restored.identity is not None
        assert restored.identity.provider_venue_id == "stock/shares/TQBR"
        assert restored.identity.provider_instrument_id == "SBER"
    finally:
        session.close()
        database.engine.dispose()


def test_legacy_moex_secid_is_not_accepted_mapping(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        with_hint = _stock(session, moex_secid="SBER")
        without_hint = create_instrument(
            session, name="Synthetic Unhinted", instrument_type=InstrumentType.FUND
        )
        assert get_instrument_mapping(session, with_hint.id).state is MarketMappingState.UNMAPPED
        assert get_instrument_mapping(session, without_hint.id).state is MarketMappingState.UNMAPPED
        assert get_instrument_mapping(session, with_hint.id).legacy_moex_secid == "SBER"
        assert get_instrument_mapping(session, without_hint.id).legacy_moex_secid is None
    finally:
        session.close()
        database.engine.dispose()


def test_isin_mismatch_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session, isin="RU0009029540")
        with pytest.raises(ValueError, match="isin mismatch"):
            set_accepted_mapping(
                session,
                instrument.id,
                **STOCK_IDENTITY,
                isin="RU0000000000",
            )
        assert get_instrument_mapping(session, instrument.id).state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


@pytest.mark.parametrize(
    "instrument_type", [InstrumentType.CURRENCY, InstrumentType.GOLD, InstrumentType.OTHER]
)
def test_unsupported_instrument_type_is_rejected(
    instrument_type: InstrumentType, tmp_path: Path
) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session, name=f"Synthetic {instrument_type.value}", instrument_type=instrument_type
        )
        with pytest.raises(ValueError, match="unsupported instrument type"):
            set_accepted_mapping(session, instrument.id, **STOCK_IDENTITY)
        assert get_instrument_mapping(session, instrument.id).state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_unsupported_provider_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        with pytest.raises(ValueError, match="unsupported market-data provider"):
            set_accepted_mapping(
                session,
                instrument.id,
                provider="other_feed",
                provider_instrument_id="opaque-security-id",
                provider_venue_id=None,
            )
        assert get_instrument_mapping(session, instrument.id).state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_incompatible_engine_market_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        bond = create_instrument(
            session, name="Synthetic Bond", instrument_type=InstrumentType.BOND
        )
        with pytest.raises(ValueError, match="incompatible"):
            set_accepted_mapping(session, bond.id, **STOCK_IDENTITY)
        fund = create_instrument(
            session, name="Synthetic Fund", instrument_type=InstrumentType.FUND
        )
        with pytest.raises(ValueError, match="incompatible"):
            set_accepted_mapping(
                session,
                fund.id,
                provider="moex_iss",
                provider_instrument_id="SU26238RMFS4",
                provider_venue_id="stock/bonds/TQCB",
            )
        assert get_instrument_mapping(session, bond.id).state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_provider_verify_rejects_ambiguity_and_never_picks_another(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        first = market_identity_from_moex(
            engine="stock",
            market="shares",
            boardid="TQBR",
            secid="SBER",
        )
        other = market_identity_from_moex(
            engine="stock",
            market="shares",
            boardid="TQTF",
            secid="SBER",
        )
        ambiguous = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.AMBIGUOUS,
                candidates=(
                    DiscoverCandidate(identity=other, instrument_kind=InstrumentType.STOCK),
                    DiscoverCandidate(
                        identity=market_identity_from_moex(
                            engine="stock",
                            market="shares",
                            boardid="FQBR",
                            secid="SBER",
                        ),
                        instrument_kind=InstrumentType.STOCK,
                    ),
                ),
            )
        )
        with pytest.raises(ValueError, match="ambiguous"):
            set_accepted_mapping(
                session,
                instrument.id,
                **STOCK_IDENTITY,
                verify_provider=ambiguous,
            )
        single_other = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(
                    DiscoverCandidate(identity=other, instrument_kind=InstrumentType.STOCK),
                ),
            )
        )
        with pytest.raises(ValueError, match="was not found among provider candidates"):
            set_accepted_mapping(
                session,
                instrument.id,
                **STOCK_IDENTITY,
                verify_provider=single_other,
            )
        chosen = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.AMBIGUOUS,
                candidates=(
                    DiscoverCandidate(identity=first, instrument_kind=InstrumentType.STOCK),
                    DiscoverCandidate(identity=other, instrument_kind=InstrumentType.STOCK),
                ),
            )
        )
        view = set_accepted_mapping(
            session,
            instrument.id,
            **STOCK_IDENTITY,
            verify_provider=chosen,
        )
        assert view.state is MarketMappingState.MAPPED
        assert view.identity is not None
        assert view.identity.provider_venue_id == "stock/shares/TQBR"
        assert chosen.discover_calls
        assert chosen.discover_calls[0]["provider_instrument_id"] == "SBER"
    finally:
        session.close()
        database.engine.dispose()


def test_provider_verify_rejects_isin_mismatch(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session, isin="RU0009029540")
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.UNAVAILABLE,
                rejected=(
                    RejectedCandidate(
                        provider_instrument_id="SBER",
                        candidate_isin="RU0000000000",
                        expected_isin="RU0009029540",
                    ),
                ),
                message="ISIN does not match candidate",
            )
        )
        with pytest.raises(ValueError, match="isin mismatch"):
            set_accepted_mapping(
                session,
                instrument.id,
                **STOCK_IDENTITY,
                verify_provider=provider,
            )
        assert get_instrument_mapping(session, instrument.id).state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_default_save_does_not_call_provider(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        view = set_accepted_mapping(session, instrument.id, **STOCK_IDENTITY)
        assert view.state is MarketMappingState.MAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_mapping_update_leaves_position_snapshot_unchanged(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        month = create_reporting_month(session, year=2031, month=3, snapshot_date=date(2031, 3, 31))
        account = create_account(
            session, name="Synthetic Broker", account_type=AccountType.BROKERAGE
        )
        instrument = _stock(session)
        snapshot = create_position_snapshot(
            session,
            reporting_month_id=month.id,
            account_id=account.id,
            instrument_id=instrument.id,
            quantity=3,
            average_cost_per_unit="100.00",
            market_price_per_unit="250.00",
            price_date=date(2031, 3, 15),
            price_source=PriceSource.MOEX,
        )
        close_reporting_month(session, month.id)
        before = session.get(PositionSnapshot, snapshot.id)
        assert before is not None
        frozen = (
            before.market_price_per_unit_kopecks,
            before.price_date,
            before.price_source,
            before.market_value_kopecks,
            before.updated_at,
            before.accrued_interest_kopecks,
        )
        set_accepted_mapping(session, instrument.id, **STOCK_IDENTITY)
        exclude_instrument_mapping(session, instrument.id)
        after = get_position_snapshot(session, snapshot.id)
        assert (
            after.market_price_per_unit_kopecks,
            after.price_date,
            after.price_source,
            after.market_value_kopecks,
            after.updated_at,
            after.accrued_interest_kopecks,
        ) == frozen
    finally:
        session.close()
        database.engine.dispose()


T_INVEST_UID = "11111111-1111-1111-1111-111111111111"
T_INVEST_IDENTITY = {
    "provider": "t_invest",
    "provider_instrument_id": T_INVEST_UID,
    "provider_venue_id": None,
}


def test_t_invest_mapping_round_trip_requires_null_venue(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = _stock(session)
        with pytest.raises(ValueError, match="provider_venue_id must be empty"):
            set_accepted_mapping(
                session,
                instrument.id,
                provider="t_invest",
                provider_instrument_id=T_INVEST_UID,
                provider_venue_id="stock/shares/TQBR",
            )
        view = set_accepted_mapping(session, instrument.id, **T_INVEST_IDENTITY)
        assert view.state is MarketMappingState.MAPPED
        assert view.identity is not None
        assert view.identity.provider == "t_invest"
        assert view.identity.provider_instrument_id == T_INVEST_UID
        assert view.identity.provider_venue_id is None
        loaded = get_instrument_mapping(session, instrument.id)
        assert loaded.identity == view.identity
        excluded = exclude_instrument_mapping(session, instrument.id)
        assert excluded.state is MarketMappingState.EXCLUDED
        assert excluded.identity is not None
        assert excluded.identity.provider_instrument_id == T_INVEST_UID
        restored = clear_instrument_mapping_exclusion(session, instrument.id)
        assert restored.state is MarketMappingState.MAPPED
        cleared = clear_accepted_mapping(session, instrument.id)
        assert cleared.state is MarketMappingState.UNMAPPED
    finally:
        session.close()
        database.engine.dispose()


def test_t_invest_and_moex_mappings_do_not_overwrite_each_other(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        stock = _stock(session)
        other = create_instrument(
            session,
            name="Synthetic Other",
            instrument_type=InstrumentType.STOCK,
            isin="RU0000000099",
        )
        moex = set_accepted_mapping(session, stock.id, **STOCK_IDENTITY)
        t_invest = set_accepted_mapping(session, other.id, **T_INVEST_IDENTITY)
        assert moex.identity is not None
        assert moex.identity.provider == "moex_iss"
        assert t_invest.identity is not None
        assert t_invest.identity.provider == "t_invest"
        assert get_instrument_mapping(session, stock.id).identity == moex.identity
    finally:
        session.close()
        database.engine.dispose()
