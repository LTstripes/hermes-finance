"""R05-01: developer-only T-Invest payout probe + sanitized official fixture."""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

from hermes_finance.market_data.t_invest import PAYOUT_PROBE_METHODS, TInvestClient
from hermes_finance.market_data.t_invest_payout_probe import (
    ALLOWED_METHODS,
    DEFAULT_FIXTURE_PATH,
    FORBIDDEN_METHOD_MARKERS,
    ORDINARY_BOND_SYNTH_UID,
    ForbiddenTInvestMethod,
    RecordingAllowlistTransport,
    load_official_fixture,
    main,
    project_official_shape,
    sanitize_official_payload,
    write_canonical_fixture,
)


def test_probe_refuses_without_live() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_probe_without_token_does_not_call_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", raising=False)

    class BoomSettings:
        t_invest_read_only_token = None

    monkeypatch.setattr("hermes_finance.market_data.t_invest_payout_probe.Settings", BoomSettings)
    code = main(["--live"])
    assert code == 2


def test_allowlist_rejects_account_portfolio_and_order_methods() -> None:
    transport = RecordingAllowlistTransport()
    for marker in (
        "UsersService/GetAccounts",
        "OperationsService/GetOperations",
        "OperationsService/GetPortfolio",
        "OperationsService/GetPositions",
        "OrdersService/PostOrder",
        "StopOrdersService/PostStopOrder",
        "SandboxService/GetSandboxAccounts",
        "UsersService/GetInfo",
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
    assert "MarketDataService/GetLastPrices" not in ALLOWED_METHODS
    assert "MarketDataService/GetCandles" not in ALLOWED_METHODS


def test_client_payout_method_rejects_non_payout_surface() -> None:
    http = httpx2.Client(
        transport=httpx2.MockTransport(lambda request: httpx2.Response(500)),
        base_url="https://invest-public-api.tbank.ru/rest",
    )
    client = TInvestClient(token="fixture-token", client=http)
    with pytest.raises(ValueError, match="does not allow"):
        client.request_payout_method("GetAccounts", {"id": "nope"})
    assert "GetAccounts" not in PAYOUT_PROBE_METHODS
    assert PAYOUT_PROBE_METHODS == {"GetBondCoupons", "GetBondEvents", "GetDividends"}


def test_sanitizer_strips_secrets_and_live_identifiers() -> None:
    raw = {
        "authorization": "Bearer t.secret",
        "accountId": "acc-1",
        "events": [
            {
                "uid": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "figi": "BBGREALLIVE01",
                "ticker": "SBER",
                "isin": "RU0009029540",
                "name": "Live Issuer",
                "tokenHint": "t.secret",
            }
        ],
    }
    cleaned = sanitize_official_payload(raw)
    dumped = json.dumps(cleaned)
    assert "t.secret" not in dumped
    assert "accountId" not in dumped
    assert "SBER" not in dumped
    assert "RU0009029540" not in dumped
    assert "Live Issuer" not in dumped
    assert cleaned["events"][0]["uid"] == "00000001-1111-1111-1111-111111111111"
    assert cleaned["events"][0]["figi"] == "BBGSYNTH00001"


def test_official_fixture_has_no_token_or_account_payload() -> None:
    fixture = load_official_fixture()
    dumped = json.dumps(fixture)
    assert "t." not in dumped
    assert "Bearer" not in dumped
    assert "accountId" not in dumped
    assert "account_id" not in dumped
    assert "Authorization" not in dumped
    assert "GetPortfolio" not in dumped
    assert "GetPositions" not in dumped
    assert DEFAULT_FIXTURE_PATH.is_file()
    stock_div = fixture["stock"]["GetDividends"]["dividends"][0]
    assert set(stock_div["dividendNet"]) == {"units", "nano", "currency"}
    assert "paymentDate" in stock_div
    assert "recordDate" in stock_div
    coupon = fixture["ordinary_bond"]["GetBondCoupons"]["events"][0]
    assert str(coupon["couponNumber"]) in {"11", "12"}
    assert set(coupon["payOneBond"]) == {"currency", "units", "nano"}
    assert fixture["empty"]["GetDividends"]["dividends"] == []
    assert fixture["empty"]["GetBondCoupons"]["events"] == []


def test_project_official_shape_keeps_payout_fields_only() -> None:
    projected = project_official_shape(
        "InstrumentsService/GetDividends",
        {
            "dividends": [
                {
                    "dividendNet": {
                        "units": "1",
                        "nano": 0,
                        "currency": "rub",
                        "extra": True,
                    },
                    "paymentDate": "2026-07-15T00:00:00Z",
                    "recordDate": "2026-06-11T00:00:00Z",
                    "accountId": "drop-me",
                    "portfolio": "drop-me",
                }
            ]
        },
    )
    assert "accountId" not in projected["dividends"][0]
    assert "portfolio" not in projected["dividends"][0]
    assert projected["dividends"][0]["dividendNet"] == {
        "units": "1",
        "nano": 0,
        "currency": "rub",
    }


def _sanitize_captured(method: str, payload: dict[str, object]) -> dict[str, object]:
    cleaned = sanitize_official_payload(project_official_shape(method, payload))
    assert isinstance(cleaned, dict)
    return cleaned


def test_write_fixture_round_trip_uses_canonical_schema(tmp_path: Path) -> None:
    live_stock_uid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    live_bond_uid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    captured = {
        "stock": {
            "GetDividends": _sanitize_captured(
                "InstrumentsService/GetDividends",
                {
                    "dividends": [
                        {
                            "dividendNet": {
                                "units": "23",
                                "nano": 450000000,
                                "currency": "rub",
                            },
                            "paymentDate": "2026-07-15T00:00:00Z",
                            "recordDate": "2026-06-11T00:00:00Z",
                            "declaredDate": "2026-05-20T00:00:00Z",
                            "lastBuyDate": "2026-06-10T00:00:00Z",
                            "dividendType": "Regular Cash",
                            "regularity": "Annual",
                            "createdAt": "2026-05-21T12:00:00Z",
                            "accountId": "drop-me",
                        }
                    ]
                },
            )
        },
        "ordinary_bond": {
            "BondBy": _sanitize_captured(
                "InstrumentsService/BondBy",
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
                        "maturityDate": "2031-11-19T00:00:00Z",
                        "floatingCouponFlag": False,
                        "perpetualFlag": False,
                        "amortizationFlag": False,
                        "nominal": {"currency": "rub", "units": "1000", "nano": 0},
                    }
                },
            ),
            "GetBondCoupons": _sanitize_captured(
                "InstrumentsService/GetBondCoupons",
                {
                    "events": [
                        {
                            "figi": "BBGLIVE00003",
                            "couponDate": "2026-11-19T00:00:00Z",
                            "couponNumber": 12,
                            "payOneBond": {"currency": "rub", "units": "37", "nano": 400000000},
                            "couponType": "COUPON_TYPE_CONSTANT",
                            "couponStartDate": "2026-05-20T00:00:00Z",
                            "couponEndDate": "2026-11-19T00:00:00Z",
                            "couponPeriod": 183,
                        }
                    ]
                },
            ),
        },
        "empty": {
            "GetDividends": _sanitize_captured(
                "InstrumentsService/GetDividends",
                {"dividends": []},
            )
        },
    }
    written = tmp_path / "official_payout_shape.json"
    write_canonical_fixture(written, captured)
    reloaded = load_official_fixture(written)
    assert "meta" in reloaded
    assert "stock" in reloaded
    assert "ordinary_bond" in reloaded
    dumped = json.dumps(reloaded)
    assert "SBER" not in dumped
    assert "SU26238" not in dumped
    assert live_stock_uid not in dumped
    assert live_bond_uid not in dumped
    assert "accountId" not in dumped
    assert reloaded["ordinary_bond"]["BondBy"]["instrument"]["uid"] == ORDINARY_BOND_SYNTH_UID
    assert reloaded["ordinary_bond"]["GetBondCoupons"]["events"][0]["couponNumber"] == 12
    assert live_stock_uid not in json.dumps(reloaded["stock"])


