"""Read-only T-Invest market-data adapter. No orders, transfers, or broker data."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Final
from uuid import UUID

import httpx2

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.capabilities import (
    T_INVEST_CAPABILITIES,
    ProviderCapabilities,
)
from hermes_finance.market_data.dto import (
    T_INVEST_PROVIDER,
    DiscoverCandidate,
    DiscoverResult,
    MarketIdentity,
    QuoteFailure,
    QuoteKind,
    QuoteResult,
    QuoteStatus,
    QuoteSuccess,
    RawPriceBasis,
    RejectedCandidate,
)
from hermes_finance.market_data.moscow import MOSCOW_TZ, moscow_calendar_date
from hermes_finance.market_data.normalize import (
    MAX_LOOKBACK_DAYS,
    SUPPORTED_KINDS,
    NormalizeError,
    classify_freshness,
    convert_to_kopecks,
    is_rub_compatible,
)
from hermes_finance.market_data.quotation import QuotationError, quotation_to_decimal

DEFAULT_BASE_URL: Final = "https://invest-public-api.tbank.ru/rest"
DEFAULT_TIMEOUT: Final = httpx2.Timeout(20.0, connect=5.0, read=10.0, write=10.0, pool=5.0)
DEFAULT_MAX_DISCOVERY: Final = 10
TOKEN_UNAVAILABLE_MESSAGE: Final = "T-Invest read-only token is not configured or is unavailable"

_INSTRUMENTS = "InstrumentsService"
_MARKET_DATA = "MarketDataService"
_GET_INSTRUMENT_BY = "GetInstrumentBy"
_FIND_INSTRUMENT = "FindInstrument"
_BOND_BY = "BondBy"
_GET_LAST_PRICES = "GetLastPrices"
_GET_CANDLES = "GetCandles"
_GET_BOND_COUPONS = "GetBondCoupons"
_GET_BOND_EVENTS = "GetBondEvents"
_GET_DIVIDENDS = "GetDividends"

PAYOUT_PROBE_METHODS: Final = frozenset(
    {
        _GET_BOND_COUPONS,
        _GET_BOND_EVENTS,
        _GET_DIVIDENDS,
    }
)

_ID_TYPE_UID: Final = "INSTRUMENT_ID_TYPE_UID"
_LAST_PRICE_EXCHANGE: Final = "LAST_PRICE_EXCHANGE"
_CANDLE_DAY: Final = "CANDLE_INTERVAL_DAY"
_CANDLE_EXCHANGE: Final = "CANDLE_SOURCE_EXCHANGE"

_KIND_MAP: Final = {
    "INSTRUMENT_TYPE_SHARE": InstrumentType.STOCK,
    "INSTRUMENT_TYPE_ETF": InstrumentType.FUND,
    "INSTRUMENT_TYPE_BOND": InstrumentType.BOND,
    "share": InstrumentType.STOCK,
    "stock": InstrumentType.STOCK,
    "etf": InstrumentType.FUND,
    "fund": InstrumentType.FUND,
    "bond": InstrumentType.BOND,
}

_KIND_TO_T_INVEST: Final = {
    InstrumentType.STOCK: "INSTRUMENT_TYPE_SHARE",
    InstrumentType.FUND: "INSTRUMENT_TYPE_ETF",
    InstrumentType.BOND: "INSTRUMENT_TYPE_BOND",
}

_DEALER_EXCHANGES: Final = frozenset({"REAL_EXCHANGE_DEALER", "REAL_EXCHANGE_OTC", "dealer", "otc"})


class _NetworkFailure(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _AuthUnavailable(Exception):
    def __init__(self, message: str = TOKEN_UNAVAILABLE_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


class _Malformed(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _Unsupported(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _NotFound(Exception):
    pass


class _Unavailable(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def normalize_t_invest_uid(value: str) -> str:
    try:
        return str(UUID(value.strip()))
    except ValueError as error:
        raise ValueError(
            "t_invest provider_instrument_id must be an instrument_uid UUID"
        ) from error


def t_invest_identity(*, provider_instrument_id: str, isin: str | None = None) -> MarketIdentity:
    return MarketIdentity(
        provider=T_INVEST_PROVIDER,
        provider_instrument_id=normalize_t_invest_uid(provider_instrument_id),
        provider_venue_id=None,
        isin=_normalize_isin(isin),
    )


def _normalize_isin(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def _field(payload: object, *names: str) -> object:
    if not isinstance(payload, dict):
        return None
    for name in names:
        if name in payload:
            return payload[name]
    lookup = {str(key).lower(): value for key, value in payload.items()}
    for name in names:
        found = lookup.get(name.lower())
        if found is not None or name.lower() in lookup:
            return found
    return None


def _text(payload: object, *names: str) -> str | None:
    value = _field(payload, *names)
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _require_object(payload: object, *, name: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise _Malformed(f"{name} is not an object")
    return payload


def _parse_timestamp(value: object, *, name: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        raise _Malformed(f"{name} is not a timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise _Malformed(f"{name} is not a timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _quotation_decimal(payload: object, *, name: str) -> Decimal:
    body = _require_object(payload, name=name)
    try:
        return quotation_to_decimal(units=_field(body, "units"), nano=_field(body, "nano"))
    except QuotationError as error:
        raise _Malformed(f"{name} is not a valid Quotation") from error


def _money_value(payload: object, *, name: str) -> tuple[Decimal, str]:
    body = _require_object(payload, name=name)
    currency = _text(body, "currency")
    if currency is None:
        raise _Malformed(f"{name} is missing currency")
    try:
        amount = quotation_to_decimal(units=_field(body, "units"), nano=_field(body, "nano"))
    except QuotationError as error:
        raise _Malformed(f"{name} is not a valid MoneyValue") from error
    return amount, currency


def _map_kind(*raw_values: str | None) -> InstrumentType | None:
    for raw in raw_values:
        if not raw:
            continue
        mapped = _KIND_MAP.get(raw.strip())
        if mapped is None:
            mapped = _KIND_MAP.get(raw.strip().lower())
        if mapped is not None:
            return mapped
    return None


def _reject_non_exchange(instrument: dict[str, object]) -> None:
    exchange = _text(instrument, "realExchange", "real_exchange")
    if exchange is None:
        return
    if exchange in _DEALER_EXCHANGES or exchange.upper() in _DEALER_EXCHANGES:
        raise _Unsupported("instrument is not an exchange RUB-per-unit listing")


def _require_rub_currency(unit: str | None, *, message: str) -> None:
    if not is_rub_compatible(unit):
        raise _Unsupported(message)


def _bond_maturity_date(bond: dict[str, object]) -> date:
    stamped = _parse_timestamp(
        _field(bond, "maturityDate", "maturity_date"),
        name="bond maturity_date",
    )
    return stamped.date()


def _bond_initial_nominal(bond: dict[str, object]) -> tuple[Decimal, str]:
    initial, currency = _money_value(
        _field(bond, "initialNominal", "initial_nominal"),
        name="initial_nominal",
    )
    if initial <= 0:
        raise _Malformed("bond initial nominal is not a positive amount")
    return initial, currency


def _bond_nominal_for_discovery(bond: dict[str, object], *, today: date) -> tuple[Decimal, str]:
    nominal, currency = _money_value(_field(bond, "nominal"), name="nominal")
    if nominal > 0:
        return nominal, currency
    if nominal < 0:
        raise _Malformed("bond nominal is negative")

    maturity_date = _bond_maturity_date(bond)
    amortizing = _optional_bool(bond, "amortizationFlag", "amortization_flag")
    if maturity_date > today or amortizing is not False:
        raise _Unsupported("historical bond nominal cannot be established safely")
    return _bond_initial_nominal(bond)


def _bond_nominal_for_target(
    bond: dict[str, object], *, target_date: date, today: date
) -> tuple[Decimal, str]:
    nominal, currency = _money_value(_field(bond, "nominal"), name="nominal")
    if nominal > 0:
        return nominal, currency
    if nominal < 0:
        raise _Malformed("bond nominal is negative")

    maturity_date = _bond_maturity_date(bond)
    if maturity_date > today:
        raise _Unsupported("historical bond nominal cannot be established safely")
    if target_date >= maturity_date:
        raise _Unavailable("bond has matured for the requested target date")
    amortizing = _optional_bool(bond, "amortizationFlag", "amortization_flag")
    if amortizing is not False:
        raise _Unsupported("historical bond nominal cannot be established safely")
    return _bond_initial_nominal(bond)


class TInvestClient:
    """Narrow official-REST client implementing MarketDataProvider."""

    def __init__(
        self,
        *,
        token: str | None,
        client: httpx2.Client | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: httpx2.Timeout = DEFAULT_TIMEOUT,
        max_discovery: int = DEFAULT_MAX_DISCOVERY,
        clock: Callable[[], date] | None = None,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        cleaned = token.strip() if token is not None else ""
        self._token = cleaned or None
        if client is None:
            self._http = httpx2.Client(
                base_url=base_url.rstrip("/"),
                timeout=timeout,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            self._owns_client = True
        else:
            self._http = client
            self._owns_client = False
        self._max_discovery = max_discovery
        self._clock = clock or (lambda: datetime.now(MOSCOW_TZ).date())
        self._utcnow = utcnow or (lambda: datetime.now(timezone.utc))
        self._instrument_cache: dict[str, dict[str, object]] = {}
        self._bond_cache: dict[str, dict[str, object]] = {}

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    @property
    def capabilities(self) -> ProviderCapabilities:
        return T_INVEST_CAPABILITIES

    def __enter__(self) -> TInvestClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def discover_candidates(
        self,
        *,
        query: str | None = None,
        provider_instrument_id: str | None = None,
        isin: str | None = None,
        instrument_kind: InstrumentType | None = None,
    ) -> DiscoverResult:
        expected_isin = _normalize_isin(isin)
        wanted_kind = instrument_kind if instrument_kind in SUPPORTED_KINDS else None
        try:
            if provider_instrument_id and provider_instrument_id.strip():
                shorts = [self._instrument_by_uid(provider_instrument_id)]
            elif expected_isin:
                shorts = self._find_instruments(expected_isin, instrument_kind=wanted_kind)
            else:
                search = (query or "").strip()
                if not search:
                    return DiscoverResult(
                        status=QuoteStatus.UNAVAILABLE,
                        message="discover query is empty",
                    )
                shorts = self._find_instruments(search, instrument_kind=wanted_kind)
        except ValueError as error:
            return DiscoverResult(status=QuoteStatus.MALFORMED_RESPONSE, message=str(error))
        except _AuthUnavailable as error:
            return DiscoverResult(status=QuoteStatus.UNAVAILABLE, message=error.message)
        except _NetworkFailure as error:
            return DiscoverResult(status=QuoteStatus.NETWORK_ERROR, message=error.message)
        except _NotFound:
            return DiscoverResult(
                status=QuoteStatus.UNAVAILABLE,
                message="T-Invest instrument was not found",
            )
        except (_Malformed, QuotationError) as error:
            return DiscoverResult(status=QuoteStatus.MALFORMED_RESPONSE, message=str(error))

        accepted: list[DiscoverCandidate] = []
        rejected: list[RejectedCandidate] = []
        saw_unsupported = False
        malformed_message: str | None = None
        for short in shorts:
            try:
                uid = normalize_t_invest_uid(_require_uid(short))
            except (ValueError, _Malformed):
                malformed_message = "T-Invest instrument is missing instrument_uid"
                continue
            candidate_isin = _normalize_isin(_text(short, "isin"))
            if expected_isin and candidate_isin and candidate_isin != expected_isin:
                rejected.append(
                    RejectedCandidate(
                        provider_instrument_id=uid,
                        candidate_isin=candidate_isin,
                        expected_isin=expected_isin,
                    )
                )
                continue
            try:
                detail = self._instrument_by_uid(uid)
                kind = _map_kind(
                    _text(detail, "instrumentKind", "instrument_kind"),
                    _text(detail, "instrumentType", "instrument_type"),
                    _text(short, "instrumentKind", "instrument_kind"),
                    _text(short, "instrumentType", "instrument_type"),
                )
                if kind not in SUPPORTED_KINDS:
                    saw_unsupported = True
                    continue
                if wanted_kind is not None and kind is not wanted_kind:
                    continue
                _reject_non_exchange(detail)
                currency = _text(detail, "currency")
                if kind is InstrumentType.BOND:
                    bond = self._bond_by_uid(uid)
                    _, nominal_currency = _bond_nominal_for_discovery(
                        bond,
                        today=self._clock(),
                    )
                    _require_rub_currency(
                        nominal_currency, message="bond nominal is not RUB-compatible"
                    )
                    _require_rub_currency(
                        _text(bond, "currency") or currency,
                        message="bond quote is not RUB-compatible",
                    )
                else:
                    _require_rub_currency(currency, message="quote is not RUB-compatible")
            except _Unsupported:
                saw_unsupported = True
                continue
            except _NotFound:
                continue
            except _AuthUnavailable as error:
                return DiscoverResult(status=QuoteStatus.UNAVAILABLE, message=error.message)
            except _NetworkFailure as error:
                return DiscoverResult(status=QuoteStatus.NETWORK_ERROR, message=error.message)
            except (_Malformed, QuotationError) as error:
                malformed_message = str(error)
                continue
            display = _candidate_display(short, detail)
            accepted.append(
                DiscoverCandidate(
                    identity=MarketIdentity(
                        provider=T_INVEST_PROVIDER,
                        provider_instrument_id=uid,
                        provider_venue_id=None,
                        isin=candidate_isin or expected_isin,
                    ),
                    instrument_kind=kind,
                    name=display.name,
                    ticker=display.ticker,
                    class_code=display.class_code,
                    exchange=display.exchange,
                    api_trade_available=display.api_trade_available,
                    position_uid=display.position_uid,
                )
            )

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
        if saw_unsupported:
            return DiscoverResult(
                status=QuoteStatus.UNSUPPORTED,
                message="T-Invest instrument cannot be represented as RUB per unit",
            )
        if malformed_message is not None:
            return DiscoverResult(
                status=QuoteStatus.MALFORMED_RESPONSE,
                message=malformed_message,
            )
        return DiscoverResult(status=QuoteStatus.UNAVAILABLE, message="no compatible candidates")

    def fetch_quote(self, identity: MarketIdentity, target_date: date) -> QuoteResult:
        if identity.provider != T_INVEST_PROVIDER:
            return QuoteFailure(
                status=QuoteStatus.UNSUPPORTED,
                message="provider is not t_invest",
                identity=identity,
            )
        if identity.provider_venue_id is not None:
            return QuoteFailure(
                status=QuoteStatus.UNSUPPORTED,
                message="t_invest identity must not include provider_venue_id",
                identity=identity,
            )
        try:
            uid = normalize_t_invest_uid(identity.provider_instrument_id)
        except ValueError:
            return QuoteFailure(
                status=QuoteStatus.MALFORMED_RESPONSE,
                message="t_invest provider_instrument_id must be an instrument_uid UUID",
                identity=identity,
            )
        try:
            return self._fetch_quote(uid, identity, target_date)
        except _AuthUnavailable as error:
            return QuoteFailure(
                status=QuoteStatus.UNAVAILABLE, message=error.message, identity=identity
            )
        except _NetworkFailure as error:
            return QuoteFailure(
                status=QuoteStatus.NETWORK_ERROR, message=error.message, identity=identity
            )
        except (_NotFound, _Unavailable) as error:
            message = (
                error.message
                if isinstance(error, _Unavailable)
                else "T-Invest instrument was not found"
            )
            return QuoteFailure(
                status=QuoteStatus.UNAVAILABLE,
                message=message,
                identity=identity,
            )
        except _Unsupported as error:
            return QuoteFailure(
                status=QuoteStatus.UNSUPPORTED, message=error.message, identity=identity
            )
        except NormalizeError as error:
            return QuoteFailure(status=error.status, message=error.message, identity=identity)
        except (_Malformed, QuotationError) as error:
            return QuoteFailure(
                status=QuoteStatus.MALFORMED_RESPONSE, message=str(error), identity=identity
            )

    def fetch_quotes(self, items: Sequence[tuple[MarketIdentity, date]]) -> list[QuoteResult]:
        return [self.fetch_quote(identity, target_date) for identity, target_date in items]

    def _fetch_quote(
        self, uid: str, identity: MarketIdentity, target_date: date
    ) -> QuoteSuccess | QuoteFailure:
        detail = self._instrument_by_uid(uid)
        kind = _map_kind(
            _text(detail, "instrumentKind", "instrument_kind"),
            _text(detail, "instrumentType", "instrument_type"),
        )
        if kind not in SUPPORTED_KINDS:
            raise _Unsupported("instrument kind is not supported in 0.4")
        _reject_non_exchange(detail)
        currency = _text(detail, "currency")
        face_value: Decimal | None = None
        basis = RawPriceBasis.CASH_PER_UNIT
        today = self._clock()
        if kind is InstrumentType.BOND:
            bond = self._bond_by_uid(uid)
            face_value, nominal_currency = _bond_nominal_for_target(
                bond,
                target_date=target_date,
                today=today,
            )
            _require_rub_currency(nominal_currency, message="bond nominal is not RUB-compatible")
            _require_rub_currency(
                _text(bond, "currency") or currency,
                message="bond quote is not RUB-compatible",
            )
            basis = RawPriceBasis.PERCENT_OF_FACE
        else:
            _require_rub_currency(currency, message="quote is not RUB-compatible")

        if target_date == today:
            last = self._exchange_last_price(uid)
            if last is not None:
                price, price_at = last
                price_date = moscow_calendar_date(price_at)
                if price_date <= target_date:
                    return self._success(
                        identity=identity,
                        kind=kind,
                        raw_price=price,
                        basis=basis,
                        face_value=face_value,
                        currency_unit="RUB",
                        price_date=price_date,
                        quote_kind=QuoteKind.LAST,
                        target_date=target_date,
                    )

        candle = self._latest_complete_daily_candle(uid, target_date)
        if candle is None:
            return QuoteFailure(
                status=QuoteStatus.UNAVAILABLE,
                message="no complete T-Invest candle within the lookback window",
                identity=identity,
            )
        close, candle_date = candle
        return self._success(
            identity=identity,
            kind=kind,
            raw_price=close,
            basis=basis,
            face_value=face_value,
            currency_unit="RUB",
            price_date=candle_date,
            quote_kind=QuoteKind.HISTORY,
            target_date=target_date,
        )

    def _success(
        self,
        *,
        identity: MarketIdentity,
        kind: InstrumentType,
        raw_price: Decimal,
        basis: RawPriceBasis,
        face_value: Decimal | None,
        currency_unit: str,
        price_date: date,
        quote_kind: QuoteKind,
        target_date: date,
    ) -> QuoteSuccess:
        freshness = classify_freshness(target_date, price_date)
        if freshness is QuoteStatus.UNAVAILABLE:
            raise _Unavailable("no complete T-Invest candle within the lookback window")
        kopecks = convert_to_kopecks(
            raw_price=raw_price,
            basis=basis,
            face_value=face_value,
            currency_unit=currency_unit,
            shares_schema_cash_default=False,
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

    def _exchange_last_price(self, uid: str) -> tuple[Decimal, datetime] | None:
        payload = self._post(
            _MARKET_DATA,
            _GET_LAST_PRICES,
            {"instrumentId": [uid], "lastPriceType": _LAST_PRICE_EXCHANGE},
        )
        rows = _field(payload, "lastPrices", "last_prices")
        if rows is None:
            return None
        if not isinstance(rows, list):
            raise _Malformed("GetLastPrices lastPrices is not a list")
        for row in rows:
            if not isinstance(row, dict):
                raise _Malformed("GetLastPrices row is not an object")
            row_uid = _text(row, "instrumentUid", "instrument_uid")
            if row_uid:
                try:
                    if normalize_t_invest_uid(row_uid) != uid:
                        continue
                except ValueError as error:
                    raise _Malformed("GetLastPrices instrumentUid is not a UUID") from error
            price_type = _text(row, "lastPriceType", "last_price_type")
            if price_type and price_type != _LAST_PRICE_EXCHANGE:
                continue
            price = _quotation_decimal(_field(row, "price"), name="last price")
            if price <= 0:
                raise _Malformed("last price is not a positive amount")
            stamped = _parse_timestamp(_field(row, "time"), name="last price time")
            return price, stamped
        return None

    def _latest_complete_daily_candle(
        self, uid: str, target_date: date
    ) -> tuple[Decimal, date] | None:
        start = target_date - timedelta(days=MAX_LOOKBACK_DAYS + 2)
        end = target_date + timedelta(days=2)
        payload = self._post(
            _MARKET_DATA,
            _GET_CANDLES,
            {
                "from": _rfc3339(datetime.combine(start, time.min, tzinfo=MOSCOW_TZ)),
                "to": _rfc3339(datetime.combine(end, time.min, tzinfo=MOSCOW_TZ)),
                "interval": _CANDLE_DAY,
                "instrumentId": uid,
                "candleSourceType": _CANDLE_EXCHANGE,
            },
        )
        rows = _field(payload, "candles")
        if rows is None:
            return None
        if not isinstance(rows, list):
            raise _Malformed("GetCandles candles is not a list")
        chosen: tuple[Decimal, date] | None = None
        for row in rows:
            if not isinstance(row, dict):
                raise _Malformed("GetCandles row is not an object")
            if _field(row, "isComplete", "is_complete") is not True:
                continue
            source = _text(row, "candleSourceType", "candle_source_type")
            if source and source != _CANDLE_EXCHANGE:
                continue
            stamped = _parse_timestamp(_field(row, "time"), name="candle time")
            candle_date = moscow_calendar_date(stamped)
            if candle_date > target_date:
                continue
            close = _quotation_decimal(_field(row, "close"), name="candle close")
            if close <= 0:
                raise _Malformed("candle close is not a positive amount")
            if chosen is None or candle_date > chosen[1]:
                chosen = (close, candle_date)
        return chosen

    def _instrument_by_uid(self, raw_uid: str) -> dict[str, object]:
        uid = normalize_t_invest_uid(raw_uid)
        cached = self._instrument_cache.get(uid)
        if cached is not None:
            return cached
        payload = self._post(
            _INSTRUMENTS,
            _GET_INSTRUMENT_BY,
            {"idType": _ID_TYPE_UID, "id": uid},
        )
        instrument = _field(payload, "instrument")
        body = _require_object(instrument, name="GetInstrumentBy instrument")
        resolved = _text(body, "uid")
        if resolved:
            try:
                if normalize_t_invest_uid(resolved) != uid:
                    raise _Malformed("GetInstrumentBy returned a different instrument_uid")
            except ValueError as error:
                raise _Malformed("GetInstrumentBy uid is not a UUID") from error
        self._instrument_cache[uid] = body
        return body

    def _bond_by_uid(self, uid: str) -> dict[str, object]:
        cached = self._bond_cache.get(uid)
        if cached is not None:
            return cached
        payload = self._post(
            _INSTRUMENTS,
            _BOND_BY,
            {"idType": _ID_TYPE_UID, "id": uid},
        )
        instrument = _field(payload, "instrument")
        body = _require_object(instrument, name="BondBy instrument")
        self._bond_cache[uid] = body
        return body

    def request_payout_method(self, method: str, body: dict[str, object]) -> dict[str, object]:
        """Developer-probe only. Not part of production quote routing."""

        if method not in PAYOUT_PROBE_METHODS:
            raise ValueError(f"payout probe does not allow InstrumentsService/{method}")
        return self._post(_INSTRUMENTS, method, body)

    def _find_instruments(
        self, query: str, *, instrument_kind: InstrumentType | None = None
    ) -> list[dict[str, object]]:
        body: dict[str, object] = {"query": query}
        if instrument_kind is not None:
            mapped = _KIND_TO_T_INVEST.get(instrument_kind)
            if mapped is not None:
                body["instrumentKind"] = mapped
        payload = self._post(_INSTRUMENTS, _FIND_INSTRUMENT, body)
        rows = _field(payload, "instruments")
        if rows is None:
            return []
        if not isinstance(rows, list):
            raise _Malformed("FindInstrument instruments is not a list")
        found: list[dict[str, object]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise _Malformed("FindInstrument row is not an object")
            if instrument_kind is not None:
                row_kind = _map_kind(
                    _text(row, "instrumentKind", "instrument_kind"),
                    _text(row, "instrumentType", "instrument_type"),
                )
                if row_kind is not None and row_kind is not instrument_kind:
                    continue
            found.append(row)
            if len(found) >= self._max_discovery:
                break
        return found

    def _post(self, service: str, method: str, body: dict[str, object]) -> dict[str, object]:
        if self._token is None:
            raise _AuthUnavailable()
        path = f"/tinkoff.public.invest.api.contract.v1.{service}/{method}"
        try:
            response = self._http.post(
                path,
                json=body,
                headers={"Authorization": f"Bearer {self._token}"},
            )
        except httpx2.TimeoutException as error:
            raise _NetworkFailure("T-Invest request timed out") from error
        except httpx2.TransportError as error:
            raise _NetworkFailure("T-Invest network error") from error
        status = response.status_code
        if status in {401, 403}:
            raise _AuthUnavailable()
        if status == 404:
            if method in {_GET_LAST_PRICES, _GET_CANDLES, _FIND_INSTRUMENT}:
                return {}
            raise _NotFound()
        if status in {408, 429} or status >= 500:
            raise _NetworkFailure("T-Invest network error")
        try:
            payload = response.json()
        except ValueError as error:
            raise _Malformed("T-Invest response is not JSON") from error
        if status >= 400:
            if _looks_like_auth_error(payload):
                raise _AuthUnavailable()
            if status == 400 and _looks_like_not_found(payload):
                raise _NotFound()
            raise _Malformed("T-Invest returned an unexpected error response")
        if not isinstance(payload, dict):
            raise _Malformed("T-Invest response is not an object")
        if _looks_like_auth_error(payload):
            raise _AuthUnavailable()
        return payload


@dataclass(frozen=True, slots=True)
class _CandidateDisplay:
    name: str | None
    ticker: str | None
    class_code: str | None
    exchange: str | None
    api_trade_available: bool | None
    position_uid: str | None


def _first_optional_bool(primary: object, secondary: object, *names: str) -> bool | None:
    first = _optional_bool(primary, *names)
    if first is not None:
        return first
    return _optional_bool(secondary, *names)


def _optional_bool(payload: object, *names: str) -> bool | None:
    value = _field(payload, *names)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return None


def _display_exchange(raw: str | None) -> str | None:
    if raw is None:
        return None
    prefix = "REAL_EXCHANGE_"
    if raw.upper().startswith(prefix):
        cleaned = raw[len(prefix) :].replace("_", " ").strip()
        return cleaned or None
    return raw


def _candidate_display(short: dict[str, object], detail: dict[str, object]) -> _CandidateDisplay:
    return _CandidateDisplay(
        name=_text(detail, "name") or _text(short, "name"),
        ticker=_text(detail, "ticker") or _text(short, "ticker"),
        class_code=_text(detail, "classCode", "class_code")
        or _text(short, "classCode", "class_code"),
        exchange=_display_exchange(
            _text(detail, "realExchange", "real_exchange")
            or _text(short, "realExchange", "real_exchange")
        ),
        api_trade_available=_first_optional_bool(
            detail,
            short,
            "apiTradeAvailableFlag",
            "api_trade_available_flag",
        ),
        position_uid=_text(detail, "positionUid", "position_uid")
        or _text(short, "positionUid", "position_uid"),
    )


def _require_uid(payload: dict[str, object]) -> str:
    uid = _text(payload, "uid", "instrumentUid", "instrument_uid")
    if uid is None:
        raise _Malformed("instrument_uid is missing")
    return uid


def _rfc3339(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _looks_like_auth_error(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    code = str(_field(payload, "code", "errorCode", "error_code") or "")
    message = str(_field(payload, "message", "error") or "").lower()
    if code in {"40003", "UNAUTHENTICATED", "PERMISSION_DENIED", "16"}:
        return True
    return "unauthenticated" in message or "token" in message and "invalid" in message


def _looks_like_not_found(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    message = str(_field(payload, "message", "error") or "").lower()
    return "not found" in message or "does not exist" in message
