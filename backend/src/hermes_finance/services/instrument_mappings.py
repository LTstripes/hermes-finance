"""Accepted instrument market-data mapping. Reference data only.

Does not read or write PositionSnapshot, quotes, or historical months.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from hermes_finance.domain import InstrumentType, MarketMappingState
from hermes_finance.market_data.dto import (
    MOEX_ISS_PROVIDER,
    T_INVEST_PROVIDER,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
    market_identity_key,
)
from hermes_finance.market_data.moex_identity import (
    InvalidMoexIdentityError,
    decode_moex_venue,
    market_identity_from_moex,
    moex_parts_from_identity,
)
from hermes_finance.market_data.normalize import SUPPORTED_KINDS, compatible_engine_market
from hermes_finance.market_data.protocol import MarketDataProvider
from hermes_finance.market_data.t_invest import normalize_t_invest_uid, t_invest_identity
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
    provider_instrument_id: str,
    provider_venue_id: str | None = None,
    isin: str | None = None,
) -> MarketIdentity:
    provider_n = _normalize_token(provider, field="provider", case="lower")
    instrument_n = _normalize_token(
        provider_instrument_id, field="provider_instrument_id", case="plain"
    )
    venue_n = provider_venue_id.strip() if provider_venue_id is not None else None
    venue_n = venue_n or None

    if provider_n == MOEX_ISS_PROVIDER:
        if venue_n is None:
            raise ValueError("provider_venue_id is required for moex_iss")
        try:
            engine, market, boardid = decode_moex_venue(venue_n)
            return market_identity_from_moex(
                engine=engine,
                market=market,
                boardid=boardid,
                secid=instrument_n,
                isin=isin,
            )
        except InvalidMoexIdentityError as error:
            raise ValueError(str(error)) from error

    if provider_n == T_INVEST_PROVIDER:
        if venue_n is not None:
            raise ValueError("provider_venue_id must be empty for t_invest")
        try:
            return t_invest_identity(provider_instrument_id=instrument_n, isin=isin)
        except ValueError as error:
            raise ValueError(str(error)) from error

    return MarketIdentity(
        provider=provider_n,
        provider_instrument_id=instrument_n,
        provider_venue_id=venue_n,
        isin=_normalize_isin(isin),
    )


def t_invest_mapping_requires_provider_verification(
    *,
    provider: str,
    instrument_isin: str | None,
    candidate_isin: str | None,
) -> bool:
    """Manual T-Invest UID cannot skip provider checks when a local ISIN is known."""

    if provider.strip().lower() != T_INVEST_PROVIDER:
        return False
    return _normalize_isin(instrument_isin) is not None and _normalize_isin(candidate_isin) is None


def validate_accepted_identity(instrument: Instrument, identity: MarketIdentity) -> MarketIdentity:
    try:
        kind = InstrumentType(instrument.instrument_type)
    except ValueError as error:
        raise ValueError(
            f"unsupported instrument type for market mapping: {instrument.instrument_type!r}"
        ) from error
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported instrument type for market mapping: {kind.value}")
    if identity.provider == T_INVEST_PROVIDER:
        if identity.provider_venue_id is not None:
            raise ValueError("provider_venue_id must be empty for t_invest")
        try:
            normalize_t_invest_uid(identity.provider_instrument_id)
        except ValueError as error:
            raise ValueError(str(error)) from error
    elif identity.provider == MOEX_ISS_PROVIDER:
        try:
            parts = moex_parts_from_identity(identity)
        except InvalidMoexIdentityError as error:
            raise ValueError(str(error)) from error
        if not compatible_engine_market(
            instrument_kind=kind,
            engine=parts.engine,
            market=parts.market,
        ):
            raise ValueError(
                f"engine/market {parts.engine}/{parts.market} is incompatible with {kind.value}"
            )
    else:
        raise ValueError(f"unsupported market-data provider: {identity.provider}")
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
        provider_instrument_id=identity.provider_instrument_id,
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

    wanted = market_identity_key(identity)
    matches = [item for item in result.candidates if market_identity_key(item.identity) == wanted]
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
    return row.provider is not None and row.provider_instrument_id is not None


def _identity_from_row(row: InstrumentMarketMapping) -> MarketIdentity | None:
    if not _row_has_identity(row):
        return None
    assert row.provider is not None
    assert row.provider_instrument_id is not None
    return MarketIdentity(
        provider=row.provider,
        provider_instrument_id=row.provider_instrument_id,
        provider_venue_id=row.provider_venue_id,
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
    provider_instrument_id: str,
    provider_venue_id: str | None = None,
    isin: str | None = None,
    verify_provider: MarketDataProvider | None = None,
) -> InstrumentMappingView:
    instrument = get_instrument(session, instrument_id)
    identity = validate_accepted_identity(
        instrument,
        normalize_accepted_identity(
            provider=provider,
            provider_instrument_id=provider_instrument_id,
            provider_venue_id=provider_venue_id,
            isin=isin,
        ),
    )
    if (
        t_invest_mapping_requires_provider_verification(
            provider=identity.provider,
            instrument_isin=instrument.isin,
            candidate_isin=identity.isin,
        )
        and verify_provider is None
    ):
        raise ValueError(
            "t_invest mapping with a known instrument ISIN requires provider verification "
            "when candidate ISIN is not provided"
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
    row.provider_instrument_id = identity.provider_instrument_id
    row.provider_venue_id = identity.provider_venue_id
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
            provider_instrument_id=None,
            provider_venue_id=None,
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


def discover_instrument_candidates(
    session: Session,
    instrument_id: int,
    *,
    provider: str,
    query: str | None,
    market_provider: MarketDataProvider,
) -> DiscoverResult:
    """Owner-triggered discovery. Never persists a candidate."""

    instrument = get_instrument(session, instrument_id)
    provider_n = _normalize_token(provider, field="provider", case="lower")
    if provider_n != T_INVEST_PROVIDER:
        raise ValueError(f"unsupported discovery provider: {provider_n}")
    try:
        kind = InstrumentType(instrument.instrument_type)
    except ValueError as error:
        raise ValueError(
            f"unsupported instrument type for market mapping: {instrument.instrument_type!r}"
        ) from error
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported instrument type for market mapping: {kind.value}")
    override = query.strip() if query is not None else ""
    return market_provider.discover_candidates(
        query=override or instrument.ticker,
        isin=instrument.isin,
    )
