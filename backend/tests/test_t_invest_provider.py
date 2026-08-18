"""Mocked official-REST tests for the T-Invest read-only market-data adapter."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

import httpx2
import pytest

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    MarketIdentity,
    QuoteFailure,
    QuoteKind,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
)
from hermes_finance.market_data.moex_identity import market_identity_from_moex
from hermes_finance.market_data.routing import (
    MOEX_PRODUCTION_DISABLED_MESSAGE,
    ProductionMarketDataProvider,
)
from hermes_finance.market_data.t_invest import (
    TOKEN_UNAVAILABLE_MESSAGE,
    TInvestClient,
    t_invest_identity,
)

TODAY = date(2026, 8, 13)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
STOCK_UID = "11111111-1111-1111-1111-111111111111"
FUND_UID = "22222222-2222-2222-2222-222222222222"
BOND_UID = "33333333-3333-3333-3333-333333333333"
STOCK_ISIN = "RU000SYNTH01"
BOND_ISIN = "RU000SYNTH03"
TEST_TOKEN = "test-token"


def _quotation(units: int | str, nano: int = 0) -> dict[str, object]:
    return {"units": str(units) if isinstance(units, int) else units, "nano": nano}


def _money(units: int | str, nano: int = 0, currency: str = "rub") -> dict[str, object]:
    return {"currency": currency, "units": units, "nano": nano}


def _instrument(
    uid: str,
    *,
    kind: str,
    instrument_type: str,
    isin: str | None,
    currency: str = "rub",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "uid": uid,
        "isin": isin,
        "currency": currency,
        "instrumentKind": kind,
        "instrumentType": instrument_type,
        "ticker": "SYNTH",
        "lot": 10,
        "realExchange": "REAL_EXCHANGE_MOEX",
    }
    if extra:
        body.update(extra)
    return {"instrument": body}


def _short(
    uid: str,
    *,
    kind: str,
    instrument_type: str,
    isin: str | None,
    ticker: str = "SYNTH",
    name: str = "Synthetic",
    class_code: str | None = None,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "uid": uid,
        "isin": isin,
        "instrumentKind": kind,
        "instrumentType": instrument_type,
        "ticker": ticker,
        "name": name,
    }
    if class_code is not None:
        body["classCode"] = class_code
    if extra:
        body.update(extra)
    return body


def _last_price(
    uid: str,
    *,
    units: int | str,
    nano: int,
    time: str,
    price_type: str = "LAST_PRICE_EXCHANGE",
) -> dict[str, object]:
    return {
        "lastPrices": [
            {
                "price": _quotation(units, nano),
                "time": time,
                "instrumentUid": uid,
                "lastPriceType": price_type,
            }
        ]
    }


def _candle(
    *,
    units: int | str,
    nano: int,
    time: str,
    complete: bool = True,
    source: str = "CANDLE_SOURCE_EXCHANGE",
) -> dict[str, object]:
    return {
        "close": _quotation(units, nano),
        "time": time,
        "isComplete": complete,
        "candleSourceType": source,
    }


class TInvestStub:
    def __init__(self) -> None:
        self.payloads: dict[str, Any] = {}
        self.errors: dict[str, Exception] = {}
        self.status_codes: dict[str, int] = {}
        self.requests: list[httpx2.Request] = []

    def set(self, method: str, payload: object) -> None:
        self.payloads[method] = payload

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else {}
        keyed = None
        if method in {"GetInstrumentBy", "BondBy"}:
            keyed = f"{method}:{body.get('id')}"
        if method in self.errors:
            raise self.errors[method]
        if keyed in self.errors:
            raise self.errors[keyed]
        if keyed in self.status_codes:
            return httpx2.Response(self.status_codes[keyed], json={"message": "upstream"})
        if method in self.status_codes:
            return httpx2.Response(self.status_codes[method], json={"message": "upstream"})
        payload = self.payloads.get(keyed) if keyed else None
        if payload is None:
            payload = self.payloads.get(method)
        if payload is None:
            return httpx2.Response(404, json={"message": "not found"})
        return httpx2.Response(200, json=payload)


def _client(
    stub: TInvestStub, *, today: date = TODAY, token: str | None = TEST_TOKEN
) -> TInvestClient:
    http = httpx2.Client(
        transport=httpx2.MockTransport(stub),
        base_url="https://invest-public-api.tbank.ru/rest",
    )
    return TInvestClient(token=token, client=http, clock=lambda: today, utcnow=lambda: FETCHED_AT)


def _stock_identity() -> MarketIdentity:
    return t_invest_identity(provider_instrument_id=STOCK_UID, isin=STOCK_ISIN)


def _prime_stock(stub: TInvestStub) -> None:
    stub.set(
        "GetInstrumentBy",
        _instrument(
            STOCK_UID,
            kind="INSTRUMENT_TYPE_SHARE",
            instrument_type="share",
            isin=STOCK_ISIN,
        ),
    )
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                _short(
                    STOCK_UID,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin=STOCK_ISIN,
                    ticker="SYNTHS",
                )
            ]
        },
    )


def test_exact_uid_resolves_one_candidate() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    result = _client(stub).discover_candidates(provider_instrument_id=STOCK_UID, isin=STOCK_ISIN)
    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    identity = result.candidates[0].identity
    assert identity.provider == T_INVEST_PROVIDER
    assert identity.provider_instrument_id == STOCK_UID
    assert identity.provider_venue_id is None
    assert identity.isin == STOCK_ISIN
    assert all("GetLastPrices" not in req.url.path for req in stub.requests)
    assert not any("figi" in json.loads(req.content) for req in stub.requests if req.content)


def test_isin_and_ticker_discovery() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    by_isin = _client(stub).discover_candidates(isin=STOCK_ISIN)
    assert by_isin.status is QuoteStatus.OK
    assert by_isin.candidates[0].identity.provider_instrument_id == STOCK_UID
    stub.requests.clear()
    by_ticker = _client(stub).discover_candidates(query="SYNTHS")
    assert by_ticker.status is QuoteStatus.OK
    bodies = [json.loads(req.content) for req in stub.requests if "FindInstrument" in req.url.path]
    assert bodies[0]["query"] == "SYNTHS"


def test_isin_mismatch_is_rejected() -> None:
    stub = TInvestStub()
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                _short(
                    STOCK_UID,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin="RU0000000000",
                )
            ]
        },
    )
    result = _client(stub).discover_candidates(isin=STOCK_ISIN)
    assert result.rejected
    assert result.rejected[0].candidate_isin == "RU0000000000"
    assert result.status is QuoteStatus.UNAVAILABLE
    assert result.candidates == ()


def test_multiple_candidates_are_ambiguous() -> None:
    stub = TInvestStub()
    other = "44444444-4444-4444-4444-444444444444"
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                _short(
                    STOCK_UID,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin=STOCK_ISIN,
                ),
                _short(
                    other, kind="INSTRUMENT_TYPE_SHARE", instrument_type="share", isin=STOCK_ISIN
                ),
            ]
        },
    )
    stub.set(
        f"GetInstrumentBy:{STOCK_UID}",
        _instrument(
            STOCK_UID, kind="INSTRUMENT_TYPE_SHARE", instrument_type="share", isin=STOCK_ISIN
        ),
    )
    stub.set(
        f"GetInstrumentBy:{other}",
        _instrument(other, kind="INSTRUMENT_TYPE_SHARE", instrument_type="share", isin=STOCK_ISIN),
    )
    result = _client(stub).discover_candidates(isin=STOCK_ISIN)
    assert result.status is QuoteStatus.AMBIGUOUS
    assert len(result.candidates) == 2


def test_ambiguous_bond_candidates_keep_disambiguation_metadata() -> None:
    stub = TInvestStub()
    bond_isin = "RU000SYNTH76"
    rows = [
        (
            "aaaa1111-1111-4111-8111-111111111111",
            "ОФЗ 26248 основной",
            "SU26248",
            "TQOB",
            True,
        ),
        (
            "aaaa2222-2222-4222-8222-222222222222",
            "ОФЗ 26248 внебиржевой контур",
            "SU26248OTC",
            "PSAU",
            False,
        ),
        (
            "aaaa3333-3333-4333-8333-333333333333",
            "ОФЗ 26248 РЕПО",
            "SU26248RP",
            "TQIR",
            True,
        ),
        (
            "aaaa4444-4444-4444-8444-444444444444",
            "ОФЗ 26248 квалифицированный",
            "SU26248QI",
            "TQCB",
            False,
        ),
        (
            "aaaa5555-5555-4555-8555-555555555555",
            "ОФЗ 26248 юань",
            "SU26248CN",
            "TQOD",
            True,
        ),
        (
            "aaaa6666-6666-4666-8666-666666666666",
            "ОФЗ 26248 лот 10",
            "SU26248L10",
            "TQOB",
            True,
        ),
        (
            "aaaa7777-7777-4777-8777-777777777777",
            "ОФЗ 26248 лот 1",
            "SU26248L1",
            "TQOB",
            True,
        ),
    ]
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                _short(
                    uid,
                    kind="INSTRUMENT_TYPE_BOND",
                    instrument_type="bond",
                    isin=bond_isin,
                    ticker=ticker,
                    name=name,
                    class_code=class_code,
                    extra={
                        "positionUid": f"bbbb{uid[4:]}",
                        "apiTradeAvailableFlag": api_trade,
                    },
                )
                for uid, name, ticker, class_code, api_trade in rows
            ]
        },
    )
    for uid, name, ticker, class_code, api_trade in rows:
        stub.set(
            f"GetInstrumentBy:{uid}",
            _instrument(
                uid,
                kind="INSTRUMENT_TYPE_BOND",
                instrument_type="bond",
                isin=bond_isin,
                extra={
                    "name": name,
                    "ticker": ticker,
                    "classCode": class_code,
                    "positionUid": f"bbbb{uid[4:]}",
                    "apiTradeAvailableFlag": api_trade,
                    "nominal": _money("1000"),
                },
            ),
        )
        stub.set(
            f"BondBy:{uid}",
            {
                "instrument": {
                    "uid": uid,
                    "currency": "rub",
                    "nominal": _money("1000"),
                }
            },
        )

    result = _client(stub).discover_candidates(isin=bond_isin)
    assert result.status is QuoteStatus.AMBIGUOUS
    assert len(result.candidates) == 7
    assert {item.identity.provider_instrument_id for item in result.candidates} == {
        uid for uid, *_ in rows
    }
    by_uid = {item.identity.provider_instrument_id: item for item in result.candidates}
    first = by_uid["aaaa1111-1111-4111-8111-111111111111"]
    assert first.identity.provider_instrument_id == "aaaa1111-1111-4111-8111-111111111111"
    assert first.name == "ОФЗ 26248 основной"
    assert first.ticker == "SU26248"
    assert first.class_code == "TQOB"
    assert first.exchange == "MOEX"
    assert first.api_trade_available is True
    assert first.position_uid == "bbbb1111-1111-4111-8111-111111111111"
    second = by_uid["aaaa2222-2222-4222-8222-222222222222"]
    assert second.api_trade_available is False
    assert second.class_code == "PSAU"
    assert all(item.identity.isin == bond_isin for item in result.candidates)


def test_malformed_neighbor_does_not_discard_valid_candidates() -> None:
    stub = TInvestStub()
    broken = "44444444-4444-4444-4444-444444444444"
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                {
                    "isin": STOCK_ISIN,
                    "instrumentKind": "INSTRUMENT_TYPE_SHARE",
                    "instrumentType": "share",
                    "ticker": "BROKEN",
                    "name": "Broken",
                },
                _short(
                    STOCK_UID,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin=STOCK_ISIN,
                ),
                _short(
                    broken,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin=STOCK_ISIN,
                ),
            ]
        },
    )
    stub.set(
        f"GetInstrumentBy:{STOCK_UID}",
        _instrument(
            STOCK_UID, kind="INSTRUMENT_TYPE_SHARE", instrument_type="share", isin=STOCK_ISIN
        ),
    )
    stub.set(
        f"GetInstrumentBy:{broken}",
        _instrument(
            "55555555-5555-5555-5555-555555555555",
            kind="INSTRUMENT_TYPE_SHARE",
            instrument_type="share",
            isin=STOCK_ISIN,
        ),
    )
    result = _client(stub).discover_candidates(isin=STOCK_ISIN)
    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    assert result.candidates[0].identity.provider_instrument_id == STOCK_UID
    assert result.candidates[0].identity.isin == STOCK_ISIN


def test_single_malformed_candidate_is_still_malformed() -> None:
    stub = TInvestStub()
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                {
                    "isin": STOCK_ISIN,
                    "instrumentKind": "INSTRUMENT_TYPE_SHARE",
                    "instrumentType": "share",
                }
            ]
        },
    )
    result = _client(stub).discover_candidates(isin=STOCK_ISIN)
    assert result.status is QuoteStatus.MALFORMED_RESPONSE
    assert result.candidates == ()


def test_unsupported_kind_and_non_null_venue() -> None:
    stub = TInvestStub()
    future = "55555555-5555-5555-5555-555555555555"
    stub.set(
        "GetInstrumentBy",
        _instrument(future, kind="INSTRUMENT_TYPE_FUTURES", instrument_type="futures", isin=None),
    )
    result = _client(stub).discover_candidates(provider_instrument_id=future)
    assert result.status is QuoteStatus.UNSUPPORTED
    with pytest.raises(ValueError, match="provider_venue_id"):
        from hermes_finance.services.instrument_mappings import normalize_accepted_identity

        normalize_accepted_identity(
            provider="t_invest",
            provider_instrument_id=STOCK_UID,
            provider_venue_id="TQBR",
        )


def test_figi_is_not_canonical() -> None:
    stub = TInvestStub()
    result = _client(stub).discover_candidates(provider_instrument_id="BBGSYNTH00001")
    assert result.status is QuoteStatus.MALFORMED_RESPONSE
    assert not stub.requests
    with pytest.raises(ValueError, match="instrument_uid UUID"):
        t_invest_identity(provider_instrument_id="BBGSYNTH00001")


def test_current_stock_and_fund_are_per_unit_not_lot() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    stub.set(
        "GetLastPrices",
        _last_price(STOCK_UID, units=15, nano=0, time="2026-08-13T10:00:00Z"),
    )
    stock = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert isinstance(stock, QuoteSuccess)
    assert stock.raw_price_basis is RawPriceBasis.CASH_PER_UNIT
    assert stock.proposed_price_kopecks == 1500
    assert stock.quote_kind is QuoteKind.LAST
    assert stock.price_date == TODAY

    stub.set(
        "GetInstrumentBy",
        _instrument(
            FUND_UID, kind="INSTRUMENT_TYPE_ETF", instrument_type="etf", isin="RU000SYNTH02"
        ),
    )
    stub.set(
        "GetLastPrices",
        _last_price(FUND_UID, units=100, nano=0, time="2026-08-13T10:00:00Z"),
    )
    fund = _client(stub).fetch_quote(t_invest_identity(provider_instrument_id=FUND_UID), TODAY)
    assert isinstance(fund, QuoteSuccess)
    assert fund.proposed_price_kopecks == 10_000
    assert fund.instrument_kind is InstrumentType.FUND


def test_current_bond_converts_points_times_provider_nominal() -> None:
    stub = TInvestStub()
    stub.set(
        "GetInstrumentBy",
        _instrument(BOND_UID, kind="INSTRUMENT_TYPE_BOND", instrument_type="bond", isin=BOND_ISIN),
    )
    stub.set(
        "BondBy",
        {
            "instrument": {
                "uid": BOND_UID,
                "currency": "rub",
                "nominal": _money(1000),
                "instrumentKind": "INSTRUMENT_TYPE_BOND",
            }
        },
    )
    stub.set(
        "GetLastPrices",
        _last_price(BOND_UID, units=97, nano=250_000_000, time="2026-08-13T10:00:00Z"),
    )
    result = _client(stub).fetch_quote(t_invest_identity(provider_instrument_id=BOND_UID), TODAY)
    assert isinstance(result, QuoteSuccess)
    assert result.raw_price_basis is RawPriceBasis.PERCENT_OF_FACE
    assert result.raw_price.startswith("97.25")
    assert result.proposed_price_kopecks == 97_250


def test_non_rub_stock_and_bond_are_unsupported() -> None:
    stub = TInvestStub()
    stub.set(
        "GetInstrumentBy",
        _instrument(
            STOCK_UID,
            kind="INSTRUMENT_TYPE_SHARE",
            instrument_type="share",
            isin=STOCK_ISIN,
            currency="usd",
        ),
    )
    stock = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert isinstance(stock, QuoteFailure)
    assert stock.status is QuoteStatus.UNSUPPORTED

    stub.set(
        "GetInstrumentBy",
        _instrument(BOND_UID, kind="INSTRUMENT_TYPE_BOND", instrument_type="bond", isin=BOND_ISIN),
    )
    stub.set(
        "BondBy",
        {
            "instrument": {
                "uid": BOND_UID,
                "currency": "usd",
                "nominal": _money(1000, currency="usd"),
            }
        },
    )
    bond = _client(stub).fetch_quote(t_invest_identity(provider_instrument_id=BOND_UID), TODAY)
    assert isinstance(bond, QuoteFailure)
    assert bond.status is QuoteStatus.UNSUPPORTED


def test_historical_candle_weekend_and_future_incomplete_ignored() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    target = date(2026, 8, 9)
    stub.set(
        "GetCandles",
        {
            "candles": [
                _candle(units=10, nano=0, time="2026-08-07T00:00:00Z", complete=True),
                _candle(units=11, nano=0, time="2026-08-08T00:00:00Z", complete=False),
                _candle(units=12, nano=0, time="2026-08-10T00:00:00Z", complete=True),
            ]
        },
    )
    result = _client(stub, today=date(2026, 8, 13)).fetch_quote(_stock_identity(), target)
    assert isinstance(result, QuoteSuccess)
    assert result.quote_kind is QuoteKind.HISTORY
    assert result.price_date == date(2026, 8, 7)
    assert result.proposed_price_kopecks == 1000
    assert result.freshness_status is QuoteStatus.OK


def test_exchange_candle_is_accepted_and_non_exchange_is_ignored() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    target = date(2026, 8, 9)
    stub.set(
        "GetCandles",
        {
            "candles": [
                _candle(
                    units=10,
                    nano=0,
                    time="2026-08-07T00:00:00Z",
                    source="CANDLE_SOURCE_EXCHANGE",
                ),
                _candle(
                    units=99,
                    nano=0,
                    time="2026-08-08T00:00:00Z",
                    source="CANDLE_SOURCE_DEALER_WEEKEND",
                ),
            ]
        },
    )
    accepted = _client(stub, today=date(2026, 8, 13)).fetch_quote(_stock_identity(), target)
    assert isinstance(accepted, QuoteSuccess)
    assert accepted.proposed_price_kopecks == 1000
    assert accepted.price_date == date(2026, 8, 7)

    stub.set(
        "GetCandles",
        {
            "candles": [
                _candle(
                    units=99,
                    nano=0,
                    time="2026-08-08T00:00:00Z",
                    source="CANDLE_SOURCE_DEALER_WEEKEND",
                )
            ]
        },
    )
    rejected = _client(stub, today=date(2026, 8, 13)).fetch_quote(_stock_identity(), target)
    assert isinstance(rejected, QuoteFailure)
    assert rejected.status is QuoteStatus.UNAVAILABLE


def test_freshness_stale_and_unavailable() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    stub.set(
        "GetCandles",
        {"candles": [_candle(units=10, nano=0, time="2026-08-01T00:00:00Z")]},
    )
    stale = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert isinstance(stale, QuoteSuccess)
    assert stale.freshness_status is QuoteStatus.STALE
    stub.set(
        "GetCandles",
        {"candles": [_candle(units=10, nano=0, time="2026-07-01T00:00:00Z")]},
    )
    missing = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert isinstance(missing, QuoteFailure)
    assert missing.status is QuoteStatus.UNAVAILABLE


def test_historical_bond_conversion() -> None:
    stub = TInvestStub()
    stub.set(
        "GetInstrumentBy",
        _instrument(BOND_UID, kind="INSTRUMENT_TYPE_BOND", instrument_type="bond", isin=BOND_ISIN),
    )
    stub.set(
        "BondBy",
        {"instrument": {"uid": BOND_UID, "currency": "rub", "nominal": _money("1000")}},
    )
    stub.set(
        "GetCandles",
        {"candles": [_candle(units=98, nano=0, time="2026-08-10T21:00:00Z")]},
    )
    result = _client(stub).fetch_quote(
        t_invest_identity(provider_instrument_id=BOND_UID), date(2026, 8, 11)
    )
    assert isinstance(result, QuoteSuccess)
    assert result.quote_kind is QuoteKind.HISTORY
    assert result.price_date == date(2026, 8, 11)
    assert result.proposed_price_kopecks == 98_000


def test_missing_token_is_unavailable_without_network() -> None:
    stub = TInvestStub()
    client = _client(stub, token=None)
    discovered = client.discover_candidates(isin=STOCK_ISIN)
    quoted = client.fetch_quote(_stock_identity(), TODAY)
    assert discovered.status is QuoteStatus.UNAVAILABLE
    assert discovered.message == TOKEN_UNAVAILABLE_MESSAGE
    assert isinstance(quoted, QuoteFailure)
    assert quoted.status is QuoteStatus.UNAVAILABLE
    assert quoted.message == TOKEN_UNAVAILABLE_MESSAGE
    assert stub.requests == []


def test_auth_timeout_408_429_and_5xx_mapping() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    stub.status_codes["GetInstrumentBy"] = 401
    unavailable = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert isinstance(unavailable, QuoteFailure)
    assert unavailable.status is QuoteStatus.UNAVAILABLE
    assert TEST_TOKEN not in (unavailable.message or "")

    stub.status_codes.clear()
    stub.errors["GetInstrumentBy"] = httpx2.ConnectError("refused")
    assert _client(stub).fetch_quote(_stock_identity(), TODAY).status is QuoteStatus.NETWORK_ERROR

    stub.errors["GetInstrumentBy"] = httpx2.TimeoutException("timeout")
    assert _client(stub).fetch_quote(_stock_identity(), TODAY).status is QuoteStatus.NETWORK_ERROR

    stub.errors.clear()
    stub.status_codes["GetInstrumentBy"] = 408
    timeout_response = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert timeout_response.status is QuoteStatus.NETWORK_ERROR
    assert TEST_TOKEN not in (timeout_response.message or "")
    stub.status_codes["GetInstrumentBy"] = 429
    assert _client(stub).fetch_quote(_stock_identity(), TODAY).status is QuoteStatus.NETWORK_ERROR
    stub.status_codes["GetInstrumentBy"] = 503
    assert _client(stub).fetch_quote(_stock_identity(), TODAY).status is QuoteStatus.NETWORK_ERROR


def test_malformed_quotation_and_payload() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    stub.set(
        "GetLastPrices",
        {
            "lastPrices": [
                {
                    "price": {"units": "1.5", "nano": 0},
                    "time": "2026-08-13T10:00:00Z",
                    "instrumentUid": STOCK_UID,
                    "lastPriceType": "LAST_PRICE_EXCHANGE",
                }
            ]
        },
    )
    bad = _client(stub).fetch_quote(_stock_identity(), TODAY)
    assert isinstance(bad, QuoteFailure)
    assert bad.status is QuoteStatus.MALFORMED_RESPONSE

    stub.set("GetLastPrices", {"lastPrices": "nope"})
    assert (
        _client(stub).fetch_quote(_stock_identity(), TODAY).status is QuoteStatus.MALFORMED_RESPONSE
    )


def test_unexpected_programming_error_propagates() -> None:
    class Boom(httpx2.BaseTransport):
        def handle_request(self, request: httpx2.Request) -> httpx2.Response:
            raise TypeError("synthetic contract bug")

    client = TInvestClient(
        token=TEST_TOKEN,
        client=httpx2.Client(transport=Boom(), base_url="https://example.test"),
        clock=lambda: TODAY,
        utcnow=lambda: FETCHED_AT,
    )
    with pytest.raises(TypeError, match="synthetic contract bug"):
        client.fetch_quote(_stock_identity(), TODAY)


def test_batch_preserves_partial_success_and_order() -> None:
    stub = TInvestStub()
    _prime_stock(stub)
    stub.set(
        f"GetInstrumentBy:{FUND_UID}",
        _instrument(
            FUND_UID, kind="INSTRUMENT_TYPE_ETF", instrument_type="etf", isin="RU000SYNTH02"
        ),
    )
    stub.set(
        "GetLastPrices",
        _last_price(STOCK_UID, units=15, nano=0, time="2026-08-13T10:00:00Z"),
    )
    fund_id = t_invest_identity(provider_instrument_id=FUND_UID)
    moex = market_identity_from_moex(engine="stock", market="shares", boardid="TQBR", secid="SBER")
    provider = ProductionMarketDataProvider(_client(stub))
    results = provider.fetch_quotes(
        [
            (_stock_identity(), TODAY),
            (fund_id, TODAY),
            (moex, TODAY),
        ]
    )
    assert isinstance(results[0], QuoteSuccess)
    assert isinstance(results[1], QuoteFailure)
    assert results[1].status is QuoteStatus.UNAVAILABLE
    assert isinstance(results[2], QuoteFailure)
    assert results[2].status is QuoteStatus.UNSUPPORTED
    assert results[2].message == MOEX_PRODUCTION_DISABLED_MESSAGE
    assert all("iss.moex.com" not in str(req.url) for req in stub.requests)
    requested_ids = [
        json.loads(req.content).get("id")
        for req in stub.requests
        if "GetInstrumentBy" in req.url.path
    ]
    assert FUND_UID in requested_ids
    assert "SBER" not in requested_ids


def test_wrong_provider_does_not_call_t_invest() -> None:
    stub = TInvestStub()
    moex = market_identity_from_moex(engine="stock", market="shares", boardid="TQBR", secid="SBER")
    result = _client(stub).fetch_quote(moex, TODAY)
    assert isinstance(result, QuoteFailure)
    assert result.status is QuoteStatus.UNSUPPORTED
    assert stub.requests == []


def test_uid_is_canonical_uuid_text() -> None:
    identity = t_invest_identity(provider_instrument_id=STOCK_UID.upper())
    assert identity.provider_instrument_id == str(UUID(STOCK_UID))
    assert identity.provider_venue_id is None


def test_sber_share_is_not_displaced_by_bond_limit() -> None:
    stub = TInvestStub()
    bond_uids = [f"33333333-3333-3333-3333-3333333333{index:02d}" for index in range(12)]
    instruments = [
        _short(
            uid,
            kind="INSTRUMENT_TYPE_BOND",
            instrument_type="bond",
            isin=f"RU000A0JX{index:03d}",
            ticker=f"SBER-{index:03d}P",
            name=f"Сбербанк БО-{index:03d}P",
        )
        for index, uid in enumerate(bond_uids)
    ]
    instruments.append(
        _short(
            STOCK_UID,
            kind="INSTRUMENT_TYPE_SHARE",
            instrument_type="share",
            isin=STOCK_ISIN,
            ticker="SBER",
            name="Сбербанк",
        )
    )
    stub.set("FindInstrument", {"instruments": instruments})
    stub.set(
        f"GetInstrumentBy:{STOCK_UID}",
        _instrument(
            STOCK_UID,
            kind="INSTRUMENT_TYPE_SHARE",
            instrument_type="share",
            isin=STOCK_ISIN,
            extra={"ticker": "SBER", "name": "Сбербанк"},
        ),
    )
    result = _client(stub).discover_candidates(query="SBER", instrument_kind=InstrumentType.STOCK)
    assert [item.ticker for item in result.candidates] == ["SBER"]
    assert result.candidates[0].identity.provider_instrument_id == STOCK_UID
    assert result.status is QuoteStatus.OK
    bodies = [json.loads(req.content) for req in stub.requests if "FindInstrument" in req.url.path]
    assert bodies[0]["query"] == "SBER"
    assert bodies[0]["instrumentKind"] == "INSTRUMENT_TYPE_SHARE"
    assert not any("BondBy" in req.url.path for req in stub.requests)


def test_discover_filters_mixed_kinds_before_accepting() -> None:
    stub = TInvestStub()
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                _short(
                    BOND_UID,
                    kind="INSTRUMENT_TYPE_BOND",
                    instrument_type="bond",
                    isin=BOND_ISIN,
                    ticker="SBER-001P",
                ),
                _short(
                    STOCK_UID,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin=STOCK_ISIN,
                    ticker="SBER",
                ),
                _short(
                    FUND_UID,
                    kind="INSTRUMENT_TYPE_ETF",
                    instrument_type="etf",
                    isin="RU000SYNTH02",
                    ticker="SBERF",
                ),
            ]
        },
    )
    stub.set(
        f"GetInstrumentBy:{STOCK_UID}",
        _instrument(
            STOCK_UID, kind="INSTRUMENT_TYPE_SHARE", instrument_type="share", isin=STOCK_ISIN
        ),
    )
    result = _client(stub).discover_candidates(query="SBER", instrument_kind=InstrumentType.STOCK)
    assert result.status is QuoteStatus.OK
    assert len(result.candidates) == 1
    assert result.candidates[0].instrument_kind is InstrumentType.STOCK
    assert result.candidates[0].identity.provider_instrument_id == STOCK_UID


def test_discover_kind_filter_preserves_isin_mismatch() -> None:
    stub = TInvestStub()
    stub.set(
        "FindInstrument",
        {
            "instruments": [
                _short(
                    STOCK_UID,
                    kind="INSTRUMENT_TYPE_SHARE",
                    instrument_type="share",
                    isin="RU0000000000",
                    ticker="SBER",
                )
            ]
        },
    )
    result = _client(stub).discover_candidates(
        isin=STOCK_ISIN, instrument_kind=InstrumentType.STOCK
    )
    assert result.rejected
    assert result.rejected[0].candidate_isin == "RU0000000000"
    assert result.status is QuoteStatus.UNAVAILABLE
    assert result.candidates == ()
