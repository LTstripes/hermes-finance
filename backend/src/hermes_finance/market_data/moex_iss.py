"""Read-only MOEX ISS adapter. No DB writes, no apply, no background fetch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx2

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import (
    MOEX_ISS_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteFailure,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    QuoteSuccess,
    RejectedCandidate,
)
from hermes_finance.market_data.iss_parse import (
    IssParseError,
    decimal_from_external,
    description_map,
    load_iss_json,
    parse_iss_payload,
    row_get,
    row_text,
)
from hermes_finance.market_data.normalize import (
    MAX_LOOKBACK_DAYS,
    SUPPORTED_KINDS,
    NormalizeError,
    classify_freshness,
    convert_to_kopecks,
    lookback_start,
    resolve_quote_basis,
)

DEFAULT_BASE_URL: Final = "https://iss.moex.com"
DEFAULT_TIMEOUT: Final = httpx2.Timeout(20.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
DEFAULT_MAX_CONCURRENCY: Final = 2
DEFAULT_MAX_DISCOVERY_SECURITIES: Final = 10


def _moscow_tz() -> timezone | ZoneInfo:
    try:
        return ZoneInfo("Europe/Moscow")
    except ZoneInfoNotFoundError:
        # Windows CPython has no IANA database; Moscow has been UTC+3 year-round since 2014.
        return timezone(timedelta(hours=3))


MOSCOW_TZ: Final = _moscow_tz()
_HISTORY_PRICE_FIELDS: Final = ("LASTPRICE", "LEGALCLOSEPRICE", "CLOSE")


class _NetworkFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _NotFound(Exception):
    pass


class MoexIssClient:
    """Board-aware ISS client implementing the R04-02 provider boundary."""

    def __init__(
        self,
        *,
        client: httpx2.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: httpx2.Timeout = DEFAULT_TIMEOUT,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_discovery_securities: int = DEFAULT_MAX_DISCOVERY_SECURITIES,
        clock: Callable[[], date] | None = None,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if client is None:
            self._http = httpx2.Client(
                base_url=base_url.rstrip("/"),
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
            self._owns_client = True
        else:
            self._http = client
            self._owns_client = False
        self._max_concurrency = max_concurrency
        self._max_discovery_securities = max_discovery_securities
        self._clock = clock or (lambda: datetime.now(MOSCOW_TZ).date())
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> MoexIssClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        secid: str | None = None,
        isin: str | None = None,
    ) -> DiscoverResult:
        expected_isin = _normalize_isin(isin)
        search = (query or secid or isin or "").strip()
        if not search:
            return DiscoverResult(
                status=QuoteStatus.UNAVAILABLE,
                message="discover query is empty",
            )
        try:
            if secid and not query:
                details = [self._load_security_details(secid.strip())]
            else:
                details = self._search_securities(search)
        except _NetworkFailure as error:
            return DiscoverResult(status=QuoteStatus.NETWORK_ERROR, message=error.message)
        except _NotFound:
            return DiscoverResult(status=QuoteStatus.UNAVAILABLE, message="security was not found")
        except (IssParseError, NormalizeError) as error:
            return DiscoverResult(status=QuoteStatus.MALFORMED_RESPONSE, message=str(error))

        accepted: list[DiscoverCandidate] = []
        rejected: list[RejectedCandidate] = []
        unsupported_only = True
        for detail in details:
            if detail is None:
                continue
            if expected_isin and detail.isin and detail.isin != expected_isin:
                rejected.append(
                    RejectedCandidate(
                        secid=detail.secid,
                        candidate_isin=detail.isin,
                        expected_isin=expected_isin,
                    )
                )
                continue
            if detail.kind not in SUPPORTED_KINDS:
                continue
            unsupported_only = False
            accepted.extend(detail.as_candidates())

        if accepted:
            status = QuoteStatus.OK if len(accepted) == 1 else QuoteStatus.AMBIGUOUS
            return DiscoverResult(
                status=status,
                candidates=tuple(accepted),
                rejected=tuple(rejected),
            )
        if rejected:
            return DiscoverResult(
                status=QuoteStatus.UNAVAILABLE,
                rejected=tuple(rejected),
                message="ISIN does not match candidate",
            )
        if unsupported_only and details:
            return DiscoverResult(
                status=QuoteStatus.UNSUPPORTED,
                message="no RUB-compatible stock/fund/bond board",
            )
        return DiscoverResult(status=QuoteStatus.UNAVAILABLE, message="no compatible candidates")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        if identity.provider != MOEX_ISS_PROVIDER:
            return QuoteFailure(
                status=QuoteStatus.UNSUPPORTED,
                message="provider is not moex_iss",
                identity=identity,
            )
        try:
            detail = self._load_security_details(identity.secid)
            kind = detail.kind
            if kind not in SUPPORTED_KINDS:
                return QuoteFailure(
                    status=QuoteStatus.UNSUPPORTED,
                    message="instrument kind is not supported in 0.4",
                    identity=identity,
                )
            if not _compatible_board(identity.engine, identity.market, kind):
                return QuoteFailure(
                    status=QuoteStatus.UNSUPPORTED,
                    message="engine/market is not a supported 0.4 family",
                    identity=identity,
                )
            if identity.isin and detail.isin and _normalize_isin(identity.isin) != detail.isin:
                return QuoteFailure(
                    status=QuoteStatus.UNSUPPORTED,
                    message="ISIN does not match candidate",
                    identity=identity,
                )

            market_tables = self._market_payload(identity)
            securities_rows = market_tables.get("securities", [])
            marketdata_rows = market_tables.get("marketdata", [])
            security_row = _row_for_identity(securities_rows, identity) or (
                securities_rows[0] if securities_rows else {}
            )
            market_row = _row_for_identity(marketdata_rows, identity) or (
                marketdata_rows[0] if marketdata_rows else {}
            )
            quoted_basis = row_text(security_row, "QUOTEBASIS") or detail.quote_basis
            currency_unit = (
                row_text(security_row, "FACEUNIT", "CURRENCYID", "CURRENCY") or detail.face_unit
            )
            face_token = row_get(security_row, "FACEVALUE") or detail.face_value
            face_value = (
                decimal_from_external(face_token, name="FACEVALUE")
                if face_token not in (None, "")
                else None
            )
            basis = resolve_quote_basis(
                quoted_basis=quoted_basis,
                market=identity.market,
                instrument_kind=kind,
            )
            shares_default = kind in {InstrumentType.STOCK, InstrumentType.FUND}

            selected = None
            if target_date >= self._clock():
                selected = self._current_last(market_row, target_date)
            if selected is None:
                selected = self._historical_quote(identity, target_date)
            if selected is None:
                return QuoteFailure(
                    status=QuoteStatus.UNAVAILABLE,
                    message="no valid quote within 30 calendar days",
                    identity=identity,
                )
            raw_price, price_date, quote_kind = selected
            freshness = classify_freshness(target_date, price_date)
            if freshness is QuoteStatus.UNAVAILABLE:
                return QuoteFailure(
                    status=QuoteStatus.UNAVAILABLE,
                    message="no valid quote within 30 calendar days",
                    identity=identity,
                )
            kopecks = convert_to_kopecks(
                raw_price=raw_price,
                basis=basis,
                face_value=face_value,
                currency_unit=currency_unit,
                shares_schema_cash_default=shares_default,
            )
        except _NetworkFailure as error:
            return QuoteFailure(
                status=QuoteStatus.NETWORK_ERROR,
                message=error.message,
                identity=identity,
            )
        except _NotFound:
            return QuoteFailure(
                status=QuoteStatus.UNAVAILABLE,
                message="security was not found",
                identity=identity,
            )
        except NormalizeError as error:
            return QuoteFailure(status=error.status, message=error.message, identity=identity)
        except IssParseError as error:
            return QuoteFailure(
                status=QuoteStatus.MALFORMED_RESPONSE,
                message=str(error),
                identity=identity,
            )

        return QuoteSuccess(
            identity=identity,
            instrument_kind=kind,
            raw_price=format(raw_price, "f"),
            raw_price_basis=basis,
            proposed_price_kopecks=kopecks,
            price_date=price_date,
            quote_kind=quote_kind,
            fetched_at_utc=self._utcnow(),
            freshness_status=freshness,
        )

    def fetch_quotes(self, items: Sequence[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        # Sequential on purpose: successes must stay even when later items fail.
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]

    def _search_securities(self, query: str) -> list[_SecurityDetails]:
        payload = self._get("/iss/securities.json", {"q": query, "iss.meta": "off"})
        rows = parse_iss_payload(payload).get("securities", [])
        secids: list[str] = []
        for row in rows:
            secid = row_text(row, "secid")
            if secid and secid not in secids:
                secids.append(secid)
        details: list[_SecurityDetails] = []
        for secid in secids[: self._max_discovery_securities]:
            try:
                details.append(self._load_security_details(secid))
            except _NotFound:
                continue
        return details

    def _load_security_details(self, secid: str) -> _SecurityDetails:
        payload = self._get(f"/iss/securities/{secid}.json", {"iss.meta": "off"})
        tables = parse_iss_payload(payload)
        description = description_map(tables.get("description", []))
        kind = classify_instrument_kind(
            group=description.get("GROUP"),
            type_code=description.get("TYPE"),
            market=None,
        )
        boards: list[MarketIdentity] = []
        for row in tables.get("boards", []):
            engine = row_text(row, "engine")
            market = row_text(row, "market")
            boardid = row_text(row, "boardid")
            if not engine or not market or not boardid:
                continue
            board_kind = kind or classify_instrument_kind(
                group=description.get("GROUP"),
                type_code=description.get("TYPE"),
                market=market,
            )
            if board_kind is None or not _compatible_board(engine, market, board_kind):
                continue
            boards.append(
                MarketIdentity(
                    provider=MOEX_ISS_PROVIDER,
                    engine=engine,
                    market=market,
                    boardid=boardid,
                    secid=secid,
                    isin=_normalize_isin(description.get("ISIN")),
                )
            )
        return _SecurityDetails(
            secid=secid,
            kind=kind,
            isin=_normalize_isin(description.get("ISIN")),
            quote_basis=description.get("QUOTEBASIS"),
            face_unit=description.get("FACEUNIT"),
            face_value=description.get("FACEVALUE"),
            boards=tuple(boards),
        )

    def _market_payload(self, identity: MarketIdentity) -> dict[str, list[dict[str, object]]]:
        path = (
            f"/iss/engines/{identity.engine}/markets/{identity.market}"
            f"/boards/{identity.boardid}/securities/{identity.secid}.json"
        )
        payload = self._get(path, {"iss.meta": "off"})
        return parse_iss_payload(payload)

    def _current_last(
        self, market_row: dict[str, object], target_date: date
    ) -> tuple[Decimal, date, QuoteKind] | None:
        last_token = row_get(market_row, "LAST")
        if last_token in (None, ""):
            return None
        raw_price = decimal_from_external(last_token, name="LAST")
        if raw_price <= 0:
            raise NormalizeError(QuoteStatus.MALFORMED_RESPONSE, "LAST is not a positive amount")
        date_token = row_text(market_row, "LASTTRADEDATE", "TRADEDATE")
        if date_token is None:
            return None
        price_date = _parse_iss_date(date_token)
        if price_date > target_date:
            return None
        return raw_price, price_date, QuoteKind.LAST

    def _historical_quote(
        self, identity: MarketIdentity, target_date: date
    ) -> tuple[Decimal, date, QuoteKind] | None:
        path = (
            f"/iss/history/engines/{identity.engine}/markets/{identity.market}"
            f"/boards/{identity.boardid}/securities/{identity.secid}.json"
        )
        payload = self._get(
            path,
            {
                "from": lookback_start(target_date).isoformat(),
                "till": target_date.isoformat(),
                "iss.meta": "off",
                "sort_order": "desc",
            },
        )
        rows = parse_iss_payload(payload).get("history", [])
        best: tuple[Decimal, date, QuoteKind] | None = None
        for row in rows:
            date_token = row_text(row, "TRADEDATE")
            if date_token is None:
                continue
            try:
                price_date = _parse_iss_date(date_token)
            except IssParseError:
                continue
            if price_date > target_date:
                continue
            if (target_date - price_date).days > MAX_LOOKBACK_DAYS:
                continue
            raw_price = _history_price(row)
            if raw_price is None or raw_price <= 0:
                continue
            if best is None or price_date > best[1]:
                best = (raw_price, price_date, QuoteKind.HISTORY)
        return best

    def _get(self, path: str, params: dict[str, str] | None = None) -> object:
        try:
            response = self._http.get(path, params=params)
        except httpx2.TimeoutException as error:
            raise _NetworkFailure("ISS request timed out") from error
        except httpx2.TransportError as error:
            raise _NetworkFailure("ISS network failure") from error
        if response.status_code == 404:
            raise _NotFound
        if response.status_code >= 400:
            raise _NetworkFailure(f"ISS HTTP {response.status_code}")
        try:
            return load_iss_json(response.text)
        except IssParseError as error:
            raise error


class _SecurityDetails:
    def __init__(
        self,
        *,
        secid: str,
        kind: InstrumentType | None,
        isin: str | None,
        quote_basis: str | None,
        face_unit: str | None,
        face_value: str | None,
        boards: tuple[MarketIdentity, ...],
    ) -> None:
        self.secid = secid
        self.kind = kind
        self.isin = isin
        self.quote_basis = quote_basis
        self.face_unit = face_unit
        self.face_value = face_value
        self.boards = boards

    def as_candidates(self) -> list[DiscoverCandidate]:
        if self.kind is None:
            return []
        return [
            DiscoverCandidate(identity=board, instrument_kind=self.kind) for board in self.boards
        ]


def classify_instrument_kind(
    *,
    group: str | None,
    type_code: str | None,
    market: str | None,
) -> InstrumentType | None:
    group_l = (group or "").lower()
    type_l = (type_code or "").lower()
    market_l = (market or "").lower()
    if (
        market_l == "bonds"
        or group_l == "stock_bonds"
        or "bond" in type_l
        or type_l.startswith("ofz")
    ):
        return InstrumentType.BOND
    if (
        group_l in {"stock_etf", "stock_ppif"}
        or "etf" in type_l
        or "ppif" in type_l
        or "fund" in type_l
    ):
        return InstrumentType.FUND
    if (
        market_l == "shares"
        or group_l == "stock_shares"
        or "share" in type_l
        or type_l in {"common_share", "preferred_share"}
    ):
        return InstrumentType.STOCK
    return None


def _compatible_board(engine: str, market: str, kind: InstrumentType) -> bool:
    if engine != "stock":
        return False
    if kind in {InstrumentType.STOCK, InstrumentType.FUND}:
        return market == "shares"
    if kind is InstrumentType.BOND:
        return market == "bonds"
    return False


def _normalize_isin(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip().upper()
    return text or None


def _parse_iss_date(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except ValueError as error:
        raise IssParseError(f"invalid ISS date: {value}") from error


def _row_for_identity(
    rows: list[dict[str, object]], identity: MarketIdentity
) -> dict[str, object] | None:
    for row in rows:
        secid = row_text(row, "SECID")
        boardid = row_text(row, "BOARDID")
        if secid == identity.secid and (boardid is None or boardid == identity.boardid):
            return row
    return None


def _history_price(row: dict[str, object]) -> Decimal | None:
    for field in _HISTORY_PRICE_FIELDS:
        token = row_get(row, field)
        if token in (None, ""):
            continue
        try:
            return decimal_from_external(token, name=field)
        except IssParseError:
            continue
    return None
