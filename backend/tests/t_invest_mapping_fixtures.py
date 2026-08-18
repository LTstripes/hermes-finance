"""Helpers to persist an already-accepted T-Invest mapping in tests."""

from __future__ import annotations

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
)
from hermes_finance.persistence import Instrument
from hermes_finance.services.instrument_mappings import set_accepted_mapping


class _AcceptingTInvestProvider:
    def __init__(self, uid: str, kind: InstrumentType, isin: str | None) -> None:
        self.uid = uid
        self.kind = kind
        self.isin = isin

    def discover_candidates(self, **kwargs: object) -> DiscoverResult:
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider=T_INVEST_PROVIDER,
                        provider_instrument_id=self.uid,
                        provider_venue_id=None,
                        isin=self.isin,
                    ),
                    instrument_kind=self.kind,
                ),
            ),
        )

    def fetch_quote(self, identity: object, target_date: object) -> object:
        raise AssertionError("mapping fixture must not fetch quotes")

    def fetch_quotes(self, items: object) -> list[object]:
        raise AssertionError("mapping fixture must not fetch quotes")


def accept_t_invest_mapping(
    session: object,
    instrument_id: int,
    uid: str,
    *,
    kind: InstrumentType | None = None,
    isin: str | None = None,
) -> object:
    instrument = session.get(Instrument, instrument_id)
    assert instrument is not None
    resolved = kind or InstrumentType(instrument.instrument_type)
    return set_accepted_mapping(
        session,
        instrument_id,
        provider=T_INVEST_PROVIDER,
        provider_instrument_id=uid,
        provider_venue_id=None,
        isin=isin,
        verify_provider=_AcceptingTInvestProvider(uid, resolved, isin or instrument.isin),
    )
