"""Bounded, read-only MOEX ISS adapter with deterministic normalization."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from threading import BoundedSemaphore
from time import monotonic
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from hermes_finance.market_data.models import (
    CandidateDiscoveryResult,
    InstrumentKind,
    MarketDataBatchResult,
    MarketDataStatus,
    MarketIdentity,
    MoexQuoteKind,
    NormalizedQuote,
    RawPriceBasis,
)

DEFAULT_BASE_URL = "https://iss.moex.com"
# Moscow has used a fixed UTC+03:00 offset since the current project period;
# keeping the named timezone avoids making the local adapter depend on tzdata.
MOSCOW_TZ = timezone(timedelta(hours=3), name="Europe/Moscow")
MAX_HISTORY_DAYS = 30
_KOPECK = Decimal("0.01")
_HUNDRED = Decimal("100")

Payload = Mapping[str, Any]
Transport = Callable[[str, float], Payload | str | bytes]


class MarketDataError(Exception):
    """Base class for deterministic provider-boundary errors."""


class MalformedResponseError(MarketDataError):
    pass


class IsinMismatchError(MarketDataError):
    pass


class _NetworkError(MarketDataError):
    pass


class _UnsupportedQuote(MarketDataError):
    pass


class _InvalidQuote(MarketDataError):
    pass


def parse_iss_table(payload: Payload, section: str) -> list[dict[str, Any]]:
    """Turn an ISS ``columns`` + ``data`` table into name-addressable rows."""

    table = payload.get(section)
    if not isinstance(table, Mapping):
        raise MalformedResponseError(f"ISS section {section!r} is missing")
    columns = table.get("columns")
    rows = table.get("data")
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        raise MalformedResponseError(f"ISS section {section!r} has invalid columns")
    if len(set(columns)) != len(columns):
        raise MalformedResponseError(f"ISS section {section!r} has duplicate columns")
    if not isinstance(rows, list):
        raise MalformedResponseError(f"ISS section {section!r} has invalid data")

    parsed: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != len(columns):
            raise MalformedResponseError(f"ISS section {section!r} row {index} has wrong width")
        parsed.append(dict(zip(columns, row, strict=True)))
    return parsed


def _field(row: Mapping[str, Any], *names: str) -> Any:
    by_upper = {str(key).upper(): value for key, value in row.items()}
    for name in names:
        if name.upper() in by_upper:
            return by_upper[name.upper()]
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _decimal(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise InvalidOperation
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as error:
        raise InvalidOperation(f"invalid decimal in {field_name}") from error
    if not result.is_finite():
        raise InvalidOperation(f"non-finite decimal in {field_name}")
    return result


def _date(value: Any, field_name: str) -> date:
    text = _text(value)
    if text is None:
        raise ValueError(f"missing date in {field_name}")
    try:
        return date.fromisoformat(text[:10])
    except ValueError as error:
        raise ValueError(f"invalid date in {field_name}") from error


def _currency(row: Mapping[str, Any], *names: str) -> str | None:
    value = _text(_field(row, *names))
    return value.upper() if value is not None else None


def _kind(row: Mapping[str, Any], market: str) -> str:
    explicit = _text(_field(row, "INSTRUMENT_KIND", "INSTRUMENT_TYPE", "HERMES_KIND"))
    if explicit is not None:
        return explicit.lower()
    if market.lower() == "bonds":
        return InstrumentKind.BOND.value
    marker = " ".join(
        value.lower()
        for value in (
            _text(_field(row, "TYPE")),
            _text(_field(row, "SECNAME")),
            _text(_field(row, "SHORTNAME")),
            _text(_field(row, "GROUP")),
        )
        if value is not None
    )
    if any(token in marker for token in ("etf", "fund", "mutual", "index fund")):
        return InstrumentKind.FUND.value
    if market.lower() == "shares":
        return InstrumentKind.STOCK.value
    return market.lower() or "unsupported"


def _basis(row: Mapping[str, Any], identity: MarketIdentity | None = None) -> str | None:
    value = _text(_field(row, "QUOTEBASIS", "QUOTE_BASIS"))
    if value is None and identity is not None:
        value = identity.quote_basis
    return value.upper() if value is not None else None


def _historical_price_field(row: Mapping[str, Any], instrument_kind: str) -> str | None:
    fields = (
        ("LASTPRICE", "LAST", "CLOSE", "LEGALCLOSEPRICE")
        if _normalized_kind(instrument_kind) == InstrumentKind.BOND.value
        else ("CLOSE", "LEGALCLOSEPRICE", "LAST", "LASTPRICE")
    )
    return next((field for field in fields if _text(_field(row, field)) is not None), None)


def _face_value(row: Mapping[str, Any], identity: MarketIdentity) -> Decimal | None:
    value = _field(row, "FACEVALUE", "FACE_VALUE")
    if value is None:
        return identity.face_value
    try:
        return _decimal(value, "FACEVALUE")
    except InvalidOperation as error:
        raise _InvalidQuote("invalid face value") from error


def _normalized_now(now: datetime | None, clock: Callable[[], datetime]) -> datetime:
    value = now or clock()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalized_kind(value: str) -> str:
    return value.strip().lower()


def _identity_from_rows(security: Mapping[str, Any], board: Mapping[str, Any]) -> MarketIdentity:
    merged = dict(security)
    merged.update(board)
    engine = _text(_field(board, "ENGINE"))
    market = _text(_field(board, "MARKET"))
    boardid = _text(_field(board, "BOARDID"))
    secid = _text(_field(merged, "SECID"))
    if not all((engine, market, boardid, secid)):
        raise MalformedResponseError("ISS candidate is missing canonical identity fields")
    kind = _kind(merged, market)
    face_value = None
    raw_face = _field(merged, "FACEVALUE", "FACE_VALUE")
    if raw_face is not None:
        try:
            face_value = _decimal(raw_face, "FACEVALUE")
        except InvalidOperation as error:
            raise MalformedResponseError("ISS candidate has invalid FACEVALUE") from error
    return MarketIdentity(
        provider="moex_iss",
        engine=engine,
        market=market,
        boardid=boardid,
        secid=secid,
        instrument_kind=kind,
        isin=_text(_field(merged, "ISIN")),
        quote_basis=_text(_field(merged, "QUOTEBASIS", "QUOTE_BASIS")),
        quote_currency=_currency(
            merged, "CURRENCYID", "CURRENCY", "SETTLECURRENCY", "SETTLE_CURRENCY"
        ),
        face_value=face_value,
        face_currency=_currency(merged, "FACEUNIT", "FACE_CURRENCY"),
    )


def parse_candidate_payload(
    payload: Payload,
    *,
    expected_isin: str | None = None,
) -> CandidateDiscoveryResult:
    """Parse security and board tables while retaining every board candidate."""

    securities = parse_iss_table(payload, "securities")
    boards = parse_iss_table(payload, "boards")
    by_secid = {_text(_field(row, "SECID")): row for row in securities}
    candidates: list[MarketIdentity] = []

    for board in boards:
        secid = _text(_field(board, "SECID"))
        if secid is None:
            raise MalformedResponseError("ISS board row is missing SECID")
        security = by_secid.get(secid, {})
        candidates.append(_identity_from_rows(security, board))

    if not candidates:
        return CandidateDiscoveryResult(status=MarketDataStatus.UNMAPPED)

    normalized_expected = expected_isin.strip().upper() if expected_isin else None
    if normalized_expected:
        matching = [candidate for candidate in candidates if candidate.isin == normalized_expected]
        mismatched = [
            candidate
            for candidate in candidates
            if candidate.isin not in (None, normalized_expected)
        ]
        if mismatched and not matching:
            raise IsinMismatchError(
                f"MOEX candidates do not match expected ISIN {normalized_expected!r}"
            )
        candidates = matching or candidates

    unique: dict[tuple[str, str, str, str, str], MarketIdentity] = {}
    for candidate in candidates:
        key = (
            candidate.provider,
            candidate.engine,
            candidate.market,
            candidate.boardid,
            candidate.secid,
        )
        unique[key] = candidate
    candidates = list(unique.values())

    supported = {
        InstrumentKind.STOCK.value,
        InstrumentKind.FUND.value,
        InstrumentKind.BOND.value,
    }
    if not any(
        _normalized_kind(candidate.instrument_kind) in supported for candidate in candidates
    ):
        status = MarketDataStatus.UNSUPPORTED
    elif len(candidates) > 1:
        status = MarketDataStatus.AMBIGUOUS
    else:
        status = MarketDataStatus.OK
    return CandidateDiscoveryResult(status=status, candidates=tuple(candidates))


class _UrllibTransport:
    def __call__(self, url: str, timeout_seconds: float) -> Payload:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "HermesFinance/0.4 read-only adapter",
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
        except (OSError, URLError, socket.timeout) as error:
            raise _NetworkError("MOEX request failed") from error
        try:
            return json.loads(body.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MalformedResponseError("MOEX response is not valid JSON") from error


class MoexIssClient:
    """A synchronous, bounded adapter; it never writes application state."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 7.0,
        total_timeout_seconds: float = 10.0,
        max_concurrency: int = 4,
        transport: Transport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        if min(connect_timeout_seconds, read_timeout_seconds, total_timeout_seconds) <= 0:
            raise ValueError("timeouts must be positive")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_seconds = connect_timeout_seconds
        self.read_timeout_seconds = read_timeout_seconds
        self.total_timeout_seconds = total_timeout_seconds
        self.max_concurrency = max_concurrency
        self._transport = transport or _UrllibTransport()
        self._request_slots = BoundedSemaphore(max_concurrency)
        self._clock = clock or (lambda: datetime.now(UTC))

    def _url(self, path: str, **query: str) -> str:
        suffix = f"?{urlencode(query)}" if query else ""
        return f"{self.base_url}{path}{suffix}"

    def _request_json(self, url: str) -> Payload:
        started = monotonic()
        if not self._request_slots.acquire(timeout=self.total_timeout_seconds):
            raise _NetworkError("MOEX request concurrency limit timed out")
        try:
            remaining = self.total_timeout_seconds - (monotonic() - started)
            if remaining <= 0:
                raise _NetworkError("MOEX request total timeout exceeded")
            request_timeout = min(
                self.connect_timeout_seconds,
                self.read_timeout_seconds,
                remaining,
            )
            try:
                payload = self._transport(url, request_timeout)
            except _NetworkError:
                raise
            except (TimeoutError, OSError, URLError, socket.timeout) as error:
                raise _NetworkError("MOEX request failed") from error
            if monotonic() - started > self.total_timeout_seconds:
                raise _NetworkError("MOEX request total timeout exceeded")
            if isinstance(payload, bytes):
                try:
                    payload = json.loads(
                        payload.decode("utf-8"), parse_float=Decimal, parse_int=Decimal
                    )
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise MalformedResponseError("MOEX response is not valid JSON") from error
            elif isinstance(payload, str):
                try:
                    payload = json.loads(payload, parse_float=Decimal, parse_int=Decimal)
                except json.JSONDecodeError as error:
                    raise MalformedResponseError("MOEX response is not valid JSON") from error
            if not isinstance(payload, Mapping):
                raise MalformedResponseError("MOEX response root must be an object")
            return payload
        finally:
            self._request_slots.release()

    def discover_candidates(
        self,
        query: str | None = None,
        *,
        secid: str | None = None,
        isin: str | None = None,
    ) -> CandidateDiscoveryResult:
        supplied = [value for value in (query, secid, isin) if value and value.strip()]
        if len(supplied) != 1:
            raise ValueError("provide exactly one of query, secid or isin")
        value = supplied[0].strip()
        expected_isin = isin.strip().upper() if isin else None
        if isin:
            path = "/iss/securities.json"
            url = self._url(path, q=value, **{"iss.meta": "off", "iss.only": "securities,boards"})
        else:
            escaped = quote(value, safe="")
            path = f"/iss/securities/{escaped}.json"
            url = self._url(path, **{"iss.meta": "off", "iss.only": "securities,boards"})
        try:
            return parse_candidate_payload(self._request_json(url), expected_isin=expected_isin)
        except IsinMismatchError:
            raise
        except _NetworkError as error:
            return CandidateDiscoveryResult(status=MarketDataStatus.NETWORK_ERROR, error=str(error))
        except (MalformedResponseError, ValueError) as error:
            return CandidateDiscoveryResult(
                status=MarketDataStatus.MALFORMED_RESPONSE,
                error=str(error),
            )

    def _quote_result(
        self,
        *,
        identity: MarketIdentity,
        status: MarketDataStatus,
        fetched_at_utc: datetime,
        raw_price: Decimal | None = None,
        raw_price_basis: RawPriceBasis | None = None,
        proposed_price_kopecks: int | None = None,
        price_date: date | None = None,
        quote_kind: MoexQuoteKind | None = None,
        error: str | None = None,
    ) -> NormalizedQuote:
        return NormalizedQuote(
            status=status,
            identity=identity,
            instrument_kind=identity.instrument_kind,
            raw_price=raw_price,
            raw_price_basis=raw_price_basis,
            proposed_price_kopecks=proposed_price_kopecks,
            price_date=price_date,
            quote_kind=quote_kind,
            fetched_at_utc=fetched_at_utc,
            freshness_status=(
                status if status in (MarketDataStatus.OK, MarketDataStatus.STALE) else None
            ),
            error=error,
        )

    def _normalize_row_quote(
        self,
        identity: MarketIdentity,
        row: Mapping[str, Any],
        *,
        price_field: str,
    ) -> tuple[Decimal, RawPriceBasis, int]:
        raw_value = _field(row, price_field)
        if raw_value is None or _text(raw_value) is None:
            raise LookupError("price is missing")
        try:
            raw_price = _decimal(raw_value, price_field)
        except InvalidOperation as error:
            raise _InvalidQuote(f"invalid {price_field} quote") from error
        if raw_price <= 0:
            raise _InvalidQuote(f"{price_field} quote must be positive")

        kind = _normalized_kind(identity.instrument_kind)
        basis = _basis(row, identity)
        currency = _currency(row, "CURRENCYID", "CURRENCY", "SETTLECURRENCY", "SETTLE_CURRENCY")
        currency = currency or identity.quote_currency
        if kind in (InstrumentKind.STOCK.value, InstrumentKind.FUND.value):
            if currency != "RUB":
                raise _UnsupportedQuote("stock/fund quote is not RUB-compatible")
            if basis not in (None, RawPriceBasis.CASH_PER_UNIT.value):
                raise _UnsupportedQuote("stock/fund quote basis is not cash-per-unit")
            normalized_basis = RawPriceBasis.CASH_PER_UNIT
            clean_rubles = raw_price
        elif kind == InstrumentKind.BOND.value:
            if basis == RawPriceBasis.CASH_PER_UNIT.value:
                if currency != "RUB":
                    raise _UnsupportedQuote("bond cash quote is not RUB-compatible")
                normalized_basis = RawPriceBasis.CASH_PER_UNIT
                clean_rubles = raw_price
            elif basis == RawPriceBasis.PERCENT_OF_FACE.value:
                face_value = _face_value(row, identity)
                face_currency = (
                    _currency(row, "FACEUNIT", "FACE_CURRENCY") or identity.face_currency
                )
                if face_value is None or face_value <= 0:
                    raise _InvalidQuote("bond percentage quote is missing positive FACEVALUE")
                if face_currency != "RUB" or currency != "RUB":
                    raise _UnsupportedQuote("bond face/settlement currency is not RUB-compatible")
                normalized_basis = RawPriceBasis.PERCENT_OF_FACE
                clean_rubles = face_value * raw_price / _HUNDRED
            else:
                raise _UnsupportedQuote("bond quote basis is unknown")
        else:
            raise _UnsupportedQuote("instrument kind is not supported in R04")

        proposed_kopecks = int(
            (clean_rubles * _HUNDRED).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        if proposed_kopecks <= 0:
            raise _InvalidQuote("normalized quote must be positive")
        return raw_price, normalized_basis, proposed_kopecks

    def _result_from_row(
        self,
        identity: MarketIdentity,
        row: Mapping[str, Any],
        *,
        target_date: date,
        fetched_at_utc: datetime,
        price_field: str,
        quote_kind: MoexQuoteKind,
    ) -> NormalizedQuote:
        try:
            price_date = _date(_field(row, "TRADEDATE", "LASTTRADEDATE", "PRICEDATE"), "price date")
            if price_date > target_date:
                raise _InvalidQuote("quote is newer than target date")
            raw_price, basis, proposed = self._normalize_row_quote(
                identity, row, price_field=price_field
            )
        except LookupError:
            raise
        except _UnsupportedQuote:
            raise
        except _InvalidQuote:
            raise
        except (ValueError, InvalidOperation) as error:
            raise _InvalidQuote("quote row is malformed") from error

        age_days = (target_date - price_date).days
        if age_days > MAX_HISTORY_DAYS:
            return self._quote_result(
                identity=identity,
                status=MarketDataStatus.UNAVAILABLE,
                fetched_at_utc=fetched_at_utc,
                error="quote is older than the 30-day lookback",
            )
        status = MarketDataStatus.OK if age_days <= 7 else MarketDataStatus.STALE
        return self._quote_result(
            identity=identity,
            status=status,
            fetched_at_utc=fetched_at_utc,
            raw_price=raw_price,
            raw_price_basis=basis,
            proposed_price_kopecks=proposed,
            price_date=price_date,
            quote_kind=quote_kind,
        )

    def _current_row(self, payload: Payload, identity: MarketIdentity) -> Mapping[str, Any] | None:
        rows = parse_iss_table(payload, "marketdata")
        matching = [
            row
            for row in rows
            if _text(_field(row, "BOARDID")) == identity.boardid
            and _text(_field(row, "SECID")) in (None, identity.secid)
        ]
        return matching[0] if matching else None

    def _historical_row(
        self,
        payload: Payload,
        identity: MarketIdentity,
        *,
        target_date: date,
    ) -> tuple[Mapping[str, Any], str] | None:
        rows = parse_iss_table(payload, "history")
        candidates: list[tuple[date, Mapping[str, Any]]] = []
        for row in rows:
            if _text(_field(row, "BOARDID")) not in (None, identity.boardid):
                continue
            if _text(_field(row, "SECID")) not in (None, identity.secid):
                continue
            try:
                trade_date = _date(_field(row, "TRADEDATE", "PRICEDATE"), "TRADEDATE")
            except ValueError:
                continue
            if target_date - timedelta(days=MAX_HISTORY_DAYS) <= trade_date <= target_date:
                candidates.append((trade_date, row))
        candidates.sort(key=lambda item: item[0], reverse=True)
        saw_invalid = False
        for _, row in candidates:
            price_field = _historical_price_field(row, identity.instrument_kind)
            if price_field is None:
                continue
            try:
                self._normalize_row_quote(identity, row, price_field=price_field)
            except _UnsupportedQuote:
                raise
            except (_InvalidQuote, InvalidOperation):
                saw_invalid = True
                continue
            return row, price_field
        if saw_invalid:
            raise _InvalidQuote("no valid historical quote row")
        return None

    def fetch_quote(
        self,
        identity: MarketIdentity,
        target_date: date,
        *,
        now: datetime | None = None,
    ) -> NormalizedQuote:
        fetched_at_utc = _normalized_now(now, self._clock)
        kind = _normalized_kind(identity.instrument_kind)
        if kind not in {
            InstrumentKind.STOCK.value,
            InstrumentKind.FUND.value,
            InstrumentKind.BOND.value,
        }:
            return self._quote_result(
                identity=identity,
                status=MarketDataStatus.UNSUPPORTED,
                fetched_at_utc=fetched_at_utc,
                error="instrument kind is not supported in R04",
            )

        current_date = fetched_at_utc.astimezone(MOSCOW_TZ).date()
        history_from = target_date - timedelta(days=MAX_HISTORY_DAYS)
        try:
            row: Mapping[str, Any] | None = None
            quote_kind = MoexQuoteKind.HISTORICAL_RESULT
            price_field = "LASTPRICE" if kind == InstrumentKind.BOND.value else "CLOSE"

            if target_date == current_date:
                current_url = self._url(
                    f"/iss/engines/{quote(identity.engine, safe='')}/markets/"
                    f"{quote(identity.market, safe='')}/boards/{quote(identity.boardid, safe='')}"
                    f"/securities/{quote(identity.secid, safe='')}.json",
                    **{"iss.meta": "off", "iss.only": "marketdata"},
                )
                current_payload = self._request_json(current_url)
                current = self._current_row(current_payload, identity)
                if current is not None and _text(_field(current, "LAST")) is not None:
                    row = current
                    price_field = "LAST"
                    quote_kind = MoexQuoteKind.CURRENT_LAST

            if row is None:
                history_url = self._url(
                    f"/iss/history/engines/{quote(identity.engine, safe='')}/markets/"
                    f"{quote(identity.market, safe='')}/boards/{quote(identity.boardid, safe='')}"
                    f"/securities/{quote(identity.secid, safe='')}.json",
                    **{
                        "from": history_from.isoformat(),
                        "till": target_date.isoformat(),
                        "iss.meta": "off",
                        "iss.only": "history",
                    },
                )
                history_payload = self._request_json(history_url)
                historical = self._historical_row(
                    history_payload, identity, target_date=target_date
                )
                if historical is None:
                    return self._quote_result(
                        identity=identity,
                        status=MarketDataStatus.UNAVAILABLE,
                        fetched_at_utc=fetched_at_utc,
                        error="no valid quote in the 30-day lookback",
                    )
                row, price_field = historical

            return self._result_from_row(
                identity,
                row,
                target_date=target_date,
                fetched_at_utc=fetched_at_utc,
                price_field=price_field,
                quote_kind=quote_kind,
            )
        except _UnsupportedQuote as error:
            return self._quote_result(
                identity=identity,
                status=MarketDataStatus.UNSUPPORTED,
                fetched_at_utc=fetched_at_utc,
                error=str(error),
            )
        except (_InvalidQuote, MalformedResponseError, InvalidOperation, ValueError) as error:
            return self._quote_result(
                identity=identity,
                status=MarketDataStatus.MALFORMED_RESPONSE,
                fetched_at_utc=fetched_at_utc,
                error=str(error),
            )
        except _NetworkError as error:
            return self._quote_result(
                identity=identity,
                status=MarketDataStatus.NETWORK_ERROR,
                fetched_at_utc=fetched_at_utc,
                error=str(error),
            )

    def fetch_quotes(
        self,
        identities: Sequence[MarketIdentity],
        target_date: date,
        *,
        now: datetime | None = None,
    ) -> MarketDataBatchResult:
        """Fetch a bounded batch while preserving every per-identity result."""

        if not identities:
            return MarketDataBatchResult(results=())
        with ThreadPoolExecutor(max_workers=min(self.max_concurrency, len(identities))) as executor:
            futures = [
                executor.submit(self.fetch_quote, identity, target_date, now=now)
                for identity in identities
            ]
            results = tuple(future.result() for future in futures)
        return MarketDataBatchResult(results=results)
