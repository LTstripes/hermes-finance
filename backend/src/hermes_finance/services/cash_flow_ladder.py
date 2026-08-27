"""Read-only treasury view of expected investment cash flows (R07-05).

The ladder is deliberately built on top of the accepted merged payout
calendar.  That keeps manual/provider reconciliation, lifecycle filtering and
the redemption-as-capital rule in one place.  Deposit estimates are the
persisted selected-month snapshot values used by the existing C04 forecast;
they are repeated monthly for the twelve-month horizon and remain visibly
approximate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import ExpectedCashFlowType, RubleAmount
from hermes_finance.persistence import Account, DepositSnapshot, ReportingMonth
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class CashFlowLadderSource(StrEnum):
    MANUAL = "manual"
    PROVIDER = "provider"
    DEPOSIT_FORECAST = "deposit_forecast"


@dataclass(frozen=True, slots=True)
class CashFlowLadderEvent:
    source_kind: CashFlowLadderSource
    source_id: int
    expected_date: date
    flow_type: str
    component: str
    account_id: int
    account_name: str
    instrument_id: int | None
    instrument_name: str | None
    expected_net_amount: RubleAmount
    is_approximate: bool
    source: str
    provider: str | None = None
    provider_instrument_uid: str | None = None
    provider_identity_key: str | None = None
    reconciliation_id: int | None = None
    counting_decision: str | None = None
    linked_manual_id: int | None = None
    linked_provider_payout_id: int | None = None
    source_as_of_date: date | None = None


@dataclass(frozen=True, slots=True)
class CashFlowLadderMonth:
    year: int
    month: int
    coupon: RubleAmount
    dividend: RubleAmount
    deposit_interest: RubleAmount
    other_capital_income: RubleAmount
    redemption_principal: RubleAmount
    passive_income: RubleAmount
    total_cash_flow: RubleAmount
    is_approximate: bool
    items: tuple[CashFlowLadderEvent, ...]


@dataclass(frozen=True, slots=True)
class UpcomingEventsWindow:
    days: int
    from_date: date
    to_date: date
    passive_income: RubleAmount
    redemption_principal: RubleAmount
    total_cash_flow: RubleAmount
    items: tuple[CashFlowLadderEvent, ...]


@dataclass(frozen=True, slots=True)
class CashFlowLadderResult:
    as_of_date: date
    forecast_version: str
    months: tuple[CashFlowLadderMonth, ...]
    upcoming_14_days: UpcomingEventsWindow
    upcoming_30_days: UpcomingEventsWindow
    warnings: tuple[str, ...]


def _month_add(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + offset
    return index // 12, index % 12 + 1


def _event_component(flow_type: str) -> str:
    if flow_type == ExpectedCashFlowType.REDEMPTION.value:
        return "redemption_principal"
    if flow_type == ExpectedCashFlowType.INTEREST.value:
        return "deposit_interest"
    if flow_type == ExpectedCashFlowType.OTHER.value:
        return "other_capital_income"
    return flow_type


def _deposit_event_date(as_of_date: date, *, year: int, month: int) -> date:
    """Place a recurring snapshot estimate on the matching monthly day."""
    # Moving the day to the last valid day keeps February and short months
    # deterministic without introducing a new maturity/payment contract.
    next_year, next_month = _month_add(year, month, 1)
    last_day = (date(next_year, next_month, 1) - timedelta(days=1)).day
    return date(year, month, min(as_of_date.day, last_day))


def _window(
    events: tuple[CashFlowLadderEvent, ...],
    *,
    as_of_date: date,
    days: int,
) -> UpcomingEventsWindow:
    to_date = as_of_date + timedelta(days=days)
    selected = tuple(event for event in events if as_of_date <= event.expected_date < to_date)
    passive = sum(
        event.expected_net_amount.kopecks
        for event in selected
        if event.component != "redemption_principal"
    )
    redemption = sum(
        event.expected_net_amount.kopecks
        for event in selected
        if event.component == "redemption_principal"
    )
    return UpcomingEventsWindow(
        days=days,
        from_date=as_of_date,
        to_date=to_date,
        passive_income=RubleAmount(passive),
        redemption_principal=RubleAmount(redemption),
        total_cash_flow=RubleAmount(passive + redemption),
        items=selected,
    )


def build_cash_flow_ladder(
    session: Session,
    reporting_month_id: int,
    *,
    forecast_version: str = "v1",
) -> CashFlowLadderResult:
    """Build a twelve-month ladder and deterministic upcoming-event windows."""
    month = session.get(ReportingMonth, reporting_month_id)
    if month is None:
        raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")
    version = forecast_version.strip()
    if not version:
        raise ValueError("forecast_version must not be empty")

    as_of_date = month.snapshot_date
    horizon_end = date(*_month_add(as_of_date.year, as_of_date.month, 12), 1)
    merged = merged_payout_calendar(
        session,
        reporting_month_id=reporting_month_id,
        forecast_version=version,
    )
    events: list[CashFlowLadderEvent] = []
    for calendar_month in merged:
        for item in calendar_month.items:
            flow_type = ExpectedCashFlowType(item.flow_type).value
            events.append(
                CashFlowLadderEvent(
                    source_kind=CashFlowLadderSource(item.source_kind.value),
                    source_id=item.source_id,
                    expected_date=item.expected_date,
                    flow_type=flow_type,
                    component=_event_component(flow_type),
                    account_id=item.account_id,
                    account_name=item.account_name,
                    instrument_id=item.instrument_id,
                    instrument_name=item.instrument_name,
                    expected_net_amount=item.expected_net_amount,
                    is_approximate=item.is_approximate,
                    source=item.manual_source or item.provider or item.source_kind.value,
                    provider=item.provider,
                    provider_instrument_uid=item.provider_instrument_uid,
                    provider_identity_key=item.provider_identity_key,
                    reconciliation_id=item.reconciliation_id,
                    counting_decision=item.counting_decision,
                    linked_manual_id=item.linked_manual_id,
                    linked_provider_payout_id=item.linked_provider_payout_id,
                    source_as_of_date=item.source_as_of_date,
                )
            )

    deposit_rows = session.execute(
        select(DepositSnapshot, Account.name)
        .join(Account, DepositSnapshot.account_id == Account.id)
        .where(DepositSnapshot.reporting_month_id == reporting_month_id)
        .order_by(DepositSnapshot.id)
    ).all()
    for snapshot, account_name in deposit_rows:
        for offset in range(12):
            year, month_number = _month_add(as_of_date.year, as_of_date.month, offset)
            expected_date = _deposit_event_date(
                as_of_date,
                year=year,
                month=month_number,
            )
            if not as_of_date <= expected_date < horizon_end:
                continue
            amount = RubleAmount(snapshot.expected_monthly_interest_kopecks)
            if amount.kopecks == 0:
                continue
            events.append(
                CashFlowLadderEvent(
                    source_kind=CashFlowLadderSource.DEPOSIT_FORECAST,
                    source_id=snapshot.id,
                    expected_date=expected_date,
                    flow_type=ExpectedCashFlowType.INTEREST.value,
                    component="deposit_interest",
                    account_id=snapshot.account_id,
                    account_name=account_name,
                    instrument_id=None,
                    instrument_name=snapshot.name,
                    expected_net_amount=amount,
                    is_approximate=True,
                    source="deposit_snapshot",
                    source_as_of_date=as_of_date,
                )
            )

    events.sort(key=lambda event: (event.expected_date, event.source_kind.value, event.source_id))
    all_events = tuple(events)
    by_month: dict[tuple[int, int], list[CashFlowLadderEvent]] = {}
    for event in all_events:
        by_month.setdefault((event.expected_date.year, event.expected_date.month), []).append(event)

    ladder_months: list[CashFlowLadderMonth] = []
    for offset in range(12):
        year, month_number = _month_add(as_of_date.year, as_of_date.month, offset)
        items = tuple(by_month.get((year, month_number), ()))
        amounts = {
            "coupon": sum(
                item.expected_net_amount.kopecks for item in items if item.component == "coupon"
            ),
            "dividend": sum(
                item.expected_net_amount.kopecks for item in items if item.component == "dividend"
            ),
            "deposit_interest": sum(
                item.expected_net_amount.kopecks
                for item in items
                if item.component == "deposit_interest"
            ),
            "other_capital_income": sum(
                item.expected_net_amount.kopecks
                for item in items
                if item.component == "other_capital_income"
            ),
            "redemption_principal": sum(
                item.expected_net_amount.kopecks
                for item in items
                if item.component == "redemption_principal"
            ),
        }
        passive = sum(amounts[key] for key in amounts if key != "redemption_principal")
        total = passive + amounts["redemption_principal"]
        ladder_months.append(
            CashFlowLadderMonth(
                year=year,
                month=month_number,
                coupon=RubleAmount(amounts["coupon"]),
                dividend=RubleAmount(amounts["dividend"]),
                deposit_interest=RubleAmount(amounts["deposit_interest"]),
                other_capital_income=RubleAmount(amounts["other_capital_income"]),
                redemption_principal=RubleAmount(amounts["redemption_principal"]),
                passive_income=RubleAmount(passive),
                total_cash_flow=RubleAmount(total),
                is_approximate=any(item.is_approximate for item in items),
                items=items,
            )
        )

    warnings: list[str] = []
    if deposit_rows:
        warnings.append(
            "Проценты по вкладам — приблизительная оценка по снимкам выбранного месяца; "
            "срок и изменение ставки не моделируются."
        )
    else:
        warnings.append(
            "Оценка процентов по вкладам недоступна: в выбранном месяце нет снимков вкладов."
        )

    return CashFlowLadderResult(
        as_of_date=as_of_date,
        forecast_version=version,
        months=tuple(ladder_months),
        upcoming_14_days=_window(all_events, as_of_date=as_of_date, days=14),
        upcoming_30_days=_window(all_events, as_of_date=as_of_date, days=30),
        warnings=tuple(warnings),
    )


cash_flow_ladder = build_cash_flow_ladder
