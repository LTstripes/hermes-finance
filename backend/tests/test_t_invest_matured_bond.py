"""Regression coverage for matured T-Invest bonds with zero current nominal (M05-07)."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import httpx2

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import QuoteFailure, QuoteKind, QuoteStatus, QuoteSuccess
from hermes_finance.market_data.t_invest import TInvestClient, t_invest_identity

TODAY = date(2026, 8, 19)
FETCHED_AT = datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)
BOND_UID = "77777777-7777-4777-8777-777777777777"
BOND_ISIN = "RU000A10AU73"
TOKEN = "test-token"


def _money(units: int | str, *, currency: str = "rub") -> dict[str, object]:
    return {"currency": currency, "units": units, "nano": 0}


def _bond_payload(*, amortizing: bool = False, include_nominal: bool = True) -> dict[str, object]:
    body: dict[str, object] = {
        "uid": BOND_UID,
        "currency": "rub",
        "initialNominal": _money(1000),
        "maturityDate": "2026-08-04T00:00:00Z",
        "amortizationFlag": amortizing,
    }
    if include_nominal:
        body["nominal"] = _money(0)
    return {"instrument": body}


class Stub:
    def __init__(self, *, amortizing: bool = False, include_nominal: bool = True) -> None:
        self.amortizing = amortizing
        self.include_nominal = include_nominal
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "FindInstrument":
            return httpx2.Response(
                200,
                json={
                    "instruments": [
                        {
                            "uid": BOND_UID,
                            "isin": BOND_ISIN,
                            "instrumentKind": "INSTRUMENT_TYPE_BOND",
                            "instrumentType": "bond",
                            "ticker": "GTLK-002P07",
                            "name": "ГТЛК БО 002P-07",
                            "classCode": "TQCB",
                            "apiTradeAvailableFlag": False,
                        }
                    ]
                },
            )
        if method == "GetInstrumentBy":
            return httpx2.Response(
                200,
                json={
                    "instrument": {
                        "uid": BOND_UID,
                        "isin": BOND_ISIN,
                        "currency": "rub",
                        "instrumentKind": "INSTRUMENT_TYPE_BOND",
                        "instrumentType": "bond",
                        "ticker": "GTLK-002P07",
                        "name": "ГТЛК БО 002P-07",
                        "realExchange": "REAL_EXCHANGE_MOEX",
                    }
                },
            )
        if method == "BondBy":
            return httpx2.Response(
                200,
                json=_bond_payload(
                    amortizing=self.amortizing,
                    include_nominal=self.include_nominal,
                ),
            )
        if method == "GetCandles":
            return httpx2.Response(
                200,
                json={
                    "candles": [
                        {
                            "close": {"units": "98", "nano": 0},
                            "time": "2026-07-31T00:00:00Z",
                            "isComplete": True,
                            "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
                        }
                    ]
                },
            )
        return httpx2.Response(404, json={"message": "not found"})


def _client(stub: Stub) -> TInvestClient:
    http = httpx2.Client(
        transport=httpx2.MockTransport(stub),
        base_url="https://invest-public-api.tbank.ru/rest",
    )
    return TInvestClient(
        token=TOKEN,
        client=http,
        clock=lambda: TODAY,
        utcnow=lambda: FETCHED_AT,
    )


def test_matured_non_amortizing_bond_can_be_discovered_with_initial_nominal() -> None:
    stub = Stub()
    result = _client(stub).discover_candidates(
        isin=BOND_ISIN,
        instrument_kind=InstrumentType.BOND,
    )

    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    assert result.candidates[0].identity.provider_instrument_id == BOND_UID


def test_matured_non_amortizing_bond_uses_initial_nominal_before_maturity() -> None:
    stub = Stub()
    result = _client(stub).fetch_quote(
        t_invest_identity(provider_instrument_id=BOND_UID, isin=BOND_ISIN),
        date(2026, 7, 31),
    )

    assert isinstance(result, QuoteSuccess)
    assert result.quote_kind is QuoteKind.HISTORY
    assert result.proposed_price_kopecks == 98_000


def test_matured_bond_does_not_invent_face_value_on_or_after_maturity() -> None:
    stub = Stub()
    result = _client(stub).fetch_quote(
        t_invest_identity(provider_instrument_id=BOND_UID, isin=BOND_ISIN),
        date(2026, 8, 5),
    )

    assert isinstance(result, QuoteFailure)
    assert result.status is QuoteStatus.UNAVAILABLE
    assert not any(request.url.path.endswith("/GetCandles") for request in stub.requests)


def test_zero_nominal_amortizing_bond_fails_closed() -> None:
    discover_stub = Stub(amortizing=True)
    discovered = _client(discover_stub).discover_candidates(
        isin=BOND_ISIN,
        instrument_kind=InstrumentType.BOND,
    )
    assert discovered.status is QuoteStatus.UNSUPPORTED

    quote_stub = Stub(amortizing=True)
    quoted = _client(quote_stub).fetch_quote(
        t_invest_identity(provider_instrument_id=BOND_UID, isin=BOND_ISIN),
        date(2026, 7, 31),
    )
    assert isinstance(quoted, QuoteFailure)
    assert quoted.status is QuoteStatus.UNSUPPORTED
    assert not any(request.url.path.endswith("/GetCandles") for request in quote_stub.requests)


def test_missing_current_nominal_stays_malformed() -> None:
    stub = Stub(include_nominal=False)
    result = _client(stub).discover_candidates(
        isin=BOND_ISIN,
        instrument_kind=InstrumentType.BOND,
    )

    assert result.status is QuoteStatus.MALFORMED_RESPONSE
    assert result.candidates == ()