def test_import_payout_probe_does_not_require_network() -> None:
    from hermes_finance.market_data import t_invest_payout_probe

    assert "GetBondCoupons" in {
        method.rsplit("/", 1)[-1] for method in t_invest_payout_probe.ALLOWED_METHODS
    }


def test_request_payout_method_posts_allowlisted_path() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        assert "Authorization" in request.headers
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx2.Response(200, json={"events": []})

    http = httpx2.Client(
        transport=httpx2.MockTransport(handler),
        base_url="https://invest-public-api.tbank.ru/rest",
    )
    client = TInvestClient(token="fixture-token", client=http)
    payload = client.request_payout_method(
        "GetBondCoupons",
        {"instrumentId": ORDINARY_BOND_SYNTH_UID},
    )
    assert payload == {"events": []}
    assert len(seen) == 1
    assert seen[0].endswith("InstrumentsService/GetBondCoupons")


def test_import_payout_probe_makes_zero_external_network() -> None:
    import os
    import subprocess
    import sys

    backend = Path(__file__).resolve().parents[1]
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        f"backend = Path(r'''{backend}''')\n"
        "sys.path.insert(0, str(backend))\n"
        "sys.path.insert(0, str(backend / 'src'))\n"
        "from tests.startup_network_guard import install_network_guard\n"
        "install_network_guard()\n"
        "import hermes_finance.market_data.t_invest_payout_probe as probe\n"
        "assert 'GetBondCoupons' in {item.rsplit('/', 1)[-1] for item in probe.ALLOWED_METHODS}\n"
        "print('import-ok')\n"
    )
    environment = os.environ.copy()
    environment.pop("HERMES_FINANCE_T_INVEST_READ_ONLY_TOKEN", None)
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "import-ok" in completed.stdout
