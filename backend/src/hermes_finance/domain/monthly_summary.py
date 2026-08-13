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

from hermes_finance.domain.cash_balance import CashBalanceResult
from hermes_finance.domain.coverage_goals import CoverageGoalsResult
from hermes_finance.domain.forecast_passive_income import (
    ForecastPassiveIncomeResult,
)
from hermes_finance.domain.iis_result import IisResult
from hermes_finance.domain.liquid_capital import LiquidCapitalResult
from hermes_finance.domain.normalized_bonus import NormalizedBonusResult
from hermes_finance.domain.salary_tax import SalaryTaxResult
from hermes_finance.domain.values import RubleAmount

CALCULATION_VERSION = "v2"

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
    salary_tax: SalaryTaxResult
    salary_actual_net: RubleAmount
    normalized_bonus: NormalizedBonusResult
    iis: tuple[IisResult, ...]
    warnings: tuple[str, ...]
    calculation_version: str = CALCULATION_VERSION
    passive_income_history_start_month: str | None = None
    passive_income_average_months_used: tuple[str, ...] = ()


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
