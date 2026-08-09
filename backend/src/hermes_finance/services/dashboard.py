"""Dashboard assembly for the selected reporting month (D07).

Builds historical series and presentation-oriented slices on top of the
existing C10 monthly summary and B-layer queries.  No financial formulas
are reinvented here — liquid capital / passive income / forecast all come
from the Phase-C services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from hermes_finance.domain.liquid_capital import LiquidCapitalResult
from hermes_finance.domain.monthly_summary import MonthlySummaryResult
from hermes_finance.domain.reporting import ReportingMonthStatus
from hermes_finance.domain.values import RubleAmount
from hermes_finance.persistence import (
    Account,
    Instrument,
    PositionSnapshot,
    ReportingMonth,
)
from hermes_finance.services.expected_cash_flows import list_expected_cash_flows
from hermes_finance.services.liquid_capital import liquid_capital_for_month
from hermes_finance.services.monthly_summary import DEFAULT_FORECAST_VERSION, monthly_summary
from hermes_finance.services.passive_income import passive_income_for_month
from hermes_finance.services.properties import mortgage_coverage, total_mortgage_balance
from hermes_finance.services.reporting_months import get_reporting_month


@dataclass(frozen=True, slots=True)
class HistoricalPoint:
    year: int
    month: int
    reporting_month_id: int
    liquid_capital_net: RubleAmount
    passive_income_actual: RubleAmount


@dataclass(frozen=True, slots=True)
class AssetClassSlice:
    asset_class: str
    amount: RubleAmount


@dataclass(frozen=True, slots=True)
class AccountResultSlice:
    account_id: int
    amount: RubleAmount


@dataclass(frozen=True, slots=True)
class InstrumentClassResult:
    instrument_type: str
    market_value: RubleAmount
    cost_basis: RubleAmount
    unrealized_result: RubleAmount


@dataclass(frozen=True, slots=True)
class ExpectedPaymentItem:
    id: int
    expected_date: date
    flow_type: str
    account_id: int
    instrument_id: int
    gross_amount: RubleAmount
    expected_tax_amount: RubleAmount | None
    expected_net_amount: RubleAmount
    is_confirmed: bool
    is_approximate: bool
    source: str
    forecast_version: str


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


def _historical_series(session: Session) -> tuple[HistoricalPoint, ...]:
    months = list(
        session.scalars(
            select(ReportingMonth)
            .where(ReportingMonth.status == ReportingMonthStatus.CLOSED)
            .order_by(ReportingMonth.year, ReportingMonth.month)
        )
    )
    points: list[HistoricalPoint] = []
    for month in months:
        liquid = liquid_capital_for_month(session, month.id)
        passive = passive_income_for_month(session, month.id)
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


def _asset_allocation(
    session: Session,
    reporting_month_id: int,
    liquid: LiquidCapitalResult,
) -> tuple[AssetClassSlice, ...]:
    """Liquid-asset allocation by E14 classes: cash, deposits, stocks, bonds, gold/other.

    Securities market value is split by ``instrument_type``: ``stock`` and
    ``bond`` are their own classes; every remaining instrument type (fund,
    currency, gold, other) plus ``other_liquid_assets`` is grouped under
    ``gold_other``. Real estate is never included — property is not liquid
    capital (MASTER_SPEC §10.1).
    """
    rows = session.execute(
        select(Instrument.instrument_type, func.sum(PositionSnapshot.market_value_kopecks))
        .join(Instrument, PositionSnapshot.instrument_id == Instrument.id)
        .join(Account, PositionSnapshot.account_id == Account.id)
        .where(PositionSnapshot.reporting_month_id == reporting_month_id)
        .where(Account.include_in_capital.is_(True))
        .group_by(Instrument.instrument_type)
    ).all()
    by_type = {instrument_type: int(total or 0) for instrument_type, total in rows}
    stocks = RubleAmount(by_type.get("stock", 0))
    bonds = RubleAmount(by_type.get("bond", 0))
    gold_other = RubleAmount(
        sum(value for kind, value in by_type.items() if kind not in ("stock", "bond"))
        + liquid.breakdown.other_liquid_assets.kopecks
    )
    return (
        AssetClassSlice("cash", liquid.breakdown.cash),
        AssetClassSlice("deposits", liquid.breakdown.deposits),
        AssetClassSlice("stocks", stocks),
        AssetClassSlice("bonds", bonds),
        AssetClassSlice("gold_other", gold_other),
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
    return tuple(
        InstrumentClassResult(
            instrument_type=instrument_type,
            market_value=RubleAmount(values[0]),
            cost_basis=RubleAmount(values[1]),
            unrealized_result=RubleAmount(values[2]),
        )
        for instrument_type, values in sorted(aggregated.items())
    )


def _expected_payments(
    session: Session,
    *,
    reporting_month_id: int,
    forecast_version: str,
) -> tuple[ExpectedPaymentItem, ...]:
    flows = list_expected_cash_flows(
        session,
        reporting_month_id=reporting_month_id,
        forecast_version=forecast_version,
    )
    return tuple(
        ExpectedPaymentItem(
            id=flow.id,
            expected_date=flow.expected_date,
            flow_type=flow.flow_type,
            account_id=flow.account_id,
            instrument_id=flow.instrument_id,
            gross_amount=RubleAmount(flow.gross_amount_kopecks),
            expected_tax_amount=(
                RubleAmount(flow.expected_tax_amount_kopecks)
                if flow.expected_tax_amount_kopecks is not None
                else None
            ),
            expected_net_amount=RubleAmount(flow.expected_net_amount_kopecks),
            is_confirmed=flow.is_confirmed,
            is_approximate=flow.is_approximate,
            source=flow.source,
            forecast_version=flow.forecast_version,
        )
        for flow in flows
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
    allocation = _asset_allocation(session, reporting_month_id, liquid)
    by_account = tuple(
        AccountResultSlice(account_id=item.account_id, amount=item.amount)
        for item in liquid.accounts
    )
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
    )
