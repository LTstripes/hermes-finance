"""Pure domain Monthly Summary DTO (framework-independent).

C10 — the single contract for dashboard and export.  This container
aggregates the results of every Phase-C calculator (C01-C09) into one
immutable DTO so the frontend never sums financial figures itself.

The DTO is pure: it imports only existing domain result types and
:class:`~hermes_finance.domain.values.RubleAmount`.  No SQLAlchemy,
FastAPI or Pydantic dependency is allowed here.

All money values are integer kopecks via :class:`RubleAmount`; binary
``float`` is never used.  No formula is duplicated — the DTO merely
holds the outputs of the existing calculators.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from hermes_finance.domain.cash_balance import CashBalanceResult
from hermes_finance.domain.coverage_goals import CoverageGoalsResult
from hermes_finance.domain.forecast_passive_income import (
    ForecastPassiveIncomeResult,
)
from hermes_finance.domain.iis_result import IisResult
from hermes_finance.domain.liquid_capital import LiquidCapitalResult
from hermes_finance.domain.normalized_bonus import NormalizedBonusResult
from hermes_finance.domain.portfolio_source_coverage import PortfolioSourceCoverage
from hermes_finance.domain.salary_tax import SalaryTaxResult
from hermes_finance.domain.values import RubleAmount

CALCULATION_VERSION = "v3"

_NO_PREVIOUS_MONTH_WARNING = "Нет предыдущего месяца для расчёта дельты"


@dataclass(frozen=True, slots=True)
class MonthlySummaryResult:
    """Unified monthly summary — one contract for dashboard/export.

    Every field is the direct output of an existing Phase-C calculator
    or a simple delta derived from the previous month.  No formula is
    recomputed here; the ORM service (``services.monthly_summary``) calls
    the existing calculators and assembles this DTO.

    Deltas (``liquid_capital_delta``, ``passive_income_delta``) are
    ``None`` when no previous reporting month exists.

    ``warnings`` is the union (order preserved, duplicates kept) of
    warnings from the constituent results, plus a delta warning when
    no previous month is available.
    """

    year: int
    month: int
    liquid_capital: LiquidCapitalResult
    liquid_capital_delta: RubleAmount | None
    passive_income_actual: RubleAmount
    passive_income_delta: RubleAmount | None
    passive_income_average: RubleAmount
    passive_income_average_months: int
    passive_income_average_complete: bool
    forecast: ForecastPassiveIncomeResult
    coverage: CoverageGoalsResult
    cash_balance: CashBalanceResult
    salary_tax: SalaryTaxResult | None
    salary_actual_net: RubleAmount
    normalized_bonus: NormalizedBonusResult
    iis: tuple[IisResult, ...]
    warnings: tuple[str, ...]
    calculation_version: str = CALCULATION_VERSION
    passive_income_history_start_month: str | None = None
    passive_income_average_months_used: tuple[str, ...] = ()
    portfolio_source_coverage: PortfolioSourceCoverage | None = None
    liquid_capital_delta_coverage: PortfolioSourceCoverage | None = None
    capital_change: MonthlyCapitalChange | None = None


def assemble_warnings(
    *,
    passive_income_average_warnings: tuple[str, ...],
    forecast_warnings: tuple[str, ...],
    coverage_warnings: tuple[str, ...],
    normalized_bonus_warnings: tuple[str, ...],
    iis_warnings: tuple[str, ...],
    liquid_capital_delta: RubleAmount | None,
) -> tuple[str, ...]:
    """Assemble the unified warning list in the fixed order.

    Order: passive_income_average, forecast, coverage_goals,
    normalized_bonus, iis results — then the delta warning when
    ``liquid_capital_delta`` is ``None``.  Duplicates are kept.
    """
    warnings: list[str] = []
    warnings.extend(passive_income_average_warnings)
    warnings.extend(forecast_warnings)
    warnings.extend(coverage_warnings)
    warnings.extend(normalized_bonus_warnings)
    warnings.extend(iis_warnings)
    if liquid_capital_delta is None:
        warnings.append(_NO_PREVIOUS_MONTH_WARNING)
    return tuple(warnings)


@dataclass(frozen=True, slots=True)
class CapitalChangeBreakdown:
    """Known signed components; unexplained is never an 'other' component.

    Component amounts are known subtotals, not assertions of complete history.
    The caller must retain source/endpoint gaps alongside this exact identity.
    """

    start: RubleAmount
    external_net: RubleAmount
    investment_result: RubleAmount
    other_changes: RubleAmount
    unexplained: RubleAmount
    end: RubleAmount


def explain_capital_change(
    *,
    start: RubleAmount,
    end: RubleAmount,
    external_net: RubleAmount,
    investment_result: RubleAmount,
    other_changes: RubleAmount,
) -> CapitalChangeBreakdown:
    """Reconcile existing producer amounts in integer minor units exactly."""
    return CapitalChangeBreakdown(
        start=start,
        external_net=external_net,
        investment_result=investment_result,
        other_changes=other_changes,
        unexplained=RubleAmount(
            end.kopecks
            - start.kopecks
            - external_net.kopecks
            - investment_result.kopecks
            - other_changes.kopecks
        ),
        end=end,
    )


@dataclass(frozen=True, slots=True)
class MonthlyCapitalChange:
    reporting_month_id: int
    previous_reporting_month_id: int | None
    period_start: date
    period_end: date
    breakdown: CapitalChangeBreakdown | None
    reason_codes: tuple[str, ...]
    flow_breakdown: CapitalFlowBreakdown | None = None
    context_hints: tuple[CapitalChangeHint, ...] = ()


@dataclass(frozen=True, slots=True)
class CapitalChangeItem:
    account_id: int
    instrument_id: int | None
    amount: RubleAmount | None
    reason_codes: tuple[str, ...] = ()
    unavailable_hint: str | None = None
    source_reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CapitalChangeComponent:
    amount: RubleAmount | None
    known_subtotal: RubleAmount
    items: tuple[CapitalChangeItem, ...]
    reason_codes: tuple[str, ...]


def capital_change_component(items: tuple[CapitalChangeItem, ...]) -> CapitalChangeComponent:
    """Keep a partial component NULL without discarding its known items."""
    subtotal = RubleAmount(sum(item.amount.kopecks for item in items if item.amount is not None))
    return CapitalChangeComponent(
        amount=subtotal if all(item.amount is not None for item in items) else None,
        known_subtotal=subtotal,
        items=items,
        reason_codes=tuple(sorted({code for item in items for code in item.reason_codes})),
    )


@dataclass(frozen=True, slots=True)
class CapitalChangeHint:
    card_debt_growth: RubleAmount
    recorded_expenses: RubleAmount
    reason_code: str = "card_debt_growth_exceeds_recorded_expenses"


@dataclass(frozen=True, slots=True)
class CapitalFlowBreakdown:
    start: RubleAmount
    monthly_flow: RubleAmount
    investment_market_change: CapitalChangeComponent
    physical_gold_revaluation: CapitalChangeComponent
    unexplained: RubleAmount
    end: RubleAmount


def explain_capital_flow(
    *,
    start: RubleAmount,
    end: RubleAmount,
    monthly_flow: RubleAmount,
    investment_market_change: CapitalChangeComponent,
    physical_gold_revaluation: CapitalChangeComponent,
) -> CapitalFlowBreakdown:
    """Reconcile known contributions; unknown items remain explicitly unallocated."""
    return CapitalFlowBreakdown(
        start=start,
        end=end,
        monthly_flow=monthly_flow,
        investment_market_change=investment_market_change,
        physical_gold_revaluation=physical_gold_revaluation,
        unexplained=RubleAmount(
            end.kopecks
            - start.kopecks
            - monthly_flow.kopecks
            - investment_market_change.known_subtotal.kopecks
            - physical_gold_revaluation.known_subtotal.kopecks
        ),
    )
