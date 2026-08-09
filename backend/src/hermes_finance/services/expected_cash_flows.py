from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from hermes_finance.domain import ExpectedCashFlowType, RubleAmount
from hermes_finance.persistence import Account, ExpectedCashFlow, Instrument, ReportingMonth
from hermes_finance.services._guard import (
    require_editable_child_month,
    require_editable_reporting_month,
)
from hermes_finance.services.accounts import AccountNotFoundError
from hermes_finance.services.instruments import InstrumentNotFoundError
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class ExpectedCashFlowNotFoundError(LookupError):
    pass


def _require_reporting_month(session: Session, month_id: int) -> ReportingMonth:
    month = session.get(ReportingMonth, month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {month_id} was not found")
    return month


def _require_account(session: Session, account_id: int) -> None:
    if session.get(Account, account_id) is None:
        raise AccountNotFoundError(f"account {account_id} was not found")


def _require_instrument(session: Session, instrument_id: int) -> None:
    if session.get(Instrument, instrument_id) is None:
        raise InstrumentNotFoundError(f"instrument {instrument_id} was not found")


def _normalize_text(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if not normalized:
        raise ValueError("currency must not be empty")
    return normalized


def _normalize_nonnegative_amount(amount: RubleAmount | str, *, field: str) -> int:
    if isinstance(amount, str):
        amount = RubleAmount.from_api(amount)
    if not isinstance(amount, RubleAmount):
        raise TypeError(f"{field} must be RubleAmount or decimal string")
    if amount.kopecks < 0:
        raise ValueError(f"{field} must not be negative")
    return amount.kopecks


def _coerce_flow_type(flow_type: ExpectedCashFlowType | str) -> ExpectedCashFlowType:
    try:
        return ExpectedCashFlowType(flow_type)
    except ValueError as error:
        raise ValueError(f"unsupported expected cash flow type: {flow_type!r}") from error


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, month=2, day=28)


def _validate_or_derive_net(
    *,
    gross_amount_kopecks: int,
    expected_tax_amount_kopecks: int | None,
    expected_net_amount: RubleAmount | str | None,
) -> tuple[int, bool]:
    if expected_tax_amount_kopecks is None:
        if expected_net_amount is not None:
            net = _normalize_nonnegative_amount(expected_net_amount, field="expected_net_amount")
            if net != gross_amount_kopecks:
                raise ValueError("expected_net_amount must equal gross_amount when tax is unknown")
        return gross_amount_kopecks, True
    expected_net = gross_amount_kopecks - expected_tax_amount_kopecks
    if expected_net_amount is not None:
        net = _normalize_nonnegative_amount(expected_net_amount, field="expected_net_amount")
        if net != expected_net:
            raise ValueError(
                "expected_net_amount must equal gross_amount minus expected_tax_amount"
            )
    return expected_net, False


def _validate_forecast_version_as_of_date(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
    source_as_of_date: date,
) -> None:
    existing_as_of_date = session.scalar(
        select(ExpectedCashFlow.source_as_of_date)
        .where(
            ExpectedCashFlow.reporting_month_id == reporting_month_id,
            ExpectedCashFlow.forecast_version == forecast_version,
        )
        .limit(1)
    )
    if existing_as_of_date is not None and existing_as_of_date != source_as_of_date:
        raise ValueError("forecast_version must use one source_as_of_date per reporting month")


def list_expected_cash_flows(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
    from_date: date | None = None,
) -> list[ExpectedCashFlow]:
    month = _require_reporting_month(session, reporting_month_id)
    start = from_date or month.snapshot_date
    end_exclusive = _one_year_after(start)
    return list(
        session.scalars(
            select(ExpectedCashFlow)
            .where(
                ExpectedCashFlow.reporting_month_id == reporting_month_id,
                ExpectedCashFlow.forecast_version
                == _normalize_text(forecast_version, field="forecast_version"),
                ExpectedCashFlow.expected_date >= start,
                ExpectedCashFlow.expected_date < end_exclusive,
            )
            .order_by(ExpectedCashFlow.expected_date, ExpectedCashFlow.id)
        )
    )


def list_expected_passive_income_cash_flows(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
    from_date: date | None = None,
) -> list[ExpectedCashFlow]:
    flows = list_expected_cash_flows(
        session,
        reporting_month_id=reporting_month_id,
        forecast_version=forecast_version,
        from_date=from_date,
    )
    return [flow for flow in flows if ExpectedCashFlowType(flow.flow_type).counts_as_passive_income]


def get_expected_cash_flow(session: Session, flow_id: int) -> ExpectedCashFlow:
    flow = session.get(ExpectedCashFlow, flow_id)
    if flow is None:
        raise ExpectedCashFlowNotFoundError(f"expected cash flow {flow_id} was not found")
    return flow


@dataclass(frozen=True, slots=True)
class CalendarItem:
    """One expected flow inside a calendar month (E16)."""

    id: int
    expected_date: date
    flow_type: str
    account_name: str
    instrument_name: str | None
    expected_net_amount: RubleAmount
    is_confirmed: bool
    is_approximate: bool
    source: str


@dataclass(frozen=True, slots=True)
class CalendarMonth:
    """Aggregated expected payouts for one calendar month (E16)."""

    year: int
    month: int
    coupon: RubleAmount
    dividend: RubleAmount
    interest: RubleAmount
    redemption: RubleAmount
    other: RubleAmount
    passive_net: RubleAmount
    total_net: RubleAmount
    items: tuple[CalendarItem, ...]


def calendar_expected_cash_flows(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
    from_date: date | None = None,
) -> tuple[CalendarMonth, ...]:
    """Group expected payouts by calendar month over the 12-month horizon.

    Per-month totals are split by flow type. ``passive_net`` sums only the
    income types (coupon/dividend/interest/other — anything but redemption);
    redemption is displayed with its own marker and never counts as passive
    income (MASTER_SPEC §10.10 / WIKI p.12).
    """
    month = _require_reporting_month(session, reporting_month_id)
    start = from_date or month.snapshot_date
    end_exclusive = _one_year_after(start)
    version = _normalize_text(forecast_version, field="forecast_version")

    rows = session.execute(
        select(ExpectedCashFlow, Account.name, Instrument.name)
        .join(Account, ExpectedCashFlow.account_id == Account.id)
        .outerjoin(Instrument, ExpectedCashFlow.instrument_id == Instrument.id)
        .where(
            ExpectedCashFlow.reporting_month_id == reporting_month_id,
            ExpectedCashFlow.forecast_version == version,
            ExpectedCashFlow.expected_date >= start,
            ExpectedCashFlow.expected_date < end_exclusive,
        )
        .order_by(ExpectedCashFlow.expected_date, ExpectedCashFlow.id)
    ).all()

    buckets: dict[tuple[int, int], dict[str, object]] = {}
    for flow, account_name, instrument_name in rows:
        key = (flow.expected_date.year, flow.expected_date.month)
        bucket = buckets.setdefault(
            key,
            {
                "coupon": 0,
                "dividend": 0,
                "interest": 0,
                "redemption": 0,
                "other": 0,
                "items": [],
            },
        )
        flow_type = ExpectedCashFlowType(flow.flow_type).value
        bucket[flow_type] = int(bucket[flow_type]) + flow.expected_net_amount_kopecks  # type: ignore[operator]
        bucket["items"].append(  # type: ignore[union-attr]
            CalendarItem(
                id=flow.id,
                expected_date=flow.expected_date,
                flow_type=flow.flow_type,
                account_name=account_name,
                instrument_name=instrument_name,
                expected_net_amount=RubleAmount(flow.expected_net_amount_kopecks),
                is_confirmed=flow.is_confirmed,
                is_approximate=flow.is_approximate,
                source=flow.source,
            )
        )

    def build(key: tuple[int, int], bucket: dict[str, object]) -> CalendarMonth:
        coupon = int(bucket["coupon"])
        dividend = int(bucket["dividend"])
        interest = int(bucket["interest"])
        redemption = int(bucket["redemption"])
        other = int(bucket["other"])
        passive = coupon + dividend + interest + other
        total = passive + redemption
        return CalendarMonth(
            year=key[0],
            month=key[1],
            coupon=RubleAmount(coupon),
            dividend=RubleAmount(dividend),
            interest=RubleAmount(interest),
            redemption=RubleAmount(redemption),
            other=RubleAmount(other),
            passive_net=RubleAmount(passive),
            total_net=RubleAmount(total),
            items=tuple(bucket["items"]),  # type: ignore[arg-type]
        )

    return tuple(build(key, bucket) for key, bucket in sorted(buckets.items()))


def create_expected_cash_flow(
    session: Session,
    *,
    reporting_month_id: int,
    account_id: int,
    instrument_id: int,
    flow_type: ExpectedCashFlowType | str,
    expected_date: date,
    gross_amount: RubleAmount | str,
    expected_tax_amount: RubleAmount | str | None = None,
    expected_net_amount: RubleAmount | str | None = None,
    currency: str = "RUB",
    source: str,
    source_as_of_date: date,
    forecast_version: str,
    is_confirmed: bool = False,
    notes: str | None = None,
) -> ExpectedCashFlow:
    require_editable_reporting_month(session, reporting_month_id)
    _require_account(session, account_id)
    _require_instrument(session, instrument_id)
    normalized_version = _normalize_text(forecast_version, field="forecast_version")
    _validate_forecast_version_as_of_date(
        session,
        reporting_month_id=reporting_month_id,
        forecast_version=normalized_version,
        source_as_of_date=source_as_of_date,
    )
    gross = _normalize_nonnegative_amount(gross_amount, field="gross_amount")
    tax = (
        _normalize_nonnegative_amount(expected_tax_amount, field="expected_tax_amount")
        if expected_tax_amount is not None
        else None
    )
    net, is_approximate = _validate_or_derive_net(
        gross_amount_kopecks=gross,
        expected_tax_amount_kopecks=tax,
        expected_net_amount=expected_net_amount,
    )
    flow = ExpectedCashFlow(
        reporting_month_id=reporting_month_id,
        account_id=account_id,
        instrument_id=instrument_id,
        flow_type=_coerce_flow_type(flow_type).value,
        expected_date=expected_date,
        gross_amount_kopecks=gross,
        expected_tax_amount_kopecks=tax,
        expected_net_amount_kopecks=net,
        currency=_normalize_currency(currency),
        source=_normalize_text(source, field="source"),
        source_as_of_date=source_as_of_date,
        forecast_version=normalized_version,
        is_confirmed=is_confirmed,
        is_approximate=is_approximate,
        notes=notes,
    )
    session.add(flow)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise ValueError("expected cash flow already exists in forecast version") from error
    session.refresh(flow)
    return flow


def update_expected_cash_flow(
    session: Session,
    flow_id: int,
    *,
    flow_type: ExpectedCashFlowType | str | None = None,
    expected_date: date | None = None,
    gross_amount: RubleAmount | str | None = None,
    expected_tax_amount: RubleAmount | str | None = None,
    expected_net_amount: RubleAmount | str | None = None,
    currency: str | None = None,
    source: str | None = None,
    is_confirmed: bool | None = None,
    notes: str | None = None,
) -> ExpectedCashFlow:
    flow = get_expected_cash_flow(session, flow_id)
    require_editable_child_month(session, flow)
    if flow_type is not None:
        flow.flow_type = _coerce_flow_type(flow_type).value
    if expected_date is not None:
        flow.expected_date = expected_date
    if gross_amount is not None:
        flow.gross_amount_kopecks = _normalize_nonnegative_amount(
            gross_amount, field="gross_amount"
        )
    tax = (
        _normalize_nonnegative_amount(expected_tax_amount, field="expected_tax_amount")
        if expected_tax_amount is not None
        else flow.expected_tax_amount_kopecks
    )
    if expected_tax_amount is not None:
        flow.expected_tax_amount_kopecks = tax
    net, is_approximate = _validate_or_derive_net(
        gross_amount_kopecks=flow.gross_amount_kopecks,
        expected_tax_amount_kopecks=tax,
        expected_net_amount=expected_net_amount,
    )
    flow.expected_net_amount_kopecks = net
    flow.is_approximate = is_approximate
    if currency is not None:
        flow.currency = _normalize_currency(currency)
    if source is not None:
        flow.source = _normalize_text(source, field="source")
    if is_confirmed is not None:
        flow.is_confirmed = is_confirmed
    if notes is not None:
        flow.notes = notes
    session.commit()
    session.refresh(flow)
    return flow


def delete_expected_cash_flow(session: Session, flow_id: int) -> None:
    flow = get_expected_cash_flow(session, flow_id)
    require_editable_child_month(session, flow)
    session.delete(flow)
    session.commit()
