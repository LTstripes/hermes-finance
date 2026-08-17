"""Read-only merged manual/provider payout calendar for R05-07."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import ExpectedCashFlowType, RubleAmount
from hermes_finance.persistence import (
    Account,
    AppliedPayoutReconciliation,
    AppliedProviderPayout,
    ExpectedCashFlow,
    Instrument,
    ReportingMonth,
)
from hermes_finance.services.applied_payouts import (
    AppliedPayoutLifecycle,
    PayoutCountingDecision,
)
from hermes_finance.services.payout_preview import _manual_candidates_for_applied
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError


class PayoutCalendarSource(StrEnum):
    MANUAL = "manual"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class MergedPayoutCalendarItem:
    source_kind: PayoutCalendarSource
    source_id: int
    expected_date: date
    flow_type: str
    account_id: int
    account_name: str
    instrument_id: int
    instrument_name: str | None
    expected_net_amount: RubleAmount
    is_confirmed: bool | None
    is_approximate: bool
    manual_source: str | None = None
    provider: str | None = None
    provider_instrument_uid: str | None = None
    provider_identity_key: str | None = None
    provider_lifecycle: str | None = None
    reconciliation_id: int | None = None
    counting_decision: str | None = None
    linked_manual_id: int | None = None
    linked_provider_payout_id: int | None = None


@dataclass(frozen=True, slots=True)
class MergedPayoutCalendarMonth:
    year: int
    month: int
    coupon: RubleAmount
    dividend: RubleAmount
    interest: RubleAmount
    redemption: RubleAmount
    other: RubleAmount
    passive_net: RubleAmount
    total_net: RubleAmount
    items: tuple[MergedPayoutCalendarItem, ...]


def merged_payout_calendar(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
    from_date: date | None = None,
) -> tuple[MergedPayoutCalendarMonth, ...]:
    """Merge countable manual and applied-provider expected payouts read-only."""

    version = forecast_version.strip()
    if not version:
        raise ValueError("forecast_version must not be empty")

    with session.no_autoflush:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")
        start = from_date or month.snapshot_date
        end_exclusive = _one_year_after(start)

        manual_rows = session.execute(
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

        manual_duplicate_pool = list(
            session.scalars(
                select(ExpectedCashFlow)
                .where(
                    ExpectedCashFlow.reporting_month_id == reporting_month_id,
                    ExpectedCashFlow.forecast_version == version,
                    ExpectedCashFlow.flow_type.in_(("coupon", "dividend", "redemption")),
                )
                .order_by(ExpectedCashFlow.expected_date, ExpectedCashFlow.id)
            )
        )

        provider_rows = session.execute(
            select(AppliedProviderPayout, Account.name, Instrument.name)
            .join(Account, AppliedProviderPayout.account_id == Account.id)
            .outerjoin(Instrument, AppliedProviderPayout.instrument_id == Instrument.id)
            .where(
                AppliedProviderPayout.reporting_month_id == reporting_month_id,
                AppliedProviderPayout.lifecycle == AppliedPayoutLifecycle.ACTIVE.value,
                AppliedProviderPayout.payment_date >= start,
                AppliedProviderPayout.payment_date < end_exclusive,
            )
            .order_by(AppliedProviderPayout.payment_date, AppliedProviderPayout.id)
        ).all()

        reconciliations = list(
            session.scalars(
                select(AppliedPayoutReconciliation)
                .join(
                    AppliedProviderPayout,
                    AppliedPayoutReconciliation.applied_payout_id == AppliedProviderPayout.id,
                )
                .where(AppliedProviderPayout.reporting_month_id == reporting_month_id)
                .order_by(AppliedPayoutReconciliation.id)
            )
        )

    manual_by_id = {flow.id: flow for flow, _, _ in manual_rows}
    manual_version_by_id = {flow.id: flow for flow in manual_duplicate_pool}
    reconciliation_by_payout = {item.applied_payout_id: item for item in reconciliations}
    reconciliation_by_manual = {
        item.expected_cash_flow_id: item
        for item in reconciliations
        if item.expected_cash_flow_id in manual_by_id
    }

    suppressed_manual_ids = {
        item.expected_cash_flow_id
        for item in reconciliations
        if item.counting_decision == PayoutCountingDecision.COUNT_PROVIDER.value
        and item.expected_cash_flow_id in manual_by_id
    }

    duplicate_pool_by_scope: dict[tuple[int, int], list[ExpectedCashFlow]] = {}
    for flow in manual_duplicate_pool:
        duplicate_pool_by_scope.setdefault((flow.account_id, flow.instrument_id), []).append(flow)

    items: list[MergedPayoutCalendarItem] = []
    for flow, account_name, instrument_name in manual_rows:
        if flow.id in suppressed_manual_ids:
            continue
        reconciliation = reconciliation_by_manual.get(flow.id)
        items.append(
            MergedPayoutCalendarItem(
                source_kind=PayoutCalendarSource.MANUAL,
                source_id=flow.id,
                expected_date=flow.expected_date,
                flow_type=flow.flow_type,
                account_id=flow.account_id,
                account_name=account_name,
                instrument_id=flow.instrument_id,
                instrument_name=instrument_name,
                expected_net_amount=RubleAmount(flow.expected_net_amount_kopecks),
                is_confirmed=flow.is_confirmed,
                is_approximate=flow.is_approximate,
                manual_source=flow.source,
                reconciliation_id=(reconciliation.id if reconciliation is not None else None),
                counting_decision=(
                    reconciliation.counting_decision if reconciliation is not None else None
                ),
                linked_provider_payout_id=(
                    reconciliation.applied_payout_id if reconciliation is not None else None
                ),
            )
        )

    for payout, account_name, instrument_name in provider_rows:
        reconciliation = reconciliation_by_payout.get(payout.id)
        effective_reconciliation = (
            reconciliation
            if reconciliation is not None
            and reconciliation.expected_cash_flow_id in manual_version_by_id
            else None
        )
        if (
            effective_reconciliation is not None
            and effective_reconciliation.counting_decision
            == PayoutCountingDecision.COUNT_MANUAL.value
        ):
            continue

        candidate_ids = _manual_candidates_for_applied(
            payout,
            duplicate_pool_by_scope.get((payout.account_id, payout.instrument_id), []),
        )
        resolved_manual_id = (
            effective_reconciliation.expected_cash_flow_id
            if effective_reconciliation is not None
            else None
        )
        if any(candidate_id != resolved_manual_id for candidate_id in candidate_ids):
            # A newly appearing extra candidate is unresolved. The ADR safe
            # default is manual-only counting until the owner explicitly resolves it.
            continue
        if effective_reconciliation is None and candidate_ids:
            continue

        items.append(
            MergedPayoutCalendarItem(
                source_kind=PayoutCalendarSource.PROVIDER,
                source_id=payout.id,
                expected_date=payout.payment_date,
                flow_type=payout.event_kind,
                account_id=payout.account_id,
                account_name=account_name,
                instrument_id=payout.instrument_id,
                instrument_name=instrument_name,
                expected_net_amount=RubleAmount(payout.total_amount_kopecks),
                is_confirmed=None,
                is_approximate=payout.is_approximate,
                provider=payout.provider,
                provider_instrument_uid=payout.provider_instrument_uid,
                provider_identity_key=payout.identity_key,
                provider_lifecycle=payout.lifecycle,
                reconciliation_id=(
                    effective_reconciliation.id if effective_reconciliation is not None else None
                ),
                counting_decision=(
                    effective_reconciliation.counting_decision
                    if effective_reconciliation is not None
                    else None
                ),
                linked_manual_id=resolved_manual_id,
            )
        )

    items.sort(
        key=lambda item: (
            item.expected_date,
            item.flow_type,
            item.source_kind.value,
            item.source_id,
        )
    )
    return _bucket_items(items)


def _bucket_items(
    items: list[MergedPayoutCalendarItem],
) -> tuple[MergedPayoutCalendarMonth, ...]:
    buckets: dict[tuple[int, int], dict[str, object]] = {}
    for item in items:
        key = (item.expected_date.year, item.expected_date.month)
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
        flow_type = ExpectedCashFlowType(item.flow_type).value
        bucket[flow_type] = int(bucket[flow_type]) + item.expected_net_amount.kopecks
        bucket["items"].append(item)  # type: ignore[union-attr]

    result: list[MergedPayoutCalendarMonth] = []
    for (year, month), bucket in sorted(buckets.items()):
        coupon = int(bucket["coupon"])
        dividend = int(bucket["dividend"])
        interest = int(bucket["interest"])
        redemption = int(bucket["redemption"])
        other = int(bucket["other"])
        passive = coupon + dividend + interest + other
        result.append(
            MergedPayoutCalendarMonth(
                year=year,
                month=month,
                coupon=RubleAmount(coupon),
                dividend=RubleAmount(dividend),
                interest=RubleAmount(interest),
                redemption=RubleAmount(redemption),
                other=RubleAmount(other),
                passive_net=RubleAmount(passive),
                total_net=RubleAmount(passive + redemption),
                items=tuple(bucket["items"]),  # type: ignore[arg-type]
            )
        )
    return tuple(result)


def _one_year_after(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, month=2, day=28)
