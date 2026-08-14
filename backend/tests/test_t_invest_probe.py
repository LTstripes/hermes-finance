"""R04-05D: developer-only T-Invest probe + sanitized official fixture."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx2
import pytest

from hermes_finance.market_data.dto import QuoteStatus, QuoteSuccess
from hermes_finance.market_data.t_invest import TInvestClient, t_invest_identity
from hermes_finance.market_data.t_invest_probe import (
    ALLOWED_METHODS,
    BOND_SYNTH_UID,
    DEFAULT_FIXTURE_PATH,
    FORBIDDEN_METHOD_MARKERS,
    STOCK_SYNTH_UID,
    ForbiddenTInvestMethod,
    RecordingAllowlistTransport,
    load_official_fixture,
    main,
    project_official_shape,
    sanitize_official_payload,
    write_canonical_fixture,
)

TODAY = date(2026, 8, 13)
FETCHED_AT = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
STOCK_UID = STOCK_SYNTH_UID
BOND_UID = BOND_SYNTH_UID


class FixtureTransport:
    def __init__(self, fixture: dict[str, object]) -> None:
        self.fixture = fixture
        self.paths: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.paths.append(request.url.path)
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else {}
        requested = str(body.get("id") or "")
        instrument_id = body.get("instrumentId")
        if not requested and isinstance(instrument_id, list) and instrument_id:
            requested = str(instrument_id[0])
        elif not requested and isinstance(instrument_id, str):
            requested = instrument_id
        section = "bond" if method == "BondBy" or requested == BOND_UID else "stock"
        payloads = self.fixture[section]
        assert isinstance(payloads, dict)
        payload = payloads.get(method)
        if payload is None:
            return httpx2.Response(404, json={"message": "not found"})
        return httpx2.Response(200, json=payload)


def _client(
    fixture: dict[str, object], *, today: date = TODAY
) -> tuple[TInvestClient, FixtureTransport]:
    stub = FixtureTransport(fixture)
    http = httpx2.Client(
        transport=httpx2.MockTransport(stub),
        base_url="https://invest-public-api.tbank.ru/rest",
    )
    client = TInvestClient(
        token="fixture-token",
        client=http,
        clock=lambda: today,
        utcnow=lambda: FETCHED_AT,
    )
    return client, stub


def test_probe_refuses_without_live() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_probe_without_token_does_not_call_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", raising=False)

    class BoomSettings:
        t_invest_read_only_token = None

    monkeypatch.setattr("hermes_finance.market_data.t_invest_probe.Settings", BoomSettings)
    code = main(["--live"])
    assert code == 2


def test_allowlist_rejects_account_and_order_methods() -> None:
    transport = RecordingAllowlistTransport()
    for marker in (
        "UsersService/GetAccounts",
        "OperationsService/GetOperations",
        "OrdersService/PostOrder",
    ):
        request = httpx2.Request(
            "POST",
            f"https://invest-public-api.tbank.ru/rest/tinkoff.public.invest.api.contract.v1.{marker}",
        )
        with pytest.raises(ForbiddenTInvestMethod, match="forbidden"):
            transport.handle_request(request)
    assert not any(
        marker in allowed for allowed in ALLOWED_METHODS for marker in FORBIDDEN_METHOD_MARKERS
    )


def test_sanitizer_strips_secrets_and_live_identifiers() -> None:
    raw = {
        "authorization": "Bearer t.secret",
        "accountId": "acc-1",
        "instrument": {
            "uid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "figi": "BBGREALLIVE01",
            "ticker": "SBER",
            "isin": "RU0009029540",
            "name": "Live Issuer",
            "tokenHint": "t.secret",
        },
    }
    cleaned = sanitize_official_payload(raw)
    dumped = json.dumps(cleaned)
    assert "t.secret" not in dumped
    assert "accountId" not in dumped
    assert "SBER" not in dumped
    assert "RU0009029540" not in dumped
    assert "Live Issuer" not in dumped
    assert cleaned["instrument"]["uid"] == "00000001-1111-1111-1111-111111111111"
    assert cleaned["instrument"]["figi"] == "BBGSYNTH00001"


def test_official_fixture_has_no_token_or_account_payload() -> None:
    fixture = load_official_fixture()
    dumped = json.dumps(fixture)
    assert "t." not in dumped
    assert "Bearer" not in dumped
    assert "accountId" not in dumped
    assert "account_id" not in dumped
    assert "Authorization" not in dumped
    assert DEFAULT_FIXTURE_PATH.is_file()
    stock = fixture["stock"]
    assert stock["GetLastPrices"]["lastPrices"][0]["lastPriceType"] == "LAST_PRICE_EXCHANGE"
    assert stock["GetCandles"]["candles"][0]["candleSourceType"] == "CANDLE_SOURCE_EXCHANGE"
    assert set(stock["GetLastPrices"]["lastPrices"][0]["price"]) == {"units", "nano"}
    assert set(fixture["bond"]["BondBy"]["instrument"]["nominal"]) == {
        "currency",
        "units",
        "nano",
    }


def _exercise_stock_historical(fixture: dict[str, object]) -> None:
    client, stub = _client(fixture)
    discovered = client.discover_candidates(query="SYNTHS")
    assert discovered.status is QuoteStatus.OK
    identity = discovered.candidates[0].identity
    assert identity.provider_instrument_id == STOCK_UID
    current = client.fetch_quote(identity, TODAY)
    assert isinstance(current, QuoteSuccess)
    assert current.quote_kind.value == "last"
    assert current.raw_price.startswith("15.25")
    assert current.proposed_price_kopecks == 1525
    assert current.price_date == TODAY

    historical = client.fetch_quote(identity, date(2026, 8, 12))
    assert isinstance(historical, QuoteSuccess)
    assert historical.quote_kind.value == "history"
    assert historical.price_date == date(2026, 8, 1)
    assert historical.price_date <= date(2026, 8, 12)
    assert historical.proposed_price_kopecks == 1480
    joined = " ".join(stub.paths)
    assert "FindInstrument" in joined
    assert "GetInstrumentBy" in joined
    assert "GetLastPrices" in joined
    assert "GetCandles" in joined
    assert "Accounts" not in joined
    assert "Orders" not in joined
    assert "Operations" not in joined
    assert "Sandbox" not in joined
    assert "Transfer" not in joined


def test_official_fixture_stock_quote_and_historical_as_of() -> None:
    _exercise_stock_historical(load_official_fixture())


def _exercise_bond_money_value(fixture: dict[str, object]) -> None:
    client, stub = _client(fixture)
    identity = t_invest_identity(provider_instrument_id=BOND_UID, isin="RU000SYNTH03")
    result = client.fetch_quote(identity, date(2026, 8, 11))
    assert isinstance(result, QuoteSuccess)
    assert result.price_date == date(2026, 8, 11)
    assert result.price_date <= date(2026, 8, 11)
    assert result.proposed_price_kopecks == 97_250
    assert any("BondBy" in path for path in stub.paths)


def test_official_fixture_bond_money_value_and_future_candle_ignored() -> None:
    _exercise_bond_money_value(load_official_fixture())


def _sanitize_captured(method: str, payload: dict[str, object]) -> dict[str, object]:
    cleaned = sanitize_official_payload(project_official_shape(method, payload))
    assert isinstance(cleaned, dict)
    return cleaned


def test_write_fixture_round_trip_uses_canonical_schema(tmp_path: Path) -> None:
    live_stock_uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    live_bond_uid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    captured = {
        "stock": {
            "FindInstrument": _sanitize_captured(
                "InstrumentsService/FindInstrument",
                {
                    "instruments": [
                        {
                            "uid": live_stock_uid,
                            "figi": "BBGLIVE00001",
                            "ticker": "SBER",
                            "classCode": "TQBR",
                            "isin": "RU0009029540",
                            "name": "Live Share",
                            "instrumentKind": "INSTRUMENT_TYPE_SHARE",
                            "instrumentType": "share",
                            "accountId": "drop-me",
                        }
                    ]
                },
            ),
            "GetInstrumentBy": _sanitize_captured(
                "InstrumentsService/GetInstrumentBy",
                {
                    "instrument": {
                        "uid": live_stock_uid,
                        "figi": "BBGLIVE00001",
                        "ticker": "SBER",
                        "classCode": "TQBR",
                        "isin": "RU0009029540",
                        "name": "Live Share",
                        "lot": 10,
                        "currency": "rub",
                        "instrumentKind": "INSTRUMENT_TYPE_SHARE",
                        "instrumentType": "share",
                        "realExchange": "REAL_EXCHANGE_MOEX",
                    }
                },
            ),
            "GetLastPrices": _sanitize_captured(
                "MarketDataService/GetLastPrices",
                {
                    "lastPrices": [
                        {
                            "figi": "BBGLIVE00001",
                            "price": {"units": "15", "nano": 250000000, "extra": True},
                            "time": "2026-08-13T10:00:00Z",
                            "instrumentUid": live_stock_uid,
                            "lastPriceType": "LAST_PRICE_EXCHANGE",
                            "accountId": "drop-me",
                        }
                    ]
                },
            ),
            "GetCandles": _sanitize_captured(
                "MarketDataService/GetCandles",
                {
                    "candles": [
                        {
                            "open": {"units": "14", "nano": 0},
                            "high": {"units": "15", "nano": 0},
                            "low": {"units": "13", "nano": 500000000},
                            "close": {"units": "14", "nano": 800000000},
                            "volume": "1000",
                            "time": "2026-08-01T00:00:00Z",
                            "isComplete": True,
                            "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
                        },
                        {
                            "close": {"units": "16", "nano": 500000000},
                            "time": "2026-08-20T00:00:00Z",
                            "isComplete": True,
                            "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
                        },
                    ]
                },
            ),
        },
        "bond": {
            "GetInstrumentBy": _sanitize_captured(
                "InstrumentsService/GetInstrumentBy",
                {
                    "instrument": {
                        "uid": live_bond_uid,
                        "figi": "BBGLIVE00003",
                        "ticker": "SU26238",
                        "classCode": "TQOB",
                        "isin": "RU000A0JX0J2",
                        "name": "Live Bond",
                        "currency": "rub",
                        "instrumentKind": "INSTRUMENT_TYPE_BOND",
                        "instrumentType": "bond",
                        "realExchange": "REAL_EXCHANGE_MOEX",
                    }
                },
            ),
            "BondBy": _sanitize_captured(
                "InstrumentsService/BondBy",
                {
                    "instrument": {
                        "uid": live_bond_uid,
                        "currency": "rub",
                        "instrumentKind": "INSTRUMENT_TYPE_BOND",
                        "instrumentType": "bond",
                        "nominal": {"currency": "rub", "units": "1000", "nano": 0},
                    }
                },
            ),
            "GetCandles": _sanitize_captured(
                "MarketDataService/GetCandles",
                {
                    "candles": [
                        {
                            "close": {"units": "97", "nano": 250000000},
                            "time": "2026-08-10T21:00:00Z",
                            "isComplete": True,
                            "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
                        },
                        {
                            "close": {"units": "99", "nano": 0},
                            "time": "2026-08-20T00:00:00Z",
                            "isComplete": True,
                            "candleSourceType": "CANDLE_SOURCE_EXCHANGE",
                        },
                    ]
                },
            ),
        },
    }
    written = tmp_path / "official_rest_shape.json"
    write_canonical_fixture(written, captured)
    reloaded = load_official_fixture(written)
    assert set(reloaded) == {"meta", "stock", "bond"}
    assert "captured_methods" not in reloaded
    assert "payloads" not in reloaded
    dumped = json.dumps(reloaded)
    assert "SBER" not in dumped
    assert "SU26238" not in dumped
    assert live_stock_uid not in dumped
    assert live_bond_uid not in dumped
    assert "accountId" not in dumped
    assert reloaded["stock"]["GetInstrumentBy"]["instrument"]["uid"] == STOCK_UID
    assert reloaded["bond"]["BondBy"]["instrument"]["uid"] == BOND_UID
    _exercise_stock_historical(reloaded)
    _exercise_bond_money_value(reloaded)


def test_project_official_shape_keeps_adapter_fields_only() -> None:
    projected = project_official_shape(
        "MarketDataService/GetLastPrices",
        {
            "lastPrices": [
                {
                    "price": {"units": "1", "nano": 0, "extra": True},
                    "instrumentUid": STOCK_UID,
                    "lastPriceType": "LAST_PRICE_EXCHANGE",
                    "accountId": "drop-me",
                }
            ]
        },
    )
    assert "accountId" not in projected["lastPrices"][0]
    assert projected["lastPrices"][0]["price"] == {"units": "1", "nano": 0}
