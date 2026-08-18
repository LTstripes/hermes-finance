"""M05-05: T-Invest discovery must respect local instrument type."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from hermes_finance.database import create_database
from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import (
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
    RejectedCandidate,
)
from hermes_finance.persistence import Base
from hermes_finance.services.instrument_mappings import (
    discover_instrument_candidates,
    get_instrument_mapping,
    set_accepted_mapping,
)
from hermes_finance.services.instruments import create_instrument

SHARE_UID = "11111111-1111-1111-1111-111111111111"
BOND_UID = "33333333-3333-3333-3333-333333333333"
FUND_UID = "22222222-2222-2222-2222-222222222222"
OTHER_SHARE_UID = "44444444-4444-4444-4444-444444444444"
SBER_ISIN = "RU0009029540"
BOND_ISIN = "RU000A0JX0J2"
FUND_ISIN = "RU000A0JTK38"
COMPATIBLE_STOCK_MESSAGE = "T-Invest не нашёл совместимый инструмент типа «Акция»."


class RecordingProvider:
    def __init__(self, result: DiscoverResult) -> None:
        self.result = result
        self.discover_calls: list[dict[str, object]] = []

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
        instrument_kind: InstrumentType | None = None,
    ) -> DiscoverResult:
        self.discover_calls.append(
            {
                "query": query,
                "provider_instrument_id": provider_instrument_id,
                "isin": isin,
                "instrument_kind": instrument_kind,
            }
        )
        return self.result

    def fetch_quote(self, identity: MarketIdentity, target_date: object) -> object:
        raise AssertionError("mapping must not fetch quotes")

    def fetch_quotes(self, items: object) -> list[object]:
        raise AssertionError("mapping must not fetch quotes")


def session_for(tmp_path: Path) -> tuple[Session, object]:
    database = create_database(tmp_path / "instrument_type_compat.db")
    Base.metadata.create_all(database.engine)
    return database.session_factory(), database


def _identity(uid: str, isin: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        provider="t_invest",
        provider_instrument_id=uid,
        provider_venue_id=None,
        isin=isin,
    )


def _candidate(
    uid: str,
    kind: InstrumentType,
    *,
    ticker: str | None = None,
    isin: str | None = None,
    name: str | None = None,
) -> DiscoverCandidate:
    return DiscoverCandidate(
        identity=_identity(uid, isin),
        instrument_kind=kind,
        ticker=ticker,
        name=name,
    )


def test_local_stock_keeps_provider_stock(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(
                    _candidate(
                        SHARE_UID,
                        InstrumentType.STOCK,
                        ticker="SBER",
                        isin=SBER_ISIN,
                        name="Сбербанк",
                    ),
                ),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query=None,
            market_provider=provider,
        )
        assert result.status is QuoteStatus.OK
        assert len(result.candidates) == 1
        assert result.candidates[0].identity.provider_instrument_id == SHARE_UID
        assert result.candidates[0].instrument_kind is InstrumentType.STOCK
        assert provider.discover_calls[0]["instrument_kind"] is InstrumentType.STOCK
        assert provider.discover_calls[0]["query"] == "SBER"
    finally:
        session.close()
        database.engine.dispose()


def test_local_stock_rejects_provider_bond(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(
                    _candidate(
                        BOND_UID,
                        InstrumentType.BOND,
                        ticker="SBER-001P",
                        isin=BOND_ISIN,
                        name="Сбербанк БО-001P",
                    ),
                ),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="SBER",
            market_provider=provider,
        )
        assert result.status is QuoteStatus.UNAVAILABLE
        assert result.candidates == ()
        assert result.message is not None
        assert COMPATIBLE_STOCK_MESSAGE in result.message
        assert "discover query is empty" not in result.message
    finally:
        session.close()
        database.engine.dispose()


def test_local_bond_rejects_provider_stock(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="ОФЗ 26238",
            instrument_type=InstrumentType.BOND,
            ticker="SU26238RMFS4",
            isin=BOND_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(
                    _candidate(
                        SHARE_UID,
                        InstrumentType.STOCK,
                        ticker="SBER",
                        isin=SBER_ISIN,
                    ),
                ),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query=None,
            market_provider=provider,
        )
        assert result.status is QuoteStatus.UNAVAILABLE
        assert result.candidates == ()
        assert result.message is not None
        assert "Облигация" in result.message
        assert provider.discover_calls[0]["instrument_kind"] is InstrumentType.BOND
    finally:
        session.close()
        database.engine.dispose()


def test_local_bond_keeps_provider_bond(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="ОФЗ 26238",
            instrument_type=InstrumentType.BOND,
            ticker="SU26238RMFS4",
            isin=BOND_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(_candidate(BOND_UID, InstrumentType.BOND, isin=BOND_ISIN),),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query=None,
            market_provider=provider,
        )
        assert result.status is QuoteStatus.OK
        assert result.candidates[0].instrument_kind is InstrumentType.BOND
        assert result.candidates[0].identity.provider_instrument_id == BOND_UID
    finally:
        session.close()
        database.engine.dispose()


def test_local_fund_accepts_provider_etf_mapped_as_fund(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Synthetic Fund",
            instrument_type=InstrumentType.FUND,
            ticker="TMOS",
            isin=FUND_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(
                    _candidate(
                        FUND_UID,
                        InstrumentType.FUND,
                        ticker="TMOS",
                        isin=FUND_ISIN,
                        name="Т-Капитал Индекс МосБиржи",
                    ),
                ),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query=None,
            market_provider=provider,
        )
        assert result.status is QuoteStatus.OK
        assert result.candidates[0].instrument_kind is InstrumentType.FUND
        assert provider.discover_calls[0]["instrument_kind"] is InstrumentType.FUND
    finally:
        session.close()
        database.engine.dispose()


def test_local_fund_rejects_provider_stock(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Synthetic Fund",
            instrument_type=InstrumentType.FUND,
            ticker="TMOS",
            isin=FUND_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(_candidate(SHARE_UID, InstrumentType.STOCK, ticker="SBER"),),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query=None,
            market_provider=provider,
        )
        assert result.status is QuoteStatus.UNAVAILABLE
        assert result.candidates == ()
        assert result.message is not None
        assert "Фонд" in result.message
    finally:
        session.close()
        database.engine.dispose()


def test_mixed_response_keeps_only_compatible_candidates(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.AMBIGUOUS,
                candidates=(
                    _candidate(BOND_UID, InstrumentType.BOND, ticker="SBER-001P", name="Bond"),
                    _candidate(
                        SHARE_UID,
                        InstrumentType.STOCK,
                        ticker="SBER",
                        isin=SBER_ISIN,
                        name="Сбербанк",
                    ),
                    _candidate(FUND_UID, InstrumentType.FUND, ticker="SBERF"),
                ),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="SBER",
            market_provider=provider,
        )
        assert result.status is QuoteStatus.OK
        assert [item.identity.provider_instrument_id for item in result.candidates] == [SHARE_UID]
        assert all(item.instrument_kind is InstrumentType.STOCK for item in result.candidates)
    finally:
        session.close()
        database.engine.dispose()


def test_sber_exact_ticker_survives_bond_majority_response(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=None,
        )
        bonds = tuple(
            _candidate(
                f"33333333-3333-3333-3333-3333333333{index:02d}",
                InstrumentType.BOND,
                ticker=f"SBER-{index:03d}P",
                name=f"Сбербанк БО-{index:03d}P",
            )
            for index in range(12)
        )
        share = _candidate(
            SHARE_UID,
            InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
            name="Сбербанк",
        )
        provider = RecordingProvider(
            DiscoverResult(status=QuoteStatus.AMBIGUOUS, candidates=(*bonds, share))
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="SBER",
            market_provider=provider,
        )
        assert [item.ticker for item in result.candidates] == ["SBER"]
        assert result.candidates[0].identity.provider_instrument_id == SHARE_UID
        assert result.status is QuoteStatus.OK
        assert provider.discover_calls[0]["query"] == "SBER"
        assert provider.discover_calls[0]["instrument_kind"] is InstrumentType.STOCK
    finally:
        session.close()
        database.engine.dispose()


def test_multiple_compatible_candidates_stay_ambiguous(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.AMBIGUOUS,
                candidates=(
                    _candidate(SHARE_UID, InstrumentType.STOCK, ticker="SBER"),
                    _candidate(OTHER_SHARE_UID, InstrumentType.STOCK, ticker="SBERP"),
                    _candidate(BOND_UID, InstrumentType.BOND, ticker="SBER-001P"),
                ),
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="SBER",
            market_provider=provider,
        )
        assert result.status is QuoteStatus.AMBIGUOUS
        assert [item.identity.provider_instrument_id for item in result.candidates] == [
            SHARE_UID,
            OTHER_SHARE_UID,
        ]
    finally:
        session.close()
        database.engine.dispose()


def test_empty_query_does_not_leak_internal_message(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
        )
        provider = RecordingProvider(
            DiscoverResult(status=QuoteStatus.UNAVAILABLE, message="discover query is empty")
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="   ",
            market_provider=provider,
        )
        assert result.status is QuoteStatus.UNAVAILABLE
        assert result.candidates == ()
        assert result.message is not None
        assert "discover query is empty" not in result.message
        assert COMPATIBLE_STOCK_MESSAGE in result.message
    finally:
        session.close()
        database.engine.dispose()


def test_isin_mismatch_is_preserved_when_kinds_also_differ(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
        )
        provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.UNAVAILABLE,
                candidates=(_candidate(BOND_UID, InstrumentType.BOND, isin=BOND_ISIN),),
                rejected=(
                    RejectedCandidate(
                        provider_instrument_id=SHARE_UID,
                        candidate_isin="RU0000000000",
                        expected_isin=SBER_ISIN,
                    ),
                ),
                message="ISIN does not match candidate",
            )
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="SBER",
            market_provider=provider,
        )
        assert result.rejected
        assert result.rejected[0].reason == "isin_mismatch"
        assert result.rejected[0].expected_isin == SBER_ISIN
        assert result.candidates == ()
        assert result.status is QuoteStatus.UNAVAILABLE
        assert result.message == "ISIN does not match candidate"
    finally:
        session.close()
        database.engine.dispose()


def test_network_error_is_not_rewritten_as_compatibility_miss(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
        )
        provider = RecordingProvider(
            DiscoverResult(status=QuoteStatus.NETWORK_ERROR, message="T-Invest request timed out")
        )
        result = discover_instrument_candidates(
            session,
            instrument.id,
            provider="t_invest",
            query="SBER",
            market_provider=provider,
        )
        assert result.status is QuoteStatus.NETWORK_ERROR
        assert result.message == "T-Invest request timed out"
    finally:
        session.close()
        database.engine.dispose()


def test_manual_uid_cannot_bypass_type_check(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
        )
        bond_provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(_candidate(BOND_UID, InstrumentType.BOND, isin=SBER_ISIN),),
            )
        )
        with pytest.raises(ValueError, match="не совместим|Акция"):
            set_accepted_mapping(
                session,
                instrument.id,
                provider="t_invest",
                provider_instrument_id=BOND_UID,
                provider_venue_id=None,
                isin=SBER_ISIN,
                verify_provider=bond_provider,
            )
        assert get_instrument_mapping(session, instrument.id).state.value == "unmapped"

        stock_provider = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(_candidate(SHARE_UID, InstrumentType.STOCK, isin=SBER_ISIN),),
            )
        )
        view = set_accepted_mapping(
            session,
            instrument.id,
            provider="t_invest",
            provider_instrument_id=SHARE_UID,
            provider_venue_id=None,
            isin=SBER_ISIN,
            verify_provider=stock_provider,
        )
        assert view.state.value == "mapped"
        assert view.identity is not None
        assert view.identity.provider_instrument_id == SHARE_UID
    finally:
        session.close()
        database.engine.dispose()


def test_unverified_bond_uid_on_stock_without_isin_is_rejected(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
        )
        assert instrument.isin is None
        with pytest.raises(ValueError, match="requires provider verification"):
            set_accepted_mapping(
                session,
                instrument.id,
                provider="t_invest",
                provider_instrument_id=BOND_UID,
                provider_venue_id=None,
            )
        assert get_instrument_mapping(session, instrument.id).state.value == "unmapped"

        verified = RecordingProvider(
            DiscoverResult(
                status=QuoteStatus.OK,
                candidates=(_candidate(SHARE_UID, InstrumentType.STOCK, ticker="SBER"),),
            )
        )
        view = set_accepted_mapping(
            session,
            instrument.id,
            provider="t_invest",
            provider_instrument_id=SHARE_UID,
            provider_venue_id=None,
            verify_provider=verified,
        )
        assert view.state.value == "mapped"
        assert view.identity is not None
        assert view.identity.provider_instrument_id == SHARE_UID
    finally:
        session.close()
        database.engine.dispose()


def test_manual_uid_isin_mismatch_still_rejected_before_kind(tmp_path: Path) -> None:
    session, database = session_for(tmp_path)
    try:
        instrument = create_instrument(
            session,
            name="Сбербанк",
            instrument_type=InstrumentType.STOCK,
            ticker="SBER",
            isin=SBER_ISIN,
        )
        with pytest.raises(ValueError, match="isin mismatch"):
            set_accepted_mapping(
                session,
                instrument.id,
                provider="t_invest",
                provider_instrument_id=SHARE_UID,
                provider_venue_id=None,
                isin="RU0000000000",
            )
        assert get_instrument_mapping(session, instrument.id).state.value == "unmapped"
    finally:
        session.close()
        database.engine.dispose()
