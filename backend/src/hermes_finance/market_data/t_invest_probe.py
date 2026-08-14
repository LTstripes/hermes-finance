"""Developer-only live T-Invest read-only probe. CI must not invoke this module.

Usage:
    uv run python -m hermes_finance.market_data.t_invest_probe --live
    uv run python -m hermes_finance.market_data.t_invest_probe --live --write-fixture
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

import httpx2

from hermes_finance.market_data.dto import QuoteSuccess
from hermes_finance.market_data.moscow import MOSCOW_TZ
from hermes_finance.market_data.routing import read_t_invest_token
from hermes_finance.market_data.t_invest import TInvestClient
from hermes_finance.settings import REPOSITORY_ROOT, Settings

ALLOWED_METHODS: Final = frozenset(
    {
        "InstrumentsService/FindInstrument",
        "InstrumentsService/GetInstrumentBy",
        "InstrumentsService/BondBy",
        "MarketDataService/GetLastPrices",
        "MarketDataService/GetCandles",
    }
)
FORBIDDEN_METHOD_MARKERS: Final = frozenset(
    {
        "Accounts",
        "Operations",
        "Orders",
        "Sandbox",
        "Transfer",
        "UsersService",
        "StopOrders",
        "SignalService",
    }
)
DEFAULT_FIXTURE_PATH: Final = (
    REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "t_invest" / "official_rest_shape.json"
)
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SENSITIVE_KEY_RE = re.compile(
    r"token|authorization|account|password|secret|refresh|transfer|order",
    re.IGNORECASE,
)


class ForbiddenTInvestMethod(RuntimeError):
    """Raised when a non-market-data T-Invest method is requested."""


class RecordingAllowlistTransport(httpx2.HTTPTransport):
    """Permit only R04-05B Instruments/MarketData methods and record their names."""

    def __init__(self) -> None:
        super().__init__()
        self.methods: list[str] = []

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        method = _method_from_path(request.url.path)
        if any(marker in method for marker in FORBIDDEN_METHOD_MARKERS):
            raise ForbiddenTInvestMethod(f"refusing forbidden T-Invest method: {method}")
        if method not in ALLOWED_METHODS:
            raise ForbiddenTInvestMethod(f"refusing unlisted T-Invest method: {method}")
        self.methods.append(method)
        return super().handle_request(request)


def _method_from_path(path: str) -> str:
    marker = "tinkoff.public.invest.api.contract.v1."
    if marker not in path:
        return path.rsplit("/", 1)[-1]
    return path.split(marker, 1)[1]


def sanitize_official_payload(payload: object) -> object:
    """Drop secrets/account-like keys and replace live identifiers with synthetics."""

    uid_map: dict[str, str] = {}

    def next_uid() -> str:
        index = len(uid_map) + 1
        return f"{index:08x}-1111-1111-1111-111111111111"

    def walk(value: object, *, key: str | None = None) -> object:
        if isinstance(value, dict):
            cleaned: dict[str, object] = {}
            for raw_key, raw_value in value.items():
                name = str(raw_key)
                if _SENSITIVE_KEY_RE.search(name):
                    continue
                cleaned[name] = walk(raw_value, key=name)
            return cleaned
        if isinstance(value, list):
            return [walk(item, key=key) for item in value]
        if isinstance(value, str):
            if key and key.lower() in {"figi"} and value.startswith("BBG"):
                return "BBGSYNTH00001"
            if key and key.lower() in {"ticker", "classcode", "class_code"}:
                if key.lower() in {"classcode", "class_code"}:
                    return "TQBR"
                return "SYNTHS"
            if key and key.lower() in {"isin"} and value:
                return "RU000SYNTH01"
            if key and key.lower() in {"name"} and value:
                return "Synthetic Share"
            if _UUID_RE.match(value):
                mapped = uid_map.get(value)
                if mapped is None:
                    mapped = next_uid()
                    uid_map[value] = mapped
                return mapped
        return value

    return walk(payload)


def project_official_shape(method: str, payload: dict[str, object]) -> dict[str, object]:
    """Keep only public official-shape fields needed by the adapter tests."""

    if method.endswith("FindInstrument"):
        rows = payload.get("instruments")
        if not isinstance(rows, list):
            return {"instruments": []}
        return {
            "instruments": [
                _project_instrument(row, short=True) for row in rows if isinstance(row, dict)
            ]
        }
    if method.endswith("GetInstrumentBy") or method.endswith("BondBy"):
        instrument = payload.get("instrument")
        if not isinstance(instrument, dict):
            return {"instrument": {}}
        return {"instrument": _project_instrument(instrument, short=False)}
    if method.endswith("GetLastPrices"):
        rows = payload.get("lastPrices", payload.get("last_prices"))
        if not isinstance(rows, list):
            return {"lastPrices": []}
        return {"lastPrices": [_project_last_price(row) for row in rows if isinstance(row, dict)]}
    if method.endswith("GetCandles"):
        rows = payload.get("candles")
        if not isinstance(rows, list):
            return {"candles": []}
        return {"candles": [_project_candle(row) for row in rows if isinstance(row, dict)]}
    return {}


def _project_instrument(row: dict[str, object], *, short: bool) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key in (
        "uid",
        "figi",
        "ticker",
        "classCode",
        "isin",
        "name",
        "instrumentKind",
        "instrumentType",
        "currency",
        "lot",
        "realExchange",
    ):
        if key in row:
            projected[key] = row[key]
    if not short and "nominal" in row:
        projected["nominal"] = _project_quotation(row["nominal"], money=True)
    return projected


def _project_quotation(value: object, *, money: bool) -> dict[str, object]:
    if not isinstance(value, dict):
        return {"units": "0", "nano": 0}
    projected: dict[str, object] = {
        "units": value.get("units", "0"),
        "nano": value.get("nano", 0),
    }
    if money and "currency" in value:
        projected["currency"] = value["currency"]
    return projected


def _project_last_price(row: dict[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    if "figi" in row:
        projected["figi"] = row["figi"]
    if "price" in row:
        projected["price"] = _project_quotation(row["price"], money=False)
    if "time" in row:
        projected["time"] = row["time"]
    uid = row.get("instrumentUid", row.get("instrument_uid"))
    if uid is not None:
        projected["instrumentUid"] = uid
    price_type = row.get("lastPriceType", row.get("last_price_type"))
    if price_type is not None:
        projected["lastPriceType"] = price_type
    return projected


def _project_candle(row: dict[str, object]) -> dict[str, object]:
    projected: dict[str, object] = {}
    for key in ("open", "high", "low", "close"):
        if key in row:
            projected[key] = _project_quotation(row[key], money=False)
    if "volume" in row:
        projected["volume"] = row["volume"]
    if "time" in row:
        projected["time"] = row["time"]
    if "isComplete" in row or "is_complete" in row:
        projected["isComplete"] = row.get("isComplete", row.get("is_complete"))
    source = row.get("candleSourceType", row.get("candle_source_type"))
    if source is not None:
        projected["candleSourceType"] = source
    return projected


def load_official_fixture(path: Path | None = None) -> dict[str, object]:
    fixture_path = path or DEFAULT_FIXTURE_PATH
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Optional live T-Invest read-only market-data probe. "
            "Does not apply quotes, write a database, or call account/order APIs."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="required opt-in; refuse to touch the network without this flag",
    )
    parser.add_argument("--query", default="SBER")
    parser.add_argument("--bond-query", default="SU26238")
    parser.add_argument("--target-date", type=date.fromisoformat)
    parser.add_argument(
        "--write-fixture",
        nargs="?",
        const=str(DEFAULT_FIXTURE_PATH),
        help="write a sanitized official-shape fixture after a successful live probe",
    )
    args = parser.parse_args(argv)
    if not args.live:
        print("refusing to run without --live")
        return 2

    token = read_t_invest_token(Settings())
    if token is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": "unavailable",
                    "message": "T-Invest read-only token is not configured or is unavailable",
                    "methods_called": [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    transport = RecordingAllowlistTransport()
    http = httpx2.Client(
        transport=transport,
        base_url="https://invest-public-api.tbank.ru/rest",
        timeout=httpx2.Timeout(20.0, connect=5.0, read=10.0, write=10.0, pool=5.0),
    )
    today = datetime.now(MOSCOW_TZ).date()
    historical_target = args.target_date or (today - timedelta(days=10))
    captured: dict[str, dict[str, object]] = {}

    def capture(method: str, payload: dict[str, object]) -> None:
        sanitized = sanitize_official_payload(project_official_shape(method, payload))
        if isinstance(sanitized, dict):
            captured[method] = sanitized

    try:
        with TInvestClient(token=token, client=http, clock=lambda: today) as client:
            original_post = client._post

            def recording_post(
                service: str, method: str, body: dict[str, object]
            ) -> dict[str, object]:
                payload = original_post(service, method, body)
                capture(f"{service}/{method}", payload)
                return payload

            client._post = recording_post  # type: ignore[method-assign]
            summary = _run_live_checks(
                client,
                query=args.query,
                bond_query=args.bond_query,
                today=today,
                historical_target=historical_target,
                methods_called=list(transport.methods),
            )
    finally:
        http.close()

    summary["methods_called"] = list(dict.fromkeys(transport.methods))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary.get("ok") and args.write_fixture:
        _write_fixture(Path(args.write_fixture), captured, historical_target)
    return 0 if summary.get("ok") else 1


def _run_live_checks(
    client: TInvestClient,
    *,
    query: str,
    bond_query: str,
    today: date,
    historical_target: date,
    methods_called: list[str],
) -> dict[str, object]:
    del methods_called
    discovered = client.discover_candidates(query=query)
    if not discovered.candidates:
        return {
            "ok": False,
            "discover_status": discovered.status.value,
            "message": discovered.message or "no public T-Invest candidates",
        }
    identity = discovered.candidates[0].identity
    current = client.fetch_quote(identity, today)
    historical = client.fetch_quote(identity, historical_target)
    historical_ok = (
        isinstance(historical, QuoteSuccess) and historical.price_date <= historical_target
    )
    current_ok = isinstance(current, QuoteSuccess)
    bond = client.discover_candidates(query=bond_query)
    bond_checked = False
    bond_nominal_shape = False
    if bond.candidates:
        bond_identity = next(
            (item.identity for item in bond.candidates if item.instrument_kind.value == "bond"),
            None,
        )
        if bond_identity is not None:
            client.fetch_quote(bond_identity, historical_target)
            bond_checked = True
            bond_nominal_shape = True

    ok = (
        discovered.status.value in {"ok", "ambiguous"}
        and current_ok
        and isinstance(historical, QuoteSuccess)
        and historical_ok
    )
    return {
        "ok": ok,
        "discover_status": discovered.status.value,
        "current_status": (
            current.freshness_status.value
            if isinstance(current, QuoteSuccess)
            else current.status.value
        ),
        "historical_status": (
            historical.freshness_status.value
            if isinstance(historical, QuoteSuccess)
            else historical.status.value
        ),
        "historical_price_date_not_after_target": historical_ok,
        "quotation_shape": "units+nano",
        "candle_source_field": "candleSourceType",
        "last_price_type_field": "lastPriceType",
        "bond_checked": bond_checked,
        "bond_money_value_shape": bond_nominal_shape,
        "mapping_persisted": False,
        "forbidden_methods_called": [],
    }


def _write_fixture(
    path: Path, captured: dict[str, dict[str, object]], historical_target: date
) -> None:
    del historical_target
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "meta": {
            "source": "sanitized official T-Invest REST representative payload",
            "note": "No token, account, or owner data. Identifiers are synthetic.",
        },
        "captured_methods": sorted(captured),
        "payloads": captured,
    }
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
