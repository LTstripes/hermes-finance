"""Deterministic T-Invest payout adapter for the provider-neutral R05 boundary."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Final

from hermes_finance.domain import InstrumentType
from hermes_finance.market_data.dto import T_INVEST_PROVIDER, DiscoverResult, QuoteStatus
from hermes_finance.market_data.moscow import MOSCOW_TZ
from hermes_finance.market_data.payout import (
    PayoutCoverage,
    PayoutDomainError,
    PayoutEvent,
    PayoutEventKind,
    PayoutEventStatus,
    normalize_currency,
    normalize_payout_date,
    resolve_coupon_identity,
    resolve_dividend_identity,
    resolve_redemption_identity,
)
from hermes_finance.market_data.payout_protocol import (
    PayoutFailure,
    PayoutFetchRequest,
    PayoutFetchResult,
)
from hermes_finance.market_data.quotation import QuotationError, quotation_to_decimal
from hermes_finance.market_data.t_invest import (
    TInvestClient,
    _AuthUnavailable,
    _Malformed,
    _NetworkFailure,
    _NotFound,
    normalize_t_invest_uid,
)

_GET_BOND_COUPONS: Final = "GetBondCoupons"
_GET_BOND_EVENTS: Final = "GetBondEvents"
_GET_DIVIDENDS: Final = "GetDividends"
_EVENT_TYPE_MTY: Final = "EVENT_TYPE_MTY"
_COUPON_FILTER_BASIS: Final = "coupon_date"
_DIVIDEND_FILTER_BASIS: Final = "record_date"
_REDEMPTION_FILTER_BASIS: Final = "event_date"

# Deliberate bounded over-fetch. This is a retrieval margin, not a record->payment rule.
DEFAULT_DIVIDEND_RECORD_MARGIN_DAYS: Final = 60


class _RowMalformed(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _MethodWindow:
    method: str
    event_kind: PayoutEventKind
    start: date
    end: date
    filter_basis: str
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class _BondFlags:
    known: bool = True
    floating_coupon: bool = False
    amortizing: bool = False
    perpetual: bool = False


@dataclass(frozen=True, slots=True)
class _CouponPrepared:
    row: dict[str, object]
    payment_date: date | None
    period_start: date | None
    period_end: date | None


@dataclass(frozen=True, slots=True)
class _DividendPrepared:
    row: dict[str, object]
    payment_date: date | None
    record_date: date | None


@dataclass(frozen=True, slots=True)
class _RedemptionPrepared:
    row: dict[str, object]
    payment_date: date | None
    event_date: date | None


class TInvestPayoutProvider:
    """Owner-triggered read-only T-Invest payout provider.

    It performs no account/portfolio discovery, no trading calls, no background
    work and no synthetic payout generation.
    """

    def __init__(
        self,
        client: TInvestClient,
        *,
        dividend_record_margin_days: int = DEFAULT_DIVIDEND_RECORD_MARGIN_DAYS,
    ) -> None:
        if (
            isinstance(dividend_record_margin_days, bool)
            or not isinstance(dividend_record_margin_days, int)
            or dividend_record_margin_days < 0
        ):
            raise ValueError("dividend_record_margin_days must be a non-negative integer")
        self._client = client
        self._dividend_record_margin_days = dividend_record_margin_days

    def fetch_payouts(self, request: PayoutFetchRequest) -> PayoutFetchResult:
        try:
            uid = normalize_t_invest_uid(request.instrument_uid)
        except ValueError:
            return PayoutFetchResult(
                provider=T_INVEST_PROVIDER,
                instrument_uid=request.instrument_uid,
                failures=(
                    PayoutFailure(
                        PayoutEventStatus.ERROR,
                        "T-Invest payout instrument_uid is not a UUID",
                    ),
                ),
            )

        discovered = self._client.discover_candidates(provider_instrument_id=uid)
        kind, discovery_failure = _resolve_discovered_kind(discovered)
        if discovery_failure is not None:
            return PayoutFetchResult(
                provider=T_INVEST_PROVIDER,
                instrument_uid=uid,
                failures=(discovery_failure,),
            )

        reference_failure: PayoutFailure | None = None
        bond_flags: _BondFlags | None = None
        if kind is InstrumentType.BOND:
            bond_flags, reference_failure = self._bond_flags(uid)
            windows = (
                self._coupon_window(uid, request),
                self._redemption_window(uid, request),
            )
        elif kind in {InstrumentType.STOCK, InstrumentType.FUND}:
            windows = (self._dividend_window(uid, request),)
        else:
            return PayoutFetchResult(
                provider=T_INVEST_PROVIDER,
                instrument_uid=uid,
                failures=(
                    PayoutFailure(
                        PayoutEventStatus.UNSUPPORTED,
                        "T-Invest instrument kind does not support payout retrieval",
                    ),
                ),
            )

        events: list[PayoutEvent] = []
        coverage: list[PayoutCoverage] = []
        failures: list[PayoutFailure] = []
        if reference_failure is not None:
            failures.append(reference_failure)
        for window in windows:
            method_events, method_coverage, method_failures = self._fetch_method(
                uid=uid,
                request=request,
                window=window,
                bond_flags=bond_flags,
            )
            events.extend(method_events)
            coverage.append(method_coverage)
            failures.extend(method_failures)

        return PayoutFetchResult(
            provider=T_INVEST_PROVIDER,
            instrument_uid=uid,
            events=tuple(events),
            coverage=tuple(coverage),
            failures=tuple(failures),
        )

    def _bond_flags(self, uid: str) -> tuple[_BondFlags, PayoutFailure | None]:
        # Exact-UID discovery already uses BondBy. On TInvestClient this is a cache read
        # after successful discovery, and remains inside the accepted reference surface.
        try:
            bond = self._client._bond_by_uid(uid)
        except _AuthUnavailable:
            return _BondFlags(known=False), PayoutFailure(
                PayoutEventStatus.UNAVAILABLE,
                "T-Invest bond reference is unavailable",
                method="BondBy",
            )
        except _NetworkFailure:
            return _BondFlags(known=False), PayoutFailure(
                PayoutEventStatus.ERROR,
                "T-Invest bond reference failed due to a network error",
                method="BondBy",
            )
        except (_NotFound, _Malformed):
            return _BondFlags(known=False), PayoutFailure(
                PayoutEventStatus.ERROR,
                "T-Invest bond reference is invalid",
                method="BondBy",
            )
        return (
            _BondFlags(
                floating_coupon=_truthy_flag(
                    _field(bond, "floatingCouponFlag", "floating_coupon_flag")
                ),
                amortizing=_truthy_flag(_field(bond, "amortizationFlag", "amortization_flag")),
                perpetual=_truthy_flag(_field(bond, "perpetualFlag", "perpetual_flag")),
            ),
            None,
        )

    def _coupon_window(self, uid: str, request: PayoutFetchRequest) -> _MethodWindow:
        start = request.calendar_from
        end = request.calendar_to
        return _MethodWindow(
            method=_GET_BOND_COUPONS,
            event_kind=PayoutEventKind.COUPON,
            start=start,
            end=end,
            filter_basis=_COUPON_FILTER_BASIS,
            body={"instrumentId": uid, **_provider_window(start, end)},
        )

    def _redemption_window(self, uid: str, request: PayoutFetchRequest) -> _MethodWindow:
        start = request.calendar_from
        end = request.calendar_to
        return _MethodWindow(
            method=_GET_BOND_EVENTS,
            event_kind=PayoutEventKind.REDEMPTION,
            start=start,
            end=end,
            filter_basis=_REDEMPTION_FILTER_BASIS,
            body={
                "instrumentId": uid,
                "type": _EVENT_TYPE_MTY,
                **_provider_window(start, end),
            },
        )

    def _dividend_window(self, uid: str, request: PayoutFetchRequest) -> _MethodWindow:
        margin = timedelta(days=self._dividend_record_margin_days)
        start = request.calendar_from - margin
        end = request.calendar_to + margin
        return _MethodWindow(
            method=_GET_DIVIDENDS,
            event_kind=PayoutEventKind.DIVIDEND,
            start=start,
            end=end,
            filter_basis=_DIVIDEND_FILTER_BASIS,
            body={"instrumentId": uid, **_provider_window(start, end)},
        )

    def _fetch_method(
        self,
        *,
        uid: str,
        request: PayoutFetchRequest,
        window: _MethodWindow,
        bond_flags: _BondFlags | None,
    ) -> tuple[list[PayoutEvent], PayoutCoverage, list[PayoutFailure]]:
        try:
            payload = self._client.request_payout_method(window.method, window.body)
        except _AuthUnavailable:
            return (
                [],
                _coverage(uid, window, successful=False, structurally_valid=False),
                [
                    PayoutFailure(
                        PayoutEventStatus.UNAVAILABLE,
                        "T-Invest read-only token is unavailable",
                        method=window.method,
                    )
                ],
            )
        except _NetworkFailure:
            return (
                [],
                _coverage(uid, window, successful=False, structurally_valid=False),
                [
                    PayoutFailure(
                        PayoutEventStatus.ERROR,
                        "T-Invest payout request failed due to a network error",
                        method=window.method,
                    )
                ],
            )
        except _NotFound:
            return (
                [],
                _coverage(uid, window, successful=False, structurally_valid=False),
                [
                    PayoutFailure(
                        PayoutEventStatus.UNAVAILABLE,
                        "T-Invest payout instrument or method result was not found",
                        method=window.method,
                    )
                ],
            )
        except (_Malformed, ValueError):
            return (
                [],
                _coverage(uid, window, successful=False, structurally_valid=False),
                [
                    PayoutFailure(
                        PayoutEventStatus.ERROR,
                        "T-Invest payout request returned an invalid response",
                        method=window.method,
                    )
                ],
            )

        if not isinstance(payload, dict):
            return (
                [],
                _coverage(uid, window, successful=True, structurally_valid=False),
                [
                    PayoutFailure(
                        PayoutEventStatus.ERROR,
                        "T-Invest payout response is not an object",
                        method=window.method,
                    )
                ],
            )

        rows_name = "dividends" if window.method == _GET_DIVIDENDS else "events"
        rows = _field(payload, rows_name)
        if not isinstance(rows, list):
            return (
                [],
                _coverage(uid, window, successful=True, structurally_valid=False),
                [
                    PayoutFailure(
                        PayoutEventStatus.ERROR,
                        f"T-Invest {window.method} {rows_name} is not a list",
                        method=window.method,
                    )
                ],
            )

        if window.method == _GET_BOND_COUPONS:
            conservative = bond_flags is None or not bond_flags.known or bond_flags.floating_coupon
            parsed, failures = _parse_coupons(uid, rows, force_tentative=conservative)
        elif window.method == _GET_DIVIDENDS:
            parsed, failures = _parse_dividends(uid, rows)
        else:
            conservative = (
                bond_flags is None
                or not bond_flags.known
                or bond_flags.amortizing
                or bond_flags.perpetual
            )
            parsed, failures = _parse_redemptions(uid, rows, force_tentative=conservative)

        if not failures and any(event.provider_filter_date is None for event in parsed):
            failures.append(
                PayoutFailure(
                    PayoutEventStatus.ERROR,
                    f"T-Invest {window.method} row is missing provider filter date",
                    method=window.method,
                )
            )
        structurally_valid = not failures
        filtered = [
            event
            for event in parsed
            if _event_belongs_to_calendar(event, request, window.event_kind)
        ]
        return (
            filtered,
            _coverage(
                uid,
                window,
                successful=True,
                structurally_valid=structurally_valid,
            ),
            failures,
        )


def _resolve_discovered_kind(
    result: DiscoverResult,
) -> tuple[InstrumentType | None, PayoutFailure | None]:
    if result.status is QuoteStatus.OK and len(result.candidates) == 1:
        return result.candidates[0].instrument_kind, None
    if result.status is QuoteStatus.UNSUPPORTED:
        status = PayoutEventStatus.UNSUPPORTED
    elif result.status in {QuoteStatus.UNAVAILABLE, QuoteStatus.UNMAPPED, QuoteStatus.EXCLUDED}:
        status = PayoutEventStatus.UNAVAILABLE
    else:
        status = PayoutEventStatus.ERROR
    return None, PayoutFailure(
        status,
        "T-Invest payout instrument could not be resolved safely",
    )


def _coverage(
    uid: str,
    window: _MethodWindow,
    *,
    successful: bool,
    structurally_valid: bool,
) -> PayoutCoverage:
    return PayoutCoverage(
        provider=T_INVEST_PROVIDER,
        method=window.method,
        instrument_uid=uid,
        event_kind=window.event_kind,
        requested_from=window.start,
        requested_to=window.end,
        provider_filter_basis=window.filter_basis,
        successful=successful,
        structurally_valid=structurally_valid,
    )


def _parse_coupons(
    uid: str,
    rows: list[object],
    *,
    force_tentative: bool,
) -> tuple[list[PayoutEvent], list[PayoutFailure]]:
    prepared: list[_CouponPrepared | None] = []
    failures: list[PayoutFailure] = []
    period_counts: Counter[tuple[date, date]] = Counter()

    for row in rows:
        try:
            body = _row_object(row, method=_GET_BOND_COUPONS)
            payment = _optional_provider_date(_field(body, "couponDate", "coupon_date"))
            start = _optional_provider_date(_field(body, "couponStartDate", "coupon_start_date"))
            end = _optional_provider_date(_field(body, "couponEndDate", "coupon_end_date"))
            if start is not None and end is not None:
                period_counts[(start, end)] += 1
            prepared.append(_CouponPrepared(body, payment, start, end))
        except _RowMalformed:
            prepared.append(None)
            failures.append(_row_failure(_GET_BOND_COUPONS, "coupon row is malformed"))

    events: list[PayoutEvent] = []
    for item in prepared:
        if item is None:
            continue
        try:
            identity = resolve_coupon_identity(
                coupon_number=_field(item.row, "couponNumber", "coupon_number"),
                coupon_start_date=item.period_start,
                coupon_end_date=item.period_end,
                period_is_unique=(
                    item.period_start is not None
                    and item.period_end is not None
                    and period_counts[(item.period_start, item.period_end)] == 1
                ),
            )
            amount, currency, amount_tentative = _optional_money(
                _field(item.row, "payOneBond", "pay_one_bond")
            )
            status = _event_status(
                identity_status=identity.status,
                payment_date=item.payment_date,
                amount=amount,
                currency=currency,
                extra_tentative=amount_tentative or force_tentative,
            )
            events.append(
                PayoutEvent(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=uid,
                    event_kind=PayoutEventKind.COUPON,
                    identity_key=(
                        identity.identity_key
                        if status is not PayoutEventStatus.AMBIGUOUS_IDENTITY
                        else None
                    ),
                    status=status,
                    payment_date=item.payment_date,
                    per_unit_amount=amount,
                    currency=currency,
                    source_method=_GET_BOND_COUPONS,
                    provider_filter_basis=(
                        _COUPON_FILTER_BASIS if item.payment_date is not None else None
                    ),
                    provider_filter_date=item.payment_date,
                    provider_status=None,
                )
            )
        except (PayoutDomainError, _RowMalformed):
            failures.append(_row_failure(_GET_BOND_COUPONS, "coupon row is malformed"))

    return _mark_identity_collisions(events), failures


def _parse_dividends(
    uid: str,
    rows: list[object],
) -> tuple[list[PayoutEvent], list[PayoutFailure]]:
    prepared: list[_DividendPrepared | None] = []
    failures: list[PayoutFailure] = []
    record_counts: Counter[date] = Counter()

    for row in rows:
        try:
            body = _row_object(row, method=_GET_DIVIDENDS)
            payment = _optional_provider_date(_field(body, "paymentDate", "payment_date"))
            record = _optional_provider_date(_field(body, "recordDate", "record_date"))
            if record is not None:
                record_counts[record] += 1
            prepared.append(_DividendPrepared(body, payment, record))
        except _RowMalformed:
            prepared.append(None)
            failures.append(_row_failure(_GET_DIVIDENDS, "dividend row is malformed"))

    events: list[PayoutEvent] = []
    for item in prepared:
        if item is None:
            continue
        try:
            identity = resolve_dividend_identity(
                stable_provider_event_id=None,
                record_date=item.record_date,
                record_date_is_unique=(
                    item.record_date is not None and record_counts[item.record_date] == 1
                ),
            )
            amount, currency, amount_tentative = _optional_money(
                _field(item.row, "dividendNet", "dividend_net")
            )
            dividend_type = _clean_text(_field(item.row, "dividendType", "dividend_type"))
            lifecycle_unresolved = (
                dividend_type is not None and dividend_type.casefold() == "cancelled"
            )
            status = _event_status(
                identity_status=identity.status,
                payment_date=item.payment_date,
                amount=amount,
                currency=currency,
                extra_tentative=amount_tentative or lifecycle_unresolved,
            )
            events.append(
                PayoutEvent(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=uid,
                    event_kind=PayoutEventKind.DIVIDEND,
                    identity_key=(
                        identity.identity_key
                        if status is not PayoutEventStatus.AMBIGUOUS_IDENTITY
                        else None
                    ),
                    status=status,
                    payment_date=item.payment_date,
                    per_unit_amount=amount,
                    currency=currency,
                    source_method=_GET_DIVIDENDS,
                    provider_filter_basis=(
                        _DIVIDEND_FILTER_BASIS if item.record_date is not None else None
                    ),
                    provider_filter_date=item.record_date,
                    provider_status=dividend_type,
                )
            )
        except (PayoutDomainError, _RowMalformed):
            failures.append(_row_failure(_GET_DIVIDENDS, "dividend row is malformed"))

    return _mark_identity_collisions(events), failures


def _parse_redemptions(
    uid: str,
    rows: list[object],
    *,
    force_tentative: bool,
) -> tuple[list[PayoutEvent], list[PayoutFailure]]:
    prepared: list[_RedemptionPrepared | None] = []
    failures: list[PayoutFailure] = []
    event_date_counts: Counter[date] = Counter()

    for row in rows:
        try:
            body = _row_object(row, method=_GET_BOND_EVENTS)
            event_type = _clean_text(_field(body, "eventType", "event_type"))
            if event_type != _EVENT_TYPE_MTY:
                raise _RowMalformed("GetBondEvents returned a non-MTY row")
            event_date = _optional_provider_date(_field(body, "eventDate", "event_date"))
            pay_date = _optional_provider_date(_field(body, "payDate", "pay_date"))
            if event_date is not None:
                event_date_counts[event_date] += 1
            prepared.append(_RedemptionPrepared(body, pay_date, event_date))
        except _RowMalformed:
            prepared.append(None)
            failures.append(_row_failure(_GET_BOND_EVENTS, "redemption row is malformed"))

    multiple_mty_unresolved = sum(item is not None for item in prepared) > 1
    events: list[PayoutEvent] = []
    for item in prepared:
        if item is None:
            continue
        try:
            identity = resolve_redemption_identity(
                event_number=_field(item.row, "eventNumber", "event_number"),
                event_date=item.event_date,
                event_date_is_unique=(
                    item.event_date is not None and event_date_counts[item.event_date] == 1
                ),
            )
            amount, currency, amount_tentative = _optional_money(
                _field(item.row, "payOneBond", "pay_one_bond")
            )
            status = _event_status(
                identity_status=identity.status,
                payment_date=item.payment_date,
                amount=amount,
                currency=currency,
                extra_tentative=(amount_tentative or force_tentative or multiple_mty_unresolved),
            )
            events.append(
                PayoutEvent(
                    provider=T_INVEST_PROVIDER,
                    instrument_uid=uid,
                    event_kind=PayoutEventKind.REDEMPTION,
                    identity_key=(
                        identity.identity_key
                        if status is not PayoutEventStatus.AMBIGUOUS_IDENTITY
                        else None
                    ),
                    status=status,
                    payment_date=item.payment_date,
                    per_unit_amount=amount,
                    currency=currency,
                    source_method=_GET_BOND_EVENTS,
                    provider_filter_basis=(
                        _REDEMPTION_FILTER_BASIS if item.event_date is not None else None
                    ),
                    provider_filter_date=item.event_date,
                    provider_status=_bond_event_status(item.row),
                )
            )
        except (PayoutDomainError, _RowMalformed):
            failures.append(_row_failure(_GET_BOND_EVENTS, "redemption row is malformed"))

    return _mark_identity_collisions(events), failures


def _event_status(
    *,
    identity_status: PayoutEventStatus,
    payment_date: date | None,
    amount: Decimal | None,
    currency: str | None,
    extra_tentative: bool,
) -> PayoutEventStatus:
    if currency is not None and currency != "RUB":
        return PayoutEventStatus.UNSUPPORTED
    if identity_status is PayoutEventStatus.AMBIGUOUS_IDENTITY:
        return PayoutEventStatus.AMBIGUOUS_IDENTITY
    if payment_date is None or amount is None or amount <= 0 or extra_tentative:
        return PayoutEventStatus.TENTATIVE
    return PayoutEventStatus.OK


def _optional_money(value: object) -> tuple[Decimal | None, str | None, bool]:
    if value is None:
        return None, None, True
    if not isinstance(value, dict):
        raise _RowMalformed("MoneyValue is not an object")
    currency_raw = _clean_text(_field(value, "currency"))
    if currency_raw is None:
        raise _RowMalformed("MoneyValue currency is missing")
    try:
        amount = quotation_to_decimal(
            units=_field(value, "units"),
            nano=_field(value, "nano"),
        )
    except QuotationError as error:
        raise _RowMalformed("MoneyValue is malformed") from error
    if amount < 0:
        raise _RowMalformed("MoneyValue amount is negative")
    currency = normalize_currency(currency_raw)
    return amount, currency, amount == 0


def _mark_identity_collisions(events: list[PayoutEvent]) -> list[PayoutEvent]:
    counts = Counter(
        (event.event_kind, event.identity_key) for event in events if event.identity_key is not None
    )
    result: list[PayoutEvent] = []
    for event in events:
        if (
            event.status is not PayoutEventStatus.UNSUPPORTED
            and event.identity_key is not None
            and counts[(event.event_kind, event.identity_key)] > 1
        ):
            result.append(
                replace(
                    event,
                    identity_key=None,
                    status=PayoutEventStatus.AMBIGUOUS_IDENTITY,
                )
            )
        else:
            result.append(event)
    return result


def _event_belongs_to_calendar(
    event: PayoutEvent,
    request: PayoutFetchRequest,
    kind: PayoutEventKind,
) -> bool:
    if event.payment_date is not None:
        return request.calendar_from <= event.payment_date <= request.calendar_to
    if kind is PayoutEventKind.DIVIDEND and event.provider_filter_date is not None:
        # A missing payment date cannot be placed on the calendar. Keep it only when
        # its provider comparison key is itself inside the requested owner horizon.
        return request.calendar_from <= event.provider_filter_date <= request.calendar_to
    # Coupons/MTY were requested with exact owner bounds, so a returned row with no
    # payout date remains relevant as a tentative provider row.
    return True


def _provider_window(start: date, end: date) -> dict[str, str]:
    return {
        "from": _rfc3339(datetime.combine(start, time.min, tzinfo=MOSCOW_TZ)),
        "to": _rfc3339(datetime.combine(end, time.min, tzinfo=MOSCOW_TZ)),
    }


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_provider_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return normalize_payout_date(value)
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise _RowMalformed("provider date is not a timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise _RowMalformed("provider date is not a timestamp") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return normalize_payout_date(parsed)


def _row_object(value: object, *, method: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _RowMalformed(f"{method} row is not an object")
    return value


def _field(payload: object, *names: str) -> object:
    if not isinstance(payload, dict):
        return None
    for name in names:
        if name in payload:
            return payload[name]
    lookup = {str(key).lower(): value for key, value in payload.items()}
    for name in names:
        lowered = name.lower()
        if lowered in lookup:
            return lookup[lowered]
    return None


def _clean_text(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _truthy_flag(value: object) -> bool:
    return value is True or value == 1 or str(value).lower() == "true"


def _bond_event_status(row: dict[str, object]) -> str | None:
    execution = _clean_text(_field(row, "execution"))
    operation = _clean_text(_field(row, "operationType", "operation_type"))
    parts = []
    if execution is not None:
        parts.append(f"execution={execution}")
    if operation is not None:
        parts.append(f"operation_type={operation}")
    return ";".join(parts) or None


def _row_failure(method: str, message: str) -> PayoutFailure:
    return PayoutFailure(PayoutEventStatus.ERROR, message, method=method)
