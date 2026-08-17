from __future__ import annotations

from datetime import date

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteStatus,
)
from hermes_finance.market_data.payout import PayoutEventStatus
from hermes_finance.market_data.payout_protocol import PayoutFetchRequest
from hermes_finance.market_data.t_invest_payout import TInvestPayoutProvider

_STOCK_UID = "11111111-1111-1111-1111-111111111111"


class _Client:
    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
    ) -> DiscoverResult:
        del query, isin
        assert provider_instrument_id == _STOCK_UID
        return DiscoverResult(
            status=QuoteStatus.OK,
            candidates=(
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider=T_INVEST_PROVIDER,
                        provider_instrument_id=_STOCK_UID,
                        provider_venue_id=None,
                    ),
                    instrument_kind=InstrumentType.STOCK,
                ),
            ),
        )

    def request_payout_method(
        self, method: str, body: dict[str, object]
    ) -> dict[str, object]:
        assert method == "GetDividends"
        assert body["instrumentId"] == _STOCK_UID
        return {
            "dividends": [
                {
                    "paymentDate": "2026-05-19T00:00:00Z",
                    "dividendNet": {"units": "278", "nano": 0, "currency": "rub"},
                }
            ]
        }


def test_missing_provider_filter_key_invalidates_coverage_without_inventing_identity() -> None:
    result = TInvestPayoutProvider(_Client()).fetch_payouts(
        PayoutFetchRequest(
            instrument_uid=_STOCK_UID,
            calendar_from=date(2026, 5, 1),
            calendar_to=date(2026, 5, 31),
        )
    )

    assert len(result.events) == 1
    assert result.events[0].status is PayoutEventStatus.AMBIGUOUS_IDENTITY
    assert result.events[0].identity_key is None
    assert result.events[0].provider_filter_date is None
    assert len(result.failures) == 1
    assert "filter date" in result.failures[0].message
    assert result.coverage[0].successful
    assert not result.coverage[0].structurally_valid
