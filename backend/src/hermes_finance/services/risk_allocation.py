"""Read-only, persisted-data-only portfolio allocation metrics (R07-06A).

The service assembles the current reporting-month snapshot and delegates all
percentage arithmetic to the framework-independent risk-allocation domain
module. It never constructs a provider, performs network I/O, writes to the
database, or infers issuer/currency/maturity metadata.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from hermes_finance.domain import ExpectedCashFlowType, InstrumentType, RubleAmount
from hermes_finance.domain.risk_allocation import (
    AllocationMetric,
    AllocationSlice,
    ConcentrationItem,
    ConcentrationMetric,
    MetricSupport,
    RiskAllocationResult,
    RiskSupportStatus,
    SupportIssue,
    percentage,
    support_from_issues,
)
from hermes_finance.persistence import (
    Account,
    AppliedProviderPayout,
    CashBalance,
    DepositSnapshot,
    ExpectedCashFlow,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.cash_flow_ladder import (
    CashFlowLadderEvent,
    CashFlowLadderSource,
    build_cash_flow_ladder,
)
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION
from hermes_finance.services.reporting_months import ReportingMonthNotFoundError

BASE_CURRENCY = "RUB"
DEFAULT_TOP_N = 5
MAX_TOP_N = 100


@dataclass(frozen=True, slots=True)
class _SafePosition:
    position_id: int
    account_id: int
    account_name: str
    instrument_id: int
    instrument_name: str
    instrument_type: str | None
    amount_kopecks: int


@dataclass(slots=True)
class _FlowAggregate:
    account_id: int
    account_name: str
    instrument_id: int
    instrument_name: str | None
    amount_kopecks: int = 0
    event_count: int = 0
    is_approximate: bool = False


def _validate_top_n(top_n: int) -> int:
    if isinstance(top_n, bool) or not isinstance(top_n, int):
        raise TypeError("top_n must be an integer")
    if not 1 <= top_n <= MAX_TOP_N:
        raise ValueError(f"top_n must be between 1 and {MAX_TOP_N}")
    return top_n


def _issue(
    source_kind: str,
    source_id: int | None,
    status: RiskSupportStatus,
    reason_code: str,
) -> SupportIssue:
    return SupportIssue(
        source_kind=source_kind,
        source_id=source_id,
        support=MetricSupport(status=status, reason_codes=(reason_code,)),
    )


def _currency_support(currency: str | None) -> MetricSupport:
    if not isinstance(currency, str) or not currency.strip():
        return MetricSupport(
            status=RiskSupportStatus.UNKNOWN,
            reason_codes=("currency_not_persisted",),
        )
    if currency.strip().upper() != BASE_CURRENCY:
        return MetricSupport(
            status=RiskSupportStatus.UNAVAILABLE,
            reason_codes=("currency_conversion_not_supported",),
        )
    return MetricSupport(status=RiskSupportStatus.SUPPORTED)


def _instrument_type_support(instrument_type: str | None) -> tuple[MetricSupport, str | None]:
    try:
        kind = InstrumentType(instrument_type)
    except (TypeError, ValueError):
        return (
            MetricSupport(
                status=RiskSupportStatus.UNKNOWN,
                reason_codes=("instrument_type_not_authoritative",),
            ),
            None,
        )
    return MetricSupport(status=RiskSupportStatus.SUPPORTED), kind.value


def _amount_is_valid(amount: object) -> bool:
    return isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0


def _money(kopecks: int) -> RubleAmount:
    return RubleAmount(kopecks)


def _allocation_metric(
    amounts: dict[str, int],
    *,
    denominator_kopecks: int,
    covered_kopecks: int,
    unallocated_kopecks: int,
    support: MetricSupport,
    excluded: tuple[SupportIssue, ...],
    account_ids: dict[str, int] | None = None,
    labels: dict[str, str] | None = None,
    instrument_types: dict[str, str] | None = None,
) -> AllocationMetric:
    slices: list[AllocationSlice] = []
    for key, amount in sorted(amounts.items(), key=lambda item: (-item[1], item[0])):
        if amount == 0:
            continue
        slices.append(
            AllocationSlice(
                key=key,
                label=labels.get(key, key) if labels is not None else key,
                amount=_money(amount),
                share_pct=percentage(amount, denominator_kopecks),
                account_id=account_ids.get(key) if account_ids is not None else None,
                instrument_type=(
                    instrument_types.get(key) if instrument_types is not None else None
                ),
            )
        )
    return AllocationMetric(
        support=support,
        denominator=_money(denominator_kopecks),
        covered_amount=_money(covered_kopecks),
        unallocated_amount=_money(unallocated_kopecks),
        coverage_pct=percentage(covered_kopecks, denominator_kopecks),
        items=tuple(slices),
        excluded=excluded,
    )


def _concentration_metric(
    items: list[ConcentrationItem],
    *,
    denominator_kopecks: int,
    top_n: int,
    issues: tuple[SupportIssue, ...],
    extra_reason_codes: tuple[str, ...] = (),
    is_approximate: bool = False,
) -> ConcentrationMetric:
    ordered = sorted(items, key=lambda item: (-item.amount.kopecks, item.key))
    selected = ordered[:top_n]
    selected_amount = sum(item.amount.kopecks for item in selected)
    with_shares = tuple(
        replace(item, share_pct=percentage(item.amount.kopecks, denominator_kopecks))
        for item in selected
    )
    return ConcentrationMetric(
        support=support_from_issues(issues, extra_reason_codes=extra_reason_codes),
        denominator=_money(denominator_kopecks),
        top_n=top_n,
        top_amount=_money(selected_amount),
        top_share_pct=percentage(selected_amount, denominator_kopecks),
        items=with_shares,
        excluded=issues,
        is_approximate=is_approximate,
    )


def _event_currency_map(
    session: Session,
    events: tuple[CashFlowLadderEvent, ...],
) -> dict[tuple[str, int], str | None]:
    manual_ids = tuple(
        event.source_id for event in events if event.source_kind is CashFlowLadderSource.MANUAL
    )
    provider_ids = tuple(
        event.source_id for event in events if event.source_kind is CashFlowLadderSource.PROVIDER
    )
    result: dict[tuple[str, int], str | None] = {}
    with session.no_autoflush:
        if manual_ids:
            for row in session.scalars(
                select(ExpectedCashFlow).where(ExpectedCashFlow.id.in_(manual_ids))
            ):
                result[(CashFlowLadderSource.MANUAL.value, row.id)] = row.currency
        if provider_ids:
            for row in session.scalars(
                select(AppliedProviderPayout).where(AppliedProviderPayout.id.in_(provider_ids))
            ):
                result[(CashFlowLadderSource.PROVIDER.value, row.id)] = row.currency
    return result


def _flow_items(
    events: tuple[CashFlowLadderEvent, ...],
    *,
    event_currencies: dict[tuple[str, int], str | None],
    redemption: bool,
) -> tuple[list[ConcentrationItem], tuple[SupportIssue, ...], tuple[SupportIssue, ...]]:
    aggregates: dict[tuple[int, int], _FlowAggregate] = {}
    issues: list[SupportIssue] = []
    currency_issues: list[SupportIssue] = []
    for event in events:
        is_redemption = event.flow_type == ExpectedCashFlowType.REDEMPTION.value
        if is_redemption != redemption:
            continue

        currency = event_currencies.get((event.source_kind.value, event.source_id))
        currency_state = _currency_support(currency)
        if currency_state.status is not RiskSupportStatus.SUPPORTED:
            row_issue = _issue(
                event.source_kind.value,
                event.source_id,
                currency_state.status,
                currency_state.reason_codes[0],
            )
            issues.append(row_issue)
            currency_issues.append(row_issue)
            continue
        if event.instrument_id is None:
            issues.append(
                _issue(
                    event.source_kind.value,
                    event.source_id,
                    RiskSupportStatus.UNKNOWN,
                    "instrument_not_persisted",
                )
            )
            continue
        if not _amount_is_valid(event.expected_net_amount.kopecks):
            issues.append(
                _issue(
                    event.source_kind.value,
                    event.source_id,
                    RiskSupportStatus.UNAVAILABLE,
                    "unsupported_position_valuation",
                )
            )
            continue

        key = (event.account_id, event.instrument_id)
        aggregate = aggregates.get(key)
        if aggregate is None:
            aggregate = _FlowAggregate(
                account_id=event.account_id,
                account_name=event.account_name,
                instrument_id=event.instrument_id,
                instrument_name=event.instrument_name,
            )
            aggregates[key] = aggregate
        aggregate.amount_kopecks += event.expected_net_amount.kopecks
        aggregate.event_count += 1
        aggregate.is_approximate = aggregate.is_approximate or event.is_approximate

    result = [
        ConcentrationItem(
            key=f"account:{aggregate.account_id}:instrument:{aggregate.instrument_id}",
            label=(
                f"{aggregate.account_name} / "
                f"{aggregate.instrument_name or f'instrument {aggregate.instrument_id}'}"
            ),
            amount=_money(aggregate.amount_kopecks),
            share_pct=None,
            account_id=aggregate.account_id,
            account_name=aggregate.account_name,
            instrument_id=aggregate.instrument_id,
            instrument_name=aggregate.instrument_name,
            event_count=aggregate.event_count,
            is_approximate=aggregate.is_approximate,
        )
        for aggregate in aggregates.values()
        if aggregate.amount_kopecks > 0
    ]
    return result, tuple(issues), tuple(currency_issues)


def _static_unavailable(reason_code: str) -> MetricSupport:
    return MetricSupport(
        status=RiskSupportStatus.UNAVAILABLE,
        reason_codes=(reason_code,),
    )


def risk_allocation_for_month(
    session: Session,
    reporting_month_id: int,
    *,
    top_n: int = DEFAULT_TOP_N,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> RiskAllocationResult:
    """Return deterministic allocation/concentration metrics for one month."""
    top_n = _validate_top_n(top_n)
    version = forecast_version.strip()
    if not version:
        raise ValueError("forecast_version must not be empty")

    with session.no_autoflush:
        month = session.get(ReportingMonth, reporting_month_id)
        if month is None:
            raise ReportingMonthNotFoundError(f"reporting month {reporting_month_id} was not found")

        cash_rows = list(
            session.scalars(
                select(CashBalance)
                .where(
                    CashBalance.reporting_month_id == reporting_month_id,
                    CashBalance.include_in_capital.is_(True),
                )
                .order_by(CashBalance.id)
            )
        )
        deposit_rows = session.execute(
            select(DepositSnapshot, Account.name)
            .join(Account, DepositSnapshot.account_id == Account.id)
            .where(
                DepositSnapshot.reporting_month_id == reporting_month_id,
                Account.include_in_capital.is_(True),
            )
            .order_by(DepositSnapshot.account_id, DepositSnapshot.id)
        ).all()
        position_rows = session.execute(
            select(
                PositionSnapshot,
                Account.name,
                Instrument.name,
                Instrument.instrument_type,
                Instrument.currency,
            )
            .join(Account, PositionSnapshot.account_id == Account.id)
            .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
            .where(
                PositionSnapshot.reporting_month_id == reporting_month_id,
                Account.include_in_capital.is_(True),
            )
            .order_by(
                PositionSnapshot.account_id,
                PositionSnapshot.instrument_id,
                PositionSnapshot.id,
            )
        ).all()
        authoritative_liquid_capital = liquid_capital_for_month(session, reporting_month_id)

    asset_amounts: dict[str, int] = defaultdict(int)
    account_amounts: dict[int, int] = defaultdict(int)
    account_names: dict[int, str] = {}
    valuation_issues: list[SupportIssue] = []
    asset_class_issues: list[SupportIssue] = []
    currency_issues: list[SupportIssue] = []
    safe_positions: list[_SafePosition] = []
    valid_cash_kopecks = 0
    unknown_asset_class_kopecks = 0

    for cash in cash_rows:
        currency_state = _currency_support(cash.currency)
        if currency_state.status is not RiskSupportStatus.SUPPORTED:
            row_issue = _issue(
                "cash_balance",
                cash.id,
                currency_state.status,
                currency_state.reason_codes[0],
            )
            currency_issues.append(row_issue)
        if not _amount_is_valid(cash.amount_kopecks):
            valuation_issues.append(
                _issue(
                    "cash_balance",
                    cash.id,
                    RiskSupportStatus.UNAVAILABLE,
                    "unsupported_position_valuation",
                )
            )
            continue
        valid_cash_kopecks += cash.amount_kopecks

    if valid_cash_kopecks:
        asset_amounts["cash"] += valid_cash_kopecks

    for deposit, account_name in deposit_rows:
        if not _amount_is_valid(deposit.balance_kopecks):
            valuation_issues.append(
                _issue(
                    "deposit_snapshot",
                    deposit.id,
                    RiskSupportStatus.UNAVAILABLE,
                    "unsupported_position_valuation",
                )
            )
            continue
        asset_amounts["deposits"] += deposit.balance_kopecks
        account_amounts[deposit.account_id] += deposit.balance_kopecks
        account_names[deposit.account_id] = account_name

    for snapshot, account_name, instrument_name, instrument_type, currency in position_rows:
        currency_state = _currency_support(currency)
        kind_state, kind = _instrument_type_support(instrument_type)
        if currency_state.status is not RiskSupportStatus.SUPPORTED:
            row_issue = _issue(
                "position_snapshot",
                snapshot.id,
                currency_state.status,
                currency_state.reason_codes[0],
            )
            currency_issues.append(row_issue)
        if kind_state.status is not RiskSupportStatus.SUPPORTED:
            asset_class_issues.append(
                _issue(
                    "position_snapshot",
                    snapshot.id,
                    kind_state.status,
                    kind_state.reason_codes[0],
                )
            )
        if not _amount_is_valid(snapshot.market_value_kopecks):
            valuation_issues.append(
                _issue(
                    "position_snapshot",
                    snapshot.id,
                    RiskSupportStatus.UNAVAILABLE,
                    "unsupported_position_valuation",
                )
            )
            continue
        safe_positions.append(
            _SafePosition(
                position_id=snapshot.id,
                account_id=snapshot.account_id,
                account_name=account_name,
                instrument_id=snapshot.instrument_id,
                instrument_name=instrument_name,
                instrument_type=kind,
                amount_kopecks=snapshot.market_value_kopecks,
            )
        )
        if kind is None:
            unknown_asset_class_kopecks += snapshot.market_value_kopecks
        else:
            asset_amounts[kind] += snapshot.market_value_kopecks
        account_amounts[snapshot.account_id] += snapshot.market_value_kopecks
        account_names[snapshot.account_id] = account_name

    denominator_kopecks = authoritative_liquid_capital.total_assets.kopecks
    valuation_issue_tuple = tuple(valuation_issues)
    asset_class_issue_tuple = tuple(asset_class_issues)
    allocation_support = support_from_issues(valuation_issue_tuple + asset_class_issue_tuple)
    asset_amounts_for_metric = dict(asset_amounts)
    if unknown_asset_class_kopecks:
        asset_amounts_for_metric["unknown_asset_class"] = unknown_asset_class_kopecks
    known_asset_class_kopecks = sum(asset_amounts.values())
    account_support = support_from_issues(
        valuation_issue_tuple,
        extra_reason_codes=("cash_not_account_linked",) if cash_rows else (),
    )
    asset_metric = _allocation_metric(
        asset_amounts_for_metric,
        denominator_kopecks=denominator_kopecks,
        covered_kopecks=known_asset_class_kopecks,
        unallocated_kopecks=unknown_asset_class_kopecks,
        support=allocation_support,
        excluded=valuation_issue_tuple + asset_class_issue_tuple,
        instrument_types={kind.value: kind.value for kind in InstrumentType},
        labels={"unknown_asset_class": "Unknown asset class"},
    )
    account_metric = _allocation_metric(
        {
            **{f"account:{account_id}": amount for account_id, amount in account_amounts.items()},
            **({"unassigned_cash": valid_cash_kopecks} if valid_cash_kopecks else {}),
        },
        denominator_kopecks=denominator_kopecks,
        covered_kopecks=sum(account_amounts.values()),
        unallocated_kopecks=valid_cash_kopecks,
        support=account_support,
        excluded=valuation_issue_tuple,
        account_ids={f"account:{account_id}": account_id for account_id in account_amounts},
        labels={
            f"account:{account_id}": account_name
            for account_id, account_name in account_names.items()
        }
        | {"unassigned_cash": "Unassigned cash"},
    )

    top_position_items = [
        ConcentrationItem(
            key=f"position:{position.position_id}",
            label=f"{position.account_name} / {position.instrument_name}",
            amount=_money(position.amount_kopecks),
            share_pct=None,
            account_id=position.account_id,
            account_name=position.account_name,
            instrument_id=position.instrument_id,
            instrument_name=position.instrument_name,
            instrument_type=position.instrument_type,
            position_id=position.position_id,
        )
        for position in safe_positions
        if position.amount_kopecks > 0
    ]
    top_positions = _concentration_metric(
        top_position_items,
        denominator_kopecks=denominator_kopecks,
        top_n=top_n,
        issues=valuation_issue_tuple,
    )

    with session.no_autoflush:
        ladder = build_cash_flow_ladder(
            session,
            reporting_month_id,
            forecast_version=version,
        )
    ladder_events = tuple(event for ladder_month in ladder.months for event in ladder_month.items)
    event_currencies = _event_currency_map(session, ladder_events)
    payout_items, payout_issues, payout_currency_issues = _flow_items(
        ladder_events,
        event_currencies=event_currencies,
        redemption=False,
    )
    redemption_items, redemption_issues, redemption_currency_issues = _flow_items(
        ladder_events,
        event_currencies=event_currencies,
        redemption=True,
    )
    deposit_reason = ("deposit_forecast_not_concentratable",) if deposit_rows else ()
    has_payout_events = any(
        event.flow_type != ExpectedCashFlowType.REDEMPTION.value for event in ladder_events
    )
    has_redemption_events = any(
        event.flow_type == ExpectedCashFlowType.REDEMPTION.value for event in ladder_events
    )
    payout_extra = deposit_reason + (("no_dated_payouts",) if not has_payout_events else ())
    redemption_extra = deposit_reason + (("no_dated_payouts",) if not has_redemption_events else ())
    payout_denominator = sum(item.amount.kopecks for item in payout_items)
    redemption_denominator = sum(item.amount.kopecks for item in redemption_items)
    payout_metric = _concentration_metric(
        payout_items,
        denominator_kopecks=payout_denominator,
        top_n=top_n,
        issues=payout_issues,
        extra_reason_codes=payout_extra,
        is_approximate=any(item.is_approximate for item in payout_items),
    )
    redemption_metric = _concentration_metric(
        redemption_items,
        denominator_kopecks=redemption_denominator,
        top_n=top_n,
        issues=redemption_issues,
        extra_reason_codes=redemption_extra,
        is_approximate=any(item.is_approximate for item in redemption_items),
    )

    currency_issues.extend(payout_currency_issues)
    currency_issues.extend(redemption_currency_issues)
    currency_support = support_from_issues(tuple(currency_issues))
    support = {
        "asset_class": allocation_support,
        "account": account_support,
        "issuer": _static_unavailable("issuer_not_persisted"),
        "currency": currency_support,
        "maturity": _static_unavailable("maturity_not_persisted"),
        "broker": _static_unavailable("broker_identity_not_persisted"),
        "bank": _static_unavailable("bank_identity_not_persisted"),
        "top_positions": top_positions.support,
        "payout": payout_metric.support,
        "redemption": redemption_metric.support,
    }
    return RiskAllocationResult(
        reporting_month_id=reporting_month_id,
        as_of_date=month.snapshot_date,
        base_currency=BASE_CURRENCY,
        liquid_assets_total=_money(denominator_kopecks),
        allocation_by_asset_class=asset_metric,
        allocation_by_account=account_metric,
        top_positions=top_positions,
        payout_concentration=payout_metric,
        redemption_concentration=redemption_metric,
        support=support,
    )


risk_allocation = risk_allocation_for_month
