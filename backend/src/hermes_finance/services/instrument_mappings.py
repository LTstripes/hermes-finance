"""Accepted instrument market-data mapping. Reference data only.

Does not read or write PositionSnapshot, quotes, or historical months.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from hermes_finance.domain import InstrumentType, MarketMappingState
from hermes_finance.market_data.dto import MOEX_ISS_PROVIDER, MarketIdentity, QuoteStatus
from hermes_finance.market_data.normalize import SUPPORTED_KINDS, compatible_engine_market
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.persistence import Instrument, InstrumentMarketMapping
from hermes_finance.services.instruments import get_instrument


@dataclass(frozen=True, slots=True)
class InstrumentMappingView:
    instrument_id: int
    state: MarketMappingState
    identity: MarketIdentity | None
    instrument_isin: str | None
    legacy_moex_secid: str | None


def _normalize_token(value: str | None, *, field: str, case: str) -> str:
    if value is None:
        raise ValueError(f"{field} is required for an accepted market mapping")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required for an accepted market mapping")
    if case == "lower":
        return normalized.lower()
    if case == "upper":
        return normalized.upper()
    return normalized


def _normalize_isin(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def normalize_accepted_identity(
    *,
    provider: str,
    engine: str,
    market: str,
    boardid: str,
    secid: str,
    isin: str | None = None,
) -> MarketIdentity:
    return MarketIdentity(
        provider=_normalize_token(provider, field="provider", case="lower"),
        engine=_normalize_token(engine, field="engine", case="lower"),
        market=_normalize_token(market, field="market", case="lower"),
        boardid=_normalize_token(boardid, field="boardid", case="upper"),
        secid=_normalize_token(secid, field="secid", case="upper"),
        isin=_normalize_isin(isin),
    )


def _identity_key(identity: MarketIdentity) -> tuple[str, str, str, str, str]:
    return (
        identity.provider.strip().lower(),
        identity.engine.strip().lower(),
        identity.market.strip().lower(),
        identity.boardid.strip().upper(),
        identity.secid.strip().upper(),
    )


def validate_accepted_identity(instrument: Instrument, identity: MarketIdentity) -> MarketIdentity:
    try:
        kind = InstrumentType(instrument.instrument_type)
    except ValueError as error:
        raise ValueError(
            f"unsupported instrument type for market mapping: {instrument.instrument_type!r}"
        ) from error
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported instrument type for market mapping: {kind.value}")
    if identity.provider != MOEX_ISS_PROVIDER:
        raise ValueError(f"unsupported market-data provider: {identity.provider}")
    if not compatible_engine_market(
        instrument_kind=kind,
        engine=identity.engine,
        market=identity.market,
    ):
        raise ValueError(
            f"engine/market {identity.engine}/{identity.market} is incompatible with {kind.value}"
        )
    instrument_isin = _normalize_isin(instrument.isin)
    if instrument_isin and identity.isin and instrument_isin != identity.isin:
        raise ValueError("isin mismatch between instrument and market identity")
    return identity


def verify_identity_with_provider(
    *,
    instrument: Instrument,
    identity: MarketIdentity,
    provider: MarketDataProvider,
) -> None:
    """Confirm an already-chosen identity. Never selects among candidates."""

    result = provider.discover_candidates(
        secid=identity.secid,
        isin=instrument.isin or identity.isin,
    )
    if result.rejected:
        raise ValueError("isin mismatch between instrument and provider candidate")
    if result.status is QuoteStatus.NETWORK_ERROR:
        raise ValueError(result.message or "market-data provider network error")
    if result.status is QuoteStatus.MALFORMED_RESPONSE:
        raise ValueError(result.message or "market-data provider malformed response")
    if result.status is QuoteStatus.UNSUPPORTED:
        raise ValueError(result.message or "provider reports the identity as unsupported")

    wanted = _identity_key(identity)
    matches = [item for item in result.candidates if _identity_key(item.identity) == wanted]
    if len(matches) == 1:
        candidate_isin = _normalize_isin(matches[0].identity.isin)
        instrument_isin = _normalize_isin(instrument.isin)
        if candidate_isin and instrument_isin and candidate_isin != instrument_isin:
            raise ValueError("isin mismatch between instrument and provider candidate")
        return
    if result.status is QuoteStatus.AMBIGUOUS or len(result.candidates) > 1:
        raise ValueError("ambiguous market-data candidates cannot be accepted automatically")
    raise ValueError("accepted mapping identity was not found among provider candidates")


def _row_has_identity(row: InstrumentMarketMapping) -> bool:
    return row.provider is not None


def _identity_from_row(row: InstrumentMarketMapping) -> MarketIdentity | None:
    if not _row_has_identity(row):
        return None
    assert row.provider is not None
    assert row.engine is not None
    assert row.market is not None
    assert row.boardid is not None
    assert row.secid is not None
    return MarketIdentity(
        provider=row.provider,
        engine=row.engine,
        market=row.market,
        boardid=row.boardid,
        secid=row.secid,
    )


def _state_from_row(row: InstrumentMarketMapping | None) -> MarketMappingState:
    if row is None:
        return MarketMappingState.UNMAPPED
    if row.excluded:
        return MarketMappingState.EXCLUDED
    return MarketMappingState.MAPPED


def _view(instrument: Instrument, row: InstrumentMarketMapping | None) -> InstrumentMappingView:
    return InstrumentMappingView(
        instrument_id=instrument.id,
        state=_state_from_row(row),
        identity=_identity_from_row(row) if row is not None else None,
        instrument_isin=instrument.isin,
        legacy_moex_secid=instrument.moex_secid,
    )


def _touch(row: InstrumentMarketMapping) -> None:
    row.updated_at = datetime.now(UTC)


def get_instrument_mapping(session: Session, instrument_id: int) -> InstrumentMappingView:
    instrument = get_instrument(session, instrument_id)
    row = session.get(InstrumentMarketMapping, instrument_id)
    return _view(instrument, row)


def set_accepted_mapping(
    session: Session,
    instrument_id: int,
    *,
    provider: str,
    engine: str,
    market: str,
    boardid: str,
    secid: str,
    isin: str | None = None,
    verify_provider: MarketDataProvider | None = None,
) -> InstrumentMappingView:
    instrument = get_instrument(session, instrument_id)
    identity = validate_accepted_identity(
        instrument,
        normalize_accepted_identity(
            provider=provider,
            engine=engine,
            market=market,
            boardid=boardid,
            secid=secid,
            isin=isin,
        ),
    )
    if verify_provider is not None:
        verify_identity_with_provider(
            instrument=instrument,
            identity=identity,
            provider=verify_provider,
        )

    row = session.get(InstrumentMarketMapping, instrument_id)
    if row is None:
        row = InstrumentMarketMapping(instrument_id=instrument.id)
        session.add(row)
    row.provider = identity.provider
    row.engine = identity.engine
    row.market = identity.market
    row.boardid = identity.boardid
    row.secid = identity.secid
    row.excluded = False
    _touch(row)
    session.commit()
    session.refresh(row)
    session.refresh(instrument)
    return _view(instrument, row)


def clear_accepted_mapping(session: Session, instrument_id: int) -> InstrumentMappingView:
    instrument = get_instrument(session, instrument_id)
    row = session.get(InstrumentMarketMapping, instrument_id)
    if row is not None:
        session.delete(row)
        session.commit()
    return _view(instrument, None)


def exclude_instrument_mapping(session: Session, instrument_id: int) -> InstrumentMappingView:
    instrument = get_instrument(session, instrument_id)
    row = session.get(InstrumentMarketMapping, instrument_id)
    if row is None:
        row = InstrumentMarketMapping(
            instrument_id=instrument.id,
            provider=None,
            engine=None,
            market=None,
            boardid=None,
            secid=None,
            excluded=True,
        )
        session.add(row)
    else:
        row.excluded = True
        _touch(row)
    session.commit()
    session.refresh(row)
    session.refresh(instrument)
    return _view(instrument, row)


def clear_instrument_mapping_exclusion(
    session: Session, instrument_id: int
) -> InstrumentMappingView:
    instrument = get_instrument(session, instrument_id)
    row = session.get(InstrumentMarketMapping, instrument_id)
    if row is None:
        return _view(instrument, None)
    if not _row_has_identity(row):
        session.delete(row)
        session.commit()
        return _view(instrument, None)
    row.excluded = False
    _touch(row)
    session.commit()
    session.refresh(row)
    session.refresh(instrument)
    return _view(instrument, row)
