"""Dashboard assembly for the selected reporting month (D07).

Builds historical series and presentation-oriented slices on top of the
existing C10 monthly summary and B-layer queries. No financial formulas
are reinvented here — liquid capital / passive income / forecast all come
from the Phase-C services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.monthly_summary import MonthlySummaryResult
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    Account,
    Instrument,
    InvestmentCashFlow,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.asset_allocation import AssetClassSlice, asset_allocation_for_month
from hermes_finance.services.cash_flow_ladder import (
    CashFlowLadderResult,
    build_cash_flow_ladder,
)
from hermes_finance.services.liquid_capital import (
    liquid_capital_for_month,
    liquid_capital_for_months,
)
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION, monthly_summary
from hermes_finance.services.passive_income import passive_income_for_months
from hermes_finance.services.payout_calendar import merged_payout_calendar
from hermes_finance.services.properties import mortgage_coverage, total_mortgage_balance
from hermes_finance.services.reporting_months import get_reporting_month

CASH_INCOME_FLOW_TYPES = (
    "coupon",
    "dividend",
    "interest",
    "realized_profit",
    "realized_loss",
)


@dataclass(frozen=True, slots=True)
class HistoricalPoint:
    year: int
    month: int
    reporting_month_id: int
    liquid_capital_net: RubleAmount
    passive_income_actual: RubleAmount


@dataclass(frozen=True, slots=True)
class AccountResultSlice:
    account_id: int
    account_name: str
    account_type: str
    cash_income: RubleAmount
    unrealized_result: RubleAmount


@dataclass(frozen=True, slots=True)
class InstrumentClassResult:
    instrument_type: str
    market_value: RubleAmount
    cost_basis: RubleAmount
    unrealized_result: RubleAmount
    realized_result: RubleAmount


@dataclass(frozen=True, slots=True)
class ExpectedPaymentItem:
    id: int
    expected_date: date
    flow_type: str
    account_id: int
    instrument_id: int
    gross_amount: RubleAmount | None
    expected_tax_amount: RubleAmount | None
    expected_net_amount: RubleAmount
    is_confirmed: bool | None
    is_approximate: bool
    source: str
    forecast_version: str
    source_kind: str = "manual"
    provider: str | None = None
    provider_instrument_uid: str | None = None
    provider_identity_key: str | None = None
    provider_lifecycle: str | None = None
    reconciliation_id: int | None = None
    counting_decision: str | None = None
    linked_manual_id: int | None = None
    linked_provider_payout_id: int | None = None


@dataclass(frozen=True, slots=True)
class MortgageCoverageSlice:
    mortgage_balance: RubleAmount
    coverage_pct: Decimal | None
    gap: RubleAmount


@dataclass(frozen=True, slots=True)
class DashboardResult:
    month: ReportingMonth
    summary: MonthlySummaryResult
    historical_series: tuple[HistoricalPoint, ...]
    asset_allocation: tuple[AssetClassSlice, ...]
    result_by_account: tuple[AccountResultSlice, ...]
    result_by_instrument_class: tuple[InstrumentClassResult, ...]
    expected_payments: tuple[ExpectedPaymentItem, ...]
    mortgage: MortgageCoverageSlice
    warnings: tuple[str, ...]
    cash_flow_ladder: CashFlowLadderResult | None = None
    asset_allocation_delta: tuple[AssetClassSlice, ...] = ()


def _historical_series(session: Session) -> tuple[HistoricalPoint, ...]:
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        )
    )
    month_ids = [month.id for month in months]
    liquid_by_month = liquid_capital_for_months(session, month_ids)
    passive_by_month = passive_income_for_months(session, month_ids)
    points: list[HistoricalPoint] = []
    for month in months:
        liquid = liquid_by_month[month.id]
        passive = passive_by_month[month.id]
        points.append(
            HistoricalPoint(
                year=month.year,
                month=month.month,
                reporting_month_id=month.id,
                liquid_capital_net=liquid.liquid_capital_net,
                passive_income_actual=passive.total_net_passive_income,
            )
        )
    return tuple(points)


def _previous_reporting_month(session: Session, *, year: int, month: int) -> ReportingMonth | None:
    return session.scalar(
        select(ReportingMonth)
        .where(
            (ReportingMonth.year < year)
            | ((ReportingMonth.year == year) & (ReportingMonth.month < month))
        )
        .order_by(ReportingMonth.year.desc(), ReportingMonth.month.desc())
        .limit(1)
    )


def _asset_allocation_delta(
    session: Session,
    *,
    month: ReportingMonth,
    allocation: tuple[AssetClassSlice, ...],
) -> tuple[AssetClassSlice, ...]:
    """Return class deltas against the same previous-month source used by KPIs."""
    previous = _previous_reporting_month(session, year=month.year, month=month.month)
    if previous is None:
        return ()

    previous_liquid = liquid_capital_for_month(session, previous.id)
    previous_allocation = asset_allocation_for_month(session, previous.id, previous_liquid)
    previous_by_class = {item.asset_class: item.amount.kopecks for item in previous_allocation}
    return tuple(
        AssetClassSlice(
            item.asset_class,
            RubleAmount(item.amount.kopecks - previous_by_class.get(item.asset_class, 0)),
        )
        for item in allocation
    )


def _instrument_class_results(
    session: Session, reporting_month_id: int
) -> tuple[InstrumentClassResult, ...]:
    rows = session.execute(
        select(
            Instrument.instrument_type,
            PositionSnapshot.market_value_kopecks,
            PositionSnapshot.cost_basis_kopecks,
            PositionSnapshot.unrealized_result_kopecks,
        )
        .join(Instrument, Instrument.id == PositionSnapshot.instrument_id)
        .where(PositionSnapshot.reporting_month_id == reporting_month_id)
    ).all()
    aggregated: dict[str, list[int]] = {}
    for instrument_type, market, cost, unrealized in rows:
        bucket = aggregated.setdefault(instrument_type, [0, 0, 0])
        bucket[0] += int(market)
        bucket[1] += int(cost)
        bucket[2] += int(unrealized)

    realized_by_type = _cash_income_by_class(session, reporting_month_id)
    return tuple(
        InstrumentClassResult(
            instrument_type=instrument_type,
            market_value=RubleAmount(values[0]),
            cost_basis=RubleAmount(values[1]),
            unrealized_result=RubleAmount(values[2]),
            realized_result=RubleAmount(realized_by_type.get(instrument_type, 0)),
        )
        for instrument_type, values in sorted(aggregated.items())
    )


def _cash_income_by_class(session: Session, reporting_month_id: int) -> dict[str, int]:
    """Cash income per instrument class.

    INNER JOIN on Instrument: flows without an instrument (realized P&L booked
    on the account only) have no class to attribute to and intentionally stay
    out of the class table — they still appear in the account-level result.
    """
    rows = session.execute(
        select(Instrument.instrument_type, func.sum(InvestmentCashFlow.net_amount_kopecks))
        .join(Instrument, InvestmentCashFlow.instrument_id == Instrument.id)
        .where(InvestmentCashFlow.reporting_month_id == reporting_month_id)
        .where(InvestmentCashFlow.flow_type.in_(CASH_INCOME_FLOW_TYPES))
        .group_by(Instrument.instrument_type)
    ).all()
    return {instrument_type: int(total or 0) for instrument_type, total in rows}


def _account_results(session: Session, reporting_month_id: int) -> tuple[AccountResultSlice, ...]:
    """Monetary result per account: realized cash income and unrealized result.

    Cash income follows the owner-fixed IIS semantics (WIKI p.12): net amounts
    of coupons, dividends, interest and realized PnL (realized_loss negative).
    Redemptions, deposits and withdrawals are never income.
    """
    income_rows = session.execute(
        select(
            Account.id,
            Account.name,
            Account.account_type,
            func.sum(InvestmentCashFlow.net_amount_kopecks),
        )
        .join(InvestmentCashFlow, InvestmentCashFlow.account_id == Account.id)
        .where(InvestmentCashFlow.reporting_month_id == reporting_month_id)
        .where(InvestmentCashFlow.flow_type.in_(CASH_INCOME_FLOW_TYPES))
        .group_by(Account.id, Account.name, Account.account_type)
    ).all()

    unrealized_rows = session.execute(
        select(
            Account.id,
            Account.name,
            Account.account_type,
            func.sum(PositionSnapshot.unrealized_result_kopecks),
        )
        .join(PositionSnapshot, PositionSnapshot.account_id == Account.id)
        .where(PositionSnapshot.reporting_month_id == reporting_month_id)
        .group_by(Account.id, Account.name, Account.account_type)
    ).all()

    merged: dict[int, AccountResultSlice] = {}
    for account_id, name, account_type, total in income_rows:
        merged[account_id] = AccountResultSlice(
            account_id=account_id,
            account_name=name,
            account_type=account_type,
            cash_income=RubleAmount(int(total or 0)),
            unrealized_result=RubleAmount(0),
        )
    for account_id, name, account_type, total in unrealized_rows:
        slice_ = merged.get(account_id)
        if slice_ is None:
            merged[account_id] = AccountResultSlice(
                account_id=account_id,
                account_name=name,
                account_type=account_type,
                cash_income=RubleAmount(0),
                unrealized_result=RubleAmount(int(total or 0)),
            )
        else:
            merged[account_id] = AccountResultSlice(
                account_id=account_id,
                account_name=slice_.account_name,
                account_type=slice_.account_type,
                cash_income=slice_.cash_income,
                unrealized_result=RubleAmount(int(total or 0)),
            )
    return tuple(merged[key] for key in sorted(merged, key=lambda k: (merged[k].account_name, k)))


def _expected_payments(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
) -> tuple[ExpectedPaymentItem, ...]:
    calendar = merged_payout_calendar(
        session,
        reporting_month_id=reporting_month_id,
        forecast_version=forecast_version,
    )
    return tuple(
        ExpectedPaymentItem(
            id=item.source_id,
            expected_date=item.expected_date,
            flow_type=item.flow_type,
            account_id=item.account_id,
            instrument_id=item.instrument_id,
            gross_amount=item.gross_amount,
            expected_tax_amount=item.expected_tax_amount,
            expected_net_amount=item.expected_net_amount,
            is_confirmed=item.is_confirmed,
            is_approximate=item.is_approximate,
            source=(item.manual_source or item.provider or item.source_kind.value),
            forecast_version=forecast_version,
            source_kind=item.source_kind.value,
            provider=item.provider,
            provider_instrument_uid=item.provider_instrument_uid,
            provider_identity_key=item.provider_identity_key,
            provider_lifecycle=item.provider_lifecycle,
            reconciliation_id=item.reconciliation_id,
            counting_decision=item.counting_decision,
            linked_manual_id=item.linked_manual_id,
            linked_provider_payout_id=item.linked_provider_payout_id,
        )
        for month in calendar
        for item in month.items
    )


def build_dashboard(
    session: Session,
    reporting_month_id: int,
    *,
    forecast_version: str = DEFAULT_FORECAST_VERSION,
) -> DashboardResult:
    """Assemble the dashboard payload for one reporting month."""
    month = get_reporting_month(session, reporting_month_id)
    summary = monthly_summary(session, reporting_month_id, forecast_version=forecast_version)
    liquid = summary.liquid_capital
    allocation = asset_allocation_for_month(session, reporting_month_id, liquid)
    allocation_delta = _asset_allocation_delta(session, month=month, allocation=allocation)
    by_account = _account_results(session, reporting_month_id)
    mortgage_balance = total_mortgage_balance(session, reporting_month_id)
    coverage_pct, gap = mortgage_coverage(session, reporting_month_id, liquid.liquid_capital_net)
    return DashboardResult(
        month=month,
        summary=summary,
        historical_series=_historical_series(session),
        asset_allocation=allocation,
        result_by_account=by_account,
        result_by_instrument_class=_instrument_class_results(session, reporting_month_id),
        expected_payments=_expected_payments(
            session,
            reporting_month_id=reporting_month_id,
            forecast_version=forecast_version,
        ),
        mortgage=MortgageCoverageSlice(
            mortgage_balance=mortgage_balance,
            coverage_pct=coverage_pct,
            gap=gap,
        ),
        warnings=summary.warnings,
        cash_flow_ladder=build_cash_flow_ladder(
            session,
            reporting_month_id,
            forecast_version=forecast_version,
        ),
        asset_allocation_delta=allocation_delta,
    )
