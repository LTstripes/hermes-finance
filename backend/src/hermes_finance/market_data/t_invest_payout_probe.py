"""Developer-only live T-Invest read-only payout probe. CI must not invoke this.

Usage:
    uv run python -m hermes_finance.market_data.t_invest_payout_probe --live
    uv run python -m hermes_finance.market_data.t_invest_payout_probe --live --write-fixture

Does not implement the payout calendar, persist mappings, or call account/trading APIs.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Final

import httpx2

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.moscow import MOSCOW_TZ, moscow_calendar_date
from hermes_finance.market_data.routing import read_t_invest_token
from hermes_finance.market_data.t_invest import (
    PAYOUT_PROBE_METHODS,
    TOKEN_UNAVAILABLE_MESSAGE,
    TInvestClient,
    _AuthUnavailable,
    _field,
    _Malformed,
    _map_kind,
    _NetworkFailure,
    _NotFound,
    _parse_timestamp,
    _rfc3339,
    _text,
    normalize_t_invest_uid,
)
from hermes_finance.settings import REPOSITORY_ROOT, Settings

ALLOWED_METHODS: Final = frozenset(
    {
        "InstrumentsService/FindInstrument",
        "InstrumentsService/GetInstrumentBy",
        "InstrumentsService/BondBy",
        "InstrumentsService/GetBondCoupons",
        "InstrumentsService/GetBondEvents",
        "InstrumentsService/GetDividends",
    }
)
FORBIDDEN_METHOD_MARKERS: Final = frozenset(
    {
        "Accounts",
        "Operations",
        "GetPortfolio",
        "GetPositions",
        "Orders",
        "Sandbox",
        "Transfer",
        "UsersService",
        "StopOrders",
        "SignalService",
    }
)
DEFAULT_FIXTURE_PATH: Final = (
    REPOSITORY_ROOT / "backend" / "tests" / "fixtures" / "t_invest" / "official_payout_shape.json"
)
STOCK_SYNTH_UID: Final = "11111111-1111-1111-1111-111111111111"
ORDINARY_BOND_SYNTH_UID: Final = "33333333-3333-3333-3333-333333333333"
FLOATING_BOND_SYNTH_UID: Final = "55555555-5555-5555-5555-555555555555"
AMORT_BOND_SYNTH_UID: Final = "77777777-7777-7777-7777-777777777777"
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SENSITIVE_KEY_RE = re.compile(
    r"token|authorization|account|password|secret|refresh|transfer|order|portfolio|position",
    re.IGNORECASE,
)
_EVENT_TYPE_UNSPECIFIED: Final = "EVENT_TYPE_UNSPECIFIED"
_EVENT_TYPE_CPN: Final = "EVENT_TYPE_CPN"
_EVENT_TYPE_MTY: Final = "EVENT_TYPE_MTY"
_HORIZON_DAYS: Final = 400
_LOOKBACK_DAYS: Final = 180


class ForbiddenTInvestMethod(RuntimeError):
    """Raised when a non-allowlisted T-Invest method is requested."""


class RecordingAllowlistTransport(httpx2.HTTPTransport):
    """Permit only R05-01 InstrumentsService methods and record their names."""

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
            lowered = (key or "").lower()
            if lowered == "figi" and value.startswith("BBG"):
                return "BBGSYNTH00001"
            if lowered in {"ticker", "classcode", "class_code"}:
                if lowered in {"classcode", "class_code"}:
                    return "TQBR"
                return "SYNTHS"
            if lowered == "isin" and value:
                return "RU000SYNTH01"
            if lowered == "name" and value:
                return "Synthetic Instrument"
            if _UUID_RE.match(value):
                mapped = uid_map.get(value)
                if mapped is None:
                    mapped = next_uid()
                    uid_map[value] = mapped
                return mapped
        return value

    return walk(payload)


def _project_quotation(value: object, *, money: bool) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        return {"units": "0", "nano": 0}
    projected: dict[str, object] = {
        "units": value.get("units", "0"),
        "nano": value.get("nano", 0),
    }
    if money and "currency" in value:
        projected["currency"] = value["currency"]
    return projected


def _project_named(row: dict[str, object], names: tuple[str, ...]) -> dict[str, object]:
    projected: dict[str, object] = {}
    lookup = {str(key).lower(): key for key in row}
    for name in names:
        actual = row.get(name)
        if actual is None:
            found = lookup.get(name.lower())
            if found is None:
                continue
            actual = row[found]
            name = found
        projected[name] = actual
    return projected


def _project_coupon(row: dict[str, object]) -> dict[str, object]:
    projected = _project_named(
        row,
        (
            "figi",
            "couponDate",
            "coupon_date",
            "couponNumber",
            "coupon_number",
            "fixDate",
            "fix_date",
            "couponType",
            "coupon_type",
            "couponStartDate",
            "coupon_start_date",
            "couponEndDate",
            "coupon_end_date",
            "couponPeriod",
            "coupon_period",
        ),
    )
    money = _field(row, "payOneBond", "pay_one_bond")
    if money is not None:
        projected["payOneBond"] = _project_quotation(money, money=True)
    return projected


def _project_bond_event(row: dict[str, object]) -> dict[str, object]:
    projected = _project_named(
        row,
        (
            "instrumentId",
            "instrument_id",
            "eventNumber",
            "event_number",
            "eventDate",
            "event_date",
            "eventType",
            "event_type",
            "fixDate",
            "fix_date",
            "realPayDate",
            "real_pay_date",
            "payDate",
            "pay_date",
            "execution",
            "operationType",
            "operation_type",
            "note",
            "couponStartDate",
            "coupon_start_date",
            "couponEndDate",
            "coupon_end_date",
            "couponPeriod",
            "coupon_period",
        ),
    )
    money = _field(row, "payOneBond", "pay_one_bond")
    if money is not None:
        projected["payOneBond"] = _project_quotation(money, money=True)
    value = _field(row, "value")
    if value is not None:
        projected["value"] = _project_quotation(value, money=False)
    return projected


def _project_dividend(row: dict[str, object]) -> dict[str, object]:
    projected = _project_named(
        row,
        (
            "paymentDate",
            "payment_date",
            "declaredDate",
            "declared_date",
            "lastBuyDate",
            "last_buy_date",
            "dividendType",
            "dividend_type",
            "recordDate",
            "record_date",
            "regularity",
            "createdAt",
            "created_at",
        ),
    )
    money = _field(row, "dividendNet", "dividend_net")
    if money is not None:
        projected["dividendNet"] = _project_quotation(money, money=True)
    return projected


def _project_instrument(row: dict[str, object], *, bond: bool) -> dict[str, object]:
    projected = _project_named(
        row,
        (
            "uid",
            "figi",
            "ticker",
            "classCode",
            "class_code",
            "isin",
            "name",
            "instrumentKind",
            "instrument_kind",
            "instrumentType",
            "instrument_type",
            "currency",
            "lot",
            "realExchange",
            "real_exchange",
        ),
    )
    if not bond:
        return projected
    for name in (
        "maturityDate",
        "maturity_date",
        "floatingCouponFlag",
        "floating_coupon_flag",
        "perpetualFlag",
        "perpetual_flag",
        "amortizationFlag",
        "amortization_flag",
        "couponQuantityPerYear",
        "coupon_quantity_per_year",
    ):
        if name in row:
            projected[name] = row[name]
    nominal = _field(row, "nominal")
    if nominal is not None:
        projected["nominal"] = _project_quotation(nominal, money=True)
    initial = _field(row, "initialNominal", "initial_nominal")
    if initial is not None:
        projected["initialNominal"] = _project_quotation(initial, money=True)
    return projected


def project_official_shape(method: str, payload: dict[str, object]) -> dict[str, object]:
    """Keep only public payout/reference fields needed for deterministic tests."""

    short = method.rsplit("/", 1)[-1]
    if short == "FindInstrument":
        rows = _field(payload, "instruments")
        if not isinstance(rows, list):
            return {"instruments": []}
        return {
            "instruments": [
                _project_instrument(row, bond=False) for row in rows if isinstance(row, dict)
            ]
        }
    if short in {"GetInstrumentBy", "BondBy"}:
        instrument = _field(payload, "instrument")
        if not isinstance(instrument, dict):
            return {"instrument": {}}
        return {"instrument": _project_instrument(instrument, bond=short == "BondBy")}
    if short == "GetBondCoupons":
        rows = _field(payload, "events")
        if not isinstance(rows, list):
            return {"events": []}
        return {"events": [_project_coupon(row) for row in rows if isinstance(row, dict)]}
    if short == "GetBondEvents":
        rows = _field(payload, "events")
        if not isinstance(rows, list):
            return {"events": []}
        return {"events": [_project_bond_event(row) for row in rows if isinstance(row, dict)]}
    if short == "GetDividends":
        rows = _field(payload, "dividends")
        if not isinstance(rows, list):
            return {"dividends": []}
        return {"dividends": [_project_dividend(row) for row in rows if isinstance(row, dict)]}
    return {}


def _rewrite_identifiers(value: object, *, kind: str) -> object:
    table = {
        "stock": {
            "uid": STOCK_SYNTH_UID,
            "figi": "BBGSYNTH00001",
            "ticker": "SYNTHS",
            "isin": "RU000SYNTH01",
            "name": "Synthetic Share",
            "class_code": "TQBR",
        },
        "ordinary_bond": {
            "uid": ORDINARY_BOND_SYNTH_UID,
            "figi": "BBGSYNTH00003",
            "ticker": "SYNTHB",
            "isin": "RU000SYNTH03",
            "name": "Synthetic Bond",
            "class_code": "TQOB",
        },
        "floating_bond": {
            "uid": FLOATING_BOND_SYNTH_UID,
            "figi": "BBGSYNTH00005",
            "ticker": "SYNTHF",
            "isin": "RU000SYNTH05",
            "name": "Synthetic Floating Bond",
            "class_code": "TQOB",
        },
        "amort_bond": {
            "uid": AMORT_BOND_SYNTH_UID,
            "figi": "BBGSYNTH00007",
            "ticker": "SYNTHA",
            "isin": "RU000SYNTH07",
            "name": "Synthetic Amortizing Bond",
            "class_code": "TQOB",
        },
        "empty": {
            "uid": ORDINARY_BOND_SYNTH_UID,
            "figi": "BBGSYNTH00003",
            "ticker": "SYNTHB",
            "isin": "RU000SYNTH03",
            "name": "Synthetic Bond",
            "class_code": "TQOB",
        },
    }[kind]

    def walk(item: object, *, key: str | None = None) -> object:
        if isinstance(item, dict):
            return {
                str(raw_key): walk(raw_value, key=str(raw_key))
                for raw_key, raw_value in item.items()
            }
        if isinstance(item, list):
            return [walk(entry, key=key) for entry in item]
        if isinstance(item, str):
            lowered = (key or "").lower()
            if _UUID_RE.match(item) or lowered in {"instrumentid", "instrument_id"}:
                return table["uid"]
            if lowered == "figi":
                return table["figi"]
            if lowered == "ticker":
                return table["ticker"]
            if lowered in {"classcode", "class_code"}:
                return table["class_code"]
            if lowered == "isin":
                return table["isin"]
            if lowered == "name":
                return table["name"]
        return item

    return walk(value)


def assemble_canonical_fixture(captured: dict[str, dict[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {
        "meta": {
            "source": "sanitized official T-Invest REST payout representative payload",
            "note": "No token, account, or owner data. Identifiers are synthetic.",
        }
    }
    for section in ("stock", "ordinary_bond", "floating_bond", "amort_bond", "empty"):
        raw = captured.get(section)
        if not raw:
            continue
        rewritten = _rewrite_identifiers(raw, kind=section)
        if not isinstance(rewritten, dict):
            raise TypeError("canonical payout fixture section must be an object")
        document[section] = rewritten
    return document


def write_canonical_fixture(path: Path, captured: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = assemble_canonical_fixture(captured)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_official_fixture(path: Path | None = None) -> dict[str, object]:
    fixture_path = path or DEFAULT_FIXTURE_PATH
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _short_method(method: str) -> str:
    return method.rsplit("/", 1)[-1]


def _truthy_flag(value: object) -> bool:
    return value is True or value == 1 or str(value).lower() == "true"


def _as_list(payload: dict[str, object] | None, *names: str) -> list[object]:
    if payload is None:
        return []
    rows = _field(payload, *names)
    return list(rows) if isinstance(rows, list) else []


def _money_shape(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    keys = sorted(str(key) for key in value)
    units = _field(value, "units")
    nano = _field(value, "nano")
    currency = _text(value, "currency")
    zero = False
    try:
        zero = int(str(units or "0")) == 0 and int(str(nano or "0")) == 0
    except ValueError:
        zero = False
    return {"keys": keys, "has_currency": currency is not None, "zero": zero}


def _timestamp_observation(value: object) -> dict[str, object]:
    if value is None:
        return {"present": False}
    if not isinstance(value, str) or not value.strip():
        return {"present": True, "parseable": False, "python_type": type(value).__name__}
    try:
        parsed = _parse_timestamp(value, name="timestamp")
    except _Malformed:
        return {"present": True, "parseable": False, "raw_sample": value[:40]}
    utc_date = parsed.astimezone(timezone.utc).date()
    moscow = moscow_calendar_date(parsed)
    return {
        "present": True,
        "parseable": True,
        "raw_sample": value,
        "utc_date": utc_date.isoformat(),
        "moscow_date": moscow.isoformat(),
        "moscow_differs_from_utc_date": utc_date != moscow,
    }


def _window(start: date, end: date) -> dict[str, object]:
    return {
        "from": _rfc3339(datetime.combine(start, time.min, tzinfo=MOSCOW_TZ)),
        "to": _rfc3339(datetime.combine(end, time.min, tzinfo=MOSCOW_TZ)),
    }


def _safe_payout(client: TInvestClient, method: str, body: dict[str, object]) -> dict[str, object]:
    try:
        payload = client.request_payout_method(method, body)
    except _AuthUnavailable:
        return {"ok": False, "error_kind": "auth", "payload": None}
    except _NetworkFailure:
        return {"ok": False, "error_kind": "network", "payload": None}
    except _NotFound:
        return {"ok": False, "error_kind": "not_found", "payload": None}
    except _Malformed:
        return {"ok": False, "error_kind": "malformed", "payload": None}
    except ValueError:
        return {"ok": False, "error_kind": "rejected_method", "payload": None}
    if not isinstance(payload, dict):
        return {"ok": False, "error_kind": "malformed", "payload": None}
    return {"ok": True, "error_kind": None, "payload": payload}


def _item_field_names(rows: list[object]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        if isinstance(row, dict):
            names.update(str(key) for key in row)
    return sorted(names)


def _coupon_identity_tuple(row: object) -> tuple[object, ...]:
    if not isinstance(row, dict):
        return ()
    return (
        _field(row, "couponNumber", "coupon_number"),
        _text(row, "couponDate", "coupon_date"),
        _text(row, "couponStartDate", "coupon_start_date"),
        _text(row, "couponEndDate", "coupon_end_date"),
    )


def _row_kind(row: dict[str, object]) -> InstrumentType | None:
    return _map_kind(
        _text(row, "instrumentKind", "instrument_kind"),
        _text(row, "instrumentType", "instrument_type"),
    )


def _resolve_public_instrument(
    client: TInvestClient,
    query: str,
    *,
    wanted: InstrumentType,
) -> dict[str, object] | None:
    try:
        rows = client._find_instruments(query)
    except (_AuthUnavailable, _NetworkFailure, _Malformed):
        return None
    inspected: list[dict[str, object]] = []
    selected: dict[str, object] | None = None
    for row in rows[:10]:
        short_kind = _row_kind(row)
        uid_text = _text(row, "uid", "instrumentUid", "instrument_uid")
        inspected.append(
            {
                "ticker": _text(row, "ticker"),
                "short_kind": _text(
                    row,
                    "instrumentKind",
                    "instrument_kind",
                    "instrumentType",
                    "instrument_type",
                ),
                "mapped_kind": short_kind.value if short_kind else None,
            }
        )
        detail = row
        mapped = short_kind
        if mapped is not wanted and uid_text:
            try:
                detail = client._instrument_by_uid(uid_text)
                mapped = _row_kind(detail)
            except (_NotFound, _Malformed, _NetworkFailure, _AuthUnavailable, ValueError):
                continue
            inspected[-1]["mapped_kind"] = mapped.value if mapped else None
        if mapped is not wanted:
            continue
        ticker = _text(detail, "ticker") or _text(row, "ticker")
        selected = detail if isinstance(detail, dict) else row
        if ticker and (
            ticker.casefold() == query.casefold() or ticker.upper().startswith(query.upper())
        ):
            break
        if selected is not None and ticker and ticker.casefold() == query.casefold():
            break
    if selected is None:
        return {"query": query, "uid": None, "kind": None, "inspected": inspected}
    uid_text = _text(selected, "uid", "instrumentUid", "instrument_uid")
    if uid_text is None:
        return {"query": query, "uid": None, "kind": None, "inspected": inspected}
    try:
        uid = normalize_t_invest_uid(uid_text)
    except ValueError:
        return {"query": query, "uid": None, "kind": None, "inspected": inspected}
    bond: dict[str, object] | None = None
    if wanted is InstrumentType.BOND:
        try:
            bond = client._bond_by_uid(uid)
        except (_NotFound, _Malformed, _NetworkFailure, _AuthUnavailable):
            bond = None
    return {
        "query": query,
        "uid": uid,
        "kind": wanted.value,
        "ticker": _text(selected, "ticker") or query,
        "isin": _text(selected, "isin"),
        "bond": bond,
        "inspected": inspected,
    }


def _bond_flags(bond: dict[str, object] | None) -> dict[str, object]:
    if bond is None:
        return {}
    return {
        "floating_coupon_flag": _truthy_flag(
            _field(bond, "floatingCouponFlag", "floating_coupon_flag")
        ),
        "amortization_flag": _truthy_flag(_field(bond, "amortizationFlag", "amortization_flag")),
        "perpetual_flag": _truthy_flag(_field(bond, "perpetualFlag", "perpetual_flag")),
        "maturity_date": _timestamp_observation(_field(bond, "maturityDate", "maturity_date")),
        "nominal": _money_shape(_field(bond, "nominal")),
        "initial_nominal": _money_shape(_field(bond, "initialNominal", "initial_nominal")),
        "currency": _text(bond, "currency"),
        "bond_field_names": sorted(str(key) for key in bond),
    }


def _analyze_coupons(rows: list[object], *, today: date) -> dict[str, object]:
    numbers: list[object] = []
    missing_number = 0
    zero_number = 0
    future_amounts: list[str] = []
    date_obs: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = _field(row, "couponNumber", "coupon_number")
        numbers.append(number)
        if number is None:
            missing_number += 1
        elif str(number) in {"0", "0.0"}:
            zero_number += 1
        coupon_date = _timestamp_observation(_field(row, "couponDate", "coupon_date"))
        date_obs.append(coupon_date)
        moscow = coupon_date.get("moscow_date")
        money = _money_shape(_field(row, "payOneBond", "pay_one_bond"))
        if isinstance(moscow, str) and date.fromisoformat(moscow) > today:
            if money is None:
                future_amounts.append("missing")
            elif money["zero"]:
                future_amounts.append("zero")
            else:
                future_amounts.append("positive")
    return {
        "count": len(rows),
        "field_names": _item_field_names(rows),
        "coupon_number_present_count": len(numbers) - missing_number,
        "coupon_number_missing_count": missing_number,
        "coupon_number_zero_count": zero_number,
        "coupon_date_observations": {
            "samples": date_obs[:3],
            "moscow_differs_from_utc_date_count": sum(
                1 for item in date_obs if item.get("moscow_differs_from_utc_date")
            ),
            "missing_count": sum(1 for item in date_obs if not item.get("present")),
        },
        "future_pay_one_bond": {
            "missing": future_amounts.count("missing"),
            "zero": future_amounts.count("zero"),
            "positive": future_amounts.count("positive"),
        },
        "identity_tuples": [_coupon_identity_tuple(row) for row in rows],
    }


def _analyze_bond_events(rows: list[object]) -> dict[str, object]:
    types: list[str] = []
    executions: list[str] = []
    operation_types: list[str] = []
    mty: list[dict[str, object]] = []
    cpn_keys: list[tuple[object, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_type = str(_field(row, "eventType", "event_type") or "")
        types.append(event_type)
        execution = _text(row, "execution")
        if execution:
            executions.append(execution)
        operation = _text(row, "operationType", "operation_type")
        if operation:
            operation_types.append(operation)
        if "MTY" in event_type.upper() or event_type.endswith("MTY"):
            mty.append(
                {
                    "event_number": _field(row, "eventNumber", "event_number"),
                    "event_date": _timestamp_observation(_field(row, "eventDate", "event_date")),
                    "pay_date": _timestamp_observation(_field(row, "payDate", "pay_date")),
                    "real_pay_date": _timestamp_observation(
                        _field(row, "realPayDate", "real_pay_date")
                    ),
                    "pay_one_bond": _money_shape(_field(row, "payOneBond", "pay_one_bond")),
                    "operation_type": operation,
                    "execution": execution,
                    "value": _money_shape(_field(row, "value")),
                }
            )
        if "CPN" in event_type.upper():
            cpn_keys.append(
                (
                    _field(row, "eventNumber", "event_number"),
                    _text(row, "payDate", "pay_date", "eventDate", "event_date"),
                )
            )
    return {
        "count": len(rows),
        "field_names": _item_field_names(rows),
        "event_types": sorted(set(types)),
        "execution_values": sorted(set(executions)),
        "operation_types": sorted(set(operation_types)),
        "mty_events": mty,
        "cpn_keys": cpn_keys,
    }


def _analyze_dividends(rows: list[object], *, today: date) -> dict[str, object]:
    types: list[str] = []
    record_dates: list[str] = []
    future_payment_present = 0
    future_payment_missing = 0
    record_without_payment = 0
    payment_before_record = 0
    payment_after_record_days: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dtype = _text(row, "dividendType", "dividend_type") or ""
        types.append(dtype)
        record = _timestamp_observation(_field(row, "recordDate", "record_date"))
        payment = _timestamp_observation(_field(row, "paymentDate", "payment_date"))
        if record.get("moscow_date"):
            record_dates.append(str(record["moscow_date"]))
        if payment.get("moscow_date") and record.get("moscow_date"):
            pay_day = date.fromisoformat(str(payment["moscow_date"]))
            rec_day = date.fromisoformat(str(record["moscow_date"]))
            delta = (pay_day - rec_day).days
            if delta < 0:
                payment_before_record += 1
            else:
                payment_after_record_days.append(delta)
        if record.get("present") and not payment.get("present"):
            record_without_payment += 1
        future = False
        if payment.get("moscow_date"):
            future = date.fromisoformat(str(payment["moscow_date"])) >= today
        elif record.get("moscow_date"):
            future = date.fromisoformat(str(record["moscow_date"])) >= today
        if future:
            if payment.get("present"):
                future_payment_present += 1
            else:
                future_payment_missing += 1
    shared_record = sorted({item for item in record_dates if record_dates.count(item) > 1})
    return {
        "count": len(rows),
        "field_names": _item_field_names(rows),
        "dividend_types": sorted(set(types)),
        "cancelled_type_present": any(item.lower() == "cancelled" for item in types),
        "shared_record_dates": shared_record,
        "future_rows_with_payment_date": future_payment_present,
        "future_rows_missing_payment_date": future_payment_missing,
        "record_without_payment_date": record_without_payment,
        "payment_before_record_count": payment_before_record,
        "payment_minus_record_days": {
            "observed_count": len(payment_after_record_days),
            "min": min(payment_after_record_days) if payment_after_record_days else None,
            "max": max(payment_after_record_days) if payment_after_record_days else None,
        },
        "date_samples": [
            {
                "record_date": _timestamp_observation(_field(row, "recordDate", "record_date")),
                "payment_date": _timestamp_observation(_field(row, "paymentDate", "payment_date")),
                "declared_date": _timestamp_observation(
                    _field(row, "declaredDate", "declared_date")
                ),
                "last_buy_date": _timestamp_observation(
                    _field(row, "lastBuyDate", "last_buy_date")
                ),
                "dividend_net": _money_shape(_field(row, "dividendNet", "dividend_net")),
                "dividend_type": _text(row, "dividendType", "dividend_type"),
            }
            for row in rows[:3]
            if isinstance(row, dict)
        ],
    }


def _public_instrument_view(resolved: dict[str, object]) -> dict[str, object]:
    return {
        "query": resolved["query"],
        "kind": resolved["kind"],
        "ticker_query": resolved.get("ticker"),
        "has_instrument_uid": bool(resolved.get("uid")),
        "has_isin": bool(resolved.get("isin")),
        "flags": _bond_flags(
            resolved.get("bond") if isinstance(resolved.get("bond"), dict) else None
        ),
        "inspected": resolved.get("inspected"),
    }


def _capture(
    captured: dict[str, dict[str, object]],
    section: str,
    method: str,
    payload: dict[str, object] | None,
) -> None:
    if payload is None:
        return
    cleaned = sanitize_official_payload(project_official_shape(method, payload))
    if not isinstance(cleaned, dict):
        return
    captured.setdefault(section, {})[_short_method(method)] = cleaned


def _run_live_checks(
    client: TInvestClient,
    *,
    stock_query: str,
    bond_query: str,
    extra_bond_queries: tuple[str, ...],
    today: date,
    captured: dict[str, dict[str, object]],
) -> dict[str, object]:
    near_start = today - timedelta(days=30)
    near_end = today + timedelta(days=_HORIZON_DAYS)
    wide_start = today - timedelta(days=_LOOKBACK_DAYS)
    empty_start = today + timedelta(days=365 * 5)
    empty_end = empty_start + timedelta(days=60)
    near = _window(near_start, near_end)
    wide = _window(wide_start, near_end)
    empty_window = _window(empty_start, empty_end)
    history_start = today - timedelta(days=800)
    history_window = _window(history_start, today)

    def _maturity_window(resolved: dict[str, object] | None) -> dict[str, object]:
        if resolved is None or not isinstance(resolved.get("bond"), dict):
            return wide
        maturity_obs = _timestamp_observation(
            _field(resolved["bond"], "maturityDate", "maturity_date")
        )
        moscow = maturity_obs.get("moscow_date")
        if not isinstance(moscow, str):
            return wide
        maturity_day = date.fromisoformat(moscow)
        start = min(today - timedelta(days=30), maturity_day - timedelta(days=30))
        end = maturity_day + timedelta(days=30)
        if end > today + timedelta(days=365 * 20):
            end = today + timedelta(days=365 * 20)
        return _window(start, end)

    first_stock_attempt = _resolve_public_instrument(
        client, stock_query, wanted=InstrumentType.STOCK
    )
    stock = first_stock_attempt
    if stock is None or not stock.get("uid"):
        for fallback in ("GAZP", "LKOH", "ROSN"):
            if fallback.casefold() == stock_query.casefold():
                continue
            stock = _resolve_public_instrument(client, fallback, wanted=InstrumentType.STOCK)
            if stock and stock.get("uid"):
                break
    ordinary = _resolve_public_instrument(client, bond_query, wanted=InstrumentType.BOND)
    extras: list[dict[str, object]] = []
    for query in extra_bond_queries:
        if query in {stock_query, bond_query}:
            continue
        resolved = _resolve_public_instrument(client, query, wanted=InstrumentType.BOND)
        if resolved is not None and resolved.get("uid"):
            extras.append(resolved)

    def _is_future_bond(item: dict[str, object]) -> bool:
        flags = _bond_flags(item.get("bond") if isinstance(item.get("bond"), dict) else None)
        maturity = flags.get("maturity_date")
        moscow = maturity.get("moscow_date") if isinstance(maturity, dict) else None
        return isinstance(moscow, str) and date.fromisoformat(moscow) >= today

    floating = next(
        (
            item
            for item in extras
            if _bond_flags(item.get("bond") if isinstance(item.get("bond"), dict) else None).get(
                "floating_coupon_flag"
            )
            and _is_future_bond(item)
        ),
        None,
    )
    amort = next(
        (
            item
            for item in extras
            if _bond_flags(item.get("bond") if isinstance(item.get("bond"), dict) else None).get(
                "amortization_flag"
            )
            and _is_future_bond(item)
        ),
        None,
    )
    if ordinary is not None and ordinary.get("uid"):
        flags = _bond_flags(
            ordinary.get("bond") if isinstance(ordinary.get("bond"), dict) else None
        )
        if floating is None and flags.get("floating_coupon_flag") and _is_future_bond(ordinary):
            floating = ordinary
        if amort is None and flags.get("amortization_flag") and _is_future_bond(ordinary):
            amort = ordinary

    observations: dict[str, object] = {
        "ok": False,
        "today_moscow": today.isoformat(),
        "windows": {
            "near": {"from": near_start.isoformat(), "to": near_end.isoformat()},
            "wide": {"from": wide_start.isoformat(), "to": near_end.isoformat()},
            "empty": {"from": empty_start.isoformat(), "to": empty_end.isoformat()},
            "history": {"from": history_start.isoformat(), "to": today.isoformat()},
        },
        "public_instruments": {
            "stock": _public_instrument_view(stock) if stock and stock.get("uid") else stock,
            "ordinary_bond": (
                _public_instrument_view(ordinary) if ordinary and ordinary.get("uid") else ordinary
            ),
            "floating_bond": _public_instrument_view(floating) if floating else None,
            "amort_bond": _public_instrument_view(amort) if amort else None,
            "first_stock_query": first_stock_attempt.get("query")
            if first_stock_attempt
            else stock_query,
            "first_stock_resolved": bool(first_stock_attempt and first_stock_attempt.get("uid")),
            "first_stock_inspected": (
                first_stock_attempt.get("inspected") if first_stock_attempt else None
            ),
            "extra_resolved_queries": [item["query"] for item in extras],
            "matured_flagged_extras": [
                {
                    "query": item["query"],
                    "ticker": item.get("ticker"),
                    "flags": _bond_flags(
                        item.get("bond") if isinstance(item.get("bond"), dict) else None
                    ),
                }
                for item in extras
                if not _is_future_bond(item)
            ],
        },
        "forbidden_methods_called": [],
        "uid_request_results": {},
        "empty_schedule": {},
        "coupon": {},
        "bond_events": {},
        "dividends": {},
        "synthetic_maturity_evidence": {},
    }

    if ordinary is None or not ordinary.get("uid"):
        observations["message"] = "public ordinary bond was not resolved"
        return observations

    stock_uid = str(stock["uid"]) if stock and stock.get("uid") else None
    ordinary_uid = str(ordinary["uid"])
    if stock_uid:
        _capture(
            captured,
            "stock",
            "InstrumentsService/FindInstrument",
            {"instruments": [{"uid": stock_uid, "ticker": stock_query}]},
        )
    ordinary_bond = ordinary.get("bond")
    if isinstance(ordinary_bond, dict):
        _capture(
            captured, "ordinary_bond", "InstrumentsService/BondBy", {"instrument": ordinary_bond}
        )

    coupon_body = {"instrumentId": ordinary_uid, **near}
    first = _safe_payout(client, "GetBondCoupons", coupon_body)
    second = _safe_payout(client, "GetBondCoupons", coupon_body)
    first_rows = _as_list(first.get("payload") if first["ok"] else None, "events")
    second_rows = _as_list(second.get("payload") if second["ok"] else None, "events")
    first_keys = [_coupon_identity_tuple(row) for row in first_rows]
    second_keys = [_coupon_identity_tuple(row) for row in second_rows]
    if first["ok"] and isinstance(first.get("payload"), dict):
        _capture(captured, "ordinary_bond", "InstrumentsService/GetBondCoupons", first["payload"])

    unspecified = _safe_payout(
        client,
        "GetBondEvents",
        {"instrumentId": ordinary_uid, "type": _EVENT_TYPE_UNSPECIFIED, **near},
    )
    if not unspecified["ok"]:
        unspecified = _safe_payout(client, "GetBondEvents", {"instrumentId": ordinary_uid, **near})
    cpn = _safe_payout(
        client,
        "GetBondEvents",
        {"instrumentId": ordinary_uid, "type": _EVENT_TYPE_CPN, **near},
    )
    mty = _safe_payout(
        client,
        "GetBondEvents",
        {"instrumentId": ordinary_uid, "type": _EVENT_TYPE_MTY, **_maturity_window(ordinary)},
    )
    unspecified_rows = _as_list(unspecified.get("payload") if unspecified["ok"] else None, "events")
    cpn_rows = _as_list(cpn.get("payload") if cpn["ok"] else None, "events")
    mty_rows = _as_list(mty.get("payload") if mty["ok"] else None, "events")
    if unspecified["ok"] and isinstance(unspecified.get("payload"), dict):
        _capture(
            captured, "ordinary_bond", "InstrumentsService/GetBondEvents", unspecified["payload"]
        )
    if mty["ok"] and isinstance(mty.get("payload"), dict):
        captured.setdefault("ordinary_bond", {})["GetBondEventsMty"] = sanitize_official_payload(
            project_official_shape("InstrumentsService/GetBondEvents", mty["payload"])
        )

    coupon_analysis = _analyze_coupons(first_rows, today=today)
    cpn_analysis = _analyze_bond_events(cpn_rows)
    coupon_dates = {
        item[1] for item in coupon_analysis["identity_tuples"] if isinstance(item, tuple) and item
    }
    cpn_dates = {item[1] for item in cpn_analysis["cpn_keys"] if item}
    observations["coupon"] = {
        "get_bond_coupons_first": {
            "ok": first["ok"],
            "error_kind": first["error_kind"],
            **{key: value for key, value in coupon_analysis.items() if key != "identity_tuples"},
        },
        "get_bond_coupons_second": {
            "ok": second["ok"],
            "error_kind": second["error_kind"],
            "count": len(second_rows),
        },
        "coupon_number_stable_across_repeated_calls": first["ok"]
        and second["ok"]
        and first_keys == second_keys,
        "repeated_call_tuple_counts": {
            "first": len(first_keys),
            "second": len(second_keys),
        },
    }
    observations["bond_events"] = {
        "unspecified_or_untyped": {
            "ok": unspecified["ok"],
            "error_kind": unspecified["error_kind"],
            **_analyze_bond_events(unspecified_rows),
        },
        "cpn": {
            "ok": cpn["ok"],
            "error_kind": cpn["error_kind"],
            **cpn_analysis,
        },
        "mty": {
            "ok": mty["ok"],
            "error_kind": mty["error_kind"],
            **_analyze_bond_events(mty_rows),
        },
        "cpn_vs_get_bond_coupons": {
            "coupon_row_count": len(first_rows),
            "cpn_row_count": len(cpn_rows),
            "shared_date_count": len(coupon_dates & cpn_dates),
            "coupon_only_date_count": len(coupon_dates - cpn_dates),
            "cpn_only_date_count": len(cpn_dates - coupon_dates),
        },
    }

    def _dividends(uid: str, window: dict[str, object] | None) -> dict[str, object]:
        bodies: list[dict[str, object]] = [{"instrumentId": uid, **(window or {})}]
        if window:
            bodies.append({"instrumentId": uid})
        last: dict[str, object] | None = None
        for body in bodies:
            last = _safe_payout(client, "GetDividends", body)
            last["request_keys"] = sorted(body)
            if last["ok"]:
                return last
        return last or {"ok": False, "error_kind": "unavailable", "payload": None}

    if stock_uid:
        stock_div_near = _dividends(stock_uid, near)
        stock_div_wide = _dividends(stock_uid, wide)
        stock_div_empty = _dividends(stock_uid, empty_window)
        stock_div_history = _dividends(stock_uid, history_window)
        stock_coupons = _safe_payout(client, "GetBondCoupons", {"instrumentId": stock_uid, **near})
    else:
        skipped = {"ok": False, "error_kind": "unresolved_stock", "payload": None}
        stock_div_near = skipped
        stock_div_wide = skipped
        stock_div_empty = skipped
        stock_div_history = skipped
        stock_coupons = skipped
    bond_div = _dividends(ordinary_uid, wide)
    near_rows = _as_list(
        stock_div_near.get("payload") if stock_div_near["ok"] else None, "dividends"
    )
    wide_rows = _as_list(
        stock_div_wide.get("payload") if stock_div_wide["ok"] else None, "dividends"
    )
    empty_rows = _as_list(
        stock_div_empty.get("payload") if stock_div_empty["ok"] else None, "dividends"
    )
    history_rows = _as_list(
        stock_div_history.get("payload") if stock_div_history["ok"] else None, "dividends"
    )
    extra_dividend_queries: list[str] = []
    if not history_rows:
        for extra_query in ("LKOH", "ROSN", "SBER"):
            if stock and extra_query.casefold() == str(stock.get("query") or "").casefold():
                continue
            extra_stock = _resolve_public_instrument(
                client, extra_query, wanted=InstrumentType.STOCK
            )
            if extra_stock is None or not extra_stock.get("uid"):
                extra_dividend_queries.append(extra_query + ":unresolved")
                continue
            extra_div = _dividends(str(extra_stock["uid"]), history_window)
            extra_rows = _as_list(
                extra_div.get("payload") if extra_div["ok"] else None, "dividends"
            )
            extra_dividend_queries.append(
                f"{extra_query}:ok={extra_div['ok']}:count={len(extra_rows)}"
            )
            if extra_rows:
                stock = extra_stock
                stock_uid = str(extra_stock["uid"])
                stock_div_history = extra_div
                history_rows = extra_rows
                observations["public_instruments"]["stock"] = _public_instrument_view(stock)
                break
    bond_div_rows = _as_list(bond_div.get("payload") if bond_div["ok"] else None, "dividends")
    stock_coupon_rows = _as_list(
        stock_coupons.get("payload") if stock_coupons["ok"] else None, "events"
    )
    if (
        history_rows
        and stock_div_history["ok"]
        and isinstance(stock_div_history.get("payload"), dict)
    ):
        _capture(captured, "stock", "InstrumentsService/GetDividends", stock_div_history["payload"])
    elif stock_div_wide["ok"] and isinstance(stock_div_wide.get("payload"), dict):
        _capture(captured, "stock", "InstrumentsService/GetDividends", stock_div_wide["payload"])
    if stock_div_empty["ok"] and isinstance(stock_div_empty.get("payload"), dict):
        _capture(captured, "empty", "InstrumentsService/GetDividends", stock_div_empty["payload"])
    elif bond_div["ok"] and isinstance(bond_div.get("payload"), dict):
        _capture(captured, "empty", "InstrumentsService/GetDividends", bond_div["payload"])
    if stock_coupons["ok"] and isinstance(stock_coupons.get("payload"), dict):
        _capture(captured, "empty", "InstrumentsService/GetBondCoupons", stock_coupons["payload"])

    observations["dividends"] = {
        "stock_near": {
            "ok": stock_div_near["ok"],
            "error_kind": stock_div_near["error_kind"],
            "request_keys": stock_div_near.get("request_keys"),
            **_analyze_dividends(near_rows, today=today),
        },
        "stock_wide": {
            "ok": stock_div_wide["ok"],
            "error_kind": stock_div_wide["error_kind"],
            "request_keys": stock_div_wide.get("request_keys"),
            **_analyze_dividends(wide_rows, today=today),
        },
        "stock_far_future": {
            "ok": stock_div_empty["ok"],
            "error_kind": stock_div_empty["error_kind"],
            "request_keys": stock_div_empty.get("request_keys"),
            "count": len(empty_rows),
        },
        "stock_history": {
            "ok": stock_div_history["ok"],
            "error_kind": stock_div_history["error_kind"],
            "request_keys": stock_div_history.get("request_keys"),
            **_analyze_dividends(history_rows, today=today),
        },
        "ordinary_bond": {
            "ok": bond_div["ok"],
            "error_kind": bond_div["error_kind"],
            "request_keys": bond_div.get("request_keys"),
            "count": len(bond_div_rows),
        },
        "extra_dividend_queries": extra_dividend_queries,
        "dividend_net_shape": next(
            (
                _money_shape(_field(row, "dividendNet", "dividend_net"))
                for row in [*history_rows, *wide_rows, *near_rows]
                if isinstance(row, dict)
            ),
            None,
        ),
    }
    observations["empty_schedule"] = {
        "stock_get_dividends_far_future": {
            "ok": stock_div_empty["ok"],
            "error_kind": stock_div_empty["error_kind"],
            "row_count": len(empty_rows),
            "appears_as_empty_list": stock_div_empty["ok"] and empty_rows == [],
        },
        "bond_get_dividends": {
            "ok": bond_div["ok"],
            "error_kind": bond_div["error_kind"],
            "row_count": len(bond_div_rows),
            "appears_as_empty_list": bond_div["ok"] and bond_div_rows == [],
        },
        "stock_get_bond_coupons": {
            "ok": stock_coupons["ok"],
            "error_kind": stock_coupons["error_kind"],
            "row_count": len(stock_coupon_rows),
            "appears_as_empty_list": stock_coupons["ok"] and stock_coupon_rows == [],
        },
    }
    observations["uid_request_results"] = {
        "request_field": "instrumentId",
        "get_bond_coupons": first["ok"],
        "get_bond_events": unspecified["ok"] or cpn["ok"] or mty["ok"],
        "get_dividends": stock_div_wide["ok"] or stock_div_near["ok"],
        "all_three_accepted_with_instrument_uid": bool(
            first["ok"]
            and (unspecified["ok"] or cpn["ok"] or mty["ok"])
            and (stock_div_wide["ok"] or stock_div_near["ok"])
        ),
    }

    if floating is not None and floating is not ordinary:
        floater_uid = str(floating["uid"])
        floater_bond = floating.get("bond")
        if isinstance(floater_bond, dict):
            _capture(
                captured, "floating_bond", "InstrumentsService/BondBy", {"instrument": floater_bond}
            )
        floater_coupons = _safe_payout(
            client, "GetBondCoupons", {"instrumentId": floater_uid, **near}
        )
        floater_rows = _as_list(
            floater_coupons.get("payload") if floater_coupons["ok"] else None, "events"
        )
        if floater_coupons["ok"] and isinstance(floater_coupons.get("payload"), dict):
            _capture(
                captured,
                "floating_bond",
                "InstrumentsService/GetBondCoupons",
                floater_coupons["payload"],
            )
        observations["coupon"]["floating_bond"] = {
            "ok": floater_coupons["ok"],
            "error_kind": floater_coupons["error_kind"],
            **{
                key: value
                for key, value in _analyze_coupons(floater_rows, today=today).items()
                if key != "identity_tuples"
            },
        }
    elif floating is ordinary:
        observations["coupon"]["floating_bond"] = {
            "same_as_ordinary_bond": True,
            **{key: value for key, value in coupon_analysis.items() if key != "identity_tuples"},
        }

    if amort is not None:
        amort_uid = str(amort["uid"])
        amort_bond = amort.get("bond")
        if isinstance(amort_bond, dict) and amort is not ordinary:
            _capture(
                captured, "amort_bond", "InstrumentsService/BondBy", {"instrument": amort_bond}
            )
        amort_mty = _safe_payout(
            client,
            "GetBondEvents",
            {
                "instrumentId": amort_uid,
                "type": _EVENT_TYPE_MTY,
                **_maturity_window(amort),
            },
        )
        amort_rows = _as_list(amort_mty.get("payload") if amort_mty["ok"] else None, "events")
        if amort_mty["ok"] and isinstance(amort_mty.get("payload"), dict) and amort is not ordinary:
            captured.setdefault("amort_bond", {})["GetBondEventsMty"] = sanitize_official_payload(
                project_official_shape("InstrumentsService/GetBondEvents", amort_mty["payload"])
            )
        observations["bond_events"]["amort_mty"] = {
            "ok": amort_mty["ok"],
            "error_kind": amort_mty["error_kind"],
            "same_as_ordinary_bond": amort is ordinary,
            **_analyze_bond_events(amort_rows),
        }

    ordinary_flags = _bond_flags(
        ordinary.get("bond") if isinstance(ordinary.get("bond"), dict) else None
    )
    mty_pay = None
    if mty_rows and isinstance(mty_rows[0], dict):
        mty_pay = _field(mty_rows[0], "payOneBond", "pay_one_bond")
    bond_nominal = None
    if isinstance(ordinary.get("bond"), dict):
        bond_nominal = _field(ordinary["bond"], "nominal")
    observations["synthetic_maturity_evidence"] = {
        "ordinary_has_maturity_date": bool(
            ordinary_flags.get("maturity_date", {}).get("present")
            if isinstance(ordinary_flags.get("maturity_date"), dict)
            else False
        ),
        "ordinary_perpetual_flag": ordinary_flags.get("perpetual_flag"),
        "ordinary_amortization_flag": ordinary_flags.get("amortization_flag"),
        "ordinary_mty_count": len(mty_rows),
        "ordinary_nominal_present": ordinary_flags.get("nominal") is not None,
        "mty_pay_one_bond": _money_shape(mty_pay),
        "bond_nominal": _money_shape(bond_nominal),
        "mty_pay_matches_nominal_units_nano": (
            isinstance(mty_pay, dict)
            and isinstance(bond_nominal, dict)
            and str(_field(mty_pay, "units")) == str(_field(bond_nominal, "units"))
            and str(_field(mty_pay, "nano")) == str(_field(bond_nominal, "nano"))
            and str(_field(mty_pay, "currency") or "").lower()
            == str(_field(bond_nominal, "currency") or "").lower()
        ),
        "synthetic_fallback_enabled": False,
    }
    observations["ok"] = bool(
        first["ok"]
        or unspecified["ok"]
        or cpn["ok"]
        or mty["ok"]
        or stock_div_near["ok"]
        or stock_div_wide["ok"]
        or stock_div_history["ok"]
    )
    return observations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Optional live T-Invest read-only payout probe. "
            "Does not apply calendar rows, write a database, or call account/order APIs."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="required opt-in; refuse to touch the network without this flag",
    )
    parser.add_argument("--stock-query", default="SBER")
    parser.add_argument("--bond-query", default="SU26238")
    parser.add_argument(
        "--extra-bond-query",
        action="append",
        default=None,
        help="additional public bond ticker/query used only to inspect flags",
    )
    parser.add_argument(
        "--write-fixture",
        nargs="?",
        const=str(DEFAULT_FIXTURE_PATH),
        help="write a sanitized official-shape payout fixture after a successful live probe",
    )
    parser.add_argument(
        "--write-summary",
        help="write the sanitized live summary JSON to this path (UTF-8)",
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
                    "message": TOKEN_UNAVAILABLE_MESSAGE,
                    "methods_called": [],
                    "forbidden_methods_called": [],
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
    captured: dict[str, dict[str, object]] = {}
    try:
        with TInvestClient(token=token, client=http, clock=lambda: today) as client:
            summary = _run_live_checks(
                client,
                stock_query=args.stock_query,
                bond_query=args.bond_query,
                extra_bond_queries=tuple(args.extra_bond_query or ("SU29006", "SU29014")),
                today=today,
                captured=captured,
            )
    finally:
        http.close()

    methods_called = list(dict.fromkeys(transport.methods))
    summary["methods_called"] = methods_called
    summary["request_count"] = len(transport.methods)
    summary["allowed_methods"] = sorted(ALLOWED_METHODS)
    summary["payout_probe_methods"] = sorted(PAYOUT_PROBE_METHODS)
    summary["forbidden_methods_called"] = [
        method
        for method in methods_called
        if any(marker in method for marker in FORBIDDEN_METHOD_MARKERS)
    ]
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.write_summary:
        Path(args.write_summary).write_text(rendered + "\n", encoding="utf-8")
    if summary.get("ok") and args.write_fixture:
        write_canonical_fixture(Path(args.write_fixture), captured)
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
